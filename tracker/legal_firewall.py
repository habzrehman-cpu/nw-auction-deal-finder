"""Evidence-boundary helpers for legal-pack acquisition.

This module implements the v1.10.1 legal-evidence firewall.  It distinguishes
candidate links, lot-specific legal-pack index pages, verified legal documents,
and auctioneer/listing evidence.  Only verified legal documents may drive legal
risk, seller identity, Companies House enrichment, or bid-readiness decisions.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

EVIDENCE_POLICY_VERSION = "1.10.1-firewall"
TIER_VERIFIED_LEGAL = "verified-legal-document"
TIER_VERIFIED_PACK_INDEX = "verified-legal-pack-index"
TIER_AUCTIONEER = "auctioneer-property-evidence"
TIER_CANDIDATE = "candidate-unverified"
TIER_CONTEXTUAL = "external-contextual"

VERIFIED_LEGAL_TYPES = {
    "Legal pack", "Special conditions", "Title register", "Title plan", "Lease",
    "Addendum", "EPC", "Uploaded legal document", "Legal document",
}

# Used for the first hop from a known auction-lot page.  Deliberately excludes
# generic terms such as "lease" and "property search" which commonly occur in
# auctioneers' navigation and advisory content.
STRONG_PACK_HINT_RE = re.compile(
    r"legal\s*pack|legal\s*documents?|download\s+legal|special\s*conditions?|"
    r"title\s*register|title\s*plan|official\s*copy|addendum|auction\s*passport|"
    r"contract\s+pack|auction\s+contract",
    re.I,
)

GENERIC_SITE_RE = re.compile(
    r"lease\s+advisory|property\s+search|business\s+sales|education|investor\s+relations|"
    r"professional\s+advisory|consultancy|news|careers|about\s+us|contact\s+us|"
    r"valuation|services|our\s+services",
    re.I,
)

STOP_ADDRESS_WORDS = {
    "road", "street", "lane", "avenue", "drive", "close", "way", "court", "place",
    "house", "flat", "apartment", "unit", "building", "property", "retail", "industrial",
    "commercial", "land", "development", "greater", "manchester", "lancashire", "cumbria",
    "cheshire", "merseyside", "england", "north", "west", "the", "and", "for", "sale",
}


def normalise_postcode(value: str) -> str:
    return "".join(str(value or "").upper().split())


def _address_tokens(lot: dict) -> set[str]:
    text = str(lot.get("address") or lot.get("title") or "")
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9]{3,}", text.lower()):
        if token in STOP_ADDRESS_WORDS:
            continue
        if token.isdigit() and len(token) > 5:
            continue
        tokens.add(token)
    return tokens


def lot_identity(lot: dict) -> dict:
    return {
        "postcode": normalise_postcode(lot.get("postcode") or ""),
        "lot_number": str(lot.get("lot_number") or "").strip(),
        "address_tokens": _address_tokens(lot),
        "lot_url": str(lot.get("url") or ""),
    }


def lot_identity_match(lot: dict, text: str = "", url: str = "") -> tuple[int, list[str]]:
    """Return a conservative property-identity score and reasons.

    A postcode match is intentionally dominant.  Lot-number matching requires
    nearby 'lot' wording.  Address-token matching needs at least two uncommon
    tokens so a city/auction-house name cannot accidentally verify a page.
    """
    ident = lot_identity(lot)
    probe_text = " ".join(str(text or "").split())
    probe_upper = probe_text.upper()
    probe_pc = re.sub(r"\s+", "", probe_upper)
    score = 0
    reasons: list[str] = []

    pc = ident["postcode"]
    if pc and pc in probe_pc:
        score += 5
        reasons.append("subject postcode matched")

    lot_no = ident["lot_number"]
    if lot_no and re.search(rf"\blot\s*(?:no\.?\s*)?{re.escape(lot_no)}\b", probe_text, re.I):
        score += 3
        reasons.append("auction lot number matched")

    tokens = ident["address_tokens"]
    if tokens:
        low = f"{probe_text} {url}".lower()
        matched = sorted(t for t in tokens if re.search(rf"\b{re.escape(t)}\b", low))
        if len(matched) >= 3:
            score += 4
            reasons.append("subject address tokens matched")
        elif len(matched) >= 2:
            score += 2
            reasons.append("partial subject address match")

    lot_parsed = urlparse(ident["lot_url"])
    candidate_parsed = urlparse(str(url or ""))
    lot_host = lot_parsed.netloc.lower()
    candidate_host = candidate_parsed.netloc.lower()
    if lot_host and candidate_host and candidate_host == lot_host:
        score += 1
        reasons.append("same auction-provider host")

    # Provider routes often carry a stable lot token even before the page exposes
    # address/postcode text (for example /auctions/lot-1 -> /legal/lot-1).  An
    # exact shared lot token on the same provider is strong identity evidence.
    def route_lot_tokens(path: str) -> set[str]:
        return {m.group(1).lower() for m in re.finditer(r"(?:^|[/_-])lot[-_/]?([a-z0-9]{1,24})(?:$|[/_.?-])", path or "", re.I)}
    if lot_host and candidate_host == lot_host:
        shared = route_lot_tokens(lot_parsed.path) & route_lot_tokens(candidate_parsed.path)
        if shared:
            score += 5
            reasons.append("matching provider lot-route identifier")
    return score, reasons


def strong_pack_link(label: str = "", url: str = "") -> bool:
    probe = f"{label or ''} {url or ''}"
    return bool(STRONG_PACK_HINT_RE.search(probe)) and not bool(GENERIC_SITE_RE.search(probe))


def generic_site_content(label: str = "", url: str = "", text: str = "") -> bool:
    probe = f"{label or ''} {url or ''} {text or ''}"
    return bool(GENERIC_SITE_RE.search(probe))


def evidence_tier(doc: dict | None) -> str:
    doc = doc or {}
    # Backward-compatible direct/in-memory legal documents used by imports/tests can
    # omit metadata entirely. Persisted legacy rows are loaded with metadata={} and
    # therefore remain quarantined until refreshed through the firewall.
    if "metadata" not in doc and doc.get("doc_type") and (doc.get("text_content") or doc.get("sha256")):
        return TIER_VERIFIED_LEGAL
    meta = doc.get("metadata") or {}
    origin = str(meta.get("origin") or "")
    if origin == "user-upload":
        return TIER_VERIFIED_LEGAL
    return str(meta.get("evidence_tier") or TIER_CANDIDATE)


def is_verified_legal_document(doc: dict | None) -> bool:
    doc = doc or {}
    if evidence_tier(doc) != TIER_VERIFIED_LEGAL:
        return False
    meta = doc.get("metadata") or {}
    if meta.get("verified_for_lot") is False:
        return False
    return True


def mark_candidate(doc: dict, reason: str = "not yet tied to the subject lot") -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_CANDIDATE,
        "verified_for_lot": False,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    reasons = list(meta.get("verification_reasons") or [])
    if reason and reason not in reasons:
        reasons.append(reason)
    meta["verification_reasons"] = reasons
    return doc


def mark_pack_index(doc: dict, reasons: list[str] | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_VERIFIED_PACK_INDEX,
        "verified_for_lot": True,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    meta["verification_reasons"] = list(dict.fromkeys((meta.get("verification_reasons") or []) + (reasons or [])))
    return doc


def mark_verified_legal(doc: dict, reasons: list[str] | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_VERIFIED_LEGAL,
        "verified_for_lot": True,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    meta["verification_reasons"] = list(dict.fromkeys((meta.get("verification_reasons") or []) + (reasons or [])))
    return doc


def verified_legal_documents(documents: list[dict] | None) -> list[dict]:
    return [d for d in (documents or []) if is_verified_legal_document(d)]
