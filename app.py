from pathlib import Path
import os
import re
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from tracker.db import Database
from tracker.pipeline import refresh_all
from tracker.deal_engine import DealConfig, score_property
from tracker.underwriting import UnderwritingDefaults, underwrite_property
from tracker.comparables import refresh_due_comparables, refresh_property_comparables
from tracker.diligence import (
    refresh_due_diligence,
    refresh_property_planning,
    refresh_property_legal,
    save_uploaded_legal_documents,
)
from tracker.legal import uploaded_document


POUND = "\u00a3"
COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}
SOLD_STATES = {"sold", "sold prior", "sold after"}
UNSOLD_STATES = {"Available post-auction", "No Bids", "Last Bid", "Unsold"}

st.set_page_config(page_title="NW Auction Deal Finder", page_icon="\U0001f3e0", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 1500px;}
[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e6e8eb; border-radius: 12px; padding: 10px 12px;}
[data-testid="stMetricLabel"] {font-size: 0.78rem; color: #667085;}
[data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 750;}
.auction-hero {padding: 4px 0 8px 0;}
.auction-hero h1 {font-size: 2rem; margin-bottom: 0.15rem;}
.muted {color: #667085; font-size: 0.9rem;}
.badge {display:inline-block; padding:4px 9px; margin:2px 4px 2px 0; border-radius:999px; font-size:0.77rem; font-weight:650; border:1px solid #d0d5dd; background:#f8fafc;}
.badge-hot {background:#fff4e5; border-color:#f5c26b; color:#8a4b08;}
.badge-risk {background:#fff1f1; border-color:#f1a3a3; color:#9b1c1c;}
.badge-good {background:#ecfdf3; border-color:#86d6a3; color:#166534;}
.property-title {font-size:1.2rem; font-weight:760; line-height:1.25; margin:2px 0 6px 0;}
.card-sub {color:#667085; font-size:0.86rem; margin-bottom:5px;}
.deal-score {font-size:1.8rem; font-weight:800; line-height:1;}
.deal-score-label {font-size:0.75rem; color:#667085; text-transform:uppercase; letter-spacing:.03em;}
.soft-panel {background:#f8fafc; border:1px solid #e6e8eb; border-radius:12px; padding:14px;}
.small-label {font-size:.74rem; color:#667085; text-transform:uppercase; letter-spacing:.03em;}
.big-number {font-size:1.2rem; font-weight:750;}
[data-testid="stImage"] img {border-radius:10px; object-fit:cover;}
div.stButton > button {border-radius:9px;}
hr {margin: 1rem 0;}
</style>
""",
    unsafe_allow_html=True,
)

DB_PATH = Path(os.environ.get("AUCTION_DB_PATH", str(Path(__file__).with_name("auction_tracker.db"))))
db = Database(DB_PATH)


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
    if legal_state(row) != "REVIEWED":
        value -= 0.35
    if planning_state(row) != "SCREENED":
        value -= 0.15
    if row.get("works_missing"):
        value -= 0.35
    if 0 < float(row.get("comparable_confidence") or 0) < 60:
        value -= 0.15
    return round(max(0.0, min(10.0, value)), 1)


def legal_state(row):
    status = str(row.get("legal_status") or "").lower()
    if status in {"parsed", "reviewed"}:
        return "REVIEWED"
    if status == "links-only":
        return "LINKS ONLY"
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
        f"{dd.get('planning_ok', 0)}/{dd.get('planning_attempted', 0)}, legal {dd.get('legal_ok', 0)}/{dd.get('legal_attempted', 0)}."
    )
    errors = [x for x in sources if x.get("status") != "ok"] + [{"source": "Geography", "error": e} for e in geo.get("errors", [])]
    errors += [{"source": "Planning/legal", "error": e} for e in (dd.get("planning_errors", []) + dd.get("legal_errors", []))]
    if errors:
        with st.expander("Refresh warnings"):
            for item in errors:
                st.write(f"**{item.get('source')}** - {item.get('error')}")


# Sidebar keeps advanced settings out of the browsing experience.
with st.sidebar:
    st.header("Deal criteria")
    commercial_target_psf = st.number_input("Commercial target GBP/sq ft", min_value=1, value=50, step=5)
    commercial_ceiling_psf = st.number_input("Commercial ceiling GBP/sq ft", min_value=1, value=60, step=5)
    commercial_min_sqft = st.number_input("Preferred commercial size", min_value=500, value=9000, step=500)
    commercial_max_price = st.number_input("Commercial max guide", min_value=0, value=1_500_000, step=50_000)
    preferred_motorway_miles = st.number_input("Preferred motorway miles", min_value=0.5, value=5.0, step=0.5)
    residential_target_price = st.number_input("Residential target guide", min_value=0, value=100_000, step=5_000)
    hot_score = st.slider("Hot sourcing threshold", 1.0, 10.0, 8.0, 0.5)
    st.divider()
    st.caption("Default underwriting allowances")
    default_auction_fee = st.number_input("Generic auction fee", min_value=0, value=1500, step=250)
    default_legal = st.number_input("Legal allowance", min_value=0, value=2000, step=250)
    default_survey = st.number_input("Survey/DD allowance", min_value=0, value=1000, step=250)
    default_res_margin = st.number_input("Residential target margin %", min_value=0.0, max_value=80.0, value=20.0, step=1.0)
    default_com_margin = st.number_input("Commercial target uplift %", min_value=0.0, max_value=80.0, value=20.0, step=1.0)

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
st.markdown('<div class="auction-hero"><h1>North West Auction Deal Finder</h1><div class="muted">Live auction stock ranked for acquisition, with valuation, auction history, planning and legal-pack intelligence.</div></div>', unsafe_allow_html=True)
head1, head2, head3, head4 = st.columns([1.05, 1.0, 1.0, 2.7])
with head1:
    if st.button("Refresh live data", type="primary", use_container_width=True):
        with st.spinner("Pulling live auction stock and priority intelligence..."):
            st.session_state["refresh_summary"] = refresh_all(db)
        st.rerun()
with head2:
    if st.button("Refresh comparables", use_container_width=True):
        with st.spinner("Refreshing priority comparable evidence..."):
            st.session_state["comp_summary"] = refresh_due_comparables(db, max_properties=35)
        st.rerun()
with head3:
    if st.button("Refresh planning/legal", use_container_width=True):
        with st.spinner("Refreshing priority due diligence..."):
            st.session_state["dd_summary"] = refresh_due_diligence(db, max_planning=35, max_legal=20)
        st.rerun()
with head4:
    runs = db.latest_runs()
    if runs:
        latest = runs[0]
        st.caption(f"Latest source check: {latest.get('completed_at') or latest.get('started_at')} | {latest.get('source')} | {latest.get('status')}")
    else:
        st.caption("No data pulled yet. Use Refresh live data.")
render_refresh_summary()

# Build analysis rows once per Streamlit rerun.
rows = db.list_properties()
history_map = db.history_map() if rows else {}
underwriting_map = db.underwriting_map() if rows else {}
comparable_map = db.comparable_summary_map() if rows else {}
planning_map = db.planning_summary_map() if rows else {}
legal_map = db.legal_summary_map() if rows else {}
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
        "legal_risk_score": float(legal.get("risk_score") or 0) if legal and str(legal.get("status") or "").lower() in {"parsed", "reviewed"} else None,
        "legal_document_count": int(legal.get("document_count") or 0) if legal else 0,
        "legal_parsed_document_count": int(legal.get("parsed_document_count") or 0) if legal else 0,
        "legal_completion_days": legal.get("completion_days"),
        "legal_deposit_pct": legal.get("deposit_pct"),
        "legal_lease_years": legal.get("lease_years"),
        "legal_buyer_fee_detected": legal.get("buyer_fee_detected"),
        "legal_vat_flag": bool(legal.get("vat_flag")) if legal else False,
        "legal_has_addendum": bool(legal.get("has_addendum")) if legal else False,
        "legal_risk_flags": legal.get("risk_flags") or [],
        "legal_warnings": legal.get("warnings") or [],
        "legal_error": legal.get("error"),
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
    if (row.get("features") or {}).get("vacant"):
        tags.append('<span class="badge">Vacant</span>')
    if row.get("listed_building_signal") or row.get("planning_listed_flag"):
        tags.append('<span class="badge badge-risk">Listed / heritage</span>')
    if legal_state(row) == "UNKNOWN":
        tags.append('<span class="badge badge-risk">Legal not reviewed</span>')
    st.markdown("".join(tags), unsafe_allow_html=True)


def render_property_card(row):
    with st.container(border=True):
        img_col, main_col, score_col = st.columns([1.25, 3.65, 0.9], vertical_alignment="top")
        with img_col:
            if row.get("image_url"):
                st.image(row["image_url"], use_container_width=True)
            else:
                st.markdown('<div class="soft-panel" style="height:150px;display:flex;align-items:center;justify-content:center;color:#667085;">Property image pending refresh</div>', unsafe_allow_html=True)
        with main_col:
            st.markdown(f'<div class="card-sub">{row.get("source") or "Auction"} | Lot {row.get("lot_number") or "-"} | {row.get("property_type") or "Property"}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="property-title">{clean_address(row)}</div>', unsafe_allow_html=True)
            render_badges(row)
            if is_commercial(row):
                a, b, c, d = st.columns(4)
                a.metric("Guide", money(row.get("guide_price")))
                b.metric("GIA", f"{int(row.get('size_sqft')):,} sq ft" if row.get("size_sqft") else "-")
                c.metric("Guide / sq ft", money(row.get("price_per_sqft"), 0) if row.get("price_per_sqft") else "-")
                d.metric("Max buy", money(row.get("max_bid")))
            else:
                a, b, c, d = st.columns(4)
                a.metric("Guide", money(row.get("guide_price")))
                b.metric("Desktop GDV", money(row.get("market_value") or row.get("comparable_valuation_mid")))
                c.metric("Max buy", money(row.get("max_bid")))
                d.metric("Est. profit", money(row.get("profit")))
            meta1, meta2, meta3 = st.columns(3)
            meta1.caption(f"Vendor motivation: {row.get('motivation_score', 0):.1f}/10")
            meta2.caption(f"Comparable confidence: {int(row.get('comparable_confidence') or 0)}%")
            if row.get("motorway_distance_miles") is not None:
                meta3.caption(f"Motorway: {row.get('motorway_distance_miles'):.1f} mi to {row.get('nearest_junction') or row.get('nearest_motorway') or 'junction'}")
            else:
                meta3.caption("Motorway distance: pending")
        with score_col:
            st.markdown(f'<div class="deal-score-label">Deal potential</div><div class="deal-score">{row.get("browse_score", 0):.1f}</div><div class="deal-score-label">out of 10</div>', unsafe_allow_html=True)
            st.write("")
            if st.button("View deal", key=f"view_{row['id']}", type="primary", use_container_width=True):
                st.session_state["selected_deal_id"] = row["id"]
                st.rerun()
            star = "Remove shortlist" if row.get("shortlisted") else "Shortlist"
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
            auction_admin_fee = st.number_input("Extra auction/admin fixed fee", min_value=0.0, value=float(saved.get("auction_admin_fee") if saved.get("auction_admin_fee") is not None else (0.0 if detected_pct is not None else underwriting_defaults.auction_admin_fee)), step=250.0)
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
            st.rerun()


def render_deal_room(chosen):
    if st.button("Back to property results"):
        st.session_state.pop("selected_deal_id", None)
        st.rerun()

    left, right = st.columns([1.45, 2.55], vertical_alignment="top")
    with left:
        if chosen.get("image_url"):
            st.image(chosen["image_url"], use_container_width=True)
        else:
            st.markdown('<div class="soft-panel" style="height:280px;display:flex;align-items:center;justify-content:center;color:#667085;">Property image pending refresh</div>', unsafe_allow_html=True)
    with right:
        st.caption(f"{chosen.get('source')} | Lot {chosen.get('lot_number') or '-'} | {chosen.get('property_type')} | {chosen.get('status')}")
        st.header(clean_address(chosen))
        render_badges(chosen)
        a, b, c, d = st.columns(4)
        a.metric("Deal potential", f"{chosen.get('browse_score', 0):.1f}/10")
        b.metric("Vendor motivation", f"{chosen.get('motivation_score', 0):.1f}/10")
        c.metric("Guide", money(chosen.get("guide_price")))
        d.metric("Max buy", money(chosen.get("max_bid")), delta="PROVISIONAL" if chosen.get("max_bid_provisional") else None)
        if chosen.get("recommended_action"):
            if chosen.get("recommendation") == "PURSUE":
                st.success(f"PURSUE - {chosen.get('recommended_action')}")
            elif chosen.get("recommendation") == "PASS":
                st.error(f"PASS - {chosen.get('recommended_action')}")
            else:
                st.warning(f"WATCH - {chosen.get('recommended_action')}")
        act1, act2 = st.columns(2)
        with act1:
            if st.button("Remove from shortlist" if chosen.get("shortlisted") else "Add to shortlist", key=f"deal_short_{chosen['id']}", use_container_width=True):
                toggle_shortlist(chosen)
        with act2:
            if chosen.get("url"):
                st.link_button("Open auctioneer listing", chosen["url"], use_container_width=True)

    tabs = st.tabs(["Overview", "Financials", "Comparables", "Auction history", "Planning & legal", "Location"])

    with tabs[0]:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Opening offer", money(chosen.get("opening_offer")))
        m2.metric("Market value / GDV", money(chosen.get("market_value") or chosen.get("comparable_valuation_mid")))
        m3.metric("Profit / equity", money(chosen.get("profit")))
        m4.metric("ROI", pct(chosen.get("roi_pct")))
        m5.metric("UW confidence", f"{int(chosen.get('underwriting_confidence') or 0)}%")
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
            if legal_state(chosen) != "REVIEWED":
                concerns.insert(0, "Legal pack has not been parsed/reviewed: legal risk remains UNKNOWN.")
            if planning_state(chosen) != "SCREENED":
                concerns.insert(0, "Planning screen is incomplete: planning risk remains UNKNOWN.")
            if not concerns:
                concerns = ["No major automated warning is currently recorded; normal auction due diligence still applies."]
            for item in concerns[:10]:
                st.write(f"- {item}")
        st.markdown("### Key property facts")
        facts = pd.DataFrame([
            ["Auction house", chosen.get("source")],
            ["Status", chosen.get("status")],
            ["Auction date", chosen.get("auction_date")],
            ["Property type", chosen.get("property_type")],
            ["Tenure", chosen.get("tenure")],
            ["Floor area", f"{int(chosen.get('size_sqft')):,} sq ft" if chosen.get("size_sqft") else "Unknown"],
            ["Guide / sq ft", money(chosen.get("price_per_sqft"), 2) if chosen.get("price_per_sqft") else "Unknown"],
            ["Failed auction signals", int(chosen.get("failure_count") or 0)],
            ["Observed guide reduction", pct(chosen.get("price_reduction_pct"))],
            ["Legal status", legal_state(chosen)],
            ["Planning status", planning_state(chosen)],
        ], columns=["Item", "Value"])
        st.dataframe(facts, hide_index=True, use_container_width=True)

    with tabs[1]:
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

    with tabs[2]:
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Refresh this property's comparables", key=f"comp_{chosen['id']}", use_container_width=True):
                with st.spinner("Refreshing comparable evidence..."):
                    refresh_property_comparables(db, chosen)
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

    with tabs[3]:
        h1, h2, h3 = st.columns(3)
        h1.metric("Failed auction signals", int(chosen.get("failure_count") or 0))
        h2.metric("Guide reductions", int(chosen.get("price_reduction_events") or 0))
        h3.metric("Observed guide drop", pct(chosen.get("price_reduction_pct")))
        hist = db.history_for(chosen["id"])
        if hist:
            chronological = list(reversed(hist))
            st.markdown("### Property auction timeline")
            for event in chronological:
                when = event.get("auction_date") or str(event.get("captured_at") or "")[:10]
                line = f"**{when}** - {event.get('status') or 'Observed'}"
                if event.get("guide_price"):
                    line += f" | Guide {money(event.get('guide_price'))}"
                if event.get("result_price"):
                    line += f" | Result {money(event.get('result_price'))}"
                st.markdown(line)
            with st.expander("Raw history table"):
                st.dataframe(pd.DataFrame(chronological), hide_index=True, use_container_width=True)
        else:
            st.info("No auction-history observations stored yet. Future refreshes and historical backfill will populate this timeline.")

    with tabs[4]:
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
                except Exception as exc:
                    st.error(str(exc))
                st.rerun()
            items = db.planning_items_for(chosen["id"])
            if items:
                frame = pd.DataFrame([{
                    "Type": i.get("kind"), "Dataset": i.get("dataset"), "Reference": i.get("reference"),
                    "Record": i.get("name"), "Severity": i.get("severity"), "Subject": bool(i.get("likely_subject")),
                    "Distance": i.get("distance_miles"), "Source": i.get("source_url"),
                } for i in items])
                st.dataframe(frame, hide_index=True, use_container_width=True, column_config={"Source": st.column_config.LinkColumn("Source"), "Distance": st.column_config.NumberColumn(format="%.2f mi")})
            else:
                st.caption("No planning records are stored for this property. A zero count is not a clean-planning certificate.")
        with lcol:
            st.markdown("### Legal-pack intelligence")
            lstate = legal_state(chosen)
            if lstate == "REVIEWED":
                st.success(f"REVIEWED | Known legal risk {float(chosen.get('legal_risk_score') or 0):.1f}/10")
            elif lstate == "LINKS ONLY":
                st.warning("Legal links found but documents not parsed. Risk is UNKNOWN.")
            elif lstate == "ERROR":
                st.error("Legal-pack check failed. Risk is UNKNOWN.")
            else:
                st.warning("Legal pack not reviewed. Risk is UNKNOWN and bid approval is blocked.")
            if st.button("Refresh legal links/pack", key=f"legal_{chosen['id']}", use_container_width=True):
                try:
                    with st.spinner("Checking public legal-pack links..."):
                        refresh_property_legal(db, chosen)
                except Exception as exc:
                    st.error(str(exc))
                st.rerun()
            docs = db.legal_documents_for(chosen["id"])
            if docs:
                frame = pd.DataFrame([{"Name": d.get("name"), "Type": d.get("doc_type"), "Access": d.get("access_status"), "URL": d.get("url")} for d in docs])
                st.dataframe(frame, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("Document")})
            uploads = st.file_uploader("Upload legal pack documents for local parsing", type=["pdf", "txt"], accept_multiple_files=True, key=f"upload_{chosen['id']}")
            if uploads and st.button("Analyse uploaded legal documents", key=f"analyse_upload_{chosen['id']}", type="primary", use_container_width=True):
                parsed = [uploaded_document(f.name, f.getvalue()) for f in uploads]
                save_uploaded_legal_documents(db, chosen, parsed)
                st.rerun()
            if chosen.get("legal_completion_days"):
                st.caption(f"Completion: {chosen.get('legal_completion_days')} days | Deposit: {pct(chosen.get('legal_deposit_pct'))} | Lease: {chosen.get('legal_lease_years') or '-'} years")
            for flag in chosen.get("legal_risk_flags") or []:
                st.write(f"- {flag.get('label')} (severity {flag.get('severity')}/5)")

    with tabs[5]:
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Nearest motorway", chosen.get("nearest_motorway") or "Pending")
        l2.metric("Nearest junction", chosen.get("nearest_junction") or "Pending")
        l3.metric("Distance", f"{chosen.get('motorway_distance_miles'):.1f} mi" if chosen.get("motorway_distance_miles") is not None else "Pending")
        l4.metric("Distance type", chosen.get("motorway_distance_kind") or "-")
        if chosen.get("latitude") is not None and chosen.get("longitude") is not None:
            st.map(pd.DataFrame([{"lat": chosen.get("latitude"), "lon": chosen.get("longitude")}]), latitude="lat", longitude="lon", zoom=12)
        else:
            st.info("Postcode coordinates not yet available.")


selected_id = st.session_state.get("selected_deal_id")
selected = next((r for r in rows if r.get("id") == selected_id), None) if selected_id else None
if selected:
    render_deal_room(selected)
elif not rows:
    st.info("No auction stock has been collected yet. Click Refresh live data to build the first live North West catalogue.")
else:
    # Auction-site style browse experience.
    market = st.segmented_control("Market", ["Residential", "Commercial"], default=st.session_state.get("market_mode", "Residential"), key="market_mode")
    market_rows = [r for r in rows if is_actionable(r) and (is_commercial(r) if market == "Commercial" else not is_commercial(r))]

    view = st.segmented_control(
        "View",
        ["Best deals", "Unsold", "New", "Reductions", "Relisted", "Shortlist"],
        default="Best deals",
        key="browse_view",
    )

    # High-level market stats.
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Properties", len(market_rows))
    k2.metric("Unsold / post-auction", len([r for r in market_rows if is_unsold(r)]))
    k3.metric("Guide reductions", len([r for r in market_rows if (r.get("price_reduction_pct") or 0) > 0]))
    k4.metric("Shortlisted", len([r for r in market_rows if r.get("shortlisted")]))

    with st.container(border=True):
        s1, s2, s3, s4 = st.columns([2.3, 1.2, 1.2, 1.3])
        with s1:
            search = st.text_input("Search", placeholder="Postcode, town, street or keyword", label_visibility="collapsed")
        with s2:
            max_price = st.selectbox("Max guide", ["Any price", "GBP 100k", "GBP 200k", "GBP 500k", "GBP 1m", "GBP 1.5m"], label_visibility="collapsed")
        with s3:
            source = st.selectbox("Auction house", ["All auction houses"] + sorted({r.get("source") or "Unknown" for r in market_rows}), label_visibility="collapsed")
        with s4:
            sort = st.selectbox("Sort", ["Best deal", "Highest motivation", "Biggest discount", "Lowest guide", "Newest"], label_visibility="collapsed")
        with st.expander("More filters"):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                statuses = st.multiselect("Status", sorted({r.get("status") or "Unknown" for r in market_rows}))
            with f2:
                areas = st.multiselect("Area", sorted({r.get("area") or "North West" for r in market_rows}))
            with f3:
                property_types = st.multiselect("Property type", sorted({r.get("property_type") or "Other" for r in market_rows}))
            with f4:
                minimum_score = st.slider("Minimum deal potential", 0.0, 10.0, 0.0, 0.5)

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

    st.caption(f"Showing {len(filtered)} {market.lower()} opportunities. Best Deal ranking weighs value, seller motivation, return, evidence confidence and known/unknown risk - not auction date order.")
    for row in filtered[:60]:
        render_property_card(row)
    if len(filtered) > 60:
        st.info(f"Showing the top 60 of {len(filtered)} results. Tighten filters to narrow the list.")

    with st.expander("Analyst table / export view"):
        frame = pd.DataFrame([{
            "Rank": r.get("browse_score"), "Decision": r.get("recommendation"), "Status": r.get("status"),
            "Auction house": r.get("source"), "Address": clean_address(r), "Type": r.get("property_type"),
            "Guide": r.get("guide_price"), "Opening offer": r.get("opening_offer"), "Max bid": r.get("max_bid"),
            "Market value": r.get("market_value"), "Motivation": r.get("motivation_score"), "Failures": r.get("failure_count"),
            "Guide reduction %": r.get("price_reduction_pct"), "Comp confidence %": r.get("comparable_confidence"),
            "Legal": legal_state(r), "Planning": planning_state(r), "Source": r.get("url"),
        } for r in filtered])
        st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
            "Rank": st.column_config.NumberColumn(format="%.1f"), "Guide": st.column_config.NumberColumn(format="GBP %d"),
            "Opening offer": st.column_config.NumberColumn(format="GBP %d"), "Max bid": st.column_config.NumberColumn(format="GBP %d"),
            "Market value": st.column_config.NumberColumn(format="GBP %d"), "Motivation": st.column_config.NumberColumn(format="%.1f"),
            "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"), "Comp confidence %": st.column_config.NumberColumn(format="%d%%"),
            "Source": st.column_config.LinkColumn("Auction listing"),
        })

st.caption(
    "Acquisition triage only. Auctioneer listings and the latest legal pack/addendum remain authoritative. "
    "Automated valuation, planning and risk outputs are evidence screens, not RICS valuation, legal or tax advice."
)
