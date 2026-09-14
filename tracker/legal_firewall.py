"""Evidence-boundary helpers for legal-pack acquisition.

v1.10.3 keeps the Property Identity Lock and adds full historic-evidence revalidation/purge.
A discovered file is not allowed to influence legal risk, ownership, rent, buyer
costs or vendor intelligence until the file itself is demonstrably tied to the
selected auction lot and is recognisable as a legal/DD document.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

EVIDENCE_POLICY_VERSION = "1.10.3-revalidation-purge"
TIER_VERIFIED_LEGAL = "verified-legal-document"
TIER_VERIFIED_PACK_INDEX = "verified-legal-pack-index"
TIER_AUCTIONEER = "auctioneer-property-evidence"
TIER_CANDIDATE = "candidate-unverified"
TIER_CONTEXTUAL = "external-contextual"
TIER_REJECTED = "rejected-cross-property"

# Core/recognisable document classes that are permitted to enter the automated
# legal analysis. A generic marketing PDF or advisory page is not enough.
VERIFIED_LEGAL_TYPES = {
    "Legal pack", "Special conditions", "Title register", "Title plan", "Lease",
    "Addendum", "EPC", "Contract", "Transfer", "Search", "Tenancy agreement",
    "Management pack", "Official copy", "Auction contract", "Uploaded legal document",
}

DOCUMENT_TYPE_PATTERNS = [
    (re.compile(r"special\s*conditions?|conditions\s+of\s+sale", re.I), "Special conditions"),
    (re.compile(r"title\s*register|official\s*copy.*register|register\s+of\s+title", re.I), "Title register"),
    (re.compile(r"title\s*plan|official\s*copy.*plan", re.I), "Title plan"),
    (re.compile(r"auction\s+contract|contract\s+for\s+sale|sale\s+contract", re.I), "Auction contract"),
    (re.compile(r"\bcontract\b", re.I), "Contract"),
    (re.compile(r"\btransfer\b|\bTP1\b|\bTR1\b", re.I), "Transfer"),
    (re.compile(r"\blease\b|underlease", re.I), "Lease"),
    (re.compile(r"tenancy\s+agreement|assured\s+shorthold|\bAST\b", re.I), "Tenancy agreement"),
    (re.compile(r"management\s+pack|LPE1|FME1", re.I), "Management pack"),
    (re.compile(r"local\s+search|environmental\s+search|drainage\s+search|search\s+result", re.I), "Search"),
    (re.compile(r"epc|energy\s+performance", re.I), "EPC"),
    (re.compile(r"addendum", re.I), "Addendum"),
    (re.compile(r"official\s+copy", re.I), "Official copy"),
    (re.compile(r"legal\s*pack|legal\s*documents?", re.I), "Legal pack"),
]

MARKETING_OR_ADVISORY_RE = re.compile(
    r"brochure|particulars|marketing|investment\s+summary|lease\s+advisory|property\s+search|"
    r"business\s+sales|education|investor\s+relations|professional\s+advisory|consultancy|"
    r"news|careers|about\s+us|contact\s+us|valuation|services|our\s+services",
    re.I,
)

# Used for the first hop from a known auction-lot page. Deliberately excludes
# generic terms such as "lease" and "property search".
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

UK_POSTCODE_RE = re.compile(
    r"\b(?:GIR\s?0AA|(?:[A-PR-UWYZ][A-HK-Y]?\d\d?|[A-PR-UWYZ]\d[A-HJKSTUW]|"
    r"[A-PR-UWYZ][A-HK-Y]\d[ABEHMNPRV-Y])\s?\d[ABD-HJLNP-UW-Z]{2})\b",
    re.I,
)

# These contexts are sufficiently explicit that a different postcode is strong
# evidence the document is about another property rather than a solicitor/owner.
SUBJECT_ADDRESS_RE = re.compile(
    r"(?:property|premises|property\s+address|address\s+of\s+(?:the\s+)?property|"
    r"known\s+as|situate(?:d)?\s+at|site\s+at|land\s+at|lot\s*\d{1,4})"
    r"[^\n]{0,220}?(?P<postcode>(?:GIR\s?0AA|(?:[A-PR-UWYZ][A-HK-Y]?\d\d?|"
    r"[A-PR-UWYZ]\d[A-HJKSTUW]|[A-PR-UWYZ][A-HK-Y]\d[ABEHMNPRV-Y])\s?\d[ABD-HJLNP-UW-Z]{2}))",
    re.I,
)

STOP_ADDRESS_WORDS = {
    "road", "street", "lane", "avenue", "drive", "close", "way", "court", "place",
    "house", "flat", "apartment", "unit", "building", "property", "retail", "industrial",
    "commercial", "land", "development", "greater", "manchester", "lancashire", "cumbria",
    "cheshire", "merseyside", "england", "north", "west", "the", "and", "for", "sale",
    "auction", "guide", "fees", "lot",
}


def normalise_postcode(value: str) -> str:
    return "".join(str(value or "").upper().split())


def extract_postcodes(text: str) -> list[str]:
    found = []
    for match in UK_POSTCODE_RE.finditer(str(text or "")):
        pc = normalise_postcode(match.group(0))
        if pc and pc not in found:
            found.append(pc)
    return found


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


def _route_lot_tokens(path: str) -> set[str]:
    return {
        m.group(1).lower()
        for m in re.finditer(r"(?:^|[/_-])lot[-_/]?([a-z0-9]{1,24})(?:$|[/_.?-])", path or "", re.I)
    }


def _normalise_document_probe(value: str) -> str:
    """Make auction-pack filenames readable to the classifier.

    Legal archives frequently contain names such as ``OfficialCopyLease...`` or
    ``LEASEHOLDOCETITLEPLAN...``.  Treating those as raw tokens caused genuine
    leases/official copies to fall through the class gate.  This normalisation is
    classification-only; it never changes the stored filename or evidence bytes.
    """
    value = str(value or "")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", value)
    value = re.sub(r"(?i)officialcopy", "official copy", value)
    value = re.sub(r"(?i)titleplan", "title plan", value)
    value = re.sub(r"(?i)headlease", "head lease", value)
    value = re.sub(r"(?i)specialconditions", "special conditions", value)
    value = re.sub(r"(?i)conditionsofsale", "conditions of sale", value)
    value = re.sub(r"[_\-./]+", " ", value)
    return " ".join(value.split())


def document_type_classification(label: str = "", url: str = "", text: str = "") -> dict:
    """Classify whether a candidate looks like a legal/DD document.

    Generic provider pages and marketing/advisory PDFs are explicitly excluded,
    even if they happen to contain words such as lease, rent or solicitor.
    """
    surface_probe = " ".join((_normalise_document_probe(label), _normalise_document_probe(url)))
    text_probe = str(text or "")[:4000]
    # Marketing/advisory blocking is based on the link/file surface, not arbitrary
    # words buried inside an otherwise genuine legal document.
    if MARKETING_OR_ADVISORY_RE.search(surface_probe):
        return {"doc_type": "Context / marketing", "allowed": False, "reason": "marketing/advisory content is not legal-pack evidence"}

    if re.search(r"\bauction\s+information\b|\bimportant\s+information\b|\bpreliminary\s+enquiries\b|\breplies\s+to\s+enquiries\b", surface_probe, re.I):
        return {"doc_type": "Uploaded legal document", "allowed": True, "reason": "recognised supporting legal-pack information document"}

    # Prefer what the file/link itself claims to be.  A generic Auction Information
    # sheet often mentions "special conditions" and must not therefore be classified
    # as the lot's Special Conditions document.
    for pattern, name in DOCUMENT_TYPE_PATTERNS:
        if pattern.search(surface_probe):
            return {"doc_type": name, "allowed": name in VERIFIED_LEGAL_TYPES, "reason": f"recognised document class from filename/link: {name}"}

    # Content fallback uses deliberately strong document-level signatures.
    strong_text_patterns = [
        (re.compile(r"(?:^|\n)\s*SPECIAL\s+CONDITIONS\s+OF\s+SALE\b", re.I), "Special conditions"),
        (re.compile(r"electronic\s+official\s+copy\s+of\s+the\s+register\s+follows|\bA:\s*Property\s+Register\b", re.I), "Title register"),
        (re.compile(r"electronic\s+official\s+copy\s+of\s+the\s+title\s+plan\s+follows", re.I), "Title plan"),
        (re.compile(r"(?:^|\n)\s*ADDENDUM\b", re.I), "Addendum"),
        (re.compile(r"electronic\s+official\s+copy\s+of\s+the\s+document\s+follows", re.I), "Official copy"),
    ]
    for pattern, name in strong_text_patterns:
        if pattern.search(text_probe):
            return {"doc_type": name, "allowed": name in VERIFIED_LEGAL_TYPES, "reason": f"recognised document class from content signature: {name}"}
    return {"doc_type": "Unclassified", "allowed": False, "reason": "document type is not recognised as legal/DD evidence"}


def document_identity_assessment(lot: dict, text: str = "", url: str = "", label: str = "") -> dict:
    """Return a 0-100 lot identity score plus hard mismatch checks.

    The score is intentionally conservative. The subject postcode carries most
    weight, while address tokens, lot number and provider route identifiers add
    corroboration. An explicit subject-property line containing a different
    postcode is an automatic cross-property rejection.
    """
    ident = lot_identity(lot)
    probe_text = " ".join(str(text or "").split())
    probe_all = f"{label or ''} {url or ''} {probe_text}"
    probe_low = probe_all.lower()
    score = 0
    reasons: list[str] = []
    conflicts: list[str] = []

    target_pc = ident["postcode"]
    all_postcodes = extract_postcodes(probe_text)
    subject_context_postcodes = []
    for match in SUBJECT_ADDRESS_RE.finditer(str(text or "")[:12000]):
        pc = normalise_postcode(match.group("postcode"))
        if pc and pc not in subject_context_postcodes:
            subject_context_postcodes.append(pc)

    hard_reject = False
    if target_pc and target_pc in all_postcodes:
        score += 60
        reasons.append("exact subject postcode matched")
    elif target_pc:
        conflicting_subject = [pc for pc in subject_context_postcodes if pc != target_pc]
        if conflicting_subject:
            hard_reject = True
            conflicts.append("document explicitly identifies a different property postcode: " + ", ".join(conflicting_subject[:3]))

    lot_no = ident["lot_number"]
    if lot_no and re.search(rf"\blot\s*(?:no\.?\s*)?{re.escape(lot_no)}\b", probe_all, re.I):
        score += 20
        reasons.append("auction lot number matched")

    tokens = ident["address_tokens"]
    matched = sorted(t for t in tokens if re.search(rf"\b{re.escape(t)}\b", probe_low))
    if len(matched) >= 4:
        score += 30
        reasons.append("strong subject address-token match")
    elif len(matched) == 3:
        score += 25
        reasons.append("subject address tokens matched")
    elif len(matched) == 2:
        score += 15
        reasons.append("partial subject address match")
    elif len(matched) == 1:
        score += 5
        reasons.append("single subject address token matched")

    lot_parsed = urlparse(ident["lot_url"])
    candidate_parsed = urlparse(str(url or ""))
    lot_host = lot_parsed.netloc.lower()
    candidate_host = candidate_parsed.netloc.lower()
    if lot_host and candidate_host and candidate_host == lot_host:
        score += 5
        reasons.append("same auction-provider host")
        shared = _route_lot_tokens(lot_parsed.path) & _route_lot_tokens(candidate_parsed.path)
        if shared:
            score += 15
            reasons.append("matching provider lot-route identifier")

    # If the file exposes several postcodes but never the subject postcode, keep it
    # unverified unless other identity evidence is exceptionally strong. This avoids
    # provider/solicitor addresses being mistaken for the property while not hard-
    # rejecting every document that contains professional contact addresses.
    foreign_postcodes = [pc for pc in all_postcodes if pc != target_pc]
    if target_pc and foreign_postcodes and target_pc not in all_postcodes and score < 60:
        conflicts.append("subject postcode absent while other postcode(s) appear: " + ", ".join(foreign_postcodes[:3]))

    score = min(100, score)
    if hard_reject:
        status = "rejected"
    elif score >= 60:
        status = "verified"
    elif score >= 40:
        status = "probable"
    else:
        status = "unverified"
    return {
        "score": score,
        "status": status,
        "hard_reject": hard_reject,
        "reasons": reasons,
        "conflicts": conflicts,
        "target_postcode": target_pc,
        "document_postcodes": all_postcodes,
        "subject_context_postcodes": subject_context_postcodes,
        "matched_address_tokens": matched,
    }


def lot_identity_match(lot: dict, text: str = "", url: str = "") -> tuple[int, list[str]]:
    """Backward-compatible compact score used by older callers/tests.

    The current policy internally uses the richer 0-100 identity assessment. Return a
    0-10-ish legacy scale here so old tests/integrations remain readable.
    """
    result = document_identity_assessment(lot, text=text, url=url)
    legacy = int(round(result["score"] / 10.0))
    return legacy, list(result["reasons"] + result["conflicts"])


def strong_pack_link(label: str = "", url: str = "") -> bool:
    probe = f"{label or ''} {url or ''}"
    return bool(STRONG_PACK_HINT_RE.search(probe)) and not bool(GENERIC_SITE_RE.search(probe))


def generic_site_content(label: str = "", url: str = "", text: str = "") -> bool:
    probe = f"{label or ''} {url or ''} {text or ''}"
    return bool(GENERIC_SITE_RE.search(probe))


def evidence_tier(doc: dict | None) -> str:
    doc = doc or {}
    # Backward-compatible direct/in-memory legal documents used by imports/tests can
    # omit metadata entirely. Persisted legacy rows use metadata={} and are quarantined.
    if "metadata" not in doc and doc.get("doc_type") and (doc.get("text_content") or doc.get("sha256")):
        return TIER_VERIFIED_LEGAL
    meta = doc.get("metadata") or {}
    origin = str(meta.get("origin") or "")
    if origin == "user-upload" and meta.get("identity_status") != "rejected":
        return TIER_VERIFIED_LEGAL
    return str(meta.get("evidence_tier") or TIER_CANDIDATE)


def is_verified_legal_document(doc: dict | None) -> bool:
    doc = doc or {}
    if evidence_tier(doc) != TIER_VERIFIED_LEGAL:
        return False
    meta = doc.get("metadata") or {}
    if meta.get("verified_for_lot") is False:
        return False
    if meta.get("identity_status") == "rejected":
        return False
    return True


def _merge_reasons(meta: dict, reasons: list[str] | None = None) -> None:
    meta["verification_reasons"] = list(dict.fromkeys((meta.get("verification_reasons") or []) + (reasons or [])))


def apply_identity_metadata(doc: dict, assessment: dict | None = None, doc_class: dict | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    assessment = assessment or {}
    doc_class = doc_class or {}
    if assessment:
        meta.update({
            "identity_score": int(assessment.get("score") or 0),
            "identity_status": assessment.get("status") or "unverified",
            "identity_reasons": assessment.get("reasons") or [],
            "identity_conflicts": assessment.get("conflicts") or [],
            "identity_target_postcode": assessment.get("target_postcode") or "",
            "identity_document_postcodes": assessment.get("document_postcodes") or [],
            "identity_matched_address_tokens": assessment.get("matched_address_tokens") or [],
        })
    if doc_class:
        meta.update({
            "document_class": doc_class.get("doc_type") or "Unclassified",
            "document_class_allowed": bool(doc_class.get("allowed")),
            "document_class_reason": doc_class.get("reason") or "",
        })
    meta["evidence_policy_version"] = EVIDENCE_POLICY_VERSION
    return doc


def mark_candidate(doc: dict, reason: str = "not yet tied to the subject lot", assessment: dict | None = None,
                   doc_class: dict | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_CANDIDATE,
        "verified_for_lot": False,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    apply_identity_metadata(doc, assessment, doc_class)
    _merge_reasons(meta, [reason] if reason else [])
    return doc


def mark_rejected(doc: dict, reason: str, assessment: dict | None = None,
                  doc_class: dict | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_REJECTED,
        "verified_for_lot": False,
        "rejection_reason": reason,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    apply_identity_metadata(doc, assessment, doc_class)
    _merge_reasons(meta, [reason])
    return doc


def mark_pack_index(doc: dict, reasons: list[str] | None = None, assessment: dict | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_VERIFIED_PACK_INDEX,
        "verified_for_lot": True,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    apply_identity_metadata(doc, assessment, {"doc_type": "Legal pack index", "allowed": True, "reason": "lot-specific legal-pack index"})
    _merge_reasons(meta, reasons)
    return doc


def mark_verified_legal(doc: dict, reasons: list[str] | None = None, assessment: dict | None = None,
                        doc_class: dict | None = None) -> dict:
    meta = doc.setdefault("metadata", {})
    meta.update({
        "evidence_tier": TIER_VERIFIED_LEGAL,
        "verified_for_lot": True,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    })
    apply_identity_metadata(doc, assessment, doc_class)
    _merge_reasons(meta, reasons)
    return doc


def verified_legal_documents(documents: list[dict] | None) -> list[dict]:
    return [d for d in (documents or []) if is_verified_legal_document(d)]
