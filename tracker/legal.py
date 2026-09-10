"""Legal-pack discovery and lightweight auction legal risk triage.

This module does not bypass logins or registration walls. It discovers public links,
extracts text from directly accessible PDFs, and can analyse user-uploaded PDFs/TXT
files locally. Results are triage only and must be reviewed by a solicitor before bid.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

LEGAL_ATTRIBUTION = "Auctioneer/seller legal documents as published; buyer must verify the latest complete pack and obtain independent legal advice."
MAX_DOC_BYTES = 12 * 1024 * 1024
MAX_DOC_CHARS = 90_000
MAX_AUTO_DOCS = 4

LEGAL_HINT_RE = re.compile(
    r"legal\s*pack|legal\s*documents?|special\s*conditions?|addendum|title\s*register|"
    r"official\s*copy|lease|epc|energy performance|auction passport|eigroup|buyer information",
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
    (r"mining search|coal mining|mine shaft", 3, "Mining risk/search issue"),
    (r"contaminat|landfill|hazardous substance", 5, "Contamination / environmental wording"),
    (r"asbestos", 3, "Asbestos wording"),
    (r"tenanted|tenant|assured shorthold|ast\b|lease in place|occupier", 2, "Occupational rights / tenancy require review"),
    (r"service charge.{0,100}(?:arrears|balancing|deficit|major works)", 3, "Service-charge liability / major works wording"),
    (r"section 20|major works", 3, "Possible leasehold major-works liability"),
    (r"licence to assign|consent to assign|alienation", 2, "Assignment/consent restriction"),
]


def _session(session=None):
    s = session or requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 NW-Auction-Deal-Finder/1.5", "Accept-Language": "en-GB,en;q=0.9"})
    return s


def classify_document(label: str, url: str = "") -> str:
    text = f"{label} {url}"
    for pattern, name in DOC_TYPE_PATTERNS:
        if pattern.search(text):
            return name
    return "Legal document"


def discover_legal_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        label = " ".join(a.get_text(" ", strip=True).split())
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        probe = f"{label} {href}"
        if not LEGAL_HINT_RE.search(probe):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append({
            "name": label or classify_document(probe),
            "url": absolute,
            "doc_type": classify_document(label, absolute),
            "access_status": "link discovered",
            "text_content": "",
            "sha256": "",
        })
    return out[:25]


def extract_pdf_text(data: bytes, max_chars: int = MAX_DOC_CHARS) -> str:
    if not data:
        return ""
    reader = PdfReader(BytesIO(data))
    parts = []
    total = 0
    for page in reader.pages[:120]:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]


def _looks_restricted(text: str, url: str) -> bool:
    t = f"{text} {url}".lower()
    return any(x in t for x in ["sign in", "log in", "login", "register to view", "create account", "auction passport", "eigroup"])


def fetch_public_legal_documents(lot_url: str, session=None, max_docs: int = MAX_AUTO_DOCS) -> tuple[list[dict], list[str]]:
    s = _session(session)
    warnings = []
    r = s.get(lot_url, timeout=25, allow_redirects=True)
    r.raise_for_status()
    links = discover_legal_links(r.text, r.url)
    downloaded = 0
    attempted = 0
    for item in links:
        if downloaded >= max_docs or attempted >= max_docs * 2:
            break
        attempted += 1
        url = item["url"]
        try:
            doc = s.get(url, timeout=30, allow_redirects=True, stream=True)
            doc.raise_for_status()
            ctype = (doc.headers.get("Content-Type") or "").lower()
            length = int(doc.headers.get("Content-Length") or 0)
            if length and length > MAX_DOC_BYTES:
                item["access_status"] = "public link; document too large for auto-analysis"
                continue
            chunks = []
            total = 0
            too_large = False
            for chunk in doc.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOC_BYTES:
                    too_large = True
                    break
                chunks.append(chunk)
            if too_large:
                item["access_status"] = "public link; document too large for auto-analysis"
                continue
            data = b"".join(chunks)
            final_url = doc.url
            if "pdf" in ctype or final_url.lower().split("?")[0].endswith(".pdf") or data[:4] == b"%PDF":
                text = extract_pdf_text(data)
                item["text_content"] = text
                item["sha256"] = hashlib.sha256(data).hexdigest()
                item["access_status"] = "public PDF parsed" if text else "public PDF; no extractable text"
                item["url"] = final_url
                downloaded += 1
            elif "text/html" in ctype:
                soup = BeautifulSoup(data, "html.parser")
                for node in soup.select("script,style,noscript,svg,template"):
                    node.decompose()
                text = " ".join(soup.get_text(" ", strip=True).split())[:40_000]
                if _looks_restricted(text[:5000], final_url):
                    item["access_status"] = "registration/login likely required"
                elif len(text) > 500 and LEGAL_HINT_RE.search(text):
                    item["text_content"] = text
                    item["sha256"] = hashlib.sha256(data).hexdigest()
                    item["access_status"] = "public legal page parsed"
                    downloaded += 1
                else:
                    item["access_status"] = "public link; manual review required"
            else:
                item["access_status"] = "public link; unsupported document type"
        except Exception as exc:
            item["access_status"] = "link found; manual access required"
            item["error"] = str(exc)[:300]
    if links and not any(x.get("text_content") for x in links):
        warnings.append("Legal-pack link(s) were found but no public text could be parsed automatically; registration or manual download may be required.")
    if not links:
        warnings.append("No legal-pack/addendum link was detected on the public lot page. Check the auctioneer lot page manually before bidding.")
    return links, warnings


def _first_number(pattern: str, text: str, low=0, high=9999):
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    try:
        n = float(m.group(1))
        return n if low <= n <= high else None
    except (TypeError, ValueError):
        return None


def analyse_legal_documents(documents: list[dict], extra_text: str = "") -> dict:
    texts = [str(d.get("text_content") or "") for d in documents if d.get("text_content")]
    text = "\n".join(texts + [extra_text or ""])
    low = text.lower()
    flags, seen = [], set()
    for pattern, severity, label in RISK_PATTERNS:
        if re.search(pattern, text, re.I | re.S) and label not in seen:
            flags.append({"severity": severity, "label": label})
            seen.add(label)

    completion_days = _first_number(r"completion.{0,100}?(\d{1,3})\s*(?:working\s*)?days", text, 1, 180)
    deposit_pct = _first_number(r"deposit.{0,80}?(\d{1,2}(?:\.\d+)?)\s*%", text, 0, 100)
    lease_years = _first_number(r"(?:lease|term|unexpired).{0,100}?(\d{1,3})\s*years", text, 1, 999)
    buyer_fee = _first_number(r"(?:buyer(?:'s)?\s*(?:fee|premium|administration fee)|administration fee).{0,60}?£\s*([\d,]+(?:\.\d+)?)", text.replace(",", ""), 0, 1_000_000)
    has_addendum = any((d.get("doc_type") or "").lower() == "addendum" for d in documents)
    vat_flag = bool(re.search(r"vat.{0,80}(?:payable|chargeable|applicable)|option to tax|opted to tax", text, re.I | re.S))
    material_types = {"Legal pack", "Special conditions", "Title register", "Title plan", "Lease", "Addendum", "Uploaded legal document"}
    parsed_count = sum(1 for d in documents if d.get("text_content") and d.get("doc_type") in material_types)
    link_count = len(documents)
    severity_total = sum(int(x["severity"]) for x in flags)
    risk_score = round(min(10.0, severity_total / 2.2), 1)
    if has_addendum:
        flags.append({"severity": 1, "label": "Addendum detected - confirm the latest version immediately before bidding"})
        risk_score = min(10.0, round(risk_score + 0.5, 1))

    if parsed_count:
        status = "parsed"
    elif link_count:
        status = "links-only"
    else:
        status = "not-found"

    return {
        "provider": "Auctioneer legal pack / uploaded documents",
        "status": status,
        "risk_score": risk_score,
        "document_count": link_count,
        "parsed_document_count": parsed_count,
        "completion_days": completion_days,
        "deposit_pct": deposit_pct,
        "lease_years": lease_years,
        "buyer_fee_detected": buyer_fee,
        "vat_flag": vat_flag,
        "has_addendum": has_addendum,
        "risk_flags": flags,
        "methodology": "Pattern-based auction legal triage across public or user-supplied legal documents. It highlights issues for solicitor review and does not determine legal acceptability.",
        "warnings": [
            "Legal documents can be incomplete, revised or replaced. Confirm the latest complete pack and addendum with the auctioneer/solicitor before bidding."
        ],
        "attribution": LEGAL_ATTRIBUTION,
    }


def analyse_online_legal_pack(lot: dict, session=None) -> tuple[dict, list[dict]]:
    url = str(lot.get("url") or "")
    if not url.startswith(("http://", "https://")):
        summary = analyse_legal_documents([], str(lot.get("detail_text") or ""))
        summary["status"] = "unavailable"
        summary["warnings"].append("No public lot URL is available for legal-pack discovery.")
        return summary, []
    docs, warnings = fetch_public_legal_documents(url, session=session)
    summary = analyse_legal_documents(docs, str(lot.get("detail_text") or ""))
    summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + warnings))
    return summary, docs


def uploaded_document(name: str, data: bytes) -> dict:
    name = name or "uploaded document"
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("Uploaded document is too large for local analysis (12 MB maximum per file).")
    lower = name.lower()
    if lower.endswith(".pdf") or data[:4] == b"%PDF":
        text = extract_pdf_text(data)
    else:
        text = data.decode("utf-8", errors="ignore")[:MAX_DOC_CHARS]
    doc_type = classify_document(name)
    if doc_type == "Legal document":
        doc_type = "Uploaded legal document"
    return {
        "name": name,
        "url": "",
        "doc_type": doc_type,
        "access_status": "uploaded and parsed" if text else "uploaded; no extractable text",
        "text_content": text,
        "sha256": hashlib.sha256(data).hexdigest(),
        "metadata": {"origin": "user-upload"},
    }
