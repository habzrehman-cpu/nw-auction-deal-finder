"""Detail-page enrichment for auction lots.

Catalogue scrapers stay lightweight. This module follows public lot URLs when the
local cache says they are due and captures text plus a representative property image.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse
import re

from bs4 import BeautifulSoup

from .common import clean_text
from .scrapers import Fetcher

ALLOWED_HOSTS = {
    "allsop.co.uk", "www.allsop.co.uk",
    "auctions.savills.co.uk", "savills.co.uk", "www.savills.co.uk",
    "eddisons.com", "www.eddisons.com",
    "auctionhouse.co.uk", "www.auctionhouse.co.uk",
}


def is_detail_url(url: str) -> bool:
    try:
        p = urlparse(url or "")
    except ValueError:
        return False
    return p.scheme in {"http", "https"} and p.netloc.lower() in ALLOWED_HOSTS


def extract_detail_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.select("script,style,noscript,svg,template"):
        node.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = clean_text(main.get_text(" ", strip=True))
    return text[:80_000]


def _candidate_image(soup: BeautifulSoup, base_url: str) -> str:
    # Auction detail pages commonly expose a canonical social/share image even when
    # the gallery itself is JavaScript-driven.
    for selector, attr in [
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[property="twitter:image"]', "content"),
    ]:
        node = soup.select_one(selector)
        value = (node.get(attr) or "").strip() if node else ""
        if value:
            return urljoin(base_url, value)

    bad = ("logo", "icon", "avatar", "sprite", "placeholder", "tracking", "pixel")
    for img in soup.find_all("img"):
        src = (img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "").strip()
        if not src:
            continue
        probe = f"{src} {img.get('alt') or ''} {img.get('class') or ''}".lower()
        if any(word in probe for word in bad):
            continue
        if src.startswith("data:"):
            continue
        return urljoin(base_url, src)
    return ""



def _detail_auction_date(text: str) -> str:
    text = clean_text(text)
    patterns = [
        r"Auction Date\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?[A-Za-z]*\s*(\d{1,2}/\d{1,2}/20\d{2})",
        r"For Sale By Auction[^|]{0,100}?\b(\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return clean_text(m.group(1))
    return ""

def extract_detail_metadata(html: str, base_url: str = "") -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    image_url = _candidate_image(soup, base_url)
    for node in soup.select("script,style,noscript,svg,template"):
        node.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = clean_text(main.get_text(" ", strip=True))[:80_000]
    return {"text": text, "image_url": image_url, "auction_date": _detail_auction_date(text)}


def fetch_detail_metadata(url: str, fetcher: Fetcher | None = None) -> dict:
    if not is_detail_url(url):
        return {"text": "", "image_url": "", "auction_date": ""}
    f = fetcher or Fetcher()
    response = f.get(url)
    return extract_detail_metadata(response.text, getattr(response, "url", url))


def fetch_detail_text(url: str, fetcher: Fetcher | None = None) -> str:
    return fetch_detail_metadata(url, fetcher=fetcher).get("text") or ""
