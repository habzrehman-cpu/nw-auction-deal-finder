import sqlite3
import json
from contextlib import closing
from pathlib import Path
from .legal_firewall import EVIDENCE_POLICY_VERSION
from datetime import datetime, timezone, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL UNIQUE,
  url TEXT,
  title TEXT,
  address TEXT,
  postcode TEXT,
  area TEXT,
  property_type TEXT,
  lot_number TEXT,
  guide_text TEXT,
  guide_price INTEGER,
  guide_price_high INTEGER,
  result_text TEXT,
  result_price INTEGER,
  status TEXT,
  auction_date TEXT,
  raw_text TEXT,
  image_url TEXT,
  detail_text TEXT,
  detail_enriched_at TEXT,
  latitude REAL,
  longitude REAL,
  geo_source TEXT,
  nearest_motorway TEXT,
  nearest_junction TEXT,
  motorway_air_miles REAL,
  motorway_road_miles REAL,
  motorway_distance_kind TEXT,
  motorway_updated_at TEXT,
  first_seen TEXT,
  last_seen TEXT
);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  guide_text TEXT,
  guide_price INTEGER,
  guide_price_high INTEGER,
  result_text TEXT,
  result_price INTEGER,
  status TEXT,
  auction_date TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS refresh_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT,
  rows_found INTEGER DEFAULT 0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS underwriting_overrides (
  property_id INTEGER PRIMARY KEY,
  updated_at TEXT NOT NULL,
  strategy TEXT,
  purchase_price REAL,
  market_psf REAL,
  manual_market_value REAL,
  gdv REAL,
  erv_annual REAL,
  exit_yield_pct REAL,
  refurb_cost REAL,
  capex_cost REAL,
  contingency_pct REAL,
  auction_admin_fee REAL,
  buyer_premium_pct REAL,
  buyer_premium_minimum REAL,
  search_fee REAL,
  legal_cost REAL,
  survey_cost REAL,
  nonrecoverable_vat_pct REAL,
  purchase_vat_pct REAL,
  vat_recoverable INTEGER,
  holding_cost_monthly REAL,
  sale_cost_pct REAL,
  exit_legal_cost REAL,
  finance_mode TEXT,
  ltv_pct REAL,
  annual_interest_pct REAL,
  term_months INTEGER,
  arrangement_fee_pct REAL,
  exit_fee_pct REAL,
  valuation_fee REAL,
  target_profit_margin_pct REAL,
  target_equity_margin_pct REAL,
  residential_sdlt_mode TEXT,
  underwriting_notes TEXT,
  use_auto_comps INTEGER,
  gdv_source_mode TEXT,
  fee_source_mode TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS postcode_cache (
  postcode TEXT PRIMARY KEY,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  source TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comparable_summaries (
  property_id INTEGER PRIMARY KEY,
  provider TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  updated_at TEXT NOT NULL,
  valuation_low REAL,
  valuation_mid REAL,
  valuation_high REAL,
  unit_psf_mid REAL,
  comp_count INTEGER DEFAULT 0,
  confidence INTEGER DEFAULT 0,
  guide_discount_pct REAL,
  methodology TEXT,
  warnings_json TEXT,
  attribution TEXT,
  error TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS comparables (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL,
  provider TEXT,
  source_ref TEXT,
  address TEXT,
  postcode TEXT,
  sale_price REAL,
  sale_date TEXT,
  property_type TEXT,
  tenure TEXT,
  distance_miles REAL,
  size_sqft REAL,
  price_per_sqft REAL,
  match_score REAL,
  same_property INTEGER DEFAULT 0,
  metadata_json TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE INDEX IF NOT EXISTS idx_comparables_property ON comparables(property_id);
CREATE TABLE IF NOT EXISTS planning_summaries (
  property_id INTEGER PRIMARY KEY,
  provider TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  updated_at TEXT NOT NULL,
  risk_score REAL DEFAULT 0,
  opportunity_score REAL DEFAULT 0,
  constraint_count INTEGER DEFAULT 0,
  application_count INTEGER DEFAULT 0,
  subject_application_count INTEGER DEFAULT 0,
  methodology TEXT,
  warnings_json TEXT,
  attribution TEXT,
  error TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS planning_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL,
  kind TEXT,
  dataset TEXT,
  reference TEXT,
  name TEXT,
  severity INTEGER DEFAULT 0,
  label TEXT,
  source_url TEXT,
  distance_miles REAL,
  likely_subject INTEGER DEFAULT 0,
  metadata_json TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE INDEX IF NOT EXISTS idx_planning_items_property ON planning_items(property_id);
CREATE TABLE IF NOT EXISTS legal_summaries (
  property_id INTEGER PRIMARY KEY,
  provider TEXT,
  status TEXT NOT NULL DEFAULT 'not-found',
  updated_at TEXT NOT NULL,
  risk_score REAL DEFAULT 0,
  document_count INTEGER DEFAULT 0,
  candidate_document_count INTEGER DEFAULT 0,
  rejected_document_count INTEGER DEFAULT 0,
  pack_index_count INTEGER DEFAULT 0,
  verified_document_count INTEGER DEFAULT 0,
  parsed_document_count INTEGER DEFAULT 0,
  auctioneer_evidence_count INTEGER DEFAULT 0,
  verification_status TEXT,
  evidence_policy_version TEXT,
  completion_days REAL,
  deposit_pct REAL,
  lease_years REAL,
  buyer_fee_detected REAL,
  vat_flag INTEGER DEFAULT 0,
  has_addendum INTEGER DEFAULT 0,
  extracted_json TEXT,
  contacts_json TEXT,
  risk_flags_json TEXT,
  evidence_json TEXT,
  pack_completeness_pct INTEGER DEFAULT 0,
  missing_components_json TEXT,
  available_components_json TEXT,
  pack_fingerprint TEXT,
  pack_changed INTEGER DEFAULT 0,
  pack_change_json TEXT,
  revalidation_json TEXT,
  methodology TEXT,
  warnings_json TEXT,
  attribution TEXT,
  error TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS legal_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL,
  name TEXT,
  url TEXT,
  doc_type TEXT,
  access_status TEXT,
  text_content TEXT,
  sha256 TEXT,
  metadata_json TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE INDEX IF NOT EXISTS idx_legal_documents_property ON legal_documents(property_id);
CREATE TABLE IF NOT EXISTS company_intelligence (
  property_id INTEGER PRIMARY KEY,
  provider TEXT,
  status TEXT NOT NULL DEFAULT 'not-run',
  updated_at TEXT NOT NULL,
  company_number TEXT,
  company_name TEXT,
  company_status TEXT,
  registered_office TEXT,
  corporate_pressure_score REAL DEFAULT 0,
  summary_json TEXT,
  error TEXT,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE INDEX IF NOT EXISTS idx_company_intelligence_number ON company_intelligence(company_number);
CREATE TABLE IF NOT EXISTS deal_workspace (
  property_id INTEGER PRIMARY KEY,
  stage TEXT NOT NULL DEFAULT 'New',
  next_action TEXT,
  follow_up_date TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS deal_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  note TEXT NOT NULL,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE INDEX IF NOT EXISTS idx_deal_notes_property ON deal_notes(property_id);
CREATE TABLE IF NOT EXISTS shortlist (
  property_id INTEGER PRIMARY KEY,
  added_at TEXT NOT NULL,
  FOREIGN KEY(property_id) REFERENCES properties(id)
);
CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);
"""

PROPERTY_MIGRATIONS = {
    "guide_price_high": "INTEGER",
    "image_url": "TEXT",
    "detail_text": "TEXT",
    "detail_enriched_at": "TEXT",
    "latitude": "REAL",
    "longitude": "REAL",
    "geo_source": "TEXT",
    "nearest_motorway": "TEXT",
    "nearest_junction": "TEXT",
    "motorway_air_miles": "REAL",
    "motorway_road_miles": "REAL",
    "motorway_distance_kind": "TEXT",
    "motorway_updated_at": "TEXT",
}


HISTORY_MIGRATIONS = {
    "guide_price_high": "INTEGER",
}

LEGAL_SUMMARY_MIGRATIONS = {
    "candidate_document_count": "INTEGER DEFAULT 0",
    "rejected_document_count": "INTEGER DEFAULT 0",
    "pack_index_count": "INTEGER DEFAULT 0",
    "verified_document_count": "INTEGER DEFAULT 0",
    "auctioneer_evidence_count": "INTEGER DEFAULT 0",
    "verification_status": "TEXT",
    "evidence_policy_version": "TEXT",
    "extracted_json": "TEXT",
    "contacts_json": "TEXT",
    "evidence_json": "TEXT",
    "pack_completeness_pct": "INTEGER DEFAULT 0",
    "missing_components_json": "TEXT",
    "available_components_json": "TEXT",
    "pack_fingerprint": "TEXT",
    "pack_changed": "INTEGER DEFAULT 0",
    "pack_change_json": "TEXT",
    "revalidation_json": "TEXT",
}


UNDERWRITING_MIGRATIONS = {
    "purchase_vat_pct": "REAL",
    "vat_recoverable": "INTEGER",
    "holding_cost_monthly": "REAL",
    "sale_cost_pct": "REAL",
    "exit_legal_cost": "REAL",
    "use_auto_comps": "INTEGER",
    "buyer_premium_minimum": "REAL",
    "search_fee": "REAL",
    "gdv_source_mode": "TEXT",
    "fee_source_mode": "TEXT",
}


class Database:
    def __init__(self, path="auction_tracker.db"):
        self.path = Path(path)
        self.init()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def init(self):
        with closing(self.connect()) as con:
            con.executescript(SCHEMA)
            existing = {r[1] for r in con.execute("PRAGMA table_info(properties)").fetchall()}
            for name, sql_type in PROPERTY_MIGRATIONS.items():
                if name not in existing:
                    con.execute(f"ALTER TABLE properties ADD COLUMN {name} {sql_type}")
            history_existing = {r[1] for r in con.execute("PRAGMA table_info(history)").fetchall()}
            for name, sql_type in HISTORY_MIGRATIONS.items():
                if name not in history_existing:
                    con.execute(f"ALTER TABLE history ADD COLUMN {name} {sql_type}")
            legal_existing = {r[1] for r in con.execute("PRAGMA table_info(legal_summaries)").fetchall()}
            for name, sql_type in LEGAL_SUMMARY_MIGRATIONS.items():
                if name not in legal_existing:
                    con.execute(f"ALTER TABLE legal_summaries ADD COLUMN {name} {sql_type}")
            uw_existing = {r[1] for r in con.execute("PRAGMA table_info(underwriting_overrides)").fetchall()}
            for name, sql_type in UNDERWRITING_MIGRATIONS.items():
                if name not in uw_existing:
                    con.execute(f"ALTER TABLE underwriting_overrides ADD COLUMN {name} {sql_type}")
            con.commit()

    def upsert(self, lot: dict):
        now = datetime.now(timezone.utc).isoformat()
        watched = ("guide_text", "guide_price", "guide_price_high", "result_text", "result_price", "status", "auction_date")
        with closing(self.connect()) as con:
            old = con.execute("SELECT * FROM properties WHERE source_key=?", (lot["source_key"],)).fetchone()
            if old is None:
                cols = [
                    "source", "source_key", "url", "title", "address", "postcode", "area", "property_type",
                    "lot_number", "guide_text", "guide_price", "guide_price_high", "result_text", "result_price", "status",
                    "auction_date", "raw_text", "image_url", "first_seen", "last_seen"
                ]
                vals = [lot.get(c) for c in cols[:-2]] + [now, now]
                q = f"INSERT INTO properties ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
                cur = con.execute(q, vals)
                pid = cur.lastrowid
                changed = True
            else:
                pid = old["id"]
                if old["status"] in {"No Bids", "Last Bid", "Unsold", "Available post-auction", "Withdrawn", "Postponed"} and lot.get("status") == "Live":
                    lot["status"] = "Relisted"
                def incoming_value(key):
                    if key == "auction_date" and not lot.get(key):
                        return old[key]
                    return lot.get(key)
                changed = any(old[k] != incoming_value(k) for k in watched)
                con.execute(
                    """
                    UPDATE properties SET url=?,title=?,address=?,postcode=?,area=?,property_type=?,lot_number=?,
                    guide_text=?,guide_price=?,guide_price_high=?,result_text=?,result_price=?,status=?,auction_date=COALESCE(NULLIF(?,''),auction_date),raw_text=?,image_url=COALESCE(NULLIF(?,''),image_url),last_seen=?
                    WHERE id=?
                    """,
                    (
                        lot.get("url"), lot.get("title"), lot.get("address"), lot.get("postcode"), lot.get("area"),
                        lot.get("property_type"), lot.get("lot_number"), lot.get("guide_text"), lot.get("guide_price"), lot.get("guide_price_high"),
                        lot.get("result_text"), lot.get("result_price"), lot.get("status"), lot.get("auction_date"),
                        lot.get("raw_text"), lot.get("image_url") or "", now, pid,
                    ),
                )
            if changed:
                con.execute(
                    """INSERT INTO history(property_id,captured_at,guide_text,guide_price,guide_price_high,result_text,result_price,status,auction_date)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        pid, now, lot.get("guide_text"), lot.get("guide_price"), lot.get("guide_price_high"), lot.get("result_text"),
                        lot.get("result_price"), lot.get("status"), lot.get("auction_date"),
                    ),
                )
            con.commit()
            return changed

    def property_for_key(self, source_key):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM properties WHERE source_key=?", (source_key,)).fetchone()
            return dict(row) if row else None

    def list_properties(self):
        with closing(self.connect()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM properties ORDER BY last_seen DESC").fetchall()]

    def detail_due(self, source_key, force=False, max_age_days=7):
        row = self.property_for_key(source_key)
        if not row:
            return True
        if force and (not row.get("detail_text") or not row.get("image_url")):
            return True
        if not row.get("detail_text") or not row.get("detail_enriched_at") or not row.get("image_url"):
            return True
        try:
            stamp = datetime.fromisoformat(str(row["detail_enriched_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - stamp > timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return True

    def update_detail(self, source_key, detail_text, image_url="", auction_date=""):
        if not detail_text and not image_url and not auction_date:
            return
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """UPDATE properties SET detail_text=COALESCE(NULLIF(?,''),detail_text),
                image_url=COALESCE(NULLIF(?,''),image_url),
                auction_date=COALESCE(NULLIF(?,''),auction_date), detail_enriched_at=? WHERE source_key=?""",
                (detail_text or "", image_url or "", auction_date or "", now, source_key),
            )
            con.commit()

    def add_history_events(self, property_id, events):
        """Persist historical auction observations without duplicating them on every refresh."""
        if not events:
            return 0
        inserted = 0
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            for event in events:
                captured = event.get("captured_at") or now
                key = (
                    property_id, event.get("guide_price"), event.get("guide_price_high"), event.get("result_price"),
                    event.get("status"), event.get("auction_date"),
                )
                exists = con.execute(
                    """SELECT 1 FROM history WHERE property_id=? AND COALESCE(guide_price,-1)=COALESCE(?,-1)
                    AND COALESCE(guide_price_high,-1)=COALESCE(?,-1) AND COALESCE(result_price,-1)=COALESCE(?,-1)
                    AND COALESCE(status,'')=COALESCE(?,'') AND COALESCE(auction_date,'')=COALESCE(?,'') LIMIT 1""", key
                ).fetchone()
                if exists:
                    continue
                con.execute(
                    """INSERT INTO history(property_id,captured_at,guide_text,guide_price,guide_price_high,result_text,result_price,status,auction_date)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (property_id, captured, event.get("guide_text"), event.get("guide_price"), event.get("guide_price_high"),
                     event.get("result_text"), event.get("result_price"), event.get("status"), event.get("auction_date")),
                )
                inserted += 1
            con.commit()
        return inserted

    def cached_postcodes(self, postcodes):
        values = [" ".join((p or "").upper().split()) for p in postcodes if p]
        if not values:
            return {}
        placeholders = ",".join("?" for _ in values)
        with closing(self.connect()) as con:
            rows = con.execute(
                f"SELECT * FROM postcode_cache WHERE postcode IN ({placeholders})", values
            ).fetchall()
        return {r["postcode"]: dict(r) for r in rows}

    def cache_postcode(self, postcode, latitude, longitude, source="Postcodes.io"):
        postcode = " ".join((postcode or "").upper().split())
        if not postcode:
            return
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """
                INSERT INTO postcode_cache(postcode,latitude,longitude,source,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(postcode) DO UPDATE SET latitude=excluded.latitude,longitude=excluded.longitude,
                source=excluded.source,updated_at=excluded.updated_at
                """,
                (postcode, latitude, longitude, source, now),
            )
            con.execute(
                "UPDATE properties SET latitude=?,longitude=?,geo_source=? WHERE UPPER(postcode)=?",
                (latitude, longitude, source, postcode),
            )
            con.commit()

    def update_motorway(self, source_key, info):
        if not info:
            return
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """
                UPDATE properties SET nearest_motorway=?,nearest_junction=?,motorway_air_miles=?,
                motorway_road_miles=?,motorway_distance_kind=?,motorway_updated_at=? WHERE source_key=?
                """,
                (
                    info.get("nearest_motorway"), info.get("nearest_junction"), info.get("motorway_air_miles"),
                    info.get("motorway_road_miles"), info.get("motorway_distance_kind"), now, source_key,
                ),
            )
            con.commit()

    def history_for(self, property_id):
        with closing(self.connect()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM history WHERE property_id=? ORDER BY captured_at DESC", (property_id,)
            ).fetchall()]

    def history_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM history ORDER BY captured_at DESC").fetchall()]
        grouped = {}
        for row in rows:
            grouped.setdefault(row["property_id"], []).append(row)
        return grouped

    def underwriting_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM underwriting_overrides WHERE property_id=?", (property_id,)).fetchone()
            return dict(row) if row else {}

    def underwriting_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM underwriting_overrides").fetchall()]
        return {r["property_id"]: r for r in rows}

    def save_underwriting(self, property_id, values):
        now = datetime.now(timezone.utc).isoformat()
        allowed = [
            "strategy", "purchase_price", "market_psf", "manual_market_value", "gdv",
            "erv_annual", "exit_yield_pct", "refurb_cost", "capex_cost", "contingency_pct",
            "auction_admin_fee", "buyer_premium_pct", "buyer_premium_minimum", "search_fee", "legal_cost", "survey_cost",
            "nonrecoverable_vat_pct", "purchase_vat_pct", "vat_recoverable", "holding_cost_monthly",
            "sale_cost_pct", "exit_legal_cost", "finance_mode", "ltv_pct", "annual_interest_pct",
            "term_months", "arrangement_fee_pct", "exit_fee_pct", "valuation_fee",
            "target_profit_margin_pct", "target_equity_margin_pct", "residential_sdlt_mode",
            "underwriting_notes", "use_auto_comps", "gdv_source_mode", "fee_source_mode",
        ]
        payload = {k: values.get(k) for k in allowed}
        cols = ["property_id", "updated_at"] + allowed
        vals = [property_id, now] + [payload[k] for k in allowed]
        updates = ",".join(f"{c}=excluded.{c}" for c in ["updated_at"] + allowed)
        with closing(self.connect()) as con:
            con.execute(
                f"INSERT INTO underwriting_overrides ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                f"ON CONFLICT(property_id) DO UPDATE SET {updates}",
                vals,
            )
            con.commit()

    def shortlist_ids(self):
        with closing(self.connect()) as con:
            return {int(r["property_id"]) for r in con.execute("SELECT property_id FROM shortlist").fetchall()}

    def set_shortlisted(self, property_id, enabled=True):
        with closing(self.connect()) as con:
            if enabled:
                con.execute(
                    "INSERT INTO shortlist(property_id,added_at) VALUES(?,?) ON CONFLICT(property_id) DO NOTHING",
                    (property_id, datetime.now(timezone.utc).isoformat()),
                )
            else:
                con.execute("DELETE FROM shortlist WHERE property_id=?", (property_id,))
            con.commit()

    def clear_underwriting(self, property_id):
        with closing(self.connect()) as con:
            con.execute("DELETE FROM underwriting_overrides WHERE property_id=?", (property_id,))
            con.commit()

    def comparable_summary_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM comparable_summaries WHERE property_id=?", (property_id,)).fetchone()
        if not row:
            return {}
        out = dict(row)
        try:
            out["warnings"] = json.loads(out.get("warnings_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["warnings"] = []
        return out

    def comparable_summary_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM comparable_summaries").fetchall()]
        out = {}
        for row in rows:
            try:
                row["warnings"] = json.loads(row.get("warnings_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["warnings"] = []
            out[row["property_id"]] = row
        return out

    def comparables_for(self, property_id):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM comparables WHERE property_id=? ORDER BY match_score DESC, sale_date DESC",
                (property_id,),
            ).fetchall()]
        for row in rows:
            try:
                row["metadata"] = json.loads(row.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["metadata"] = {}
        return rows

    def comparables_due(self, property_id, max_age_days=14):
        summary = self.comparable_summary_for(property_id)
        if not summary or summary.get("status") == "error" or not summary.get("updated_at"):
            return True
        try:
            stamp = datetime.fromisoformat(str(summary["updated_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - stamp > timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return True

    def save_comparable_bundle(self, property_id, summary, comps):
        now = datetime.now(timezone.utc).isoformat()
        warnings = summary.get("warnings") or []
        with closing(self.connect()) as con:
            con.execute("DELETE FROM comparables WHERE property_id=?", (property_id,))
            for comp in comps:
                con.execute(
                    """
                    INSERT INTO comparables(
                      property_id,provider,source_ref,address,postcode,sale_price,sale_date,property_type,tenure,
                      distance_miles,size_sqft,price_per_sqft,match_score,same_property,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        property_id, comp.get("provider"), comp.get("source_ref"), comp.get("address"),
                        comp.get("postcode"), comp.get("sale_price"), comp.get("sale_date"), comp.get("property_type"),
                        comp.get("tenure"), comp.get("distance_miles"), comp.get("size_sqft"),
                        comp.get("price_per_sqft"), comp.get("match_score"), int(bool(comp.get("same_property"))),
                        json.dumps(comp.get("metadata") or {}, ensure_ascii=False),
                    ),
                )
            con.execute(
                """
                INSERT INTO comparable_summaries(
                  property_id,provider,status,updated_at,valuation_low,valuation_mid,valuation_high,unit_psf_mid,
                  comp_count,confidence,guide_discount_pct,methodology,warnings_json,attribution,error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET
                  provider=excluded.provider,status=excluded.status,updated_at=excluded.updated_at,
                  valuation_low=excluded.valuation_low,valuation_mid=excluded.valuation_mid,valuation_high=excluded.valuation_high,
                  unit_psf_mid=excluded.unit_psf_mid,comp_count=excluded.comp_count,confidence=excluded.confidence,
                  guide_discount_pct=excluded.guide_discount_pct,methodology=excluded.methodology,
                  warnings_json=excluded.warnings_json,attribution=excluded.attribution,error=excluded.error
                """,
                (
                    property_id, summary.get("provider"), "ok", now, summary.get("valuation_low"),
                    summary.get("valuation_mid"), summary.get("valuation_high"), summary.get("unit_psf_mid"),
                    summary.get("comp_count") or 0, summary.get("confidence") or 0, summary.get("guide_discount_pct"),
                    summary.get("methodology"), json.dumps(warnings, ensure_ascii=False), summary.get("attribution"), None,
                ),
            )
            con.commit()

    def record_comparable_error(self, property_id, error):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            existing = con.execute("SELECT provider FROM comparable_summaries WHERE property_id=?", (property_id,)).fetchone()
            if existing:
                con.execute(
                    "UPDATE comparable_summaries SET status='error', updated_at=?, error=? WHERE property_id=?",
                    (now, error, property_id),
                )
            else:
                con.execute(
                    "INSERT INTO comparable_summaries(property_id,provider,status,updated_at,error) VALUES(?,?,?,?,?)",
                    (property_id, None, "error", now, error),
                )
            con.commit()

    def planning_summary_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM planning_summaries WHERE property_id=?", (property_id,)).fetchone()
        if not row:
            return {}
        out = dict(row)
        try:
            out["warnings"] = json.loads(out.get("warnings_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["warnings"] = []
        return out

    def planning_summary_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM planning_summaries").fetchall()]
        out = {}
        for row in rows:
            try:
                row["warnings"] = json.loads(row.get("warnings_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["warnings"] = []
            out[row["property_id"]] = row
        return out

    def planning_constraint_flags_map(self):
        with closing(self.connect()) as con:
            rows = con.execute(
                "SELECT property_id,dataset,MAX(severity) AS severity FROM planning_items WHERE kind='constraint' GROUP BY property_id,dataset"
            ).fetchall()
        out = {}
        for row in rows:
            flags = out.setdefault(row["property_id"], {})
            flags[row["dataset"]] = int(row["severity"] or 0)
        return out

    def planning_items_for(self, property_id):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM planning_items WHERE property_id=? ORDER BY kind, likely_subject DESC, severity DESC, distance_miles",
                (property_id,),
            ).fetchall()]
        for row in rows:
            try:
                row["metadata"] = json.loads(row.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["metadata"] = {}
        return rows

    def planning_due(self, property_id, max_age_days=21):
        summary = self.planning_summary_for(property_id)
        if not summary or summary.get("status") == "error" or not summary.get("updated_at"):
            return True
        try:
            stamp = datetime.fromisoformat(str(summary["updated_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - stamp > timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return True

    def save_planning_bundle(self, property_id, summary, items):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("DELETE FROM planning_items WHERE property_id=?", (property_id,))
            for item in items or []:
                con.execute(
                    """INSERT INTO planning_items(
                    property_id,kind,dataset,reference,name,severity,label,source_url,distance_miles,likely_subject,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (property_id, item.get("kind"), item.get("dataset"), item.get("reference"), item.get("name"),
                     item.get("severity") or 0, item.get("label"), item.get("source_url"), item.get("distance_miles"),
                     int(bool(item.get("likely_subject"))), json.dumps(item.get("metadata") or {}, ensure_ascii=False)),
                )
            con.execute(
                """INSERT INTO planning_summaries(
                property_id,provider,status,updated_at,risk_score,opportunity_score,constraint_count,application_count,
                subject_application_count,methodology,warnings_json,attribution,error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET
                provider=excluded.provider,status=excluded.status,updated_at=excluded.updated_at,risk_score=excluded.risk_score,
                opportunity_score=excluded.opportunity_score,constraint_count=excluded.constraint_count,
                application_count=excluded.application_count,subject_application_count=excluded.subject_application_count,
                methodology=excluded.methodology,warnings_json=excluded.warnings_json,attribution=excluded.attribution,error=excluded.error""",
                (property_id, summary.get("provider"), summary.get("status") or "ok", now, summary.get("risk_score") or 0,
                 summary.get("opportunity_score") or 0, summary.get("constraint_count") or 0, summary.get("application_count") or 0,
                 summary.get("subject_application_count") or 0, summary.get("methodology"),
                 json.dumps(summary.get("warnings") or [], ensure_ascii=False), summary.get("attribution"), summary.get("error")),
            )
            con.commit()

    def record_planning_error(self, property_id, error):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """INSERT INTO planning_summaries(property_id,provider,status,updated_at,error) VALUES(?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET status='error',updated_at=excluded.updated_at,error=excluded.error""",
                (property_id, "Planning Data (MHCLG)", "error", now, str(error)[:1000]),
            )
            con.commit()

    def legal_summary_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM legal_summaries WHERE property_id=?", (property_id,)).fetchone()
        if not row:
            return {}
        out = dict(row)
        try:
            out["warnings"] = json.loads(out.get("warnings_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["warnings"] = []
        try:
            out["risk_flags"] = json.loads(out.get("risk_flags_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["risk_flags"] = []
        try:
            out["extracted_fields"] = json.loads(out.get("extracted_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            out["extracted_fields"] = {}
        try:
            out["contacts"] = json.loads(out.get("contacts_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["contacts"] = []
        try:
            out["evidence"] = json.loads(out.get("evidence_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["evidence"] = []
        try:
            out["missing_components"] = json.loads(out.get("missing_components_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["missing_components"] = []
        try:
            out["available_components"] = json.loads(out.get("available_components_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            out["available_components"] = []
        try:
            out["pack_change"] = json.loads(out.get("pack_change_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            out["pack_change"] = {}
        try:
            out["revalidation_report"] = json.loads(out.get("revalidation_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            out["revalidation_report"] = {}
        return out

    def legal_summary_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM legal_summaries").fetchall()]
        out = {}
        for row in rows:
            try:
                row["warnings"] = json.loads(row.get("warnings_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["warnings"] = []
            try:
                row["risk_flags"] = json.loads(row.get("risk_flags_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["risk_flags"] = []
            try:
                row["extracted_fields"] = json.loads(row.get("extracted_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["extracted_fields"] = {}
            try:
                row["contacts"] = json.loads(row.get("contacts_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["contacts"] = []
            try:
                row["evidence"] = json.loads(row.get("evidence_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["evidence"] = []
            try:
                row["missing_components"] = json.loads(row.get("missing_components_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["missing_components"] = []
            try:
                row["available_components"] = json.loads(row.get("available_components_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                row["available_components"] = []
            try:
                row["pack_change"] = json.loads(row.get("pack_change_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["pack_change"] = {}
            try:
                row["revalidation_report"] = json.loads(row.get("revalidation_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["revalidation_report"] = {}
            out[row["property_id"]] = row
        return out

    def legal_documents_for(self, property_id):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM legal_documents WHERE property_id=? ORDER BY id", (property_id,)
            ).fetchall()]
        for row in rows:
            try:
                row["metadata"] = json.loads(row.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                row["metadata"] = {}
        return rows

    def legal_due(self, property_id, max_age_days=3):
        summary = self.legal_summary_for(property_id)
        if not summary or summary.get("status") == "error" or not summary.get("updated_at"):
            return True
        if str(summary.get("evidence_policy_version") or "") != EVIDENCE_POLICY_VERSION:
            return True
        try:
            stamp = datetime.fromisoformat(str(summary["updated_at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - stamp > timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return True

    def save_legal_bundle(self, property_id, summary, documents):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("DELETE FROM legal_documents WHERE property_id=?", (property_id,))
            for doc in documents or []:
                con.execute(
                    """INSERT INTO legal_documents(
                    property_id,name,url,doc_type,access_status,text_content,sha256,metadata_json,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (property_id, doc.get("name"), doc.get("url"), doc.get("doc_type"), doc.get("access_status"),
                     doc.get("text_content"), doc.get("sha256"), json.dumps(doc.get("metadata") or {}, ensure_ascii=False), now),
                )
            con.execute(
                """INSERT INTO legal_summaries(
                property_id,provider,status,updated_at,risk_score,document_count,candidate_document_count,rejected_document_count,pack_index_count,verified_document_count,
                parsed_document_count,auctioneer_evidence_count,verification_status,evidence_policy_version,completion_days,deposit_pct,
                lease_years,buyer_fee_detected,vat_flag,has_addendum,extracted_json,contacts_json,risk_flags_json,evidence_json,
                pack_completeness_pct,missing_components_json,available_components_json,pack_fingerprint,pack_changed,pack_change_json,revalidation_json,
                methodology,warnings_json,attribution,error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET
                provider=excluded.provider,status=excluded.status,updated_at=excluded.updated_at,risk_score=excluded.risk_score,
                document_count=excluded.document_count,candidate_document_count=excluded.candidate_document_count,
                rejected_document_count=excluded.rejected_document_count,pack_index_count=excluded.pack_index_count,
                verified_document_count=excluded.verified_document_count,parsed_document_count=excluded.parsed_document_count,
                auctioneer_evidence_count=excluded.auctioneer_evidence_count,verification_status=excluded.verification_status,
                evidence_policy_version=excluded.evidence_policy_version,
                completion_days=excluded.completion_days,deposit_pct=excluded.deposit_pct,lease_years=excluded.lease_years,
                buyer_fee_detected=excluded.buyer_fee_detected,vat_flag=excluded.vat_flag,has_addendum=excluded.has_addendum,
                extracted_json=excluded.extracted_json,contacts_json=excluded.contacts_json,risk_flags_json=excluded.risk_flags_json,
                evidence_json=excluded.evidence_json,pack_completeness_pct=excluded.pack_completeness_pct,
                missing_components_json=excluded.missing_components_json,available_components_json=excluded.available_components_json,
                pack_fingerprint=excluded.pack_fingerprint,pack_changed=excluded.pack_changed,pack_change_json=excluded.pack_change_json,
                revalidation_json=excluded.revalidation_json,methodology=excluded.methodology,warnings_json=excluded.warnings_json,attribution=excluded.attribution,error=excluded.error""",
                (property_id, summary.get("provider"), summary.get("status") or "not-found", now, summary.get("risk_score") or 0,
                 summary.get("document_count") or 0, summary.get("candidate_document_count") or 0,
                 summary.get("rejected_document_count") or 0, summary.get("pack_index_count") or 0,
                 summary.get("verified_document_count") or 0, summary.get("parsed_document_count") or 0,
                 summary.get("auctioneer_evidence_count") or 0, summary.get("verification_status") or summary.get("status"),
                 summary.get("evidence_policy_version"), summary.get("completion_days"),
                 summary.get("deposit_pct"), summary.get("lease_years"), summary.get("buyer_fee_detected"),
                 int(bool(summary.get("vat_flag"))), int(bool(summary.get("has_addendum"))),
                 json.dumps(summary.get("extracted_fields") or {}, ensure_ascii=False),
                 json.dumps(summary.get("contacts") or [], ensure_ascii=False),
                 json.dumps(summary.get("risk_flags") or [], ensure_ascii=False),
                 json.dumps(summary.get("evidence") or [], ensure_ascii=False),
                 int(summary.get("pack_completeness_pct") or 0),
                 json.dumps(summary.get("missing_components") or [], ensure_ascii=False),
                 json.dumps(summary.get("available_components") or [], ensure_ascii=False),
                 summary.get("pack_fingerprint"), int(bool(summary.get("pack_changed"))),
                 json.dumps(summary.get("pack_change") or {}, ensure_ascii=False),
                 json.dumps(summary.get("revalidation_report") or {}, ensure_ascii=False),
                 summary.get("methodology"), json.dumps(summary.get("warnings") or [], ensure_ascii=False),
                 summary.get("attribution"), summary.get("error")),
            )
            con.commit()

    def company_intelligence_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM company_intelligence WHERE property_id=?", (property_id,)).fetchone()
        if not row:
            return {}
        out = dict(row)
        try:
            out.update(json.loads(out.get("summary_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            pass
        return out

    def company_intelligence_map(self):
        with closing(self.connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM company_intelligence").fetchall()]
        out = {}
        for row in rows:
            try:
                row.update(json.loads(row.get("summary_json") or "{}"))
            except (TypeError, json.JSONDecodeError):
                pass
            out[row["property_id"]] = row
        return out

    def save_company_intelligence(self, property_id, summary):
        now = summary.get("updated_at") or datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """INSERT INTO company_intelligence(
                property_id,provider,status,updated_at,company_number,company_name,company_status,registered_office,
                corporate_pressure_score,summary_json,error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET
                provider=excluded.provider,status=excluded.status,updated_at=excluded.updated_at,
                company_number=excluded.company_number,company_name=excluded.company_name,company_status=excluded.company_status,
                registered_office=excluded.registered_office,corporate_pressure_score=excluded.corporate_pressure_score,
                summary_json=excluded.summary_json,error=excluded.error""",
                (property_id, summary.get("provider"), summary.get("status") or "ok", now,
                 summary.get("company_number"), summary.get("company_name"), summary.get("company_status"),
                 summary.get("registered_office"), summary.get("corporate_pressure_score") or 0,
                 json.dumps(summary or {}, ensure_ascii=False), summary.get("error")),
            )
            con.commit()

    def clear_company_intelligence(self, property_id):
        """Remove corporate enrichment that is no longer supported by verified seller evidence."""
        with closing(self.connect()) as con:
            con.execute("DELETE FROM company_intelligence WHERE property_id=?", (property_id,))
            con.commit()

    def record_company_error(self, property_id, error, company_number=None):
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "provider": "Companies House Public Data API", "status": "error", "updated_at": now,
            "company_number": company_number, "error": str(error)[:1000],
        }
        with closing(self.connect()) as con:
            con.execute(
                """INSERT INTO company_intelligence(property_id,provider,status,updated_at,company_number,summary_json,error)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET provider=excluded.provider,status='error',updated_at=excluded.updated_at,
                company_number=COALESCE(excluded.company_number,company_intelligence.company_number),summary_json=excluded.summary_json,error=excluded.error""",
                (property_id, payload["provider"], "error", now, company_number, json.dumps(payload), str(error)[:1000]),
            )
            con.commit()

    def record_legal_error(self, property_id, error):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """INSERT INTO legal_summaries(property_id,provider,status,updated_at,error) VALUES(?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET status='error',updated_at=excluded.updated_at,error=excluded.error""",
                (property_id, "Auctioneer legal pack", "error", now, str(error)[:1000]),
            )
            con.commit()

    def workspace_for(self, property_id):
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM deal_workspace WHERE property_id=?", (property_id,)).fetchone()
        return dict(row) if row else {"property_id": property_id, "stage": "New", "next_action": "", "follow_up_date": ""}

    def save_workspace(self, property_id, stage="New", next_action="", follow_up_date=""):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """INSERT INTO deal_workspace(property_id,stage,next_action,follow_up_date,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(property_id) DO UPDATE SET stage=excluded.stage,next_action=excluded.next_action,
                follow_up_date=excluded.follow_up_date,updated_at=excluded.updated_at""",
                (property_id, stage or "New", next_action or "", follow_up_date or "", now),
            )
            con.commit()

    def notes_for(self, property_id):
        with closing(self.connect()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM deal_notes WHERE property_id=? ORDER BY created_at DESC, id DESC", (property_id,)
            ).fetchall()]

    def add_note(self, property_id, note):
        note = str(note or "").strip()
        if not note:
            return
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("INSERT INTO deal_notes(property_id,created_at,note) VALUES(?,?,?)", (property_id, now, note[:8000]))
            con.commit()

    def delete_note(self, note_id, property_id=None):
        with closing(self.connect()) as con:
            if property_id is None:
                con.execute("DELETE FROM deal_notes WHERE id=?", (note_id,))
            else:
                con.execute("DELETE FROM deal_notes WHERE id=? AND property_id=?", (note_id, property_id))
            con.commit()

    def start_run(self, source):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            cur = con.execute(
                "INSERT INTO refresh_runs(source,started_at,status) VALUES(?,?,?)", (source, now, "running")
            )
            con.commit()
            return cur.lastrowid

    def finish_run(self, run_id, status, count=0, error=""):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                "UPDATE refresh_runs SET completed_at=?,status=?,rows_found=?,error=? WHERE id=?",
                (now, status, count, error, run_id),
            )
            con.commit()

    def latest_runs(self):
        with closing(self.connect()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM refresh_runs ORDER BY id DESC LIMIT 16"
            ).fetchall()]

    def get_app_state(self, key, default=None):
        with closing(self.connect()) as con:
            row = con.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_app_state(self, key, value):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute(
                """
                INSERT INTO app_state(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
                """,
                (key, str(value) if value is not None else "", now),
            )
            con.commit()
