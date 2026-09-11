import hashlib
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import urljoin

POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
MONEY_RE = re.compile(r"£\s*([\d,.]+(?:\.\d+)?)\s*([kKmM]?)")
MONEY_TOKEN_RE = re.compile(r"£?\s*([\d,.]+(?:\.\d+)?)\s*([kKmM]?)")

NW_COUNTIES = {
    "lancashire", "greater manchester", "merseyside", "cheshire", "cumbria",
    "blackpool", "blackburn with darwen", "halton", "warrington"
}
STRONG_NW_POSTCODE_AREAS = {"BB", "BL", "CA", "CW", "FY", "L", "LA", "M", "PR", "WA", "WN"}
CONDITIONAL_AREAS = {
    "CH": {"chester", "ellesmere port", "birkenhead", "wallasey", "wirral", "heswall", "neston"},
    "OL": {"oldham", "rochdale", "heywood", "middleton", "saddleworth", "rossendale", "bacup"},
    "SK": {"stockport", "macclesfield", "wilmslow", "alderley edge", "hazel grove", "cheadle", "disley"},
}

STATUS_PATTERNS = [
    ("available post-auction", "Available post-auction"),
    ("available post auction", "Available post-auction"),
    ("sold prior", "Sold Prior"),
    ("sold after", "Sold After"),
    ("withdrawn", "Withdrawn"),
    ("postponed", "Postponed"),
    ("no bids", "No Bids"),
    ("unsold", "Unsold"),
    ("last bid", "Last Bid"),
    ("sold for", "Sold"),
    ("sold", "Sold"),
]

TYPE_PATTERNS = [
    ("industrial", "Industrial"), ("warehouse", "Industrial"), ("factory", "Industrial"),
    ("commercial", "Commercial"), ("shop", "Commercial"), ("retail", "Commercial"),
    ("office", "Commercial"), ("pub", "Commercial"), ("restaurant", "Commercial"),
    ("mixed use", "Mixed Use"), ("mixed-use", "Mixed Use"),
    ("development", "Development"), ("land", "Land"),
    ("block of apartments", "Block / HMO"), ("block of flats", "Block / HMO"), ("hmo", "Block / HMO"),
    ("apartment", "Flat"), ("flat", "Flat"),
    ("bungalow", "House"), ("terraced house", "House"), ("semi-detached", "House"),
    ("detached house", "House"), ("house", "House"), ("cottage", "House"),
]

@dataclass
class Lot:
    source: str
    source_key: str
    url: str
    title: str
    address: str = ""
    postcode: str = ""
    area: str = ""
    property_type: str = "Other"
    lot_number: str = ""
    guide_text: str = ""
    guide_price: int | None = None
    guide_price_high: int | None = None
    result_text: str = ""
    result_price: int | None = None
    status: str = "Live"
    auction_date: str = ""
    raw_text: str = ""
    image_url: str = ""
    captured_at: str = ""
    historical_events: list | None = None

    def to_dict(self):
        d = asdict(self)
        d["captured_at"] = self.captured_at or datetime.now(timezone.utc).isoformat()
        return d


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_postcode(text: str) -> str:
    m = POSTCODE_RE.search(text or "")
    if not m:
        return ""
    p = re.sub(r"\s+", "", m.group(1).upper())
    return f"{p[:-3]} {p[-3:]}"


def postcode_area(postcode: str) -> str:
    m = re.match(r"([A-Z]{1,2})", postcode or "")
    return m.group(1) if m else ""


def is_north_west(text: str, postcode: str = "") -> bool:
    t = clean_text(text).lower()
    if any(c in t for c in NW_COUNTIES):
        return True
    p = postcode or extract_postcode(text)
    a = postcode_area(p)
    if a in STRONG_NW_POSTCODE_AREAS:
        return True
    if a in CONDITIONAL_AREAS and any(place in t for place in CONDITIONAL_AREAS[a]):
        return True
    return False


def area_from_text(text: str, postcode: str = "") -> str:
    t = clean_text(text).lower()
    for county, label in [
        ("greater manchester", "Greater Manchester"), ("merseyside", "Merseyside"),
        ("cheshire", "Cheshire"), ("cumbria", "Cumbria"), ("lancashire", "Lancashire"),
        ("blackpool", "Lancashire"), ("blackburn", "Lancashire"),
    ]:
        if county in t:
            return label
    p = postcode or extract_postcode(text)
    a = postcode_area(p)
    if a in {"M", "BL", "WN", "OL"}: return "Greater Manchester"
    if a == "L": return "Merseyside"
    if a in {"CW", "WA", "CH", "SK"}: return "Cheshire"
    if a in {"CA", "LA"}: return "Cumbria" if a == "CA" else "Lancashire / Cumbria"
    if a in {"BB", "FY", "PR"}: return "Lancashire"
    return "North West"


def parse_money(text: str) -> int | None:
    m = MONEY_RE.search(text or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    suffix = m.group(2).lower()
    if suffix == "k": n *= 1_000
    elif suffix == "m": n *= 1_000_000
    return int(round(n))



def parse_money_range(text: str) -> tuple[int | None, int | None]:
    """Return low/high monetary guide values while preserving single-figure guides.

    Examples: ``£65,000 - £85,000`` -> (65000, 85000), ``£120,000+`` ->
    (120000, None).  The low value remains the acquisition/filtering basis; callers
    can use the high value for display and range-aware analysis.
    """
    raw = clean_text(text)
    if not raw:
        return None, None
    values = []
    for m in MONEY_TOKEN_RE.finditer(raw):
        # Avoid interpreting unrelated numbers unless the token is currency-like.
        prefix = raw[max(0, m.start()-2):m.start()]
        token = m.group(0)
        if "£" not in token and "£" not in prefix and not values:
            continue
        n = float(m.group(1).replace(",", ""))
        suffix = m.group(2).lower()
        if suffix == "k": n *= 1_000
        elif suffix == "m": n *= 1_000_000
        values.append(int(round(n)))
        if len(values) >= 2:
            break
    if not values:
        first = parse_money(raw)
        return first, None
    low = values[0]
    # Only treat the second currency number as a range where the wording connects it
    # to the first guide, rather than e.g. an administration fee later in the text.
    range_like = bool(re.search(r"£\s*[\d,.]+\s*[kKmM]?\s*(?:-|–|—|to)\s*£?\s*[\d,.]+", raw, re.I))
    high = values[1] if len(values) > 1 and range_like else None
    return low, high

def infer_status(text: str, default="Live") -> str:
    t = clean_text(text).lower()
    for needle, label in STATUS_PATTERNS:
        if needle in t:
            return label
    return default


def infer_type(text: str) -> str:
    t = clean_text(text).lower()
    for needle, label in TYPE_PATTERNS:
        if needle in t:
            return label
    return "Other"


def make_key(source: str, url: str, text: str) -> str:
    # Identity deliberately ignores guide/result/status text so the same address keeps
    # one history record when it is repriced, fails, or is relisted. Keep text only
    # up to the postcode to avoid changing feature descriptions breaking identity.
    t = clean_text(text)
    m = POSTCODE_RE.search(t)
    if m:
        t = t[:m.end()]
    t = re.sub(r"\bLot\s*#?\s*[0-9]+[A-Za-z]?\b", " ", t, flags=re.I)
    t = re.sub(r"(?:Guide(?: Price)?\s*(?:\||:)?\s*)?£\s*[\d,.]+(?:\.\d+)?\s*[kKmM]?(?:\s*(?:-|–|to)\s*£?\s*[\d,.]+(?:\.\d+)?\s*[kKmM]?)?\+?", " ", t, flags=re.I)
    t = re.sub(r"\b(?:sold prior|sold after|sold for|sold|available post[- ]auction|no bids|last bid|unsold|withdrawn|postponed)\b", " ", t, flags=re.I)
    t = re.sub(r"\(plus fees\)", " ", t, flags=re.I)
    stable = clean_text(t).lower()
    seed = f"{source}|{extract_postcode(text)}|{stable[:260]}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()


def absolute(base: str, href: str) -> str:
    return urljoin(base, href or "")


def opportunity_score(lot: dict) -> int:
    score = 3
    status = (lot.get("status") or "").lower()
    typ = (lot.get("property_type") or "").lower()
    raw = (lot.get("raw_text") or "").lower()
    price = lot.get("guide_price") or 0
    if "available post" in status: score += 3
    if status in {"no bids", "last bid"}: score += 2
    if "relisted" in status: score += 2
    if typ in {"industrial", "commercial", "mixed use", "development", "land"}: score += 1
    if any(x in raw for x in ["vacant", "modernisation", "refurbishment", "redevelopment", "development potential"]): score += 1
    if price and price <= 150_000: score += 1
    return min(score, 10)
