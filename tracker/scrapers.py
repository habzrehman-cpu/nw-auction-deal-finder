import re
from datetime import datetime, timezone
from dataclasses import replace
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup, NavigableString

from .common import Lot, clean_text, extract_postcode, parse_money, infer_status, infer_type, is_north_west, area_from_text, make_key, absolute

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
LOTNO_RE = re.compile(r"\bLot\s*#?\s*([0-9]+[A-Za-z]?)\b", re.I)
GUIDE_RE = re.compile(r"(?:Guide(?: Price)?\s*(?:\||:)?\s*)(£[^\n|]+?)(?=(?:Your Bid|\(|\s{2,}|$))", re.I)
RESULT_RE = re.compile(r"((?:Sold for|Last Bid)\s*:?[ ]*£[\d,]+|Sold Prior|Sold After|No Bids|Withdrawn|Postponed)", re.I)
DATE_RE = re.compile(r"(?:To be offered on\s+)?((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+20\d{2})?)", re.I)

class Fetcher:
    def __init__(self, timeout=20):
        self.s = requests.Session(); self.s.headers.update(HEADERS); self.timeout=timeout
    def get(self, url):
        r=self.s.get(url,timeout=self.timeout,allow_redirects=True); r.raise_for_status(); return r


def _money_text(text):
    m = GUIDE_RE.search(text)
    if m: return clean_text(m.group(1))
    m = re.search(r"£\s*[\d,.]+\s*[kKmM]?\s*(?:\+|(?:-|–|to)\s*£?\s*[\d,.]+\s*[kKmM]?\+?)?", text)
    return clean_text(m.group(0)) if m else ""


def _result(text):
    m=RESULT_RE.search(text); return clean_text(m.group(1)) if m else ""


def _date(text):
    m=DATE_RE.search(text); return clean_text(m.group(1)) if m else ""


def _lot(source, base, text, href="", default_status="Live"):
    text=clean_text(text)
    pc=extract_postcode(text)
    if not pc or not is_north_west(text, pc): return None
    url=absolute(base, href) if href else base
    lotno=(LOTNO_RE.search(text).group(1) if LOTNO_RE.search(text) else "")
    g=_money_text(text); res=_result(text); status=infer_status(text, default_status)
    if default_status=="Available post-auction" and status=="Live": status=default_status
    title=text[:260]
    return Lot(source=source,source_key=make_key(source,url,text),url=url,title=title,address=text,postcode=pc,
               area=area_from_text(text,pc),property_type=infer_type(text),lot_number=lotno,guide_text=g,
               guide_price=parse_money(g),result_text=res,result_price=parse_money(res),status=status,
               auction_date=_date(text),raw_text=text)


class AuctionHouseScraper:
    source="Auction House NW"
    current="https://www.auctionhouse.co.uk/northwest/auction/search-results"
    unsold="https://www.auctionhouse.co.uk/unsold"
    past="https://www.auctionhouse.co.uk/northwest/auction/past-auctions?page={}"
    def __init__(self, fetcher=None): self.f=fetcher or Fetcher()

    def _anchor_lots(self,url,default_status):
        soup=BeautifulSoup(self.f.get(url).text,"html.parser"); out=[]
        for a in soup.find_all("a",href=True):
            txt=clean_text(a.get_text(" ",strip=True))
            if "£" not in txt or not extract_postcode(txt): continue
            lot=_lot(self.source,url,txt,a["href"],default_status)
            if lot: out.append(lot)
        return self._dedupe(out)

    def _past_lots(self,url):
        soup=BeautifulSoup(self.f.get(url).text,"html.parser"); out=[]
        for tr in soup.find_all("tr"):
            txt=clean_text(tr.get_text(" ",strip=True))
            if not extract_postcode(txt) or not any(x.lower() in txt.lower() for x in ["No Bids","Last Bid","Sold for","Sold Prior","Sold After","Withdrawn","Postponed"]): continue
            href=""
            a=tr.find("a",href=True)
            if a: href=a["href"]
            lot=_lot(self.source,url,txt,href,infer_status(txt,"Result"))
            if lot: out.append(lot)
        return self._dedupe(out)

    def scrape(self):
        lots=[]
        lots += self._anchor_lots(self.current,"Live")
        lots += self._anchor_lots(self.unsold,"Available post-auction")
        for p in range(1,5):
            try: lots += self._past_lots(self.past.format(p))
            except Exception: pass
        return self._dedupe(lots)

    @staticmethod
    def _dedupe(lots):
        d={}
        failures={"No Bids","Last Bid","Withdrawn","Postponed"}
        for l in lots:
            key=l.source_key
            prev=d.get(key)
            if prev is None:
                d[key]=l; continue
            # Current availability beats an older failed result. If a property appears
            # live again after a failed auction, surface it explicitly as Relisted.
            if l.status=="Available post-auction":
                d[key]=l
            elif prev.status in failures and l.status=="Live":
                l.status="Relisted"; d[key]=l
            elif l.status in failures and prev.status=="Live":
                prev.status="Relisted"; d[key]=prev
            elif prev.status=="Available post-auction":
                pass
            elif l.status!="Live" and prev.status=="Live":
                d[key]=l
        return list(d.values())


class AllsopScraper:
    source="Allsop"
    starts=[
      ("https://www.allsop.co.uk/residential-current-auction?view=table","Live"),
      ("https://www.allsop.co.uk/commercial-current-auction?view=table","Live"),
      ("https://www.allsop.co.uk/property-search?available_only=true&lot_type=residential&view=table","Availability page"),
      ("https://www.allsop.co.uk/property-search?available_only=true&lot_type=commercial&view=table","Availability page"),
    ]
    def __init__(self, fetcher=None): self.f=fetcher or Fetcher()

    def scrape(self):
        out=[]
        for url,default in self.starts:
            r=self.f.get(url); soup=BeautifulSoup(r.text,"html.parser")
            rows=soup.select("tbody tr")
            for row in rows:
                txt=clean_text(row.get_text(" ",strip=True)); href=self._row_href(row)
                lot=_lot(self.source,r.url,txt,href,"Live" if default=="Availability page" else default)
                if lot:
                    if default=="Availability page": lot.status=self._availability_status(lot.raw_text)
                    out.append(lot)
            # Fallback for card layouts / homepage-style lot links.
            for a in soup.select("a[href*='/lot-overview/']"):
                container=a
                for _ in range(4):
                    if container.parent and len(clean_text(container.parent.get_text(" ",strip=True))) < 1800: container=container.parent
                txt=clean_text(container.get_text(" ",strip=True))
                lot=_lot(self.source,r.url,txt,a.get("href"),"Live" if default=="Availability page" else default)
                if lot:
                    if default=="Availability page": lot.status=self._availability_status(lot.raw_text)
                    out.append(lot)
        d={l.source_key:l for l in out}; return list(d.values())

    @staticmethod
    def _availability_status(text):
        low=text.lower()
        if "available post auction" in low or "available post-auction" in low:
            return "Available post-auction"
        # Allsop's available_only pages contain both future lots and unsold past lots.
        # Where the lot label exposes Mon YYYY, classify older months as post-auction.
        m=re.search(r"-\s*([A-Za-z]{3})\s+(20\d{2})", text)
        if m:
            try:
                dt=datetime.strptime(f"{m.group(1)} {m.group(2)}","%b %Y").replace(tzinfo=timezone.utc)
                now=datetime.now(timezone.utc)
                if (dt.year,dt.month) < (now.year,now.month): return "Available post-auction"
            except ValueError:
                pass
        return "Live"

    @staticmethod
    def _row_href(row):
        a=row.find("a",href=True)
        if a: return a["href"]
        for attr in ["data-href","data-url","href"]:
            if row.get(attr): return row.get(attr)
        onclick=row.get("onclick","")
        m=re.search(r"['\"]([^'\"]+/lot-overview/[^'\"]+)['\"]",onclick)
        return m.group(1) if m else ""


class SavillsScraper:
    source="Savills"
    home="https://auctions.savills.co.uk/"
    past="https://auctions.savills.co.uk/past-auctions"
    def __init__(self, fetcher=None): self.f=fetcher or Fetcher()

    def _find_catalogue(self):
        r=self.f.get(self.home); soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.find_all("a",href=True):
            if "view catalogue" in clean_text(a.get_text(" ",strip=True)).lower(): return absolute(r.url,a["href"])
        for a in soup.find_all("a",href=True):
            if "/auctions/" in a["href"] and "past" not in a["href"]: return absolute(r.url,a["href"])
        return self.home

    def _parse_catalogue_page(self,url):
        r=self.f.get(url); soup=BeautifulSoup(r.text,"html.parser"); out=[]
        # Cards are found by locating Lot labels then climbing to the smallest useful block.
        for node in soup.find_all(string=re.compile(r"^\s*Lot\s+\d+[A-Za-z]?\s*$",re.I)):
            block=node.parent
            for _ in range(7):
                txt=clean_text(block.get_text(" ",strip=True))
                if "Guide Price" in txt and extract_postcode(txt) and len(txt)>60: break
                if not block.parent: break
                block=block.parent
            txt=clean_text(block.get_text(" ",strip=True))
            href=""
            for a in block.find_all("a",href=True):
                if "full details" in clean_text(a.get_text(" ",strip=True)).lower() or "/auctions/" in a["href"] or "option=com_bidding" in a["href"]:
                    href=a["href"]; break
            lot=_lot(self.source,r.url,txt,href,"Live")
            if lot: out.append(lot)
        return out,soup,r.url

    def scrape(self):
        base=self._find_catalogue(); out=[]; seen=set(); url=base
        for _ in range(40):
            if url in seen: break
            seen.add(url)
            page_lots,soup,current=self._parse_catalogue_page(url); out += page_lots
            nxt=None
            for a in soup.find_all("a",href=True):
                if clean_text(a.get_text(" ",strip=True)).lower()=="next": nxt=absolute(current,a["href"]); break
            if not nxt: break
            url=nxt
        # Recent past-auction pages carry sold/available result signals.
        try:
            r=self.f.get(self.past); soup=BeautifulSoup(r.text,"html.parser")
            past_links=[]
            for a in soup.find_all("a",href=True):
                href=absolute(r.url,a["href"])
                if "/auctions/" in href and href not in past_links: past_links.append(href)
            for link in past_links[:4]:
                page_lots,_,_=self._parse_catalogue_page(link)
                for l in page_lots:
                    l.status=infer_status(l.raw_text,"Result")
                out += page_lots
        except Exception: pass
        d={l.source_key:l for l in out}; return list(d.values())


class EddisonsScraper:
    source="BTG Eddisons"
    search="https://www.eddisons.com/property-search?sale_type=3&sort=lot_number&order=ASC&limit=100"
    def __init__(self, fetcher=None): self.f=fetcher or Fetcher()

    def scrape(self):
        out=[]
        # Search is paginated. Stop when a page stops yielding unseen North West auction lots.
        for page in range(1,25):
            sep="&" if "?" in self.search else "?"; url=f"{self.search}{sep}page={page}"
            r=self.f.get(url); soup=BeautifulSoup(r.text,"html.parser"); page_hits=0
            # Prefer property detail anchors and use their surrounding card text.
            for a in soup.find_all("a",href=True):
                href=a["href"]
                if "/property-search/" not in href or href.rstrip("/")=="/property-search": continue
                block=a
                for _ in range(5):
                    parent=block.parent
                    if not parent: break
                    ptxt=clean_text(parent.get_text(" ",strip=True))
                    if len(ptxt)>2200: break
                    block=parent
                txt=clean_text(block.get_text(" ",strip=True))
                if not extract_postcode(txt): continue
                lot=_lot(self.source,r.url,txt,href,"Live")
                if lot:
                    out.append(lot); page_hits+=1
            if page_hits==0 and page>3: break
        d={l.source_key:l for l in out}; return list(d.values())


SCRAPERS=[AuctionHouseScraper,AllsopScraper,SavillsScraper,EddisonsScraper]
