"""Detail-page enrichment for auction lots.

The catalogue scrapers stay intentionally lightweight. This module follows the lot URL
only when the local cache says it is due, and captures the public detail-page text used
by the deal engine for floor area, tenure, parking, loading and development signals.
"""
from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .common import clean_text
from .scrapers import Fetcher

ALLOWED_HOSTS = {
    "allsop.co.uk",
    "www.allsop.co.uk",
    "auctions.savills.co.uk",
    "savills.co.uk",
    "www.savills.co.uk",
    "eddisons.com",
    "www.eddisons.com",
    "auctionhouse.co.uk",
    "www.auctionhouse.co.uk",
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
    # Keep enough text for schedules and dimensions while bounding DB growth.
    return text[:80_000]


def fetch_detail_text(url: str, fetcher: Fetcher | None = None) -> str:
    if not is_detail_url(url):
        return ""
    f = fetcher or Fetcher()
    response = f.get(url)
    return extract_detail_text(response.text)
