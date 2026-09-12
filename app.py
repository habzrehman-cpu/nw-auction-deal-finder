from pathlib import Path
import os
import re
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from tracker.db import Database
from tracker.pipeline import refresh_all, refresh_geography
from tracker.deal_engine import DealConfig, score_property
from tracker.underwriting import UnderwritingDefaults, underwrite_property
from tracker.comparables import refresh_due_comparables, refresh_property_comparables
from tracker.diligence import (
    refresh_due_diligence,
    refresh_property_planning,
    refresh_property_legal,
    refresh_property_company,
    refresh_due_company_intelligence,
    save_uploaded_legal_documents,
)
from tracker.legal import uploaded_document, uploaded_documents
from tracker.legal_firewall import EVIDENCE_POLICY_VERSION
from tracker.legal_access import config_from_mapping as legal_access_from_mapping, provider_access_status
from tracker.cloud import SupabaseStorage, config_from_mapping
from tracker.intelligence import build_vendor_story, deal_readiness, next_actions, solicitor_questions, deal_brief_markdown


POUND = "\u00a3"
COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}
SOLD_STATES = {"sold", "sold prior", "sold after"}
UNSOLD_STATES = {"Available post-auction", "No Bids", "Last Bid", "Unsold"}

ASSET_DIR = Path(__file__).with_name("assets")
LOTLY_LOGO = ASSET_DIR / "lotly_logo.png"
LOTLY_ICON = ASSET_DIR / "lotly_icon.png"

st.set_page_config(page_title="Lotly | Property Auction Intelligence", page_icon="🏷️", layout="wide")

st.markdown(
    """
<style>
:root {--ink:#0b1f33;--muted:#667085;--line:#e4e9ef;--panel:#ffffff;--soft:#f7fafb;--accent:#0f8f83;--accent2:#2dd4bf;--good:#147d5b;--warn:#9a6700;--risk:#b42318;}
.stApp {background:linear-gradient(180deg,#fbfdfd 0%,#f7f9fb 100%);}
.block-container {padding-top: 1.0rem; padding-bottom: 4rem; max-width: 1480px;}
[data-testid="stSidebar"] {background:#fbfdfd; border-right:1px solid #e4e9ef;}
[data-testid="stSidebar"] .block-container {padding-top:.8rem;}
[data-testid="stMetric"] {background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; box-shadow:0 1px 2px rgba(16,24,40,.03);}
[data-testid="stMetricLabel"] {font-size: 0.75rem; color: var(--muted);}
[data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 760; color:var(--ink);}
[data-testid="stExpander"] {border-color:var(--line)!important; border-radius:12px!important; background:#fff;}
.auction-hero {padding: 6px 0 10px 0;}
.auction-hero h1 {font-size: 2.05rem; margin-bottom: 0.12rem; letter-spacing:-.025em; color:var(--ink);}
.auction-hero .muted {max-width:900px;}
.muted {color: var(--muted); font-size: 0.9rem;}
.eyebrow {font-size:.72rem;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:#7b8495;margin-bottom:4px;}
.badge {display:inline-flex;align-items:center;padding:4px 9px;margin:2px 4px 2px 0;border-radius:999px;font-size:.75rem;font-weight:680;border:1px solid #d5dae2;background:#f8fafc;color:#344054;}
.badge-hot {background:#fff7e8;border-color:#f4c56a;color:#8a4b08;}
.badge-risk {background:#fff1f0;border-color:#f5aaa5;color:#a32018;}
.badge-good {background:#edfdf3;border-color:#91d8ad;color:#166534;}
.badge-info {background:#eef4ff;border-color:#b6c7f7;color:#284c9b;}
.property-title {font-size:1.18rem;font-weight:770;line-height:1.28;margin:2px 0 6px 0;color:var(--ink);letter-spacing:-.01em;}
.card-sub {color:var(--muted);font-size:.82rem;margin-bottom:5px;}
.deal-score {font-size:1.75rem;font-weight:820;line-height:1;color:var(--ink);}
.deal-score-label {font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;}
.score-caption {font-size:.76rem;font-weight:700;margin-top:5px;color:#344054;}
.soft-panel {background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:14px;}
.small-label {font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;}
.big-number {font-size:1.2rem;font-weight:760;color:var(--ink);}
.quick-stat {background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;min-height:84px;}
.quick-stat .q-label {font-size:.75rem;color:var(--muted);margin-bottom:6px;}
.quick-stat .q-value {font-size:1.4rem;font-weight:800;color:var(--ink);}
.card-reason {font-size:.82rem;color:#475467;background:#f8fafc;border-left:3px solid #cdd5df;border-radius:7px;padding:7px 9px;margin-top:8px;}
.decision-banner {border:1px solid var(--line);border-radius:14px;padding:13px 16px;margin:8px 0 12px;background:#fff;}
.decision-banner strong {color:var(--ink);}
.section-note {font-size:.82rem;color:var(--muted);}
.identity-verified {color:#166534;font-weight:700;}
.identity-rejected {color:#b42318;font-weight:700;}
.identity-candidate {color:#9a6700;font-weight:700;}
[data-testid="stImage"] img {border-radius:12px;object-fit:cover;}
div.stButton > button, div.stLinkButton > a {border-radius:10px;min-height:42px;font-weight:650;}
[data-testid="stSegmentedControl"] {margin-bottom:.25rem;}
[data-testid="stHorizontalBlock"] {gap:.7rem;}
hr {margin: 1rem 0;}
.lotly-brandbar {display:flex;align-items:center;gap:14px;margin:2px 0 10px 0;}
.lotly-kicker {font-size:.76rem;font-weight:780;letter-spacing:.11em;text-transform:uppercase;color:#0f8f83;margin-bottom:5px;}
.lotly-title {font-size:2.35rem;font-weight:840;letter-spacing:-.04em;line-height:1.05;color:#0b1f33;margin:0 0 7px 0;}
.lotly-subtitle {font-size:1rem;color:#667085;max-width:900px;line-height:1.5;}
.lotly-trust {display:inline-flex;align-items:center;gap:7px;background:#ecfdf7;color:#116149;border:1px solid #b7ead6;border-radius:999px;padding:5px 10px;font-size:.76rem;font-weight:700;margin-top:10px;}
div.stButton > button[kind="primary"] {background:linear-gradient(135deg,#0f8f83,#0b756d)!important;border-color:#0b756d!important;color:#fff!important;box-shadow:0 6px 16px rgba(15,143,131,.16);}
div.stButton > button[kind="primary"]:hover {background:linear-gradient(135deg,#0b8278,#09675f)!important;}
[data-baseweb="tab-highlight"] {background-color:#0f8f83!important;}

</style>
""",
    unsafe_allow_html=True,
)

DB_PATH = Path(os.environ.get("AUCTION_DB_PATH", str(Path(__file__).with_name("auction_tracker.db"))))

# Optional private cloud persistence. Streamlit Community Cloud has ephemeral local
# storage, so a Supabase Storage snapshot is restored on a cold start and synced
# after meaningful changes. The app remains fully usable in local-only mode.
try:
    _secrets_mapping = st.secrets
except Exception:
    _secrets_mapping = {}
cloud_config = config_from_mapping(_secrets_mapping)
cloud_store = SupabaseStorage(cloud_config) if cloud_config.configured else None
try:
    _ch_mapping = _secrets_mapping.get("companies_house", {}) if _secrets_mapping else {}
except Exception:
    _ch_mapping = {}
companies_house_api_key = str(
    os.environ.get("COMPANIES_HOUSE_API_KEY") or
    (_ch_mapping.get("api_key", "") if hasattr(_ch_mapping, "get") else "")
).strip()
legal_access = legal_access_from_mapping(_secrets_mapping)
cloud_bootstrap = {"restored": False, "reason": "not-configured"}
cloud_bootstrap_error = ""
cloud_probe = st.session_state.get("cloud_probe", {}) if cloud_store else {}
cloud_probe_error = st.session_state.get("cloud_probe_error", "") if cloud_store else ""
if cloud_store:
    try:
        cloud_bootstrap = cloud_store.restore_database_if_missing(DB_PATH)
    except Exception as exc:
        cloud_bootstrap_error = str(exc)[:800]
    # A configured Secrets block is not the same as a verified connection. Probe
    # the existing private bucket once per Streamlit session so the UI does not
    # claim that cloud persistence is connected until Supabase has responded.
    if not cloud_probe and not cloud_probe_error:
        try:
            cloud_probe = cloud_store.probe()
            st.session_state["cloud_probe"] = cloud_probe
            st.session_state["cloud_probe_error"] = ""
        except Exception as exc:
            cloud_probe_error = str(exc)[:800]
            st.session_state["cloud_probe_error"] = cloud_probe_error

db = Database(DB_PATH)

def sync_cloud(reason="update", quiet=True):
    if not cloud_store:
        return {"synced": False, "reason": "not-configured"}
    try:
        result = cloud_store.upload_database(DB_PATH)
        result["reason_label"] = reason
        st.session_state["cloud_last_sync"] = datetime.now(timezone.utc).isoformat()
        st.session_state["cloud_last_error"] = ""
        st.session_state["cloud_write_verified"] = True
        return result
    except Exception as exc:
        st.session_state["cloud_last_error"] = str(exc)[:500]
        if not quiet:
            st.warning(f"Cloud persistence could not sync this update: {exc}")
        return {"synced": False, "reason": str(exc)}


def money(value, digits=0):
    if value is None or value == "":
        return "-"
    try:
        return f"{POUND}{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def pct(value):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def guide_display(row):
    """Human-readable guide preserving auctioneer guide ranges."""
    low = row.get("guide_price")
    high = row.get("guide_price_high")
    if high and low and float(high) > float(low):
        return f"{money(low)}-{money(high)}"
    text = " ".join(str(row.get("guide_text") or "").split())
    # guide_text is already isolated by the scraper; retain a range if one is present.
    if text and ("-" in text or "–" in text or " to " in text.lower()):
        return text.replace(" (plus fees)", "").replace("(plus fees)", "").strip()
    return money(low)


def is_commercial(row):
    return (row.get("property_type") or "").strip().lower() in COMMERCIAL_TYPES


def is_actionable(row):
    return (row.get("status") or "").strip().lower() not in SOLD_STATES


def is_unsold(row):
    return row.get("status") in UNSOLD_STATES


def clean_address(row):
    text = " ".join(str(row.get("address") or row.get("title") or "").split())
    postcode = str(row.get("postcode") or "").strip()
    if not text:
        return postcode or "Property"
    if postcode and postcode in text:
        before = text[: text.rfind(postcode)].strip(" ,-|*")
        # Prefer the final building number/street sequence before the postcode.
        matches = list(re.finditer(r"\b\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?\s+[A-Za-z][^|]{2,120}$", before))
        if matches:
            candidate = matches[-1].group(0).strip(" ,-|*")
            return f"{candidate}, {postcode}"
        tail = before[-120:].strip(" ,-|*")
        return f"{tail}, {postcode}" if tail else postcode
    return text[:150]


def first_seen_today(row):
    try:
        stamp = datetime.fromisoformat(str(row.get("first_seen") or "").replace("Z", "+00:00"))
        return stamp.date() == datetime.now(timezone.utc).date()
    except Exception:
        return False


def browse_rank(row):
    comp = float(row.get("comparable_confidence") or 0) / 10.0
    financial = float(row.get("financial_score") or 0)
    sourcing = float(row.get("deal_score") or 0)
    motivation = float(row.get("motivation_score") or 0)
    asset = float(row.get("asset_quality_score") or 0)
    risk = float(row.get("risk_score") or 0)
    value = 0.34 * sourcing + 0.26 * motivation + 0.22 * financial + 0.10 * comp + 0.08 * asset - 0.10 * risk
    if row.get("status") == "Available post-auction":
        value += 0.35
    if (row.get("price_reduction_pct") or 0) >= 5:
        value += 0.2
    # Unknown evidence must never improve a rank simply because its numeric risk is
    # currently blank/zero. Keep good sourcing leads visible, but slightly penalise
    # incomplete DD and zero-works assumptions until the evidence is supplied.
    if legal_state(row) != "VERIFIED" or int(row.get("legal_pack_completeness_pct") or 0) < 100:
        value -= 0.45
    if planning_state(row) != "SCREENED":
        value -= 0.15
    if row.get("works_missing"):
        value -= 0.35
    if 0 < float(row.get("comparable_confidence") or 0) < 60:
        value -= 0.15
    corporate_pressure = float(row.get("corporate_pressure_score") or 0)
    if corporate_pressure >= 8:
        value += 0.25
    elif corporate_pressure >= 6:
        value += 0.15
    return round(max(0.0, min(10.0, value)), 1)


def legal_state(row):
    status = str(row.get("legal_status") or "").lower()
    policy = str(row.get("legal_evidence_policy_version") or "")
    verified = int(row.get("legal_verified_document_count") or 0)
    # Any extraction saved under an older evidence policy is deliberately
    # downgraded until v1.10.3 revalidation has rebuilt its derived findings.
    if status and policy != EVIDENCE_POLICY_VERSION:
        return "UNVERIFIED"
    if status == "verified" and verified > 0 and policy == EVIDENCE_POLICY_VERSION:
        return "VERIFIED"
    if status == "verified-no-text" and verified > 0:
        return "VERIFIED NO TEXT"
    if status in {"candidates-only", "links-only"}:
        return "CANDIDATES ONLY"
    if status == "error":
        return "ERROR"
    return "UNKNOWN"


def planning_state(row):
    status = str(row.get("planning_status") or "").lower()
    if status == "ok":
        return "SCREENED"
    if status == "error":
        return "ERROR"
    return "UNKNOWN"


def render_refresh_summary():
    refresh = st.session_state.get("refresh_summary")
    if not refresh:
        return
    sources = refresh.get("sources", [])
    geo = refresh.get("geography", {})
    comps = refresh.get("comparables", {})
    dd = refresh.get("diligence", {})
    company = refresh.get("companies_house", {})
    ok = sum(x.get("status") == "ok" for x in sources)
    found = sum(int(x.get("found") or 0) for x in sources)
    changed = sum(int(x.get("changed") or 0) for x in sources)
    detail = sum(int(x.get("detail_enriched") or 0) for x in sources)
    st.success(
        f"Live refresh complete: {ok}/{len(sources) or 4} sources responded | {found} North West rows | "
        f"{changed} new/changed | {detail} detail/image pages enriched."
    )
    st.caption(
        f"Location: {geo.get('postcodes_newly_geocoded', 0)} new postcodes | "
        f"{geo.get('motorway_enriched', 0)} junction distances. Comparable evidence: "
        f"{comps.get('ok', 0)}/{comps.get('attempted', 0)}. Due diligence: planning "
        f"{dd.get('planning_ok', 0)}/{dd.get('planning_attempted', 0)}, legal {dd.get('legal_ok', 0)}/{dd.get('legal_attempted', 0)}"
        + (f", Companies House {company.get('ok', 0)}/{company.get('attempted', 0)}." if company.get("configured") else ".")
    )
    errors = [x for x in sources if x.get("status") != "ok"] + [{"source": "Geography", "error": e} for e in geo.get("errors", [])]
    errors += [{"source": "Planning/legal", "error": e} for e in (dd.get("planning_errors", []) + dd.get("legal_errors", []))]
    errors += [{"source": "Companies House", "error": e} for e in company.get("errors", [])]
    if errors:
        with st.expander("Refresh warnings"):
            for item in errors:
                st.write(f"**{item.get('source')}** - {item.get('error')}")


# Sidebar keeps strategy visible and moves technical settings into compact groups.
with st.sidebar:
    if LOTLY_LOGO.exists():
        st.image(str(LOTLY_LOGO), width=175)
    st.markdown("### Lotly workspace")
    st.caption("Set your buying criteria once. Lotly ranks live auction opportunities around how you actually invest.")

    with st.expander("Acquisition strategy", expanded=True):
        commercial_target_psf = st.number_input("Commercial target GBP/sq ft", min_value=1, value=50, step=5)
        commercial_ceiling_psf = st.number_input("Commercial ceiling GBP/sq ft", min_value=1, value=60, step=5)
        commercial_min_sqft = st.number_input("Preferred commercial size", min_value=500, value=9000, step=500)
        commercial_max_price = st.number_input("Commercial max guide", min_value=0, value=1_500_000, step=50_000)
        preferred_motorway_miles = st.number_input("Preferred motorway miles", min_value=0.5, value=5.0, step=0.5)
        residential_target_price = st.number_input("Residential target guide", min_value=0, value=100_000, step=5_000)
        hot_score = st.slider("Hot deal threshold", 1.0, 10.0, 8.0, 0.5)

    with st.expander("Underwriting defaults", expanded=False):
        st.caption("These are starting allowances. Each deal can override them.")
        default_auction_fee = st.number_input("Generic auction fee", min_value=0, value=1500, step=250)
        default_legal = st.number_input("Legal allowance", min_value=0, value=2000, step=250)
        default_survey = st.number_input("Survey / DD allowance", min_value=0, value=1000, step=250)
        default_res_margin = st.number_input("Residential target margin %", min_value=0.0, max_value=80.0, value=20.0, step=1.0)
        default_com_margin = st.number_input("Commercial target uplift %", min_value=0.0, max_value=80.0, value=20.0, step=1.0)

    st.markdown("#### System health")
    if cloud_store and not cloud_bootstrap_error and not cloud_probe_error:
        if st.session_state.get("cloud_write_verified"):
            st.success("Cloud history protected")
        else:
            st.info("Cloud connected - verify write")
        last_sync = st.session_state.get("cloud_last_sync")
        if last_sync:
            st.caption(f"Last sync {str(last_sync)[:16].replace('T', ' ')} UTC")
        if st.button("Sync cloud snapshot", use_container_width=True):
            result = sync_cloud("manual sync", quiet=False)
            if result.get("synced"):
                st.success("Snapshot saved")
    elif cloud_bootstrap_error or cloud_probe_error:
        st.error("Cloud needs attention")
        st.caption(cloud_bootstrap_error or cloud_probe_error)
        if st.button("Retry cloud connection", use_container_width=True):
            st.session_state.pop("cloud_probe", None)
            st.session_state.pop("cloud_probe_error", None)
            st.rerun()
    else:
        st.warning("Local-only history")
        st.caption("Configure Supabase before relying on long-term auction history.")

    with st.expander("Data connections", expanded=False):
        if companies_house_api_key:
            st.success("Companies House connected")
        else:
            st.info("Companies House not configured")
        if legal_access.auto_enabled:
            st.success("Legal-pack automation on")
        else:
            st.info("Legal-pack automation off")
        for provider in ("eddisons", "savills", "auction_house", "allsop"):
            access_status = provider_access_status(legal_access, provider)
            label = access_status.get("label") or provider
            status = access_status.get("status") or "unknown"
            icon = "OK" if access_status.get("allowed") else "BLOCKED"
            st.caption(f"{icon} - {label}: {status}")
        st.caption("No CAPTCHA or anti-bot bypass is attempted. Permission-gated sources stay blocked until authorised.")

config = DealConfig(
    commercial_target_psf=int(commercial_target_psf),
    commercial_ceiling_psf=int(max(commercial_target_psf, commercial_ceiling_psf)),
    commercial_min_sqft=int(commercial_min_sqft),
    commercial_max_price=int(commercial_max_price),
    commercial_preferred_motorway_miles=float(preferred_motorway_miles),
    residential_target_price=int(residential_target_price),
    hot_score=float(hot_score),
)
underwriting_defaults = UnderwritingDefaults(
    auction_admin_fee=float(default_auction_fee),
    legal_cost=float(default_legal),
    survey_cost=float(default_survey),
    target_residential_profit_margin_pct=float(default_res_margin),
    target_commercial_equity_margin_pct=float(default_com_margin),
)

# Header and refresh controls.
if LOTLY_LOGO.exists():
    st.image(str(LOTLY_LOGO), width=230)
st.markdown(
    '<div class="auction-hero"><div class="lotly-kicker">Property Auction Intelligence</div>'
    '<div class="lotly-title">Find your next opportunity.</div>'
    '<div class="lotly-subtitle">Live auction stock ranked around value, seller motivation, evidence quality and risk — so you can move from discovery to decision faster.</div>'
    '<div class="lotly-trust">● Evidence-led deal sourcing</div></div>',
    unsafe_allow_html=True,
)
head1, head2, head3, head4 = st.columns([1.05, 1.0, 1.0, 2.7])
with head1:
    if st.button("Refresh live data", type="primary", use_container_width=True):
        with st.spinner("Pulling live auction stock and priority intelligence..."):
            st.session_state["refresh_summary"] = refresh_all(db, companies_house_api_key=companies_house_api_key, legal_access=legal_access, cloud_store=cloud_store)
            sync_cloud("live refresh", quiet=False)
        st.rerun()
with head2:
    if st.button("Refresh comparables", use_container_width=True):
        with st.spinner("Refreshing priority comparable evidence..."):
            st.session_state["comp_summary"] = refresh_due_comparables(db, max_properties=35)
            sync_cloud("comparable refresh", quiet=False)
        st.rerun()
with head3:
    if st.button("Refresh planning/legal", use_container_width=True):
        with st.spinner("Refreshing priority due diligence..."):
            dd_result = refresh_due_diligence(db, max_planning=35, max_legal=20, legal_access=legal_access, cloud_store=cloud_store)
            company_result = refresh_due_company_intelligence(db, companies_house_api_key, max_companies=20)
            st.session_state["dd_summary"] = {**dd_result, "companies_house": company_result}
            sync_cloud("planning/legal/company refresh", quiet=False)
        st.rerun()
with head4:
    runs = db.latest_runs()
    if runs:
        latest = runs[0]
        st.caption(f"Latest source check: {latest.get('completed_at') or latest.get('started_at')} | {latest.get('source')} | {latest.get('status')}")
    else:
        st.caption("No data pulled yet. Use Refresh live data.")
    if cloud_store and not cloud_bootstrap_error and not cloud_probe_error:
        status = "read/write verified" if st.session_state.get("cloud_write_verified") else "connected; write not yet verified"
        st.caption(f"Persistence: private cloud {status}")
    elif cloud_bootstrap_error or cloud_probe_error:
        st.caption("Persistence: cloud configured but connection needs attention")
    else:
        st.caption("Persistence: local only (data can reset on Streamlit reboot)")
render_refresh_summary()

# Build analysis rows once per Streamlit rerun.
rows = db.list_properties()
history_map = db.history_map() if rows else {}
underwriting_map = db.underwriting_map() if rows else {}
comparable_map = db.comparable_summary_map() if rows else {}
planning_map = db.planning_summary_map() if rows else {}
legal_map = db.legal_summary_map() if rows else {}
company_map = db.company_intelligence_map() if rows else {}
planning_flags_map = db.planning_constraint_flags_map() if rows else {}
shortlist_ids = db.shortlist_ids() if rows else set()

for row in rows:
    analysis = score_property(row, history_map.get(row["id"], []), strategy="auto", config=config)
    row.update(analysis)
    comp = comparable_map.get(row["id"], {})
    comp_conf = int(comp.get("confidence") or 0)
    if comp.get("status") == "error" and comp_conf:
        comp_conf = max(0, comp_conf - 15)
    row.update({
        "comparable_provider": comp.get("provider"),
        "comparable_status": comp.get("status"),
        "comparable_updated_at": comp.get("updated_at"),
        "comparable_valuation_low": comp.get("valuation_low"),
        "comparable_valuation_mid": comp.get("valuation_mid"),
        "comparable_valuation_high": comp.get("valuation_high"),
        "comparable_unit_psf_mid": comp.get("unit_psf_mid"),
        "comparable_count": comp.get("comp_count") or 0,
        "comparable_confidence": comp_conf,
        "comparable_guide_discount_pct": comp.get("guide_discount_pct"),
        "comparable_methodology": comp.get("methodology"),
        "comparable_warnings": comp.get("warnings") or [],
        "comparable_attribution": comp.get("attribution"),
        "comparable_error": comp.get("error"),
    })
    planning = planning_map.get(row["id"], {})
    legal = legal_map.get(row["id"], {})
    legal_current = str(legal.get("evidence_policy_version") or "") == EVIDENCE_POLICY_VERSION
    legal_fields_current = (legal.get("extracted_fields") or {}) if legal_current else {}
    legal_field_sources = (legal_fields_current.get("field_sources") or {}) if isinstance(legal_fields_current, dict) else {}
    flags = planning_flags_map.get(row["id"], {})
    row.update({
        "planning_provider": planning.get("provider"),
        "planning_status": planning.get("status"),
        "planning_updated_at": planning.get("updated_at"),
        "planning_risk_score": float(planning.get("risk_score") or 0) if planning else None,
        "planning_opportunity_score": float(planning.get("opportunity_score") or 0) if planning else 0,
        "planning_constraint_count": int(planning.get("constraint_count") or 0) if planning else 0,
        "planning_application_count": int(planning.get("application_count") or 0) if planning else 0,
        "planning_subject_application_count": int(planning.get("subject_application_count") or 0) if planning else 0,
        "planning_warnings": planning.get("warnings") or [],
        "planning_error": planning.get("error"),
        "planning_listed_flag": bool(flags.get("listed-building") or flags.get("listed-building-outline")),
        "legal_provider": legal.get("provider"),
        "legal_status": legal.get("status"),
        "legal_updated_at": legal.get("updated_at"),
        "legal_risk_score": float(legal.get("risk_score") or 0) if legal and str(legal.get("status") or "").lower() == "verified" and str(legal.get("evidence_policy_version") or "") == EVIDENCE_POLICY_VERSION else None,
        "legal_document_count": int(legal.get("document_count") or 0) if legal else 0,
        "legal_candidate_document_count": int(legal.get("candidate_document_count") if legal.get("candidate_document_count") is not None else (legal.get("document_count") or 0)) if legal else 0,
        "legal_rejected_document_count": int(legal.get("rejected_document_count") or 0) if legal else 0,
        "legal_pack_index_count": int(legal.get("pack_index_count") or 0) if legal else 0,
        "legal_verified_document_count": int(legal.get("verified_document_count") or 0) if legal else 0,
        "legal_parsed_document_count": int(legal.get("parsed_document_count") or 0) if legal else 0,
        "legal_auctioneer_evidence_count": int(legal.get("auctioneer_evidence_count") or 0) if legal else 0,
        "legal_verification_status": legal.get("verification_status"),
        "legal_evidence_policy_version": legal.get("evidence_policy_version"),
        "legal_completion_days": legal.get("completion_days") if legal_current else None,
        "legal_deposit_pct": legal.get("deposit_pct") if legal_current else None,
        "legal_lease_years": legal.get("lease_years") if legal_current and legal_field_sources.get("lease_years_remaining") == "verified legal document" else None,
        "legal_buyer_fee_detected": legal.get("buyer_fee_detected") if legal_current else None,
        "legal_vat_flag": bool(legal.get("vat_flag")) if legal_current else False,
        "legal_has_addendum": bool(legal.get("has_addendum")) if legal_current else False,
        "legal_risk_flags": (legal.get("risk_flags") or []) if legal_current else [],
        "legal_warnings": legal.get("warnings") or [],
        "legal_error": legal.get("error"),
        "legal_extracted_fields": legal_fields_current if isinstance(legal_fields_current, dict) else {},
        "legal_contacts": (legal.get("contacts") or []) if legal_current else [],
        "legal_evidence": (legal.get("evidence") or []) if legal_current else [],
        "legal_pack_completeness_pct": int(legal.get("pack_completeness_pct") or 0) if legal_current else 0,
        "legal_missing_components": (legal.get("missing_components") or []) if legal_current else [],
        "legal_available_components": (legal.get("available_components") or []) if legal_current else [],
        "legal_pack_changed": bool(legal.get("pack_changed")) if legal else False,
        "legal_pack_change": legal.get("pack_change") or {},
        "legal_revalidation_report": legal.get("revalidation_report") or {},
    })
    # Parsed legal evidence outranks listing inference. A stated lease term is
    # definitive evidence that the interest being sold is leasehold.
    if row.get("legal_lease_years") is not None:
        row["tenure"] = "Leasehold"
        row["effective_lease_years"] = row.get("legal_lease_years")
    company = company_map.get(row["id"], {})
    legal_identity_ok = bool((row.get("legal_extracted_fields") or {}).get("company_identity_verified")) and str(row.get("legal_status") or "").lower() == "verified"
    if not legal_identity_ok:
        company = {}
    row.update({
        "company_intelligence_status": company.get("status"),
        "company_number_verified": company.get("company_number"),
        "company_name_verified": company.get("company_name"),
        "company_status": company.get("company_status"),
        "company_registered_office": company.get("registered_office"),
        "corporate_pressure_score": float(company.get("corporate_pressure_score") or 0),
        "corporate_pressure_label": company.get("corporate_pressure_label"),
        "company_intelligence": company,
    })
    uw = underwrite_property(
        row,
        row,
        assumptions=underwriting_map.get(row["id"], {}),
        defaults=underwriting_defaults,
        strategy="auto",
    )
    row.update(uw)
    row["browse_score"] = browse_rank(row)
    row["shortlisted"] = row["id"] in shortlist_ids


def toggle_shortlist(row):
    enabled = row["id"] not in db.shortlist_ids()
    db.set_shortlisted(row["id"], enabled)
    sync_cloud("shortlist")
    st.rerun()


def render_badges(row):
    tags = []
    if row.get("status"):
        cls = "badge-hot" if is_unsold(row) or row.get("status") == "Relisted" else ""
        tags.append(f'<span class="badge {cls}">{row.get("status")}</span>')
    if (row.get("failure_count") or 0) > 0:
        tags.append(f'<span class="badge badge-hot">Failed {int(row.get("failure_count") or 0)}x</span>')
    if (row.get("price_reduction_pct") or 0) > 0:
        tags.append(f'<span class="badge badge-good">Guide down {float(row.get("price_reduction_pct")):.1f}%</span>')
    if float(row.get("corporate_pressure_score") or 0) >= 7:
        tags.append(f'<span class="badge badge-risk">Corporate pressure {float(row.get("corporate_pressure_score")):.1f}/10</span>')
    if (row.get("features") or {}).get("vacant"):
        tags.append('<span class="badge">Vacant</span>')
    if row.get("listed_building_signal") or row.get("planning_listed_flag"):
        tags.append('<span class="badge badge-risk">Listed / heritage</span>')
    if row.get("short_lease_signal"):
        yrs = row.get("effective_lease_years") or row.get("listing_lease_years") or row.get("legal_lease_years")
        label = f"Short lease ~{float(yrs):.0f}y" if yrs else "Short lease"
        tags.append(f'<span class="badge badge-risk">{label}</span>')
    if row.get("max_bid_provisional"):
        tags.append('<span class="badge badge-risk">Max buy provisional</span>')
    if legal_state(row) != "VERIFIED":
        label = "Legal unverified" if legal_state(row) in {"CANDIDATES ONLY", "UNVERIFIED", "VERIFIED NO TEXT"} else "Legal not reviewed"
        tags.append(f'<span class="badge badge-risk">{label}</span>')
    st.markdown("".join(tags), unsafe_allow_html=True)



def score_label(score):
    score = float(score or 0)
    if score >= 8.0:
        return "Priority"
    if score >= 6.5:
        return "Worth a look"
    if score >= 5.0:
        return "Review"
    return "Early stage"


def top_deal_reason(row):
    if row.get("status") == "Available post-auction":
        return "Post-auction availability may create a stronger negotiation window."
    if (row.get("price_reduction_pct") or 0) >= 10:
        return f"Guide has reduced by {float(row.get('price_reduction_pct')):.1f}%."
    if (row.get("failure_count") or 0) > 0:
        return f"{int(row.get('failure_count') or 0)} failed auction attempt(s) recorded."
    if row.get("comparable_guide_discount_pct") is not None and float(row.get("comparable_guide_discount_pct") or 0) >= 15:
        return f"Guide is {float(row.get('comparable_guide_discount_pct')):.1f}% below the current comparable midpoint."
    reasons = (row.get("motivation_reasons") or []) + (row.get("reasons") or [])
    if reasons:
        return str(reasons[0]).lstrip("+-0123456789: ")[:150]
    return "Open the deal room to complete valuation and due diligence."

def render_property_card(row):
    with st.container(border=True):
        img_col, main_col, score_col = st.columns([1.15, 3.8, 0.95], vertical_alignment="top")
        with img_col:
            if row.get("image_url"):
                st.image(row["image_url"], use_container_width=True)
            else:
                st.markdown('<div class="soft-panel" style="height:150px;display:flex;align-items:center;justify-content:center;color:#667085;text-align:center;">Image pending<br>next refresh</div>', unsafe_allow_html=True)
        with main_col:
            st.markdown(f'<div class="card-sub">{row.get("source") or "Auction"} &nbsp;·&nbsp; Lot {row.get("lot_number") or "-"} &nbsp;·&nbsp; {row.get("property_type") or "Property"}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="property-title">{clean_address(row)}</div>', unsafe_allow_html=True)
            render_badges(row)
            if is_commercial(row):
                a, b, c, d = st.columns(4)
                a.metric("Guide", guide_display(row))
                b.metric("GIA", f"{int(row.get('size_sqft')):,} sq ft" if row.get("size_sqft") else "-")
                c.metric("Guide / sq ft", money(row.get("price_per_sqft"), 0) if row.get("price_per_sqft") else "-")
                d.metric("Max buy", money(row.get("max_bid")))
            else:
                a, b, c, d = st.columns(4)
                a.metric("Guide", guide_display(row))
                b.metric("Desktop value", money(row.get("market_value") or row.get("comparable_valuation_mid")))
                c.metric("Max buy", money(row.get("max_bid")))
                d.metric("Est. profit", money(row.get("profit")))
            meta1, meta2, meta3 = st.columns(3)
            meta1.caption(f"Seller motivation {row.get('motivation_score', 0):.1f}/10")
            meta2.caption(f"Evidence confidence {int(row.get('comparable_confidence') or 0)}% comps")
            if row.get("motorway_distance_miles") is not None:
                meta3.caption(f"Access {row.get('motorway_distance_miles'):.1f} mi to {row.get('nearest_junction') or row.get('nearest_motorway') or 'junction'}")
            else:
                meta3.caption("Access distance pending")
            st.markdown(f'<div class="card-reason"><strong>Why it ranks:</strong> {top_deal_reason(row)}</div>', unsafe_allow_html=True)
        with score_col:
            st.markdown(
                f'<div class="deal-score-label">Deal potential</div><div class="deal-score">{row.get("browse_score", 0):.1f}</div>'
                f'<div class="deal-score-label">out of 10</div><div class="score-caption">{score_label(row.get("browse_score"))}</div>',
                unsafe_allow_html=True,
            )
            st.write("")
            if st.button("Open deal room", key=f"view_{row['id']}", type="primary", use_container_width=True):
                st.session_state["selected_deal_id"] = row["id"]
                st.rerun()
            star = "Remove" if row.get("shortlisted") else "Shortlist"
            if st.button(star, key=f"short_{row['id']}", use_container_width=True):
                toggle_shortlist(row)


def underwriting_form(chosen):
    saved = db.underwriting_for(chosen["id"])
    strategy = "commercial" if is_commercial(chosen) else "residential"
    st.caption("Save property-specific assumptions. Manual evidence overrides automated comparable estimates.")
    with st.form(f"uw_{chosen['id']}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            purchase_price = st.number_input("Working purchase price", min_value=0.0, value=float(saved.get("purchase_price") or chosen.get("opening_offer") or chosen.get("guide_price") or 0), step=1000.0)
            refurb_cost = st.number_input("Refurbishment / works", min_value=0.0, value=float(saved.get("refurb_cost") or 0), step=1000.0)
            contingency_pct = st.number_input("Works contingency %", min_value=0.0, value=float(saved.get("contingency_pct") if saved.get("contingency_pct") is not None else 10.0), step=1.0)
        with c2:
            if strategy == "residential":
                gdv = st.number_input("GDV / resale value", min_value=0.0, value=float(saved.get("gdv") or 0), step=5000.0, help="Leave 0 to use eligible automated residential comps.")
                market_psf = 0.0
                manual_market_value = 0.0
                erv_annual = 0.0
                exit_yield_pct = 0.0
                target_profit_margin_pct = st.number_input("Target profit margin % of GDV", min_value=0.0, max_value=80.0, value=float(saved.get("target_profit_margin_pct") if saved.get("target_profit_margin_pct") is not None else underwriting_defaults.target_residential_profit_margin_pct), step=1.0)
                target_equity_margin_pct = 20.0
            else:
                gdv = 0.0
                market_psf = st.number_input("Market GBP / sq ft", min_value=0.0, value=float(saved.get("market_psf") or 0), step=5.0)
                manual_market_value = st.number_input("Manual market value", min_value=0.0, value=float(saved.get("manual_market_value") or 0), step=5000.0)
                erv_annual = st.number_input("ERV annual", min_value=0.0, value=float(saved.get("erv_annual") or 0), step=1000.0)
                exit_yield_pct = st.number_input("Exit yield %", min_value=0.0, value=float(saved.get("exit_yield_pct") or 0), step=0.25)
                target_equity_margin_pct = st.number_input("Target equity uplift %", min_value=0.0, max_value=80.0, value=float(saved.get("target_equity_margin_pct") if saved.get("target_equity_margin_pct") is not None else underwriting_defaults.target_commercial_equity_margin_pct), step=1.0)
                target_profit_margin_pct = 20.0
        with c3:
            detected_pct = chosen.get("detected_buyer_premium_pct")
            detected_min = chosen.get("detected_buyer_premium_minimum")
            detected_search = chosen.get("detected_search_fee")
            detected_fixed = chosen.get("detected_auction_admin_fee_fixed")
            auction_admin_default = detected_fixed if detected_fixed is not None else (0.0 if detected_pct is not None else underwriting_defaults.auction_admin_fee)
            auction_admin_fee = st.number_input("Auction/admin fixed fee", min_value=0.0, value=float(saved.get("auction_admin_fee") if saved.get("auction_admin_fee") is not None else auction_admin_default), step=100.0)
            buyer_premium_pct = st.number_input("Buyer/admin fee %", min_value=0.0, value=float(saved.get("buyer_premium_pct") if saved.get("buyer_premium_pct") is not None else (detected_pct or 0.0)), step=0.25)
            buyer_premium_minimum = st.number_input("Minimum buyer/admin fee", min_value=0.0, value=float(saved.get("buyer_premium_minimum") if saved.get("buyer_premium_minimum") is not None else (detected_min or 0.0)), step=100.0)
            search_fee = st.number_input("Search fee", min_value=0.0, value=float(saved.get("search_fee") if saved.get("search_fee") is not None else (detected_search or 0.0)), step=50.0)
        c4, c5, c6 = st.columns(3)
        with c4:
            legal_cost = st.number_input("Legal allowance", min_value=0.0, value=float(saved.get("legal_cost") if saved.get("legal_cost") is not None else underwriting_defaults.legal_cost), step=250.0)
            survey_cost = st.number_input("Survey / DD allowance", min_value=0.0, value=float(saved.get("survey_cost") if saved.get("survey_cost") is not None else underwriting_defaults.survey_cost), step=250.0)
        with c5:
            finance_mode = st.selectbox("Funding", ["Cash", "Bridge / debt"], index=1 if str(saved.get("finance_mode") or "Cash").lower() != "cash" else 0)
            ltv_pct = st.number_input("LTV %", min_value=0.0, max_value=100.0, value=float(saved.get("ltv_pct") if saved.get("ltv_pct") is not None else underwriting_defaults.ltv_pct), step=5.0)
            annual_interest_pct = st.number_input("Annual interest %", min_value=0.0, value=float(saved.get("annual_interest_pct") if saved.get("annual_interest_pct") is not None else underwriting_defaults.annual_interest_pct), step=0.5)
        with c6:
            term_months = st.number_input("Hold / finance months", min_value=1, value=int(saved.get("term_months") or underwriting_defaults.term_months), step=1)
            holding_cost_monthly = st.number_input("Holding / rates / utilities per month", min_value=0.0, value=float(saved.get("holding_cost_monthly") or 0), step=100.0)
            use_auto = st.checkbox("Use automatic commercial comparable value", value=bool(saved.get("use_auto_comps")), disabled=strategy != "commercial")
        notes = st.text_area("Deal notes / evidence", value=str(saved.get("underwriting_notes") or ""), placeholder="Agent feedback, works quote, ERV evidence, local comparable, title point...")
        save = st.form_submit_button("Save and recalculate", type="primary", use_container_width=True)
        if save:
            db.save_underwriting(chosen["id"], {
                "strategy": strategy,
                "purchase_price": purchase_price or None,
                "gdv": gdv or None,
                "market_psf": market_psf or None,
                "manual_market_value": manual_market_value or None,
                "erv_annual": erv_annual or None,
                "exit_yield_pct": exit_yield_pct or None,
                "refurb_cost": refurb_cost or 0,
                "capex_cost": 0,
                "contingency_pct": contingency_pct,
                "auction_admin_fee": auction_admin_fee,
                "buyer_premium_pct": buyer_premium_pct,
                "buyer_premium_minimum": buyer_premium_minimum,
                "search_fee": search_fee,
                "legal_cost": legal_cost,
                "survey_cost": survey_cost,
                "finance_mode": finance_mode,
                "ltv_pct": ltv_pct,
                "annual_interest_pct": annual_interest_pct,
                "term_months": term_months,
                "holding_cost_monthly": holding_cost_monthly,
                "target_profit_margin_pct": target_profit_margin_pct,
                "target_equity_margin_pct": target_equity_margin_pct,
                "residential_sdlt_mode": "Additional dwelling",
                "underwriting_notes": notes,
                "use_auto_comps": 1 if use_auto else 0,
            })
            sync_cloud("underwriting", quiet=False)
            st.rerun()


def render_deal_room(chosen):
    if st.button("← Back to deal feed"):
        st.session_state.pop("selected_deal_id", None)
        st.rerun()

    # Assemble evidence-led intelligence for this property only when its Deal Room is opened.
    hist = db.history_for(chosen["id"])
    planning_items = db.planning_items_for(chosen["id"])
    raw_legal_summary = db.legal_summary_for(chosen["id"])
    legal_summary = raw_legal_summary
    if raw_legal_summary and str(raw_legal_summary.get("evidence_policy_version") or "") != EVIDENCE_POLICY_VERSION:
        # Pre-firewall extractions are deliberately quarantined. They can remain in
        # storage for audit/history but cannot drive the live deal decision or seller story.
        legal_summary = dict(raw_legal_summary)
        legal_summary.update({
            "status": "candidates-only" if raw_legal_summary.get("document_count") else "not-found",
            "risk_score": 0, "verified_document_count": 0, "parsed_document_count": 0,
            "pack_completeness_pct": 0, "extracted_fields": {}, "contacts": [], "evidence": [],
            "risk_flags": [],
        })
        legal_summary["warnings"] = list(dict.fromkeys((raw_legal_summary.get("warnings") or []) + [
            "Saved legal extraction predates the v1.10.3 Evidence Revalidation & Purge policy and is quarantined until the legal pack is refreshed."
        ]))
    company_summary = db.company_intelligence_for(chosen["id"])
    chosen["legal_extracted_fields"] = legal_summary.get("extracted_fields") or {}
    legal_identity_verified = bool(chosen["legal_extracted_fields"].get("company_identity_verified")) and str(legal_summary.get("status") or "").lower() == "verified"
    # Quarantine any company lookup created from pre-firewall/generic website text.
    # It remains in storage for audit, but cannot influence the seller story until a
    # verified legal document establishes the seller/company identity.
    effective_company_summary = company_summary if legal_identity_verified else {}
    chosen["legal_contacts"] = legal_summary.get("contacts") or []
    chosen["legal_evidence"] = legal_summary.get("evidence") or []
    chosen["legal_pack_completeness_pct"] = int(legal_summary.get("pack_completeness_pct") or 0)
    chosen["legal_missing_components"] = legal_summary.get("missing_components") or []
    chosen["legal_available_components"] = legal_summary.get("available_components") or []
    story = build_vendor_story(chosen, hist, chosen, legal_summary, planning_items, effective_company_summary)
    readiness = deal_readiness(chosen)
    actions = next_actions(chosen, story)
    profile = story.get("seller_profile") or {}

    left, right = st.columns([1.35, 2.65], vertical_alignment="top")
    with left:
        if chosen.get("image_url"):
            st.image(chosen["image_url"], use_container_width=True)
        else:
            st.markdown('<div class="soft-panel" style="height:280px;display:flex;align-items:center;justify-content:center;color:#667085;">Property image pending refresh</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="eyebrow">Deal room</div>', unsafe_allow_html=True)
        st.caption(f"{chosen.get('source')} · Lot {chosen.get('lot_number') or '-'} · {chosen.get('property_type')} · {chosen.get('status')}")
        st.header(clean_address(chosen))
        render_badges(chosen)
        a, b, c, d = st.columns(4)
        a.metric("Deal potential", f"{chosen.get('browse_score', 0):.1f}/10")
        b.metric("Vendor motivation", f"{chosen.get('motivation_score', 0):.1f}/10")
        c.metric("Buyer leverage", f"{story.get('buyer_leverage_score', 0):.1f}/10")
        d.metric("Deal readiness", f"{readiness.get('readiness_pct', 0)}%")
        e, f, g, h = st.columns(4)
        e.metric("Guide", guide_display(chosen))
        f.metric("Opening offer", money(chosen.get("opening_offer")))
        g.metric("Max buy", money(chosen.get("max_bid")), delta="PROVISIONAL" if chosen.get("max_bid_provisional") else None)
        h.metric("Seller-story confidence", f"{story.get('story_confidence', 0)}%", delta=story.get("story_confidence_label"))
        next_action_text = actions[0].get("action") if actions else (chosen.get("recommended_action") or "Continue due diligence")
        st.markdown(
            f'<div class="decision-banner"><span class="eyebrow">Current decision</span><br><strong>{readiness.get("readiness_status")}</strong> · {readiness.get("readiness_pct", 0)}% ready &nbsp;—&nbsp; Next: {next_action_text}</div>',
            unsafe_allow_html=True,
        )
        if chosen.get("recommended_action"):
            if chosen.get("recommendation") == "PURSUE":
                st.success(f"PURSUE - {chosen.get('recommended_action')}")
            elif chosen.get("recommendation") == "PASS":
                st.error(f"PASS - {chosen.get('recommended_action')}")
            else:
                st.warning(f"WATCH - {chosen.get('recommended_action')}")
        act1, act2, act3 = st.columns(3)
        with act1:
            if st.button("Remove from shortlist" if chosen.get("shortlisted") else "Add to shortlist", key=f"deal_short_{chosen['id']}", use_container_width=True):
                toggle_shortlist(chosen)
        with act2:
            if chosen.get("url"):
                st.link_button("Open auctioneer listing", chosen["url"], use_container_width=True)
        with act3:
            if profile.get("company_number"):
                st.link_button("Companies House", f"https://find-and-update.company-information.service.gov.uk/company/{profile['company_number']}", use_container_width=True)

    tabs = st.tabs(["Summary", "Seller", "Numbers", "Comps", "History", "Legal & planning", "Location", "Workspace"])

    with tabs[0]:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Opening offer", money(chosen.get("opening_offer")))
        m2.metric("Market value / GDV", money(chosen.get("market_value") or chosen.get("comparable_valuation_mid")))
        m3.metric("Profit / equity", money(chosen.get("profit")))
        m4.metric("ROI", pct(chosen.get("roi_pct")))
        m5.metric("UW confidence", f"{int(chosen.get('underwriting_confidence') or 0)}%")

        st.markdown("### Acquisition readiness")
        st.progress(readiness.get("readiness_pct", 0) / 100.0, text=f"{readiness.get('readiness_status')} - {readiness.get('readiness_pct')}% complete")
        if readiness.get("readiness_blockers"):
            st.error("Bid blockers: " + " | ".join(readiness.get("readiness_blockers")[:5]))
        with st.expander("Readiness checklist"):
            readiness_frame = pd.DataFrame([{
                "Check": x.get("name"), "Status": x.get("state").title(), "Detail": x.get("detail"), "Bid blocker": bool(x.get("blocker"))
            } for x in readiness.get("readiness_checks") or []])
            st.dataframe(readiness_frame, hide_index=True, use_container_width=True)

        good, concern = st.columns(2)
        with good:
            st.markdown("### Why this may be a deal")
            positives = []
            positives.extend(chosen.get("reasons") or [])
            positives.extend(chosen.get("motivation_reasons") or [])
            if chosen.get("comparable_guide_discount_pct") is not None:
                positives.append(f"Guide is {chosen.get('comparable_guide_discount_pct'):.1f}% below the comparable midpoint")
            if not positives:
                positives = ["Insufficient positive evidence has been captured yet."]
            for item in positives[:10]:
                st.write(f"- {item}")
        with concern:
            st.markdown("### What needs checking")
            concerns = []
            concerns.extend(chosen.get("underwriting_warnings") or [])
            concerns.extend(chosen.get("warnings") or [])
            if legal_state(chosen) != "VERIFIED":
                concerns.insert(0, "Authoritative lot-bound legal documents have not been verified: legal risk remains UNKNOWN.")
            elif int(chosen.get("legal_pack_completeness_pct") or 0) < 100:
                concerns.insert(0, "Verified legal evidence is only partial: the core legal pack is incomplete and bid approval remains blocked.")
            if planning_state(chosen) != "SCREENED":
                concerns.insert(0, "Planning screen is incomplete: planning risk remains UNKNOWN.")
            if not concerns:
                concerns = ["No major automated warning is currently recorded; normal auction due diligence still applies."]
            for item in concerns[:10]:
                st.write(f"- {item}")

        st.markdown("### Recommended next actions")
        if actions:
            for n, action in enumerate(actions, start=1):
                st.markdown(f"**{n}. {action['action']}**  ")
                st.caption(action["reason"])
        else:
            st.caption("No automated action queue has been generated yet.")

        st.markdown("### Key property facts")
        extracted = chosen.get("legal_extracted_fields") or {}
        facts = pd.DataFrame([
            ["Auction house", chosen.get("source")],
            ["Status", chosen.get("status")],
            ["Auction date", chosen.get("auction_date")],
            ["Property type", chosen.get("property_type")],
            ["Tenure", chosen.get("tenure")],
            ["Lease remaining", f"{float(chosen.get('legal_lease_years') or chosen.get('listing_lease_years')):.1f} years" if (chosen.get("legal_lease_years") or chosen.get("listing_lease_years")) else "Unknown"],
            ["Lease start", chosen.get("listing_lease_start_date") or "Unknown"],
            ["Guide range", guide_display(chosen)],
            ["EPC", chosen.get("listing_epc_rating") or "Unknown"],
            ["Allocated parking", "Yes" if (chosen.get("features") or {}).get("parking") else "Not confirmed"],
            ["Balcony", "Yes" if (chosen.get("features") or {}).get("balcony") else "Not confirmed"],
            ["Auctioneer phone", chosen.get("listing_auctioneer_phone") or "Unknown"],
            ["Auctioneer email", chosen.get("listing_auctioneer_email") or "Unknown"],
            ["Published admin fee", money(chosen.get("detected_auction_admin_fee_fixed")) if chosen.get("detected_auction_admin_fee_fixed") is not None else "Not detected"],
            ["Registered proprietor / seller", extracted.get("seller_name") or extracted.get("proprietor_name") or "Unknown"],
            ["Title number", extracted.get("title_number") or "Unknown"],
            ["Floor area", f"{int(chosen.get('size_sqft')):,} sq ft" if chosen.get("size_sqft") else "Unknown"],
            ["Guide / sq ft", money(chosen.get("price_per_sqft"), 2) if chosen.get("price_per_sqft") else "Unknown"],
            ["Failed auction attempts", int(chosen.get("failure_count") or 0)],
            ["Observed guide reduction", pct(chosen.get("price_reduction_pct"))],
            ["Legal status", legal_state(chosen)],
            ["Planning status", planning_state(chosen)],
        ], columns=["Item", "Value"])
        st.dataframe(facts, hide_index=True, use_container_width=True)

    with tabs[1]:
        s1, s2, s3 = st.columns(3)
        s1.metric("Vendor motivation", f"{chosen.get('motivation_score', 0):.1f}/10", delta=chosen.get("motivation_label"))
        s2.metric("Buyer leverage", f"{story.get('buyer_leverage_score', 0):.1f}/10", delta=story.get("buyer_leverage_label"))
        s3.metric("Story confidence", f"{story.get('story_confidence', 0)}%", delta=story.get("story_confidence_label"))

        st.markdown("### Seller profile")
        seller_rows = [
            ["Registered proprietor / seller", profile.get("seller_name") or "Not extracted yet"],
            ["Seller / disposal type", profile.get("seller_type") or "Not identified"],
            ["Disposal evidence", profile.get("seller_type_evidence") or "Not established"],
            ["Title number", profile.get("title_number") or "Not extracted"],
            ["Company number", profile.get("company_number") or "Not extracted"],
            ["Registered office", profile.get("registered_office") or "Not extracted"],
            ["Title price paid", money(profile.get("title_price_paid")) if profile.get("title_price_paid") is not None else "Not extracted"],
            ["Title price date", profile.get("title_price_paid_date") or "Not extracted"],
        ]
        st.dataframe(pd.DataFrame(seller_rows, columns=["Item", "Evidence"]), hide_index=True, use_container_width=True)

        st.markdown("### Ownership / company intelligence")
        company_number = profile.get("company_number") or effective_company_summary.get("company_number")
        seller_name = profile.get("seller_name") or effective_company_summary.get("company_name")
        if company_summary and not legal_identity_verified:
            st.warning("Stored Companies House intelligence is quarantined because the seller/company identity was not established by verified lot-bound legal evidence. Refresh the legal pack after the evidence-firewall upgrade.")
        if companies_house_api_key and legal_identity_verified and (company_number or seller_name):
            if st.button("Refresh official Companies House intelligence", key=f"ch_refresh_{chosen['id']}", use_container_width=True):
                try:
                    with st.spinner("Checking Companies House profile, charges, insolvency, officers and filings..."):
                        refresh_property_company(db, chosen, companies_house_api_key)
                        sync_cloud("Companies House refresh", quiet=False)
                    st.success("Companies House intelligence refreshed.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Companies House refresh failed: {exc}")
        elif legal_identity_verified and (company_number or (seller_name and re.search(r"\b(?:LTD|LIMITED|PLC|LLP)\b", seller_name, re.I))):
            st.info("Corporate seller identified. Add a free Companies House API key in Streamlit Secrets to enrich company status, charges, insolvency, directors, PSCs and filings automatically.")

        if effective_company_summary.get("status") == "ok":
            ci1, ci2, ci3, ci4 = st.columns(4)
            ci1.metric("Company status", effective_company_summary.get("company_status") or "Unknown")
            ci2.metric("Corporate pressure", f"{float(effective_company_summary.get('corporate_pressure_score') or 0):.1f}/10", delta=effective_company_summary.get("corporate_pressure_label"))
            ci3.metric("Outstanding charges", int(effective_company_summary.get("outstanding_charge_count") or 0))
            ci4.metric("Insolvency cases", int(effective_company_summary.get("insolvency_case_count") or 0))
            company_rows = [
                ["Verified company", effective_company_summary.get("company_name") or "-"],
                ["Company number", effective_company_summary.get("company_number") or "-"],
                ["Registered office", effective_company_summary.get("registered_office") or "-"],
                ["Incorporated", effective_company_summary.get("incorporation_date") or "-"],
                ["Accounts overdue", "Yes" if effective_company_summary.get("accounts_overdue") else "No"],
                ["Confirmation statement overdue", "Yes" if effective_company_summary.get("confirmation_overdue") else "No"],
                ["SIC codes", ", ".join(effective_company_summary.get("sic_codes") or []) or "-"],
            ]
            st.dataframe(pd.DataFrame(company_rows, columns=["Corporate fact", "Official record"]), hide_index=True, use_container_width=True)
            reasons = effective_company_summary.get("corporate_pressure_reasons") or []
            if reasons:
                with st.expander("Corporate pressure evidence"):
                    for reason in reasons:
                        st.write(f"- {reason}")
                    st.caption("Outstanding charges show secured financing but are not treated as proof of distress on their own.")
            directors = effective_company_summary.get("active_directors") or []
            pscs = effective_company_summary.get("persons_with_significant_control") or []
            charges = effective_company_summary.get("charges") or []
            filings = effective_company_summary.get("recent_filings") or []
            if directors:
                with st.expander("Active directors"):
                    st.dataframe(pd.DataFrame(directors), hide_index=True, use_container_width=True)
            if pscs:
                with st.expander("Persons with significant control"):
                    psc_frame = pd.DataFrame([{
                        "Name": x.get("name"), "Kind": x.get("kind"),
                        "Control": ", ".join(x.get("natures_of_control") or []),
                    } for x in pscs if not x.get("ceased_on")])
                    if not psc_frame.empty:
                        st.dataframe(psc_frame, hide_index=True, use_container_width=True)
            if charges:
                with st.expander("Company charges"):
                    st.dataframe(pd.DataFrame([{
                        "Status": x.get("status"), "Created": x.get("created_on"),
                        "Holder": ", ".join(x.get("persons_entitled") or []),
                        "Type": x.get("classification"),
                    } for x in charges]), hide_index=True, use_container_width=True)
            if filings:
                with st.expander("Recent Companies House filings"):
                    st.dataframe(pd.DataFrame(filings[:15]), hide_index=True, use_container_width=True)
        elif effective_company_summary.get("status") == "unresolved":
            st.warning("A corporate seller name was found but the Companies House match was not definitive, so the app has not guessed the company identity.")
            candidates = (effective_company_summary.get("resolution") or {}).get("candidates") or []
            if candidates:
                st.dataframe(pd.DataFrame(candidates), hide_index=True, use_container_width=True)
        elif effective_company_summary.get("status") == "error":
            st.warning(f"Companies House intelligence needs refreshing: {effective_company_summary.get('error') or 'last lookup failed'}")

        fact_col, inference_col = st.columns(2)
        with fact_col:
            st.markdown("### Confirmed evidence")
            facts = story.get("confirmed_facts") or ["No material seller-motivation facts beyond the auction listing have been confirmed yet."]
            for fact in facts:
                st.write(f"- {fact}")
        with inference_col:
            st.markdown("### What the evidence may indicate")
            inferences = story.get("inferences") or ["There is not enough evidence to form a useful seller-pressure interpretation yet."]
            for item in inferences:
                st.write(f"- {item}")
            st.caption("Interpretations are hypotheses for negotiation planning, not statements of fact about the seller.")

        st.markdown("### Vendor story timeline")
        timeline = story.get("timeline") or []
        if timeline:
            for event in timeline:
                source = f" [source]({event.get('source_url')})" if event.get("source_url") else ""
                st.markdown(f"**{event.get('display_date')} - {event.get('label')}**{source}")
                if event.get("detail"):
                    st.caption(event.get("detail"))
        else:
            st.info("No dated auction/planning story has been assembled yet. Historical backfill and planning/legal refreshes will strengthen this section.")

        contacts = story.get("seller_profile", {}).get("contacts") or []
        if contacts:
            st.markdown("### Professional contacts found in legal evidence")
            st.dataframe(pd.DataFrame(contacts), hide_index=True, use_container_width=True)
            st.caption("Only professional/business contact details found in the supplied/public legal evidence are surfaced here; the app does not hunt for private personal contact details.")

    with tabs[2]:
        f1, f2, f3, f4, f5 = st.columns(5)
        f1.metric("Working purchase", money(chosen.get("working_purchase_price")))
        f2.metric("All-in cost", money(chosen.get("all_in_cost")))
        f3.metric("Max bid", money(chosen.get("max_bid")))
        f4.metric("Profit / equity", money(chosen.get("profit")))
        f5.metric("Financial score", f"{chosen.get('financial_score', 0):.1f}/10")
        if chosen.get("works_missing"):
            st.error("Works/refurbishment is indicated in the listing but the works budget is GBP 0. The return score is capped and the maximum bid is provisional until a works estimate is entered.")
        if chosen.get("detected_fee_evidence"):
            st.info("Auction fee evidence detected: " + " | ".join(chosen.get("detected_fee_evidence") or []))

        st.markdown("### Purchase-price scenario compare")
        guide = float(chosen.get("guide_price") or 0)
        candidates = [chosen.get("opening_offer"), guide * 0.90 if guide else None, guide or None, chosen.get("max_bid")]
        labels = ["Opening offer", "90% of guide", "Guide", "Maximum bid"]
        saved = db.underwriting_for(chosen["id"])
        scenario_data = []
        seen_prices = set()
        for label, price in zip(labels, candidates):
            if not price:
                continue
            price = int(round(float(price) / 1000) * 1000)
            if price in seen_prices:
                continue
            seen_prices.add(price)
            assumptions = dict(saved)
            assumptions["purchase_price"] = price
            result = underwrite_property(chosen, chosen, assumptions=assumptions, defaults=underwriting_defaults, strategy="auto")
            scenario_data.append({
                "Scenario": label, "Purchase": price, "All-in": result.get("all_in_cost"),
                "Profit/equity": result.get("profit"), "ROI %": result.get("roi_pct"),
                "Financial score": result.get("financial_score"), "Decision": result.get("recommendation"),
            })
        if scenario_data:
            st.dataframe(pd.DataFrame(scenario_data), hide_index=True, use_container_width=True, column_config={
                "Purchase": st.column_config.NumberColumn(format="GBP %d"),
                "All-in": st.column_config.NumberColumn(format="GBP %d"),
                "Profit/equity": st.column_config.NumberColumn(format="GBP %d"),
                "ROI %": st.column_config.NumberColumn(format="%.1f%%"),
                "Financial score": st.column_config.NumberColumn(format="%.1f"),
            })

        underwriting_form(chosen)
        st.markdown("### Cost stack at working purchase price")
        costs = pd.DataFrame([
            ["Purchase", chosen.get("working_purchase_price")],
            ["SDLT", chosen.get("sdlt")],
            ["Auction/admin fixed", chosen.get("auction_admin_fee")],
            ["Buyer/admin premium", chosen.get("buyer_premium")],
            ["Search fee", chosen.get("search_fee")],
            ["Legal", chosen.get("legal_cost")],
            ["Survey/DD", chosen.get("survey_cost")],
            ["Finance", chosen.get("finance_cost")],
            ["Works", chosen.get("works_cost")],
            ["Contingency", chosen.get("works_contingency")],
            ["Holding", chosen.get("holding_cost")],
            ["Exit/sale", chosen.get("sale_cost")],
            ["Total all-in", chosen.get("all_in_cost")],
        ], columns=["Cost", "GBP"])
        st.dataframe(costs, hide_index=True, use_container_width=True, column_config={"GBP": st.column_config.NumberColumn(format="GBP %d")})

    with tabs[3]:
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Refresh this property's comparables", key=f"comp_{chosen['id']}", use_container_width=True):
                with st.spinner("Refreshing comparable evidence..."):
                    refresh_property_comparables(db, chosen)
                    sync_cloud("property comparable refresh")
                st.rerun()
        with c2:
            st.caption(f"Provider: {chosen.get('comparable_provider') or 'Not run'} | Confidence: {int(chosen.get('comparable_confidence') or 0)}% | Usable comps: {int(chosen.get('comparable_count') or 0)}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Low", money(chosen.get("comparable_valuation_low")))
        c2.metric("Midpoint", money(chosen.get("comparable_valuation_mid")))
        c3.metric("High", money(chosen.get("comparable_valuation_high")))
        c4.metric("Guide discount", pct(chosen.get("comparable_guide_discount_pct")))
        comps = db.comparables_for(chosen["id"])
        if comps:
            frame = pd.DataFrame([{k: r.get(k) for k in ["address", "postcode", "sale_price", "sale_date", "property_type", "tenure", "distance_miles", "price_per_sqft", "match_score"]} for r in comps])
            st.dataframe(frame, hide_index=True, use_container_width=True, column_config={"sale_price": st.column_config.NumberColumn(format="GBP %d"), "price_per_sqft": st.column_config.NumberColumn(format="GBP %.2f"), "distance_miles": st.column_config.NumberColumn(format="%.2f mi"), "match_score": st.column_config.NumberColumn(format="%.0f")})
        else:
            st.info("No comparable evidence stored yet.")
        for warning in chosen.get("comparable_warnings") or []:
            st.caption(f"Comparable note: {warning}")

    with tabs[4]:
        h1, h2, h3 = st.columns(3)
        h1.metric("Failed auction attempts", int(chosen.get("failure_count") or 0))
        h2.metric("Guide reductions", int(chosen.get("price_reduction_events") or 0))
        h3.metric("Observed guide drop", pct(chosen.get("price_reduction_pct")))
        if hist:
            chronological = list(reversed(hist))
            st.markdown("### Property auction timeline")
            for event in chronological:
                when = event.get("auction_date") or str(event.get("captured_at") or "")[:10]
                line = f"**{when}** - {event.get('status') or 'Observed'}"
                if event.get("guide_text"):
                    line += f" | {event.get('guide_text')}"
                elif event.get("guide_price"):
                    line += f" | Guide {money(event.get('guide_price'))}"
                if event.get("result_price"):
                    line += f" | Result {money(event.get('result_price'))}"
                st.markdown(line)
            with st.expander("Raw history table"):
                st.dataframe(pd.DataFrame(chronological), hide_index=True, use_container_width=True)
        else:
            st.info("No auction-history observations stored yet. Future refreshes and historical backfill will populate this timeline.")

    with tabs[5]:
        pcol, lcol = st.columns(2)
        with pcol:
            st.markdown("### Planning intelligence")
            pstate = planning_state(chosen)
            if pstate == "SCREENED":
                st.success(f"SCREENED | Known planning/designation risk {float(chosen.get('planning_risk_score') or 0):.1f}/10 | Coverage varies by authority")
            elif pstate == "ERROR":
                st.error("Planning screen failed. Risk is UNKNOWN.")
            else:
                st.warning("Planning not screened. Risk is UNKNOWN.")
            if st.button("Refresh planning", key=f"plan_{chosen['id']}", use_container_width=True):
                try:
                    with st.spinner("Checking official planning data..."):
                        refresh_property_planning(db, chosen)
                        sync_cloud("property planning refresh")
                except Exception as exc:
                    st.error(str(exc))
                st.rerun()
            if planning_items:
                frame = pd.DataFrame([{
                    "Type": i.get("kind"), "Dataset": i.get("dataset"), "Reference": i.get("reference"),
                    "Record": i.get("name"), "Severity": i.get("severity"), "Subject": bool(i.get("likely_subject")),
                    "Distance": i.get("distance_miles"), "Source": i.get("source_url"),
                } for i in planning_items])
                st.dataframe(frame, hide_index=True, use_container_width=True, column_config={"Source": st.column_config.LinkColumn("Source"), "Distance": st.column_config.NumberColumn(format="%.2f mi")})
            else:
                st.caption("No planning records are stored for this property. A zero count is not a clean-planning certificate.")

        with lcol:
            st.markdown("### Legal-pack intelligence")
            lstate = legal_state(chosen)
            completeness = int(legal_summary.get("pack_completeness_pct") or chosen.get("legal_pack_completeness_pct") or 0)
            verified_docs_count = int(legal_summary.get("verified_document_count") or chosen.get("legal_verified_document_count") or 0)
            candidate_docs_count = int(legal_summary.get("candidate_document_count") if legal_summary.get("candidate_document_count") is not None else chosen.get("legal_candidate_document_count") or 0)
            rejected_docs_count = int(legal_summary.get("rejected_document_count") or chosen.get("legal_rejected_document_count") or 0)
            if lstate == "VERIFIED" and completeness >= 100:
                st.success(f"CORE LEGAL PACK VERIFIED | Known-document risk {float(chosen.get('legal_risk_score') or 0):.1f}/10")
            elif lstate == "VERIFIED":
                st.warning(f"PARTIAL VERIFIED LEGAL EVIDENCE | Core pack {completeness}% complete | BID BLOCKED until missing core documents are verified")
            elif lstate == "VERIFIED NO TEXT":
                st.warning("LOT-BOUND DOCUMENTS FOUND, TEXT UNREADABLE | Manual review required before bidding.")
            elif lstate == "CANDIDATES ONLY":
                st.warning("LEGAL PACK NOT VERIFIED | Candidate links exist, but no authoritative lot-bound legal document passed the Property Identity Lock. Risk is UNKNOWN.")
            elif lstate == "UNVERIFIED":
                st.warning("LEGAL EVIDENCE NEEDS RE-VERIFYING | Saved extraction predates the v1.10.3 purge policy. Refresh to re-check every stored document and remove stale derived evidence.")
            elif lstate == "ERROR":
                st.error("Legal-pack check failed. Risk is UNKNOWN.")
            else:
                st.warning("LEGAL PACK NOT VERIFIED | Risk is UNKNOWN and bid approval is blocked.")
            if st.button("Fetch / refresh legal pack", key=f"legal_{chosen['id']}", use_container_width=True):
                try:
                    with st.spinner("Checking legal-pack links and permitted/authenticated sources..."):
                        refresh_property_legal(db, chosen, legal_access=legal_access, cloud_store=cloud_store)
                        if companies_house_api_key:
                            try:
                                refresh_property_company(db, chosen, companies_house_api_key)
                            except Exception:
                                pass
                        sync_cloud("property legal/company refresh")
                except Exception as exc:
                    st.error(str(exc))
                st.rerun()

            extracted = chosen.get("legal_extracted_fields") or {}
            legal_evidence = legal_summary.get("evidence") or chosen.get("legal_evidence") or []
            miss = legal_summary.get("missing_components") or chosen.get("legal_missing_components") or []
            lm1, lm2, lm3, lm4, lm5 = st.columns(5)
            lm1.metric("Core pack", f"{completeness}%")
            lm2.metric("Verified docs", verified_docs_count)
            lm3.metric("Candidates", candidate_docs_count)
            lm4.metric("Rejected", rejected_docs_count)
            lm5.metric("Known risk", f"{float(chosen.get('legal_risk_score') or 0):.1f}/10" if verified_docs_count else "Unknown")
            if int(legal_summary.get("pack_index_count") or chosen.get("legal_pack_index_count") or 0):
                st.caption(f"Lot-specific legal-pack index verified: {int(legal_summary.get('pack_index_count') or chosen.get('legal_pack_index_count') or 0)}")
            if miss:
                st.warning("Missing / not yet evidenced: " + ", ".join(miss))
            legal_warnings = legal_summary.get("warnings") or chosen.get("legal_warnings") or []
            for warning in legal_warnings[:4]:
                warning_text = str(warning)
                if any(term in warning_text.lower() for term in ("permission required", "login", "captcha", "manual")):
                    st.info(warning_text)
                else:
                    st.caption(warning_text)

            revalidation = legal_summary.get("revalidation_report") or chosen.get("legal_revalidation_report") or {}
            if revalidation.get("checked"):
                downgraded = int(revalidation.get("downgraded") or 0)
                rejected = int(revalidation.get("rejected") or 0)
                purged = int(revalidation.get("purged_findings") or 0)
                retained = int(revalidation.get("retained_verified") or 0)
                tone = st.warning if (downgraded or rejected or purged) else st.success
                tone(
                    f"Evidence revalidation complete: {int(revalidation.get('checked') or 0)} stored document(s) checked | "
                    f"{retained} retained as verified | {downgraded} downgraded | {rejected} cross-property rejected."
                )
                if purged:
                    st.caption("Stale rent, seller/company, contact and legal-risk findings derived from downgraded documents were purged and recalculated from verified evidence only.")

            pack_change = legal_summary.get("pack_change") or {}
            if legal_summary.get("pack_changed") or pack_change.get("changed"):
                st.error("LEGAL PACK CHANGED since the previous saved snapshot - re-review before bidding.")
                change_bits = []
                if pack_change.get("added"):
                    change_bits.append("Added: " + ", ".join(pack_change.get("added") or []))
                if pack_change.get("modified"):
                    change_bits.append("Modified: " + ", ".join(pack_change.get("modified") or []))
                if pack_change.get("removed"):
                    change_bits.append("Removed: " + ", ".join(pack_change.get("removed") or []))
                if change_bits:
                    st.caption(" | ".join(change_bits))

            field_sources = extracted.get("field_sources") or {}
            legal_facts = []
            def add_legal_fact(label, key, value):
                source = field_sources.get(key)
                if value not in (None, "", False) and source:
                    legal_facts.append([label, value, source])

            add_legal_fact("Registered proprietor / seller", "seller_name" if extracted.get("seller_name") else "proprietor_name", extracted.get("seller_name") or extracted.get("proprietor_name"))
            add_legal_fact("Seller / disposal type", "seller_type", extracted.get("seller_type"))
            add_legal_fact("Title number", "title_number", extracted.get("title_number"))
            add_legal_fact("Company number", "company_number", extracted.get("company_number"))
            add_legal_fact("Registered office", "registered_office", extracted.get("registered_office"))
            add_legal_fact("Title price paid", "title_price_paid", money(extracted.get("title_price_paid")) if extracted.get("title_price_paid") is not None else None)
            add_legal_fact("Title price date", "title_price_paid_date", extracted.get("title_price_paid_date"))
            add_legal_fact("Lease remaining", "lease_years_remaining", f"{float(extracted.get('lease_years_remaining')):.1f} years" if extracted.get("lease_years_remaining") is not None else None)
            add_legal_fact("Lease start", "lease_start_date", extracted.get("lease_start_date"))
            add_legal_fact("Ground rent", "ground_rent_amount", money(extracted.get("ground_rent_amount")) if extracted.get("ground_rent_amount") is not None else None)
            add_legal_fact("Service charge", "service_charge_amount", money(extracted.get("service_charge_amount")) if extracted.get("service_charge_amount") is not None else None)
            add_legal_fact("Seller costs charged to buyer", "seller_costs_amount", money(extracted.get("seller_costs_amount")) if extracted.get("seller_costs_amount") is not None else None)
            add_legal_fact("Tenancy / occupation", "tenancy_type", extracted.get("tenancy_type"))
            add_legal_fact("Passing rent", "tenancy_rent_amount", (money(extracted.get("tenancy_rent_amount")) + (f" per {extracted.get('tenancy_rent_period')}" if extracted.get("tenancy_rent_period") else "")) if extracted.get("tenancy_rent_amount") is not None else None)
            add_legal_fact("Tenancy end / expiry", "tenancy_end_date", extracted.get("tenancy_end_date"))
            positive_flags = [
                ("Reserve / sinking fund wording", "reserve_fund_flag"),
                ("Section 20 / major works wording", "section20_or_major_works_flag"),
                ("Assignment restriction wording", "assignment_restriction_flag"),
                ("Rights / easements wording", "rights_easements_flag"),
                ("Restrictive covenant wording", "restrictive_covenant_flag"),
                ("Overage / clawback wording", "overage_clawback_flag"),
                ("Arrears wording", "arrears_flag"),
                ("EWS1 / cladding wording", "ews1_or_cladding_flag"),
                ("Fire / building-safety wording", "fire_safety_flag"),
            ]
            for label, key in positive_flags:
                if extracted.get(key) and field_sources.get(key):
                    legal_facts.append([label, "Detected - review source evidence", field_sources.get(key)])
            if int(extracted.get("registered_charge_count") or 0) > 0 and field_sources.get("registered_charge_count"):
                legal_facts.append(["Registered charge references", int(extracted.get("registered_charge_count") or 0), field_sources.get("registered_charge_count")])
            if legal_state(chosen) == "VERIFIED":
                if chosen.get("legal_completion_days"):
                    legal_facts.append(["Completion", f"{chosen.get('legal_completion_days')} days", "verified legal document"])
                if chosen.get("legal_deposit_pct") is not None:
                    legal_facts.append(["Deposit", pct(chosen.get("legal_deposit_pct")), "verified legal document"])
                if chosen.get("legal_vat_flag"):
                    legal_facts.append(["VAT / option-to-tax wording", "Detected", "verified legal document"])
                if chosen.get("legal_has_addendum"):
                    legal_facts.append(["Addendum", "Detected - verify latest version", "verified legal document"])

            if legal_facts:
                st.markdown("#### What we can actually evidence")
                st.dataframe(pd.DataFrame(legal_facts, columns=["Legal fact", "Evidence", "Source tier"]), hide_index=True, use_container_width=True)
            else:
                st.caption("No verified legal facts have been extracted yet. Candidate/rejected material is intentionally excluded from the deal decision.")

            if legal_evidence:
                st.markdown("#### Evidence trail")
                evidence_frame = pd.DataFrame([{
                    "Finding": e.get("finding"), "Value": e.get("value"), "Document": e.get("document"),
                    "Page": e.get("page"), "Evidence": e.get("excerpt"),
                } for e in legal_evidence])
                st.dataframe(evidence_frame, hide_index=True, use_container_width=True)
                st.caption("Page references are generated from the uploaded/public PDF text where page boundaries are extractable. Always verify against the original document.")

            contacts = chosen.get("legal_contacts") or []
            if contacts:
                st.markdown("#### Professional contacts in the pack")
                st.dataframe(pd.DataFrame(contacts), hide_index=True, use_container_width=True)
                st.caption("Only professional/business contacts found in the legal evidence are surfaced; the app does not search for private personal contact details.")

            docs = db.legal_documents_for(chosen["id"])
            if docs:
                st.markdown("#### Document identity checks")
                st.caption("Every automatic file is scored against this property's postcode/address/lot identity before it can influence the deal.")
                doc_rows = []
                for d in docs:
                    meta = d.get("metadata") or {}
                    tier = meta.get("evidence_tier") or "legacy/unverified"
                    status = meta.get("identity_status") or ("verified" if meta.get("verified_for_lot") else "unverified")
                    reasons = meta.get("identity_reasons") or []
                    conflicts = meta.get("identity_conflicts") or []
                    rejection = meta.get("rejection_reason") or ""
                    why = rejection or ("; ".join(conflicts[:2]) if conflicts else "; ".join(reasons[:2]))
                    doc_rows.append({
                        "Name": d.get("name"),
                        "Class": meta.get("document_class") or d.get("doc_type") or "Unclassified",
                        "Identity": status.title(),
                        "Match": int(meta.get("identity_score")) if meta.get("identity_score") is not None else None,
                        "Evidence tier": tier,
                        "Why": why,
                        "Cloud": "Stored" if meta.get("cloud_storage_path") else "-",
                        "URL": d.get("url"),
                    })
                frame = pd.DataFrame(doc_rows)
                st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
                    "Match": st.column_config.ProgressColumn("Property match", min_value=0, max_value=100, format="%d%%"),
                    "URL": st.column_config.LinkColumn("Source"),
                })

                rejected_docs = [d for d in docs if (d.get("metadata") or {}).get("evidence_tier") == "rejected-cross-property"]
                if rejected_docs:
                    with st.expander(f"Rejected by Property Identity Lock ({len(rejected_docs)})", expanded=False):
                        for d in rejected_docs:
                            meta = d.get("metadata") or {}
                            st.markdown(f"**{d.get('name') or 'Document'}**")
                            st.caption(meta.get("rejection_reason") or "; ".join(meta.get("identity_conflicts") or []) or "Property identity mismatch")

                cloud_docs = [d for d in docs if (d.get("metadata") or {}).get("cloud_storage_path")]
                if cloud_store and cloud_docs:
                    selected_doc_name = st.selectbox("Stored original", [d.get("name") for d in cloud_docs], key=f"cloud_doc_{chosen['id']}")
                    selected_doc = next(d for d in cloud_docs if d.get("name") == selected_doc_name)
                    if st.button("Retrieve original from private cloud", key=f"retrieve_doc_{chosen['id']}", use_container_width=True):
                        try:
                            path = (selected_doc.get("metadata") or {}).get("cloud_storage_path")
                            st.session_state[f"cloud_doc_bytes_{chosen['id']}"] = cloud_store.download_bytes(path)
                            st.session_state[f"cloud_doc_name_{chosen['id']}"] = selected_doc_name
                        except Exception as exc:
                            st.error(f"Could not retrieve original: {exc}")
                    stored_bytes = st.session_state.get(f"cloud_doc_bytes_{chosen['id']}")
                    stored_name = st.session_state.get(f"cloud_doc_name_{chosen['id']}")
                    if stored_bytes and stored_name == selected_doc_name:
                        st.download_button("Download retrieved original", stored_bytes, file_name=stored_name, key=f"download_cloud_{chosen['id']}", use_container_width=True)

            uploads = st.file_uploader(
                "Upload legal pack (PDF/TXT or ZIP containing PDFs)", type=["pdf", "txt", "zip"],
                accept_multiple_files=True, key=f"upload_{chosen['id']}"
            )
            if uploads and st.button("Analyse & save legal pack", key=f"analyse_upload_{chosen['id']}", type="primary", use_container_width=True):
                try:
                    parsed = []
                    with st.spinner("Parsing legal documents and building evidence trail..."):
                        for f in uploads:
                            for doc in uploaded_documents(f.name, f.getvalue()):
                                raw = doc.pop("_raw_bytes", b"")
                                if cloud_store and raw:
                                    try:
                                        path = cloud_store.upload_legal_document(chosen["id"], doc.get("name") or f.name, raw, doc.get("sha256") or "document")
                                        doc.setdefault("metadata", {})["cloud_storage_path"] = path
                                        doc["access_status"] = "uploaded, parsed and stored privately" if doc.get("text_content") else "uploaded and stored; no extractable text"
                                    except Exception as cloud_exc:
                                        doc.setdefault("metadata", {})["cloud_storage_error"] = str(cloud_exc)[:300]
                                parsed.append(doc)
                        save_uploaded_legal_documents(db, chosen, parsed)
                        if companies_house_api_key:
                            try:
                                refresh_property_company(db, chosen, companies_house_api_key)
                            except Exception:
                                pass
                        sync_cloud("legal pack/company upload", quiet=False)
                    st.success(f"Analysed {len(parsed)} legal document(s).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Legal pack could not be analysed: {exc}")

            risk_flags = legal_summary.get("risk_flags") or chosen.get("legal_risk_flags") or []
            if risk_flags:
                st.markdown("#### Legal risk register")
                risk_frame = pd.DataFrame([{
                    "Severity": f.get("severity"), "Issue": f.get("label"), "Document": f.get("document") or "-",
                    "Page": f.get("page"), "Evidence": f.get("excerpt") or ""
                } for f in sorted(risk_flags, key=lambda x: int(x.get("severity") or 0), reverse=True)])
                st.dataframe(risk_frame, hide_index=True, use_container_width=True)
            st.markdown("#### Questions for your solicitor")
            for question in solicitor_questions(chosen, legal_summary):
                st.write(f"- {question}")
            st.caption("Automated legal-pack analysis is triage only. The latest complete pack/addendum and legal acceptability must be confirmed by the buyer's solicitor before bidding.")

    with tabs[6]:
        if st.button("Retry location / motorway enrichment", key=f"geo_retry_{chosen['id']}", use_container_width=True):
            try:
                with st.spinner("Refreshing postcode and motorway-junction evidence..."):
                    result = refresh_geography(db)
                    sync_cloud("geography refresh", quiet=False)
                if result.get("errors"):
                    st.warning("Location refresh completed with a fallback/warning: " + " | ".join(result.get("errors") or []))
                else:
                    st.success(f"Location refresh complete: {result.get('motorway_enriched', 0)} junction distances updated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Location refresh failed: {exc}")
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Nearest motorway", chosen.get("nearest_motorway") or "Pending")
        l2.metric("Nearest junction", chosen.get("nearest_junction") or "Pending")
        l3.metric("Distance", f"{chosen.get('motorway_distance_miles'):.1f} mi" if chosen.get("motorway_distance_miles") is not None else "Pending")
        l4.metric("Distance type", chosen.get("motorway_distance_kind") or "-")
        if chosen.get("latitude") is not None and chosen.get("longitude") is not None:
            st.map(pd.DataFrame([{"lat": chosen.get("latitude"), "lon": chosen.get("longitude")}]), latitude="lat", longitude="lon", zoom=12)
        else:
            st.info("Postcode coordinates not yet available.")

    with tabs[7]:
        st.markdown("### Lotly workspace")
        brief = deal_brief_markdown(chosen, story, readiness, actions)
        st.download_button(
            "Download one-page deal brief", brief,
            file_name=f"deal-brief-{chosen.get('postcode') or chosen.get('id')}.md".replace(" ", "-"),
            mime="text/markdown", use_container_width=True,
        )
        workspace = db.workspace_for(chosen["id"])
        stages = ["New", "Reviewing", "Auctioneer Contacted", "Viewing", "Legal Review", "Offer Made", "Negotiating", "Bid Approved", "Won", "Lost", "Archived"]
        w1, w2, w3 = st.columns([1.1, 2.0, 1.1])
        with w1:
            current_stage = workspace.get("stage") if workspace.get("stage") in stages else "New"
            stage = st.selectbox("Stage", stages, index=stages.index(current_stage), key=f"stage_{chosen['id']}")
        with w2:
            next_action = st.text_input("Next action", value=workspace.get("next_action") or "", key=f"next_{chosen['id']}")
        with w3:
            follow_up = st.text_input("Follow-up date", value=workspace.get("follow_up_date") or "", placeholder="YYYY-MM-DD", key=f"follow_{chosen['id']}")
        if st.button("Save deal stage", key=f"save_workspace_{chosen['id']}", type="primary"):
            db.save_workspace(chosen["id"], stage, next_action, follow_up)
            sync_cloud("deal workspace", quiet=False)
            st.success("Deal workspace saved.")

        st.markdown("### Action centre")
        q1, q2, q3, q4 = st.columns(4)
        if chosen.get("url"):
            q1.link_button("Auction listing", chosen["url"], use_container_width=True)
        else:
            q1.caption("Auction link unavailable")
        legal_docs = [d for d in db.legal_documents_for(chosen["id"]) if d.get("url")]
        if legal_docs:
            q2.link_button("Legal document", legal_docs[0]["url"], use_container_width=True)
        else:
            q2.caption("Legal document link pending")
        plan_links = [i for i in planning_items if i.get("source_url")]
        if plan_links:
            q3.link_button("Planning record", plan_links[0]["source_url"], use_container_width=True)
        else:
            q3.caption("Planning record link pending")
        if profile.get("company_number"):
            q4.link_button("Companies House", f"https://find-and-update.company-information.service.gov.uk/company/{profile['company_number']}", use_container_width=True)
        else:
            q4.caption("Company owner not identified")

        st.markdown("### Deal notes")
        note = st.text_area("Add call, viewing, negotiation or due-diligence note", key=f"new_note_{chosen['id']}", height=100)
        if st.button("Add note", key=f"add_note_{chosen['id']}"):
            db.add_note(chosen["id"], note)
            sync_cloud("deal note")
            st.rerun()
        notes = db.notes_for(chosen["id"])
        if notes:
            for item in notes:
                c1, c2 = st.columns([8, 1])
                with c1:
                    st.markdown(f"**{str(item.get('created_at') or '')[:16].replace('T', ' ')}**")
                    st.write(item.get("note"))
                with c2:
                    if st.button("Delete", key=f"del_note_{item['id']}"):
                        db.delete_note(item["id"], chosen["id"])
                        sync_cloud("delete note")
                        st.rerun()
                st.divider()
        else:
            st.caption("No deal notes yet.")


selected_id = st.session_state.get("selected_deal_id")
selected = next((r for r in rows if r.get("id") == selected_id), None) if selected_id else None
if selected:
    render_deal_room(selected)
elif not rows:
    st.info("Lotly has not built the live opportunity feed yet. Click Refresh live data to pull the first auction catalogue.")
else:
    # Modern deal-feed experience: fast scan first, deep diligence second.
    st.markdown('<div class="eyebrow">Live opportunity feed</div><div class="muted">Ranked around your acquisition strategy, not just auction date. Use the quick views to move from discovery to diligence.</div>', unsafe_allow_html=True)
    nav1, nav2 = st.columns([1.0, 2.2])
    with nav1:
        market = st.segmented_control("Market", ["Residential", "Commercial"], default=st.session_state.get("market_mode", "Residential"), key="market_mode")
    market_rows = [r for r in rows if is_actionable(r) and (is_commercial(r) if market == "Commercial" else not is_commercial(r))]
    with nav2:
        view = st.segmented_control(
            "Opportunity view",
            ["Best deals", "Unsold", "New", "Reductions", "Relisted", "Shortlist"],
            default=st.session_state.get("browse_view", "Best deals"), key="browse_view",
        )

    # High-level scan stats inspired by modern property/investment dashboards.
    bid_ready = len([
        r for r in market_rows
        if legal_state(r) == "VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0) >= 100
        and planning_state(r) == "SCREENED" and r.get("max_bid")
    ])
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Live opportunities", len(market_rows))
    k2.metric("Post-auction / unsold", len([r for r in market_rows if is_unsold(r)]))
    k3.metric("Price reductions", len([r for r in market_rows if (r.get("price_reduction_pct") or 0) > 0]))
    k4.metric("DD ready", bid_ready, help="Core legal pack complete, planning screened and maximum bid available.")

    with st.container(border=True):
        s1, s2, s3, s4 = st.columns([2.5, 1.1, 1.25, 1.2])
        with s1:
            search = st.text_input("Search", placeholder="Search postcode, town, street or keyword", label_visibility="collapsed")
        with s2:
            max_price = st.selectbox("Max guide", ["Any price", "GBP 100k", "GBP 200k", "GBP 500k", "GBP 1m", "GBP 1.5m"], label_visibility="collapsed")
        with s3:
            source = st.selectbox("Auction house", ["All auction houses"] + sorted({r.get("source") or "Unknown" for r in market_rows}), label_visibility="collapsed")
        with s4:
            sort = st.selectbox("Sort", ["Best deal", "Highest motivation", "Biggest discount", "Lowest guide", "Newest"], label_visibility="collapsed")
        display_mode = st.segmented_control("Display", ["Cards", "Map", "Table"], default=st.session_state.get("display_mode", "Cards"), key="display_mode")
        with st.expander("Advanced filters"):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                statuses = st.multiselect("Status", sorted({r.get("status") or "Unknown" for r in market_rows}))
            with f2:
                areas = st.multiselect("Area", sorted({r.get("area") or "North West" for r in market_rows}))
            with f3:
                property_types = st.multiselect("Property type", sorted({r.get("property_type") or "Other" for r in market_rows}))
            with f4:
                minimum_score = st.slider("Minimum deal potential", 0.0, 10.0, 0.0, 0.5)
            a1, a2, a3 = st.columns(3)
            with a1:
                only_failed = st.checkbox("Failed / post-auction only")
            with a2:
                only_reduced = st.checkbox("Price reductions only")
            with a3:
                legal_only = st.checkbox("Verified core legal pack only")

    filtered = list(market_rows)
    if view == "Unsold":
        filtered = [r for r in filtered if is_unsold(r)]
    elif view == "New":
        filtered = [r for r in filtered if first_seen_today(r)]
    elif view == "Reductions":
        filtered = [r for r in filtered if (r.get("price_reduction_pct") or 0) > 0]
    elif view == "Relisted":
        filtered = [r for r in filtered if r.get("status") == "Relisted"]
    elif view == "Shortlist":
        filtered = [r for r in filtered if r.get("shortlisted")]

    price_map = {"GBP 100k": 100_000, "GBP 200k": 200_000, "GBP 500k": 500_000, "GBP 1m": 1_000_000, "GBP 1.5m": 1_500_000}
    if max_price in price_map:
        filtered = [r for r in filtered if (r.get("guide_price") or 0) <= price_map[max_price]]
    if source != "All auction houses":
        filtered = [r for r in filtered if r.get("source") == source]
    if statuses:
        filtered = [r for r in filtered if r.get("status") in statuses]
    if areas:
        filtered = [r for r in filtered if r.get("area") in areas]
    if property_types:
        filtered = [r for r in filtered if r.get("property_type") in property_types]
    if minimum_score:
        filtered = [r for r in filtered if float(r.get("browse_score") or 0) >= minimum_score]
    if only_failed:
        filtered = [r for r in filtered if is_unsold(r) or int(r.get("failure_count") or 0) > 0]
    if only_reduced:
        filtered = [r for r in filtered if float(r.get("price_reduction_pct") or 0) > 0]
    if legal_only:
        filtered = [r for r in filtered if legal_state(r) == "VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0) >= 100]
    if search:
        q = search.lower().strip()
        filtered = [r for r in filtered if q in " ".join(str(r.get(k) or "") for k in ("title", "address", "postcode", "area", "raw_text")).lower()]

    if sort == "Best deal":
        filtered.sort(key=lambda r: (r.get("browse_score") or 0, r.get("motivation_score") or 0, r.get("deal_score") or 0), reverse=True)
    elif sort == "Highest motivation":
        filtered.sort(key=lambda r: (r.get("motivation_score") or 0, r.get("browse_score") or 0), reverse=True)
    elif sort == "Biggest discount":
        filtered.sort(key=lambda r: (r.get("comparable_guide_discount_pct") or -999), reverse=True)
    elif sort == "Lowest guide":
        filtered.sort(key=lambda r: r.get("guide_price") or 10**12)
    else:
        filtered.sort(key=lambda r: str(r.get("first_seen") or ""), reverse=True)

    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown(f"### {len(filtered)} {market.lower()} opportunities")
        st.caption("Best Deal combines value, vendor motivation, financial return, evidence confidence and unresolved risk. Unknown due diligence is penalised rather than treated as safe.")
    with h2:
        if filtered:
            st.caption(f"Top score {float(filtered[0].get('browse_score') or 0):.1f}/10 · {score_label(filtered[0].get('browse_score'))}")

    def analyst_frame(items):
        return pd.DataFrame([{
            "Rank": r.get("browse_score"), "Decision": r.get("recommendation"), "Status": r.get("status"),
            "Auction house": r.get("source"), "Address": clean_address(r), "Type": r.get("property_type"),
            "Guide": r.get("guide_price"), "Opening offer": r.get("opening_offer"), "Max bid": r.get("max_bid"),
            "Market value": r.get("market_value"), "Motivation": r.get("motivation_score"), "Failures": r.get("failure_count"),
            "Guide reduction %": r.get("price_reduction_pct"), "Comp confidence %": r.get("comparable_confidence"),
            "Legal pack %": r.get("legal_pack_completeness_pct"), "Legal": legal_state(r), "Planning": planning_state(r), "Source": r.get("url"),
        } for r in items])

    if display_mode == "Map":
        map_rows = [r for r in filtered if r.get("latitude") is not None and r.get("longitude") is not None]
        if map_rows:
            map_df = pd.DataFrame({"lat": [float(r["latitude"]) for r in map_rows], "lon": [float(r["longitude"]) for r in map_rows]})
            st.map(map_df, use_container_width=True)
            st.caption(f"Mapped {len(map_rows)} of {len(filtered)} opportunities with coordinates. Open a card below for the full Deal Room.")
            for row in filtered[:12]:
                render_property_card(row)
        else:
            st.info("No coordinates are available for the current result set yet. Refresh location enrichment or switch to Cards.")
    elif display_mode == "Table":
        frame = analyst_frame(filtered)
        st.dataframe(frame, hide_index=True, use_container_width=True, height=720, column_config={
            "Rank": st.column_config.NumberColumn(format="%.1f"), "Guide": st.column_config.NumberColumn(format="GBP %d"),
            "Opening offer": st.column_config.NumberColumn(format="GBP %d"), "Max bid": st.column_config.NumberColumn(format="GBP %d"),
            "Market value": st.column_config.NumberColumn(format="GBP %d"), "Motivation": st.column_config.NumberColumn(format="%.1f"),
            "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"), "Comp confidence %": st.column_config.NumberColumn(format="%d%%"),
            "Legal pack %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
            "Source": st.column_config.LinkColumn("Auction listing"),
        })
    else:
        for row in filtered[:50]:
            render_property_card(row)
        if len(filtered) > 50:
            st.info(f"Showing the top 50 of {len(filtered)} results. Tighten filters or switch to Table for the full list.")

    with st.expander("Export / analyst view"):
        frame = analyst_frame(filtered)
        st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
            "Rank": st.column_config.NumberColumn(format="%.1f"), "Guide": st.column_config.NumberColumn(format="GBP %d"),
            "Opening offer": st.column_config.NumberColumn(format="GBP %d"), "Max bid": st.column_config.NumberColumn(format="GBP %d"),
            "Market value": st.column_config.NumberColumn(format="GBP %d"), "Motivation": st.column_config.NumberColumn(format="%.1f"),
            "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"), "Comp confidence %": st.column_config.NumberColumn(format="%d%%"),
            "Source": st.column_config.LinkColumn("Auction listing"),
        })

st.caption(
    "Lotly is an acquisition-intelligence tool. Auctioneer listings and the latest legal pack/addendum remain authoritative. "
    "Automated valuation, planning and risk outputs are evidence screens, not RICS valuation, legal or tax advice."
)
