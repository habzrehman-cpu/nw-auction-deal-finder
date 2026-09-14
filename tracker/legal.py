"""Legal-pack discovery, guarded acquisition and auction legal risk triage.

The module can automatically retrieve directly accessible legal documents and, where
configured and permitted, use the buyer's own authenticated account session. It never
bypasses CAPTCHAs, anti-bot controls, paywalls or provider permission requirements.
Results are acquisition triage only and must be reviewed by a solicitor before bid.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import re
import copy
import zipfile
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from dateutil import parser as date_parser

from .legal_access import (
    LegalAccessConfig, provider_for_lot, provider_access_status, prepare_authenticated_session,
)
from .legal_firewall import (
    EVIDENCE_POLICY_VERSION, TIER_VERIFIED_LEGAL, TIER_VERIFIED_PACK_INDEX, TIER_CANDIDATE, TIER_REJECTED,
    strong_pack_link, generic_site_content, lot_identity_match, document_identity_assessment,
    document_type_classification, evidence_tier, is_verified_legal_document,
    mark_candidate, mark_rejected, mark_pack_index, mark_verified_legal, verified_legal_documents,
)

LEGAL_ATTRIBUTION = "Auctioneer/seller legal documents as published; buyer must verify the latest complete pack and obtain independent legal advice."
MAX_DOC_BYTES = 12 * 1024 * 1024
MAX_DOC_CHARS = 90_000
MAX_AUTO_DOCS = 16
MAX_AUTO_TOTAL_BYTES = 80 * 1024 * 1024
MAX_ZIP_MEMBERS = 40
MAX_ZIP_TOTAL_BYTES = 60 * 1024 * 1024

LEGAL_HINT_RE = re.compile(
    r"legal\s*pack|legal\s*documents?|special\s*conditions?|addendum|title\s*register|"
    r"official\s*copy|lease|epc|energy performance|auction passport|eigroup|buyer information",
    re.I,
)

# First-hop discovery is intentionally stricter than general legal-document classification.
# Bare words such as "lease" or generic advisory/navigation content must never be
# allowed to turn an auctioneer website page into legal evidence.
INITIAL_LEGAL_HINT_RE = re.compile(
    r"legal\s*pack|legal\s*documents?|special\s*conditions?|addendum|title\s*register|"
    r"title\s*plan|official\s*copy|auction\s*passport|contract\s*pack|auction\s+contract",
    re.I,
)

DOC_TYPE_PATTERNS = [
    (re.compile(r"addendum", re.I), "Addendum"),
    (re.compile(r"special\s*conditions?", re.I), "Special conditions"),
    (re.compile(r"title\s*register|official\s*copy.*register", re.I), "Title register"),
    (re.compile(r"title\s*plan|official\s*copy.*plan", re.I), "Title plan"),
    (re.compile(r"lease", re.I), "Lease"),
    (re.compile(r"epc|energy performance", re.I), "EPC"),
    (re.compile(r"legal\s*pack|legal\s*documents?", re.I), "Legal pack"),
]

RISK_PATTERNS = [
    (r"possessory title|qualified title|unregistered title|adverse possession", 5, "Title quality / unregistered-title issue"),
    (r"defect(?:ive)? title|title defect|indemnity polic(?:y|ies)", 4, "Potential title defect / indemnity issue"),
    (r"overage|clawback|uplift provision", 4, "Overage / clawback obligation"),
    (r"restrictive covenant|covenant not to|restriction on use", 3, "Restrictive covenant / use restriction"),
    (r"rentcharge|estate rentcharge", 4, "Rentcharge / estate-rentcharge issue"),
    (r"ground rent.{0,80}(?:double|doubling|review|rpi|retail price)", 4, "Ground-rent review/escalation clause"),
    (r"lease.{0,80}(?:term|unexpired).{0,40}(?:[0-6]\d|7\d)\s*years", 5, "Possible sub-80-year lease"),
    (r"short lease", 5, "Short lease"),
    (r"buyer.{0,100}(?:pay|reimburse|contribute).{0,100}(?:seller|vendor).{0,80}(?:legal|search|auction|cost|fee)", 3, "Buyer required to pay seller/vendor costs"),
    (r"buyer.{0,100}(?:discharge|pay).{0,80}(?:arrears|service charge|ground rent)", 4, "Buyer may inherit/discharge arrears"),
    (r"completion.{0,80}(?:5|7|10)\s*(?:working\s*)?days", 3, "Very short completion timetable"),
    (r"completion.{0,80}(?:14)\s*(?:working\s*)?days", 2, "Short completion timetable"),
    (r"vat.{0,80}(?:payable|chargeable|applicable)|option to tax|opted to tax", 3, "VAT / option-to-tax wording"),
    (r"transfer of a going concern|\btogc\b", 2, "TOGC treatment requires tax/legal confirmation"),
    (r"easement|right of way|rights of access|rights reserved", 2, "Easement / access rights require review"),
    (r"chancel repair", 2, "Chancel-repair wording"),
    (r"mine\s*shaft|mine\s+entry|mining\s+subsidence|ground\s+movement|coal\s+mining.{0,120}(?:affected|risk|hazard|entry|subsidence)", 3, "Mining risk/search issue"),
    (r"contaminat|landfill|hazardous substance", 5, "Contamination / environmental wording"),
    (r"asbestos", 3, "Asbestos wording"),
    (r"tenanted|tenant|assured shorthold|ast\b|lease in place|occupier", 2, "Occupational rights / tenancy require review"),
    (r"service charge.{0,100}(?:arrears|balancing|deficit|major works)", 3, "Service-charge liability / major works wording"),
    (r"section 20|major works", 3, "Possible leasehold major-works liability"),
    (r"licence to assign|consent to assign|alienation", 2, "Assignment/consent restriction"),
]


def _session(session=None):
    s = session or requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 NW-Auction-Deal-Finder/1.10.3", "Accept-Language": "en-GB,en;q=0.9"})
    return s


def classify_document(label: str, url: str = "", text: str = "") -> str:
    """Classify a legal candidate using the current document-class gate."""
    result = document_type_classification(label, url, text)
    dtype = result.get("doc_type") or "Unclassified"
    return "Legal document" if dtype == "Unclassified" else dtype


def discover_legal_links(html: str, base_url: str, pack_context: bool = False) -> list[dict]:
    """Discover candidate legal-pack links without crawling generic site navigation.

    The first hop from an auction-lot page requires a strong legal-pack signal.
    Once a lot-specific legal-pack index has been verified, direct PDF/ZIP/download
    links may be queued even when their visible labels are generic.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()

    candidates = []
    for node in soup.find_all(["a", "button", "iframe", "form"]):
        label = " ".join(node.get_text(" ", strip=True).split())
        attrs = []
        for attr in ("href", "src", "action", "data-href", "data-url", "data-download", "data-src"):
            value = node.get(attr)
            if value:
                attrs.append(value)
        for href in attrs:
            candidates.append((label, href))

    # Script discovery is limited to actual PDF/ZIP URLs. We deliberately do not
    # extract arbitrary HTML URLs from scripts because that previously allowed normal
    # auctioneer navigation/advisory pages to leak into the legal evidence set.
    script_url_re = re.compile(r'''["'](https?://[^"']+\.(?:pdf|zip)(?:\?[^"']*)?|/[^"']+\.(?:pdf|zip)(?:\?[^"']*)?)["']''', re.I)
    for m in script_url_re.finditer(html or ""):
        candidates.append(("Legal document", m.group(1)))

    for label, href in candidates:
        href = str(href or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        probe = f"{label} {href}"
        binaryish = bool(re.search(r"\.(?:pdf|zip)(?:$|\?)", href, re.I))
        downloadish = bool(re.search(r"(?:^|[/_-])(?:download|document|legal)(?:[/_.?&=-]|$)", href, re.I))
        if pack_context:
            allowed = binaryish or downloadish or strong_pack_link(label, href)
        else:
            allowed = (
                bool(INITIAL_LEGAL_HINT_RE.search(probe))
                or (binaryish and bool(LEGAL_HINT_RE.search(probe)))
            ) and not generic_site_content(label, href)
        if not allowed or absolute in seen:
            continue
        seen.add(absolute)
        item = {
            "name": label or classify_document(probe),
            "url": absolute,
            "doc_type": classify_document(label, absolute),
            "access_status": "candidate link discovered",
            "text_content": "",
            "sha256": "",
            "metadata": {},
        }
        mark_candidate(item, "candidate legal link discovered; lot binding not yet verified")
        out.append(item)
    return out[:50]

def extract_pdf_text(data: bytes, max_chars: int = MAX_DOC_CHARS) -> str:
    """Extract PDF text with stable page markers for audit-friendly evidence references."""
    if not data:
        return ""
    reader = PdfReader(BytesIO(data))
    parts = []
    total = 0
    for page_no, page in enumerate(reader.pages[:120], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            block = f"--- PAGE {page_no} ---\n{text}"
            parts.append(block)
            total += len(block)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]


def _looks_restricted(text: str, url: str) -> bool:
    t = f"{text} {url}".lower()
    return any(x in t for x in [
        "sign in", "log in", "login", "register to view", "create account",
        "auction passport", "login to view legal documents", "content is restricted to members",
    ])


def _read_response_bytes(response) -> tuple[bytes, bool]:
    try:
        length = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        length = 0
    if length and length > MAX_DOC_BYTES:
        return b"", True
    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_DOC_BYTES:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


def _identity_threshold(doc_class: dict) -> int:
    # A combined file merely called "Legal pack" is broad, so require stronger
    # property identity than a recognised title/lease/special-conditions document.
    return 80 if (doc_class.get("doc_type") == "Legal pack") else 60


def _zip_documents(name: str, data: bytes, source_url: str, provider: str, authenticated: bool,
                   lot: dict, parent_verified: bool) -> list[dict]:
    """Expand a ZIP and identity-lock every member independently."""
    out = uploaded_documents(name or "legal-pack.zip", data)
    checked = []
    for doc in out:
        meta = doc.setdefault("metadata", {})
        meta.update({
            "origin": "auto-download-authenticated" if authenticated else "auto-download-public",
            "provider": provider,
            "source_url": source_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_property_url": lot.get("url") or "",
            "parent_verified_pack": bool(parent_verified),
        })
        doc["url"] = source_url
        text = doc.get("text_content") or ""
        doc_class = document_type_classification(doc.get("name") or "", source_url, text)
        assessment = document_identity_assessment(lot, text=text, url=source_url, label=doc.get("name") or "")
        doc["doc_type"] = doc_class.get("doc_type") if doc_class.get("allowed") else doc.get("doc_type") or "Legal document"
        if assessment.get("hard_reject"):
            reason = "; ".join(assessment.get("conflicts") or ["document identifies a different property"])
            mark_rejected(doc, reason, assessment, doc_class)
            doc["text_content"] = ""
            doc["access_status"] = "ZIP member rejected: cross-property identity mismatch"
        elif not doc_class.get("allowed"):
            mark_candidate(doc, doc_class.get("reason") or "unrecognised legal document type", assessment, doc_class)
            doc["text_content"] = ""
            doc["access_status"] = "candidate ZIP member rejected by document-class gate"
        elif int(assessment.get("score") or 0) >= _identity_threshold(doc_class):
            reasons = list(assessment.get("reasons") or [])
            if parent_verified:
                reasons.append("discovered inside a verified lot-specific legal-pack chain")
            mark_verified_legal(doc, reasons, assessment, doc_class)
            doc["access_status"] = "verified legal ZIP member parsed" if text else "verified legal ZIP member; no extractable text"
        else:
            reason = "document type recognised but property identity score is below the verification threshold"
            if assessment.get("conflicts"):
                reason += ": " + "; ".join(assessment.get("conflicts") or [])
            mark_candidate(doc, reason, assessment, doc_class)
            doc["text_content"] = ""
            doc["access_status"] = "candidate ZIP member held outside legal analysis by Property Identity Lock"
        checked.append(doc)
    return checked


def _html_pack_index_verified(lot: dict, item: dict, text: str, final_url: str,
                              parent_verified: bool, direct_from_lot: bool) -> tuple[bool, list[str], dict]:
    """Verify an HTML pack index by property identity, not link wording alone."""
    if generic_site_content(item.get("name") or "", final_url, text[:4000]):
        assessment = document_identity_assessment(lot, text=text, url=final_url, label=item.get("name") or "")
        return False, ["generic auction-provider/advisory page rejected"], assessment
    assessment = document_identity_assessment(lot, text=text, url=final_url, label=item.get("name") or "")
    if assessment.get("hard_reject"):
        return False, list(assessment.get("conflicts") or ["pack page identifies a different property"]), assessment
    reasons = list(assessment.get("reasons") or [])
    if int(assessment.get("score") or 0) >= 60:
        if direct_from_lot and strong_pack_link(item.get("name") or "", item.get("url") or final_url):
            reasons.append("reached from the subject auction lot's legal-pack link")
        return True, list(dict.fromkeys(reasons)), assessment
    # A nested pack page may inherit navigation context, but still needs at least a
    # probable property identity score. This prevents a verified page linking into
    # generic provider navigation and creating a new trust bridge.
    if parent_verified and int(assessment.get("score") or 0) >= 40 and strong_pack_link(item.get("name") or "", item.get("url") or final_url):
        reasons.append("nested legal-pack page with corroborating lot identity")
        return True, list(dict.fromkeys(reasons)), assessment
    return False, ["HTML legal-pack candidate did not contain sufficient subject-lot identity"] + list(assessment.get("conflicts") or []), assessment


def _binary_document_verified(lot: dict, item: dict, text: str, final_url: str,
                              parent_verified: bool, direct_from_lot: bool) -> tuple[bool, list[str], dict, dict, str]:
    """Run document class + property identity locks before legal promotion."""
    label = item.get("name") or ""
    source_url = item.get("url") or final_url
    doc_class = document_type_classification(label, source_url, text)
    assessment = document_identity_assessment(lot, text=text, url=final_url, label=label)

    if generic_site_content(label, final_url, text[:4000]) or not doc_class.get("allowed"):
        reason = doc_class.get("reason") or "generic/provider content is not legal evidence"
        return False, [], assessment, doc_class, reason
    if assessment.get("hard_reject"):
        reason = "; ".join(assessment.get("conflicts") or ["document identifies a different property"])
        return False, [], assessment, doc_class, reason

    threshold = _identity_threshold(doc_class)
    score = int(assessment.get("score") or 0)
    reasons = list(assessment.get("reasons") or [])
    if score >= threshold:
        if parent_verified:
            reasons.append("discovered from a verified lot-specific legal-pack index")
        if direct_from_lot:
            reasons.append("discovered directly from the known auction lot page")
        reasons.append(doc_class.get("reason") or "recognised legal/DD document class")
        return True, list(dict.fromkeys(reasons)), assessment, doc_class, ""

    reason = f"property identity score {score}/100 is below the {threshold}/100 verification threshold"
    if assessment.get("conflicts"):
        reason += "; " + "; ".join(assessment.get("conflicts") or [])
    return False, reasons, assessment, doc_class, reason



def revalidate_saved_legal_documents(lot: dict, documents: list[dict] | None) -> tuple[list[dict], dict]:
    """Re-run stored evidence through the current firewall and identity lock.

    This is the v1.10.3 purge boundary.  Historic automatic documents are never
    grandfathered merely because an older build marked them verified.  Every saved
    automatic document is reclassified from its stored filename/URL/text against the
    *current* subject lot.  Cross-property/generic material is quarantined and can no
    longer drive rent, seller/company identity, legal risk, contacts or bid readiness.

    User uploads remain user-attested to the selected property.  They still go through
    current legal analysis, but are not silently discarded during an online refresh.
    """
    out: list[dict] = []
    report = {
        "checked": 0, "retained_verified": 0, "downgraded": 0,
        "rejected": 0, "candidates": 0, "user_uploads": 0,
        "purged_findings": 0, "notes": [],
    }
    for original in list(documents or []):
        doc = copy.deepcopy(original)
        meta = doc.setdefault("metadata", {})
        previous_tier = evidence_tier(doc)
        origin = str(meta.get("origin") or "")
        report["checked"] += 1

        # A document deliberately uploaded while viewing this property is a user
        # attestation. Preserve it, but stamp the current evidence policy so stale
        # automatic metadata cannot masquerade as a current verification.
        if origin == "user-upload":
            meta.update({
                "evidence_tier": TIER_VERIFIED_LEGAL,
                "verified_for_lot": True,
                "identity_status": "user-attested",
                "evidence_policy_version": EVIDENCE_POLICY_VERSION,
                "revalidated_at": datetime.now(timezone.utc).isoformat(),
                "revalidation_outcome": "retained-user-upload",
            })
            meta.pop("rejection_reason", None)
            report["user_uploads"] += 1
            report["retained_verified"] += 1
            out.append(doc)
            continue

        # Pack-index HTML deliberately has no stored body text.  It may remain an
        # access/navigation artefact only when its previous identity metadata still
        # proves the same subject postcode/lot. It never contributes legal findings.
        if previous_tier == TIER_VERIFIED_PACK_INDEX:
            target_pc = "".join(str(lot.get("postcode") or "").upper().split())
            old_target = "".join(str(meta.get("identity_target_postcode") or "").upper().split())
            score = int(meta.get("identity_score") or 0)
            source_property_url = str(meta.get("source_property_url") or "")
            same_lot_url = bool(source_property_url and source_property_url == str(lot.get("url") or ""))
            if score >= 60 and (not target_pc or old_target == target_pc) and same_lot_url:
                meta.update({
                    "evidence_policy_version": EVIDENCE_POLICY_VERSION,
                    "revalidated_at": datetime.now(timezone.utc).isoformat(),
                    "revalidation_outcome": "retained-pack-index",
                })
                report["retained_verified"] += 1
            else:
                mark_candidate(doc, "historic pack index could not be re-proven against the current lot")
                meta["revalidated_at"] = datetime.now(timezone.utc).isoformat()
                meta["revalidation_outcome"] = "downgraded-pack-index"
                report["downgraded"] += 1
                report["candidates"] += 1
            out.append(doc)
            continue

        text = str(doc.get("text_content") or "")
        label = str(doc.get("name") or "")
        url = str(doc.get("url") or "")
        direct_from_lot = bool(meta.get("direct_from_lot"))

        # Crucially, an old 'parent_verified_pack' flag is NOT inherited during
        # revalidation. The stored file itself must now prove its identity.
        verified, reasons, assessment, doc_class, rejection_reason = _binary_document_verified(
            lot, doc, text, url, parent_verified=False, direct_from_lot=direct_from_lot
        )
        doc["doc_type"] = doc_class.get("doc_type") if doc_class.get("allowed") else (doc.get("doc_type") or "Legal document")

        if verified:
            mark_verified_legal(doc, reasons, assessment, doc_class)
            meta = doc.setdefault("metadata", {})
            meta["revalidation_outcome"] = "verified-current-policy"
            report["retained_verified"] += 1
        elif assessment.get("hard_reject"):
            reason = rejection_reason or "; ".join(assessment.get("conflicts") or ["document identifies a different property"] )
            mark_rejected(doc, reason, assessment, doc_class)
            meta = doc.setdefault("metadata", {})
            meta["revalidation_outcome"] = "rejected-cross-property"
            report["rejected"] += 1
            if previous_tier == TIER_VERIFIED_LEGAL:
                report["downgraded"] += 1
        else:
            reason = rejection_reason or "; ".join(reasons) or "stored document could not be re-verified for the current lot"
            mark_candidate(doc, reason, assessment, doc_class)
            meta = doc.setdefault("metadata", {})
            meta["revalidation_outcome"] = "downgraded-candidate" if previous_tier == TIER_VERIFIED_LEGAL else "candidate-current-policy"
            report["candidates"] += 1
            if previous_tier == TIER_VERIFIED_LEGAL:
                report["downgraded"] += 1

        meta = doc.setdefault("metadata", {})
        meta["revalidated_at"] = datetime.now(timezone.utc).isoformat()
        if previous_tier == TIER_VERIFIED_LEGAL and evidence_tier(doc) != TIER_VERIFIED_LEGAL:
            # Any fields/risks/contacts previously derived from this file are rebuilt
            # from scratch by analyse_legal_documents; record the purge for audit.
            report["purged_findings"] += 1
        out.append(doc)

    if report["downgraded"]:
        report["notes"].append(
            f"{report['downgraded']} previously trusted automatic document(s) were downgraded by the current Property Identity Lock."
        )
    if report["rejected"]:
        report["notes"].append(
            f"{report['rejected']} stored document(s) were quarantined as cross-property evidence."
        )
    if report["purged_findings"]:
        report["notes"].append(
            "Derived rent, seller/company identity, contacts and legal-risk findings from downgraded documents were purged and recalculated."
        )
    return out, report

def fetch_legal_documents(lot: dict, session=None, max_docs: int = MAX_AUTO_DOCS,
                          access_config: LegalAccessConfig | None = None) -> tuple[list[dict], list[str]]:
    """Discover and acquire lot-bound legal evidence with a strict evidence firewall.

    Candidate links are retained for audit/manual access, but only documents that can
    be tied to the current auction lot through a verified pack-index chain, a strong
    direct legal-document link from the lot page, or strong subject identity matching
    are marked as verified legal documents. Generic auctioneer website pages can never
    become legal evidence.
    """
    lot_url = str(lot.get("url") or "")
    provider = provider_for_lot(lot, lot_url)
    access = provider_access_status(access_config, provider)
    s = _session(session)
    warnings = []
    if not lot_url.startswith(("http://", "https://")):
        return [], ["No public lot URL is available for legal-pack discovery."]
    if not access.get("allowed"):
        return [], [f"{access.get('label')}: {access.get('status')}. {access.get('reason') or ''}".strip()]

    r = s.get(lot_url, timeout=25, allow_redirects=True)
    r.raise_for_status()
    initial = discover_legal_links(r.text, r.url, pack_context=False)
    queue = []
    for item in initial:
        item.setdefault("metadata", {}).update({
            "provider": provider,
            "origin": "auto-discovery",
            "source_property_url": lot_url,
            "discovered_from": r.url,
            "direct_from_lot": True,
        })
        queue.append((item, False, True))  # item, parent_verified_pack, direct_from_lot

    links: list[dict] = []
    seen_urls = set()
    verified_downloads = 0
    attempted = 0
    max_attempts = max(12, max_docs * 8)
    authenticated = False
    auth_attempted = False
    total_auto_bytes = 0

    while queue and verified_downloads < max_docs and attempted < max_attempts:
        item, parent_verified, direct_from_lot = queue.pop(0)
        url = str(item.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        item.setdefault("metadata", {}).update({
            "provider": provider,
            "origin": item.get("metadata", {}).get("origin") or "auto-discovery",
            "source_property_url": lot_url,
            "parent_verified_pack": bool(parent_verified),
            "direct_from_lot": bool(direct_from_lot),
        })
        mark_candidate(item, "candidate legal link pending lot verification")
        links.append(item)
        attempted += 1
        try:
            doc = s.get(url, timeout=30, allow_redirects=True, stream=True)
            doc.raise_for_status()
            ctype = (doc.headers.get("Content-Type") or "").lower()
            data, too_large = _read_response_bytes(doc)
            if too_large:
                item["access_status"] = "candidate document too large for automatic analysis"
                continue
            if total_auto_bytes + len(data) > MAX_AUTO_TOTAL_BYTES:
                item["access_status"] = "automatic pack-size safety limit reached"
                warnings.append("Automatic legal-pack download reached the 80 MB per-property safety limit.")
                break
            total_auto_bytes += len(data)
            final_url = doc.url
            is_html = "text/html" in ctype or data.lstrip().lower().startswith((b"<!doctype html", b"<html"))

            if is_html:
                decoded = data.decode("utf-8", errors="ignore")
                soup = BeautifulSoup(decoded, "html.parser")
                for node in soup.select("script,style,noscript,svg,template"):
                    node.decompose()
                text = " ".join(soup.get_text(" ", strip=True).split())[:40_000]
                login_form_present = bool(soup.find("input", attrs={"type": re.compile("password", re.I)}))
                if login_form_present or _looks_restricted(text[:8000] + " " + decoded[:8000], final_url):
                    if not auth_attempted:
                        auth_attempted = True
                        ok, message = prepare_authenticated_session(s, final_url, provider, access_config)
                        if ok:
                            authenticated = True
                            seen_urls.discard(url)
                            queue.insert(0, (item, parent_verified, direct_from_lot))
                            continue
                        item["access_status"] = message
                        warnings.append(f"{access.get('label')}: {message}.")
                    else:
                        item["access_status"] = "login required or authenticated session was not accepted"
                    continue

                pack_verified, reasons, assessment = _html_pack_index_verified(
                    lot, item, text, final_url, parent_verified, direct_from_lot
                )
                if not pack_verified:
                    if assessment.get("hard_reject"):
                        mark_rejected(item, "; ".join(reasons) if reasons else "HTML page identifies a different property", assessment)
                    else:
                        mark_candidate(item, "; ".join(reasons) if reasons else "HTML page is not demonstrably lot-specific legal content", assessment)
                    item["access_status"] = "candidate page rejected by legal evidence firewall"
                    # Critical boundary: never crawl onward from an unverified HTML page.
                    continue

                mark_pack_index(item, reasons, assessment)
                item["access_status"] = "verified lot-specific legal-pack index"
                item["url"] = final_url
                item["sha256"] = hashlib.sha256(data).hexdigest()
                item["metadata"].update({
                    "origin": "auto-download-authenticated" if authenticated else "auto-download-public",
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                })
                # HTML pack/index text is intentionally NOT stored as legal evidence.
                item["text_content"] = ""
                nested = discover_legal_links(decoded, final_url, pack_context=True)
                for child in nested:
                    child.setdefault("metadata", {}).update({
                        "provider": provider,
                        "origin": "auto-discovery",
                        "source_property_url": lot_url,
                        "discovered_from": final_url,
                    })
                    if child.get("url") not in seen_urls and all(child.get("url") != q[0].get("url") for q in queue):
                        queue.append((child, True, False))
                continue

            if "zip" in ctype or final_url.lower().split("?")[0].endswith(".zip") or data[:4] == b"PK\x03\x04":
                # A ZIP linked from a verified pack index/direct legal link inherits the
                # lot binding. Members are then individually marked verified/candidate.
                direct_verified, reasons, assessment, doc_class, rejection_reason = _binary_document_verified(
                    lot, item, "", final_url, parent_verified, direct_from_lot
                )
                expanded = _zip_documents(
                    item.get("name") or "legal-pack.zip", data, final_url, provider,
                    authenticated, lot, direct_verified
                )
                item["sha256"] = hashlib.sha256(data).hexdigest()
                item["url"] = final_url
                if direct_verified:
                    mark_pack_index(item, reasons + ["ZIP container for lot-specific legal documents"], assessment)
                    item["access_status"] = f"verified lot-specific legal ZIP; {len(expanded)} member(s) inspected"
                else:
                    if assessment.get("hard_reject"):
                        mark_rejected(item, rejection_reason or "ZIP container identifies a different property", assessment, doc_class)
                        item["access_status"] = "ZIP rejected: cross-property identity mismatch"
                    else:
                        mark_candidate(item, rejection_reason or "ZIP container could not be tied to the subject lot", assessment, doc_class)
                        item["access_status"] = "candidate ZIP held outside legal analysis by Property Identity Lock"
                item["metadata"].update({
                    "origin": "auto-download-authenticated" if authenticated else "auto-download-public",
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                })
                for child in expanded:
                    links.append(child)
                    if is_verified_legal_document(child):
                        verified_downloads += 1
                    if verified_downloads >= max_docs:
                        break
                continue

            if "pdf" in ctype or final_url.lower().split("?")[0].endswith(".pdf") or data[:4] == b"%PDF":
                extracted_text = extract_pdf_text(data)
                verified, reasons, assessment, doc_class, rejection_reason = _binary_document_verified(
                    lot, item, extracted_text, final_url, parent_verified, direct_from_lot
                )
                item["sha256"] = hashlib.sha256(data).hexdigest()
                item["url"] = final_url
                item["metadata"].update({
                    "origin": "auto-download-authenticated" if authenticated else "auto-download-public",
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                })
                if verified:
                    item["doc_type"] = doc_class.get("doc_type") or item.get("doc_type") or "Legal document"
                    mark_verified_legal(item, reasons, assessment, doc_class)
                    item["text_content"] = extracted_text
                    item["access_status"] = (
                        "verified authenticated legal PDF parsed" if authenticated and extracted_text else
                        "verified authenticated legal PDF; no extractable text" if authenticated else
                        "verified public legal PDF parsed" if extracted_text else
                        "verified public legal PDF; no extractable text"
                    )
                    item["_raw_bytes"] = data
                    verified_downloads += 1
                else:
                    item["doc_type"] = doc_class.get("doc_type") if doc_class.get("allowed") else item.get("doc_type") or "Legal document"
                    if assessment.get("hard_reject"):
                        mark_rejected(item, rejection_reason or "PDF identifies a different property", assessment, doc_class)
                        item["access_status"] = "PDF rejected: cross-property identity mismatch"
                    else:
                        mark_candidate(item, rejection_reason or "; ".join(reasons) or "PDF could not be tied to the subject lot", assessment, doc_class)
                        item["access_status"] = "candidate PDF held outside legal analysis by Property Identity Lock"
                    item["text_content"] = ""
                continue

            item["access_status"] = "candidate link checked; unsupported document type"
        except Exception as exc:
            item["access_status"] = "candidate link found; automatic access failed"
            item["error"] = str(exc)[:300]

    verified = [d for d in links if is_verified_legal_document(d)]
    if links and not verified:
        if "not configured" in str(access.get("status") or ""):
            warnings.append(
                f"{access.get('label')}: candidate legal-pack access was found, but no lot-bound legal documents were verified. "
                "Configure your own account credentials where permitted or upload the pack manually."
            )
        else:
            warnings.append(
                "Candidate legal-pack links were discovered, but no authoritative lot-bound legal documents were verified. "
                "Legal risk remains UNKNOWN until a verified pack is acquired or uploaded."
            )
    if not links:
        warnings.append("No legal-pack/addendum candidate was detected on the lot page. Check the auctioneer lot page manually before bidding.")
    return links, list(dict.fromkeys(warnings))

def fetch_public_legal_documents(lot_url: str, session=None, max_docs: int = MAX_AUTO_DOCS) -> tuple[list[dict], list[str]]:
    """Backward-compatible public-only wrapper used by older tests/integrations."""
    lot = {"url": lot_url, "source": ""}
    return fetch_legal_documents(lot, session=session, max_docs=max_docs, access_config=LegalAccessConfig())

def legal_pack_fingerprint(documents: list[dict]) -> str:
    """Stable fingerprint of verified legal evidence only.

    Candidate/index pages do not trigger legal-pack change alarms.
    """
    parts = []
    for doc in verified_legal_documents(documents):
        key = str(doc.get("url") or doc.get("name") or "").strip().lower()
        digest = str(doc.get("sha256") or "").strip().lower()
        dtype = str(doc.get("doc_type") or "").strip().lower()
        parts.append(f"{key}|{dtype}|{digest}")
    if not parts:
        return ""
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def compare_legal_documents(previous: list[dict], current: list[dict]) -> dict:
    """Explain pack changes without treating first discovery as an alarming change."""
    def key(doc):
        url = str(doc.get("url") or "").split("?")[0].rstrip("/").lower()
        name = str(doc.get("name") or "").strip().lower()
        return url or name
    old_docs = verified_legal_documents(previous)
    new_docs = verified_legal_documents(current)
    old = {key(d): d for d in old_docs if key(d)}
    new = {key(d): d for d in new_docs if key(d)}
    added = [new[k].get("name") or new[k].get("url") for k in new.keys() - old.keys()]
    removed = [old[k].get("name") or old[k].get("url") for k in old.keys() - new.keys()]
    changed = []
    for k in new.keys() & old.keys():
        old_hash = str(old[k].get("sha256") or "")
        new_hash = str(new[k].get("sha256") or "")
        if old_hash and new_hash and old_hash != new_hash:
            changed.append(new[k].get("name") or new[k].get("url"))
    return {
        "is_first_snapshot": not bool(old_docs),
        "changed": bool(old_docs) and bool(added or removed or changed),
        "added": sorted(x for x in added if x),
        "removed": sorted(x for x in removed if x),
        "modified": sorted(x for x in changed if x),
    }

def _first_number(pattern: str, text: str, low=0, high=9999):
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    try:
        n = float(m.group(1))
        return n if low <= n <= high else None
    except (TypeError, ValueError):
        return None



def _clean_line(value: str, limit: int = 260) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _first_text(patterns, text: str, limit: int = 260):
    for pattern in patterns:
        m = re.search(pattern, text, re.I | re.M)
        if m:
            return _clean_line(m.group(1), limit)
    return None


def _money_near(label_pattern: str, text: str):
    m = re.search(label_pattern + r".{0,100}?(?:£|GBP\s*)\s*([\d,]+(?:\.\d+)?)", text, re.I | re.S)
    if not m:
        return None, None
    try:
        amount = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, None
    context = _clean_line(text[max(0, m.start()-40):m.end()+90], 220)
    return amount, context


def _remaining_lease_years(text: str, fallback=None):
    direct = _first_number(r"(?:unexpired|remaining).{0,60}?(\d{1,3}(?:\.\d+)?)\s*years", text, 1, 999)
    if direct is not None:
        return round(direct, 1), None, None
    # Auctioneer particulars often use labels such as "Length of Lease/Term: 250 years".
    # Prefer that explicit labelled term over looser mentions elsewhere on the page.
    date_pat = r"(\d{1,2}\s+[A-Za-z]+\s+20\d{2}|[A-Za-z]+\s+\d{1,2},?\s+20\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2})"
    m = re.search(
        r"(?:length\s+of\s+lease(?:\s*/\s*term)?|lease\s+term|term\s+of\s+lease)\s*[:\-]?\s*"
        r"(\d{1,3})\s*years?(?:\s*\([^)]*\))?\s+(?:from|commencing(?:\s+on)?|beginning(?:\s+on)?)\s+" + date_pat,
        text, re.I,
    )
    if not m:
        m = re.search(
            r"(?:term\s+of\s+)?(\d{1,3})\s*years?\s+(?:from|commencing(?:\s+on)?|beginning(?:\s+on)?)\s+" + date_pat,
            text, re.I,
        )
    if not m:
        return fallback, None, None
    try:
        term = float(m.group(1))
        start = date_parser.parse(_clean_line(m.group(2), 45), dayfirst=True, fuzzy=True).date()
        today = datetime.now(timezone.utc).date()
        elapsed = (today - start).days / 365.2425
        remaining = max(0.0, term - elapsed)
        return round(remaining, 1), start.isoformat(), term
    except Exception:
        return fallback, None, None


def _seller_type(text: str):
    low = text.lower()
    for needle, label in (
        ("lpa receiver", "LPA receiver"),
        ("mortgagee in possession", "Mortgagee in possession"),
        ("mortgagee", "Mortgagee"),
        ("administrator", "Administrator"),
        ("liquidator", "Liquidator"),
        ("receiver", "Receiver"),
        ("executor", "Executor"),
        ("probate", "Probate / estate"),
        ("trustee in bankruptcy", "Trustee in bankruptcy"),
        ("fund disposal", "Fund disposal"),
    ):
        if needle in low:
            return label
    return None


def _extract_professional_contacts(text: str) -> list[dict]:
    """Extract business/professional contacts appearing in the supplied legal evidence.

    The tracker deliberately does not attempt to enrich or discover private personal
    contact details outside the documents. It surfaces auctioneer, solicitor, managing
    agent and similar professional contacts that are actually present in the pack.
    """
    lines = [" ".join(x.split()) for x in (text or "").splitlines() if x.strip()]
    email_re = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
    phone_re = re.compile(r"(?:(?:\+44\s?\(?0?\)?|0)\d{2,4}[\s.\-]?\d{3,4}[\s.\-]?\d{3,4})")
    role_terms = (
        ("seller's solicitor", "Seller solicitor"), ("sellers solicitor", "Seller solicitor"),
        ("vendor's solicitor", "Seller solicitor"), ("vendor solicitor", "Seller solicitor"),
        ("solicitor", "Solicitor"), ("conveyancer", "Conveyancer"),
        ("auctioneer", "Auctioneer"), ("managing agent", "Managing agent"),
        ("management company", "Management company"), ("freeholder", "Freeholder/landlord contact"),
        ("landlord", "Freeholder/landlord contact"),
    )
    out, seen = [], set()
    for i, line in enumerate(lines):
        window = " | ".join(lines[max(0, i-2):min(len(lines), i+3)])
        emails = email_re.findall(window)
        phones = phone_re.findall(window)
        if not emails and not phones:
            continue
        low = window.lower()
        role = next((label for needle, label in role_terms if needle in low), None)
        # Known auction-house business domains outrank nearby generic words such as
        # "solicitors" in a property listing. This prevents the auctioneer's contact
        # details being incorrectly labelled as the seller's solicitor.
        business_probe = " ".join(emails).lower() + " " + low
        if any(domain in business_probe for domain in (
            "auctionhouse.co.uk", "allsop.co.uk", "savills.com", "savills.co.uk", "eddisons.com"
        )) or any(name in low for name in (
            "btg eddisons", "eddisons property", "auction house north west", "auction house london",
            "allsop auction", "savills auction"
        )):
            role = "Auctioneer"
        if not role:
            # Do not surface an isolated personal email/phone with no professional context.
            continue
        key = (role, tuple(sorted(set(emails))), tuple(sorted(set(phones))))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "role": role,
            "email": emails[0] if emails else None,
            "phone": phones[0] if phones else None,
            "context": _clean_line(window, 320),
        })
        if len(out) >= 8:
            break
    return out


def extract_legal_fields(text: str, fallback_lease_years=None) -> tuple[dict, list[dict]]:
    text = text or ""
    title_number = _first_text([
        r"(?:title\s*(?:number|no\.?))\s*[:\-]?\s*([A-Z]{1,4}\s?\d{3,10})",
    ], text, 40)
    proprietor_raw = _first_text([
        r"\bPROPRIETOR(?:S)?\s*:\s*([^\n]{3,260})",
        r"\bRegistered proprietor(?:s)?\s*:\s*([^\n]{3,260})",
    ], text)
    seller_raw = _first_text([
        r"\b(?:the\s+)?(?:Seller|Vendor)[\s\u2018\u2019\u201c\u201d\"']*(?:is|:)\s*([^\n]{3,260})",
        r"\b(?:Seller|Vendor)\s*:\s*([^\n]{3,260})",
    ], text)
    proprietor_name = proprietor_raw
    if proprietor_name:
        proprietor_name = re.split(r"\s+(?:of|whose registered office is)\s+", proprietor_name, maxsplit=1, flags=re.I)[0]
        proprietor_name = re.sub(r"\s*\((?:Co\.?\s*Regn\.?|Company).*?$", "", proprietor_name, flags=re.I).strip(" ,;.-")
    seller_name = seller_raw
    if seller_name:
        seller_name = re.split(r"\s+(?:of|whose registered office is)\s+", seller_name, maxsplit=1, flags=re.I)[0].strip(" ,;.-")

    registered_office = _first_text([
        r"whose registered office is(?: at)?\s+([^\n;]{5,260})",
        r"registered office(?: is| is at)?\s*[:\-]?\s*([^\n;]{5,260})",
    ], text)
    company_number = _first_text([
        r"(?:company\s*(?:number|no\.?|registration\s*number)|co\.?\s*regn\.?\s*no\.?)\s*[:.)\-]?\s*([A-Z0-9]{6,10})",
        r"\bCompany\s+registered\s+number\s+([A-Z0-9]{6,10})",
    ], text, 20)
    lease_remaining, lease_start, lease_term = _remaining_lease_years(text, fallback_lease_years)
    price_paid = None
    price_paid_date = None
    price_match = re.search(
        r"price\s+(?:stated\s+to\s+have\s+been\s+)?paid(?:\s+on\s+([^\n]{4,45}?))?\s+(?:was|of|:)\s*(?:£|GBP\s*)\s*([\d,]+(?:\.\d+)?)",
        text, re.I,
    )
    if price_match:
        try:
            price_paid = float(price_match.group(2).replace(",", ""))
        except Exception:
            price_paid = None
        if price_match.group(1):
            try:
                price_paid_date = date_parser.parse(_clean_line(price_match.group(1), 45), dayfirst=True, fuzzy=True).date().isoformat()
            except Exception:
                price_paid_date = _clean_line(price_match.group(1), 45)
    ground_rent, ground_context = _money_near(r"ground\s+rent", text)
    service_charge, service_context = _money_near(r"service\s+charge", text)
    sellers_costs, sellers_costs_context = _money_near(r"(?:seller|vendor).{0,50}(?:legal|search|cost|fee)", text)
    registered_charges = len(re.findall(r"\bREGISTERED\s+CHARGE\b", text, re.I))
    arrears_positive = bool(re.search(r"(?:\barrears\b|outstanding\s+(?:service\s+charge|ground\s+rent|rent))", text, re.I))
    arrears_negative_only = bool(re.search(r"\b(?:no|nil|zero)\s+(?:known\s+)?(?:service\s+charge\s+|ground\s+rent\s+|rent\s+)?arrears\b", text, re.I))
    arrears_flag = arrears_positive and not arrears_negative_only
    ews1_flag = bool(re.search(r"\bEWS1\b|external\s+wall\s+system|cladding", text, re.I))
    fire_safety_flag = bool(re.search(r"fire\s+risk\s+assessment|building\s+safety\s+act|fire\s+safety", text, re.I))
    tenancy_rent, tenancy_rent_context = _money_near(r"(?:current\s+)?(?:rent|rental\s+income|passing\s+rent)", text)
    tenancy_type = None
    if re.search(r"assured\s+shorthold|\bAST\b", text, re.I):
        tenancy_type = "Assured Shorthold Tenancy (AST)"
    elif re.search(r"assured\s+tenancy", text, re.I):
        tenancy_type = "Assured tenancy"
    elif re.search(r"commercial\s+lease|business\s+tenancy|contracted\s+out", text, re.I):
        tenancy_type = "Commercial/business tenancy"
    elif re.search(r"tenanted|tenant\s+in\s+occupation|occupational\s+lease", text, re.I):
        tenancy_type = "Occupational tenancy"
    tenancy_rent_period = None
    if tenancy_rent_context:
        if re.search(r"per\s+calendar\s+month|\bpcm\b|per\s+month", tenancy_rent_context, re.I):
            tenancy_rent_period = "month"
        elif re.search(r"per\s+annum|per\s+year|\bp\.?a\.?\b", tenancy_rent_context, re.I):
            tenancy_rent_period = "year"
        elif re.search(r"per\s+week|\bpw\b", tenancy_rent_context, re.I):
            tenancy_rent_period = "week"
    tenancy_end_date = _first_text([
        r"(?:tenancy|lease).{0,50}?(?:expires|expiry|ending|ends)\s*(?:on)?\s*[:\-]?\s*([^\n;]{6,40})",
        r"term\s+expir(?:es|y)\s*(?:on)?\s*[:\-]?\s*([^\n;]{6,40})",
    ], text, 40)
    reserve_fund_flag = bool(re.search(r"reserve\s+fund|sinking\s+fund", text, re.I))
    section20_flag = bool(re.search(r"section\s*20|major\s+works", text, re.I))
    assignment_restriction_flag = bool(re.search(r"licen[cs]e\s+to\s+assign|consent\s+to\s+assign|alienation", text, re.I))
    rights_easements_flag = bool(re.search(r"easement|rights?\s+of\s+way|rights\s+of\s+access|rights\s+reserved", text, re.I))
    restrictive_covenant_flag = bool(re.search(r"restrictive\s+covenant|covenant\s+not\s+to|restriction\s+on\s+use", text, re.I))
    overage_flag = bool(re.search(r"overage|clawback|uplift\s+provision", text, re.I))
    insurance_flag = bool(re.search(r"buildings?\s+insurance|insurance\s+premium|insured\s+by\s+the\s+landlord", text, re.I))
    building_regs_completion_flag = bool(re.search(
        r"building\s+(?:regulations?|control).{0,140}(?:completion|final)\s+(?:certificate|notice)|"
        r"(?:completion|final)\s+certificate.{0,140}building\s+(?:regulations?|control)", text, re.I | re.S
    ))
    building_regs_issue_flag = bool(re.search(
        r"(?:no|without|lack(?:ing)?|missing|not\s+obtained|not\s+available).{0,100}building\s+(?:regulations?|control)|"
        r"building\s+(?:regulations?|control).{0,120}(?:not\s+obtained|missing|no\s+completion|regularisation|indemnity)", text, re.I | re.S
    ))
    mining_search_present = bool(re.search(r"coal\s+mining\s+search|mining\s+search|\bCON29M\b", text, re.I))
    mining_issue_flag = bool(re.search(
        r"mine\s*shaft|mine\s+entry|ground\s+movement|mining\s+subsidence|"
        r"coal\s+mining.{0,120}(?:affected|risk|hazard|entry|subsidence)", text, re.I | re.S
    ))

    extracted = {
        "title_number": title_number,
        "proprietor_name": proprietor_name,
        "seller_name": seller_name or proprietor_name,
        "seller_type": _seller_type(text),
        "company_number": company_number,
        "registered_office": registered_office,
        "title_price_paid": price_paid,
        "title_price_paid_date": price_paid_date,
        "lease_years_remaining": lease_remaining,
        "lease_start_date": lease_start,
        "lease_term_years": lease_term,
        "ground_rent_amount": ground_rent,
        "ground_rent_context": ground_context,
        "service_charge_amount": service_charge,
        "service_charge_context": service_context,
        "seller_costs_amount": sellers_costs,
        "seller_costs_context": sellers_costs_context,
        "registered_charge_count": registered_charges,
        "arrears_flag": arrears_flag,
        "ews1_or_cladding_flag": ews1_flag,
        "fire_safety_flag": fire_safety_flag,
        "tenancy_type": tenancy_type,
        "tenancy_rent_amount": tenancy_rent,
        "tenancy_rent_period": tenancy_rent_period,
        "tenancy_rent_context": tenancy_rent_context,
        "tenancy_end_date": tenancy_end_date,
        "reserve_fund_flag": reserve_fund_flag,
        "section20_or_major_works_flag": section20_flag,
        "assignment_restriction_flag": assignment_restriction_flag,
        "rights_easements_flag": rights_easements_flag,
        "restrictive_covenant_flag": restrictive_covenant_flag,
        "overage_clawback_flag": overage_flag,
        "insurance_wording_flag": insurance_flag,
        "building_regs_completion_flag": building_regs_completion_flag,
        "building_regs_issue_flag": building_regs_issue_flag,
        "mining_search_present": mining_search_present,
        "mining_issue_flag": mining_issue_flag,
    }
    return extracted, _extract_professional_contacts(text)




def _evidence_location(documents: list[dict], pattern: str, label: str, value=None) -> dict | None:
    """Locate a finding in a specific legal document and page where possible."""
    rx = re.compile(pattern, re.I | re.S)
    for doc in documents or []:
        text = str(doc.get("text_content") or "")
        m = rx.search(text)
        if not m:
            continue
        before = text[:m.start()]
        pages = list(re.finditer(r"--- PAGE (\d+) ---", before))
        page = int(pages[-1].group(1)) if pages else None
        start = max(0, m.start() - 110)
        end = min(len(text), m.end() + 150)
        excerpt = _clean_line(re.sub(r"--- PAGE \d+ ---", " ", text[start:end]), 360)
        return {
            "finding": label, "value": value, "document": doc.get("name") or "Legal document",
            "page": page, "excerpt": excerpt, "doc_type": doc.get("doc_type"),
        }
    return None


def _normalise_title_number(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _document_title_numbers(doc: dict) -> set[str]:
    """Return Land Registry-style title numbers evidenced by one document."""
    text = str(doc.get("text_content") or "")
    name = str(doc.get("name") or "")
    out = set()
    for m in re.finditer(r"(?:title\s*(?:number|no\.?))\s*[:\-]?\s*([A-Z]{1,4}\s?\d{3,10})", text, re.I):
        out.add(_normalise_title_number(m.group(1)))
    # Auction archives often embed the title number in a compressed filename,
    # immediately after markers such as TITLEPLAN/OCE/LEASE.
    compact_name = re.sub(r"[^A-Za-z0-9]", "", name)
    for m in re.finditer(
        r"(?:TITLEPLAN|OCE|COPYLEASE\d{0,8}|LEASE\d{0,8}|HEADLEASE\d{0,8})([A-Z]{1,4}\d{3,10})",
        compact_name, re.I
    ):
        out.add(_normalise_title_number(m.group(1)))
    for m in re.finditer(r"\b([A-Z]{1,4}\d{3,10})\b", name, re.I):
        out.add(_normalise_title_number(m.group(1)))
    return {x for x in out if x}


def _doc_matches_subject_title(doc: dict, subject_title_number: str | None) -> bool:
    subject = _normalise_title_number(subject_title_number)
    if not subject:
        return True
    return subject in _document_title_numbers(doc)


def _subject_title_number(documents: list[dict], listing_fields: dict) -> str | None:
    """Resolve the title being sold, preferring lot-specific evidence over superior titles."""
    listing_title = _normalise_title_number(listing_fields.get("title_number"))
    if listing_title:
        return listing_title
    for doc in documents:
        if str(doc.get("doc_type") or "") != "Special conditions":
            continue
        fields, _ = extract_legal_fields(str(doc.get("text_content") or ""), fallback_lease_years=None)
        title = _normalise_title_number(fields.get("title_number"))
        if title:
            return title
    # A subject lease/title plan often contains the sold title even where the listing omitted it.
    for dtype in ("Lease", "Title plan"):
        candidates = [d for d in documents if str(d.get("doc_type") or "") == dtype and "head lease" not in str(d.get("name") or "").lower().replace("_", " ")]
        numbers = {n for d in candidates for n in _document_title_numbers(d)}
        if len(numbers) == 1:
            return next(iter(numbers))
    return None


def _core_doc_present(documents: list[dict], dtype: str, subject_title_number: str | None) -> bool:
    candidates = [d for d in documents if str(d.get("doc_type") or "") == dtype]
    if not candidates:
        return False
    if dtype in {"Special conditions", "Addendum"}:
        return True
    subject = _normalise_title_number(subject_title_number)
    if not subject:
        return True
    return any(_doc_matches_subject_title(d, subject) for d in candidates)


def _pack_completeness(documents: list[dict], extracted_fields: dict, subject_title_number: str | None = None) -> tuple[int, list[str], list[str]]:
    """Return core-pack completeness for the actual title being sold.

    Superior freehold/headlease registers are useful supporting evidence, but they must
    never satisfy the subject property's Title Register requirement.
    """
    available, missing = [], []
    checks = [
        ("Title register", "Title register"),
        ("Title plan", "Title plan"),
        ("Special conditions", "Special conditions"),
    ]
    subject_lease_present = _core_doc_present(documents, "Lease", subject_title_number)
    if (
        extracted_fields.get("lease_years_remaining") is not None
        or extracted_fields.get("lease_term_years") is not None
        or subject_lease_present
    ):
        checks.append(("Lease", "Lease"))
    present_count = 0
    for dtype, label in checks:
        if _core_doc_present(documents, dtype, subject_title_number):
            available.append(label)
            present_count += 1
        else:
            missing.append(label)
    if _core_doc_present(documents, "Addendum", subject_title_number):
        available.append("Addendum")
    parsed = sum(1 for d in documents if d.get("text_content"))
    if parsed:
        available.append(f"{parsed} document(s) text-readable")
    base = max(1, len(checks))
    score = int(round(100 * (present_count / base)))
    if parsed == 0:
        score = 0
    return min(100, score), missing, available

def analyse_legal_documents(documents: list[dict], extra_text: str = "") -> dict:
    """Analyse legal evidence while enforcing strict source tiers.

    Only documents explicitly verified as belonging to the selected auction lot may
    drive legal risk, seller/company identity, pack completeness or bid-readiness.
    Auctioneer listing/detail text is retained as Tier-2 property evidence and may
    provide labelled signals, but it cannot confirm legal conclusions.
    """
    documents = list(documents or [])
    # Work on local copies so a smarter classifier never mutates the persisted source row.
    verified_docs = [copy.deepcopy(d) for d in verified_legal_documents(documents)]
    for doc in verified_docs:
        current_type = str(doc.get("doc_type") or "")
        if current_type in {"", "Legal document", "Uploaded legal document", "Official copy", "Unclassified"}:
            inferred = classify_document(
                str(doc.get("name") or ""),
                str(doc.get("url") or ""),
                str(doc.get("text_content") or ""),
            )
            if inferred != "Legal document":
                doc["doc_type"] = inferred

    verified_texts = [str(d.get("text_content") or "") for d in verified_docs if d.get("text_content")]
    verified_text = "\n".join(verified_texts)
    listing_text = str(extra_text or "")

    all_verified_fields, contacts = extract_legal_fields(verified_text, fallback_lease_years=None) if verified_text else ({}, [])
    listing_fields, _ignored_listing_contacts = extract_legal_fields(listing_text, fallback_lease_years=None) if listing_text else ({}, [])
    subject_title_number = _subject_title_number(verified_docs, listing_fields)

    # Identity fields must come from the title actually being sold.  Superior freehold
    # and headlease registers are valuable context but can name a different proprietor.
    subject_register_docs = [
        d for d in verified_docs
        if str(d.get("doc_type") or "") == "Title register"
        and _doc_matches_subject_title(d, subject_title_number)
    ]
    subject_register_text = "\n".join(str(d.get("text_content") or "") for d in subject_register_docs)
    subject_register_fields, _ = extract_legal_fields(subject_register_text, fallback_lease_years=None) if subject_register_text else ({}, [])
    special_conditions_docs = [d for d in verified_docs if str(d.get("doc_type") or "") == "Special conditions"]
    special_conditions_text = "\n".join(str(d.get("text_content") or "") for d in special_conditions_docs)
    special_fields, _ = extract_legal_fields(special_conditions_text, fallback_lease_years=None) if special_conditions_text else ({}, [])

    verified_fields = dict(all_verified_fields)
    if subject_title_number:
        verified_fields["title_number"] = subject_title_number
    for key in ("proprietor_name", "title_price_paid", "title_price_paid_date"):
        verified_fields[key] = subject_register_fields.get(key)
    verified_fields["registered_charge_count"] = subject_register_fields.get("registered_charge_count") or 0
    # The seller named in Special Conditions is safer than a company/solicitor name
    # found elsewhere in a mixed legal pack.
    verified_fields["seller_name"] = special_fields.get("seller_name") or subject_register_fields.get("proprietor_name")
    verified_fields["company_number"] = subject_register_fields.get("company_number") or special_fields.get("company_number")
    verified_fields["registered_office"] = subject_register_fields.get("registered_office") or special_fields.get("registered_office")

    def present(value):
        return value not in (None, "", False, [], {})

    # Identity/ownership fields are deliberately legal-document-only.  A company
    # number found on an auctioneer/provider website must never be treated as the
    # seller's company number.
    legal_only_identity = {
        "proprietor_name", "seller_name", "company_number", "registered_office",
        "title_price_paid", "title_price_paid_date", "registered_charge_count",
    }
    # A small set of auctioneer facts can be shown as clearly-labelled signals until
    # the pack confirms them.  They do not make the legal pack VERIFIED.
    listing_signal_fields = {
        "seller_type", "title_number", "lease_years_remaining", "lease_start_date",
        "lease_term_years", "tenancy_type", "tenancy_rent_amount", "tenancy_rent_period",
        "tenancy_rent_context", "tenancy_end_date",
    }

    all_keys = set(verified_fields) | set(listing_fields)
    extracted_fields = {}
    field_sources = {}
    for key in all_keys:
        v = verified_fields.get(key)
        l = listing_fields.get(key)
        if present(v):
            extracted_fields[key] = v
            field_sources[key] = "verified legal document"
        elif key in listing_signal_fields and present(l):
            extracted_fields[key] = l
            field_sources[key] = "auctioneer property evidence"
        elif key in legal_only_identity:
            # Never copy these from listing/provider text.
            extracted_fields[key] = None if key != "registered_charge_count" else 0
        else:
            # Risk/liability flags remain legal-only. False/None is safer than a
            # generic website keyword creating a legal conclusion.
            extracted_fields[key] = v if v is not None else (False if isinstance(l, bool) else None)

    extracted_fields["field_sources"] = field_sources
    extracted_fields["company_identity_verified"] = bool(
        field_sources.get("company_number") == "verified legal document" or
        field_sources.get("seller_name") == "verified legal document" or
        field_sources.get("proprietor_name") == "verified legal document"
    )
    if extracted_fields.get("seller_type"):
        extracted_fields["seller_type_evidence"] = (
            "confirmed in verified legal document"
            if field_sources.get("seller_type") == "verified legal document"
            else "auctioneer listing signal - legal confirmation outstanding"
        )

    flags, seen = [], set()
    for pattern, severity, label in RISK_PATTERNS:
        if verified_text and re.search(pattern, verified_text, re.I | re.S) and label not in seen:
            flags.append({"severity": severity, "label": label})
            seen.add(label)

    # Lot-specific Special Conditions override generic auction-information wording.
    # This matters for novice buyers: a catalogue may say completion is usually 28
    # days while the actual lot contract can require 14 days.
    terms_text = special_conditions_text or verified_text
    completion_days = _first_number(r"completion.{0,100}?(\d{1,3})\s*(?:working\s*)?days", terms_text, 1, 180) if terms_text else None
    deposit_pct = _first_number(r"deposit.{0,80}?(\d{1,2}(?:\.\d+)?)\s*%", terms_text, 0, 100) if terms_text else None
    lease_years = extracted_fields.get("lease_years_remaining")
    fee_text = special_conditions_text or verified_text
    buyer_fee = _first_number(
        r"(?:buyer(?:'s)?\s*(?:fee|premium|administration fee)|administration fee).{0,60}?£\s*([\d,]+(?:\.\d+)?)",
        fee_text.replace(",", ""), 0, 1_000_000
    ) if fee_text else None
    has_addendum = any((d.get("doc_type") or "").lower() == "addendum" for d in verified_docs)
    vat_flag = bool(verified_text and re.search(
        r"vat.{0,80}(?:payable|chargeable|applicable)|option to tax|opted to tax", verified_text, re.I | re.S
    ))

    if verified_fields.get("ews1_or_cladding_flag") and "EWS1 / cladding / external-wall wording" not in seen:
        flags.append({"severity": 4, "label": "EWS1 / cladding / external-wall wording"})
        seen.add("EWS1 / cladding / external-wall wording")
    if verified_fields.get("arrears_flag") and "Arrears / outstanding sums require apportionment review" not in seen:
        flags.append({"severity": 3, "label": "Arrears / outstanding sums require apportionment review"})
        seen.add("Arrears / outstanding sums require apportionment review")

    # Only a VERIFIED legal lease term can suppress/create a legal short-lease risk.
    verified_remaining = verified_fields.get("lease_years_remaining")
    if verified_remaining is not None and verified_remaining >= 80:
        contradictory = {"Possible sub-80-year lease", "Short lease", "Lease appears to have fewer than 80 years remaining"}
        flags = [f for f in flags if f.get("label") not in contradictory]
        seen -= contradictory
    elif verified_remaining is not None and verified_remaining < 80 and "Lease appears to have fewer than 80 years remaining" not in seen:
        flags.append({"severity": 5, "label": "Lease appears to have fewer than 80 years remaining"})
        seen.add("Lease appears to have fewer than 80 years remaining")

    total_document_count = len(documents)
    candidate_count = sum(1 for d in documents if evidence_tier(d) == TIER_CANDIDATE)
    rejected_count = sum(1 for d in documents if evidence_tier(d) == TIER_REJECTED)
    pack_index_count = sum(1 for d in documents if evidence_tier(d) == TIER_VERIFIED_PACK_INDEX)
    verified_count = len(verified_docs)
    parsed_count = sum(1 for d in verified_docs if d.get("text_content"))
    severity_total = sum(int(x["severity"]) for x in flags)
    risk_score = round(min(10.0, severity_total / 2.2), 1) if parsed_count else 0.0
    if has_addendum and parsed_count:
        flags.append({"severity": 1, "label": "Addendum detected - confirm the latest version immediately before bidding"})
        risk_score = min(10.0, round(risk_score + 0.5, 1))

    if parsed_count:
        status = "verified"
    elif verified_count:
        status = "verified-no-text"
    elif total_document_count:
        status = "candidates-only"
    else:
        status = "not-found"

    completeness_pct, missing_components, available_components = _pack_completeness(
        verified_docs, extracted_fields, subject_title_number
    )
    evidence = []
    evidence_specs = [
        (r"(?:title\s*(?:number|no\.?))\s*[:\-]?\s*[A-Z]{1,4}\s?\d{3,10}", "Title number", verified_fields.get("title_number")),
        (r"(?:PROPRIETOR(?:S)?|Registered proprietor(?:s)?)\s*:\s*[^\n]{3,260}", "Registered proprietor", verified_fields.get("proprietor_name")),
        (r"(?:Seller|Vendor)\s*:\s*[^\n]{3,260}", "Seller", verified_fields.get("seller_name")),
        (r"(?:company\s*(?:number|no\.?|registration\s*number)|co\.?\s*regn\.?\s*no\.?).{0,25}[A-Z0-9]{6,10}", "Company number", verified_fields.get("company_number")),
        (r"registered office.{0,260}", "Registered office", verified_fields.get("registered_office")),
        (r"price\s+(?:stated\s+to\s+have\s+been\s+)?paid.{0,100}?(?:£|GBP)", "Title price paid", verified_fields.get("title_price_paid")),
        (r"(?:unexpired|remaining).{0,60}?\d{1,3}(?:\.\d+)?\s*years|\d{1,3}\s*years?\s+(?:from|commencing|beginning)", "Lease term", verified_fields.get("lease_years_remaining")),
        (r"ground\s+rent.{0,120}?(?:£|GBP)", "Ground rent", verified_fields.get("ground_rent_amount")),
        (r"service\s+charge.{0,120}?(?:£|GBP)", "Service charge", verified_fields.get("service_charge_amount")),
        (r"completion.{0,100}?\d{1,3}\s*(?:working\s*)?days", "Completion period", completion_days),
        (r"deposit.{0,80}?\d{1,2}(?:\.\d+)?\s*%", "Deposit", deposit_pct),
        (r"vat.{0,80}(?:payable|chargeable|applicable)|option to tax|opted to tax", "VAT / option to tax", "Detected" if vat_flag else None),
        (r"assured\s+shorthold|\bAST\b|commercial\s+lease|business\s+tenancy|tenanted", "Tenancy / occupation", verified_fields.get("tenancy_type")),
        (r"(?:current\s+)?(?:rent|rental\s+income|passing\s+rent).{0,100}?(?:£|GBP)", "Passing rent", verified_fields.get("tenancy_rent_amount")),
        (r"section\s*20|major\s+works", "Section 20 / major works", "Detected" if verified_fields.get("section20_or_major_works_flag") else None),
        (r"reserve\s+fund|sinking\s+fund", "Reserve / sinking fund", "Detected" if verified_fields.get("reserve_fund_flag") else None),
        (r"restrictive\s+covenant|covenant\s+not\s+to|restriction\s+on\s+use", "Restrictive covenant", "Detected" if verified_fields.get("restrictive_covenant_flag") else None),
        (r"easement|rights?\s+of\s+way|rights\s+of\s+access|rights\s+reserved", "Rights / easements", "Detected" if verified_fields.get("rights_easements_flag") else None),
        (r"overage|clawback|uplift\s+provision", "Overage / clawback", "Detected" if verified_fields.get("overage_clawback_flag") else None),
        (r"building\s+(?:regulations?|control).{0,140}(?:completion|final)\s+(?:certificate|notice)|(?:completion|final)\s+certificate.{0,140}building", "Building Regulations completion evidence", "Detected" if verified_fields.get("building_regs_completion_flag") else None),
        (r"coal\s+mining\s+search|mining\s+search|\bCON29M\b", "Coal / mining search", "Detected" if verified_fields.get("mining_search_present") else None),
    ]
    for pattern, label, value in evidence_specs:
        if value in (None, "", False):
            continue
        found = _evidence_location(verified_docs, pattern, label, value)
        if found:
            found["evidence_tier"] = TIER_VERIFIED_LEGAL
            evidence.append(found)

    for pattern, _severity, label in RISK_PATTERNS:
        flag = next((f for f in flags if f.get("label") == label), None)
        if not flag:
            continue
        found = _evidence_location(verified_docs, pattern, label)
        if found:
            flag["document"] = found.get("document")
            flag["page"] = found.get("page")
            flag["excerpt"] = found.get("excerpt")
            flag["evidence_tier"] = TIER_VERIFIED_LEGAL

    warnings = [
        "Legal documents can be incomplete, revised or replaced. Confirm the latest complete pack and addendum with the auctioneer/solicitor before bidding."
    ]
    if total_document_count and not verified_count:
        warnings.insert(0,
            "LEGAL PACK NOT VERIFIED: candidate links were discovered, but no authoritative lot-bound legal documents passed the evidence firewall. Legal risk remains UNKNOWN."
        )
    if verified_count and not parsed_count:
        warnings.insert(0,
            "Lot-bound legal documents were verified, but no extractable text was available. Legal risk remains UNKNOWN until the originals are reviewed manually."
        )
    if rejected_count:
        warnings.insert(0,
            f"Property Identity Lock rejected {rejected_count} candidate document(s) because they were unclassified legal evidence or did not match the selected lot. Rejected material cannot influence the deal."
        )

    return {
        "provider": "Verified auction legal evidence / auctioneer property evidence",
        "status": status,
        "verification_status": status,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        "risk_score": risk_score,
        "document_count": total_document_count,
        "candidate_document_count": candidate_count,
        "rejected_document_count": rejected_count,
        "pack_index_count": pack_index_count,
        "verified_document_count": verified_count,
        "parsed_document_count": parsed_count,
        "auctioneer_evidence_count": 1 if listing_text else 0,
        "completion_days": completion_days,
        "deposit_pct": deposit_pct,
        "lease_years": lease_years,
        "buyer_fee_detected": buyer_fee,
        "vat_flag": vat_flag,
        "has_addendum": has_addendum,
        "extracted_fields": extracted_fields,
        "contacts": contacts,
        "risk_flags": flags,
        "evidence": evidence,
        "pack_completeness_pct": completeness_pct,
        "missing_components": missing_components,
        "available_components": available_components,
        "pack_fingerprint": legal_pack_fingerprint(verified_docs),
        "pack_changed": False,
        "pack_change": {},
        "methodology": (
            "v1.10.3 Evidence Revalidation & Purge: every automatic document must pass the current legal-document class gate and lot-specific Property Identity Lock before it may drive legal risk, ownership/company identity, rent, contacts, buyer costs, pack completeness or bid approval. "
            "Historic automatic evidence is revalidated on refresh; downgraded/cross-property material is quarantined and all derived findings are rebuilt from verified evidence only."
        ),
        "warnings": warnings,
        "attribution": LEGAL_ATTRIBUTION,
    }

def analyse_online_legal_pack(lot: dict, session=None, access_config: LegalAccessConfig | None = None) -> tuple[dict, list[dict]]:
    url = str(lot.get("url") or "")
    if not url.startswith(("http://", "https://")):
        summary = analyse_legal_documents([], str(lot.get("detail_text") or ""))
        summary["status"] = "unavailable"
        summary["warnings"].append("No public lot URL is available for legal-pack discovery.")
        return summary, []
    docs, warnings = fetch_legal_documents(lot, session=session, access_config=access_config)
    summary = analyse_legal_documents(docs, str(lot.get("detail_text") or ""))
    summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + warnings))
    return summary, docs


def uploaded_document(name: str, data: bytes) -> dict:
    """Parse one PDF/TXT legal document and keep transient raw bytes for cloud retention."""
    name = name or "uploaded document"
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("Uploaded document is too large for analysis (12 MB maximum per file).")
    lower = name.lower()
    if lower.endswith(".pdf") or data[:4] == b"%PDF":
        text = extract_pdf_text(data)
    else:
        text = data.decode("utf-8", errors="ignore")[:MAX_DOC_CHARS]
    doc_type = classify_document(name, text=text)
    if doc_type == "Legal document":
        doc_type = "Uploaded legal document"
    return {
        "name": name,
        "url": "",
        "doc_type": doc_type,
        "access_status": "uploaded and parsed" if text else "uploaded; no extractable text",
        "text_content": text,
        "sha256": hashlib.sha256(data).hexdigest(),
        "metadata": {
            "origin": "user-upload", "original_filename": name,
            "evidence_tier": TIER_VERIFIED_LEGAL, "verified_for_lot": True,
            "verification_reasons": ["user explicitly uploaded this document against the selected property"],
            "identity_status": "user-attested", "identity_score": None,
            "document_class": doc_type, "document_class_allowed": True,
            "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        },
        "_raw_bytes": data,
    }


def uploaded_documents(name: str, data: bytes) -> list[dict]:
    """Parse a PDF/TXT or a ZIP legal pack containing PDF/TXT documents safely."""
    name = name or "uploaded legal pack"
    if not (name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04"):
        return [uploaded_document(name, data)]
    out = []
    total = 0
    with zipfile.ZipFile(BytesIO(data)) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError(f"ZIP contains too many files ({len(members)}); maximum is {MAX_ZIP_MEMBERS}.")
        for member in members:
            clean_name = member.filename.replace("\\", "/").split("/")[-1]
            if not clean_name or clean_name.startswith("."):
                continue
            lower = clean_name.lower()
            if not lower.endswith((".pdf", ".txt")):
                continue
            if member.file_size > MAX_DOC_BYTES:
                continue
            total += member.file_size
            if total > MAX_ZIP_TOTAL_BYTES:
                raise ValueError("ZIP legal pack exceeds the 60 MB extracted-size safety limit.")
            raw = archive.read(member)
            doc = uploaded_document(clean_name, raw)
            doc["metadata"]["uploaded_container"] = name
            out.append(doc)
    if not out:
        raise ValueError("No supported PDF or TXT legal documents were found in the ZIP.")
    return out
