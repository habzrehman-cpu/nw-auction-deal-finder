from pathlib import Path
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from tracker.db import Database
from tracker.pipeline import refresh_all
from tracker.deal_engine import DealConfig, score_property
from tracker.underwriting import UnderwritingDefaults, underwrite_property
from tracker.comparables import refresh_due_comparables, refresh_property_comparables, HMLR_ATTRIBUTION
from tracker.diligence import (
    refresh_due_diligence, refresh_property_planning, refresh_property_legal, save_uploaded_legal_documents,
)
from tracker.legal import uploaded_document


st.set_page_config(page_title="North West Auction Deal Finder", layout="wide")
DB_PATH = Path(os.environ.get("AUCTION_DB_PATH", str(Path(__file__).with_name("auction_tracker.db"))))
db = Database(DB_PATH)

st.title("North West Property Auction Deal Finder")
st.caption(
    "Live auction sourcing + sold comparables + planning intelligence + legal-pack triage + persistent underwriting for "
    "Allsop, Savills, BTG Eddisons and Auction House North West."
)

head1, head2, head3, head4, head5 = st.columns([1.15, 1.15, 1.15, 0.8, 2.15])
with head1:
    if st.button("Refresh live data", type="primary", use_container_width=True):
        with st.spinner("Pulling auction data, details, locations, comparables and priority due diligence..."):
            st.session_state["refresh_summary"] = refresh_all(db)
        st.rerun()
with head2:
    if st.button("Refresh comparable evidence", use_container_width=True):
        with st.spinner("Refreshing sold comparable evidence..."):
            st.session_state["comparable_refresh_summary"] = refresh_due_comparables(db, max_properties=35)
        st.rerun()
with head3:
    if st.button("Refresh planning + legal", use_container_width=True):
        with st.spinner("Refreshing official planning checks and public legal-pack intelligence..."):
            st.session_state["diligence_refresh_summary"] = refresh_due_diligence(db, max_planning=35, max_legal=20)
        st.rerun()
with head4:
    if st.button("Clear filters", use_container_width=True):
        for key in [
            "status_filter", "house_filter", "area_filter", "type_filter", "max_price",
            "min_score", "max_motorway", "search", "recommendation_filter"
        ]:
            st.session_state.pop(key, None)
        st.rerun()
with head5:
    runs = db.latest_runs()
    if runs:
        last = runs[0]
        st.caption(
            f"Latest source check: {last.get('completed_at') or last.get('started_at')} - "
            f"{last.get('source')} - {last.get('status')}"
        )
    else:
        st.info("No data has been pulled yet. Click Refresh live data.")

if st.session_state.get("refresh_summary"):
    refresh = st.session_state["refresh_summary"]
    summary = refresh.get("sources", []) if isinstance(refresh, dict) else refresh
    geo = refresh.get("geography", {}) if isinstance(refresh, dict) else {}
    comps_refresh = refresh.get("comparables", {}) if isinstance(refresh, dict) else {}
    diligence_refresh = refresh.get("diligence", {}) if isinstance(refresh, dict) else {}
    ok = sum(x["status"] == "ok" for x in summary)
    found = sum(x.get("found", 0) for x in summary)
    changed = sum(x.get("changed", 0) for x in summary)
    detail_enriched = sum(x.get("detail_enriched", 0) for x in summary)
    st.success(
        f"Refresh finished: {ok}/{len(summary) or 4} sources responded - {found} North West rows found - "
        f"{changed} new/changed records - {detail_enriched} detail pages enriched."
    )
    if geo:
        st.caption(
            f"Location enrichment: {geo.get('postcodes_newly_geocoded', 0)} new postcodes geocoded - "
            f"{geo.get('motorway_enriched', 0)} junction distances added - "
            f"{geo.get('road_routed', 0)} road-routed / {geo.get('straight_line_fallbacks', 0)} straight-line fallbacks."
        )
    if comps_refresh:
        st.caption(
            f"Comparable enrichment: {comps_refresh.get('ok', 0)}/{comps_refresh.get('attempted', 0)} priority properties refreshed "
            f"({comps_refresh.get('due', 0)} stale/due before this pass)."
        )
    if diligence_refresh:
        st.caption(
            f"Due diligence: planning {diligence_refresh.get('planning_ok', 0)}/{diligence_refresh.get('planning_attempted', 0)} · "
            f"legal {diligence_refresh.get('legal_ok', 0)}/{diligence_refresh.get('legal_attempted', 0)} refreshed."
        )
    errors = [x for x in summary if x["status"] != "ok"]
    geo_errors = geo.get("errors", []) if geo else []
    diligence_errors = (diligence_refresh.get("planning_errors", []) + diligence_refresh.get("legal_errors", [])) if diligence_refresh else []
    if errors or geo_errors or diligence_errors:
        with st.expander("Refresh warnings / source errors"):
            for item in errors:
                st.write(f"**{item['source']}** - {item.get('error', 'Unknown error')}")
            for error in geo_errors:
                st.write(f"**Geography** - {error}")
            for error in diligence_errors:
                st.write(f"**Planning/legal** - {error}")

if st.session_state.get("diligence_refresh_summary"):
    dd_run = st.session_state["diligence_refresh_summary"]
    st.success(
        f"Due-diligence refresh: planning {dd_run.get('planning_ok', 0)}/{dd_run.get('planning_attempted', 0)} · "
        f"legal {dd_run.get('legal_ok', 0)}/{dd_run.get('legal_attempted', 0)} completed."
    )
    if dd_run.get("planning_errors") or dd_run.get("legal_errors"):
        with st.expander("Planning/legal refresh warnings"):
            for err in (dd_run.get("planning_errors") or []) + (dd_run.get("legal_errors") or []):
                st.write(f"- {err}")

if st.session_state.get("comparable_refresh_summary"):
    comp_run = st.session_state["comparable_refresh_summary"]
    if comp_run.get("errors"):
        st.warning(
            f"Comparable refresh completed: {comp_run.get('ok', 0)}/{comp_run.get('attempted', 0)} succeeded. "
            "Open the warning details if a public data service timed out."
        )
        with st.expander("Comparable refresh warnings"):
            for err in comp_run.get("errors") or []:
                st.write(f"- {err}")
    else:
        st.success(
            f"Comparable refresh completed: {comp_run.get('ok', 0)} properties updated; "
            f"{max(0, comp_run.get('due', 0) - comp_run.get('attempted', 0))} remain queued if the due list exceeded this pass."
        )

st.subheader("Deal strategy")
profile_label = st.segmented_control(
    "Scoring profile",
    options=["Auto by property type", "Commercial acquisition", "Residential flip"],
    default="Auto by property type",
    help="Auto applies the commercial model to commercial/industrial/development/land and the residential model to houses/flats.",
)
profile_map = {
    "Auto by property type": "auto",
    "Commercial acquisition": "commercial",
    "Residential flip": "residential",
}
profile = profile_map.get(profile_label or "Auto by property type", "auto")

with st.expander("Acquisition criteria - tune the sourcing engine"):
    cfg1, cfg2, cfg3, cfg4, cfg5, cfg6 = st.columns(6)
    with cfg1:
        commercial_target_psf = st.number_input("Commercial target GBP/sq ft", min_value=1, value=50, step=5)
    with cfg2:
        commercial_ceiling_psf = st.number_input("Commercial ceiling GBP/sq ft", min_value=1, value=60, step=5)
    with cfg3:
        commercial_min_sqft = st.number_input("Preferred commercial size sq ft", min_value=500, value=9000, step=500)
    with cfg4:
        commercial_max_price = st.number_input("Commercial max guide GBP", min_value=0, value=1_500_000, step=50_000)
    with cfg5:
        preferred_motorway_miles = st.number_input("Preferred motorway miles", min_value=0.5, value=5.0, step=0.5)
    with cfg6:
        residential_target_price = st.number_input("Residential target guide GBP", min_value=0, value=100_000, step=5_000)
    hot_score = st.slider("Hot sourcing score threshold", 1.0, 10.0, 8.0, 0.5)

config = DealConfig(
    commercial_target_psf=int(commercial_target_psf),
    commercial_ceiling_psf=int(max(commercial_target_psf, commercial_ceiling_psf)),
    commercial_min_sqft=int(commercial_min_sqft),
    commercial_max_price=int(commercial_max_price),
    commercial_preferred_motorway_miles=float(preferred_motorway_miles),
    residential_target_price=int(residential_target_price),
    hot_score=float(hot_score),
)

with st.expander("Underwriting defaults - costs, finance and return hurdles"):
    st.caption(
        "These are working assumptions for triage. Property-specific values can be saved on each deal. "
        "Auction/legal-pack figures should replace allowances before bidding."
    )
    u1, u2, u3, u4 = st.columns(4)
    with u1:
        default_auction_fee = st.number_input("Auction/admin allowance GBP", min_value=0, value=1500, step=250)
        default_legal = st.number_input("Legal allowance GBP", min_value=0, value=2000, step=250)
    with u2:
        default_survey = st.number_input("Survey/DD allowance GBP", min_value=0, value=1000, step=250)
        default_buyer_pct = st.number_input("Buyer premium default %", min_value=0.0, value=0.0, step=0.25)
    with u3:
        default_res_margin = st.number_input("Residential target profit margin % of GDV", min_value=0.0, max_value=80.0, value=20.0, step=1.0)
        default_com_margin = st.number_input("Commercial target equity uplift %", min_value=0.0, max_value=80.0, value=20.0, step=1.0)
    with u4:
        default_finance = st.selectbox("Default funding", ["Cash", "Bridge / debt"], index=0)
        default_sdlt_mode = st.selectbox(
            "Default residential SDLT",
            ["Additional dwelling", "Standard residential", "Corporate 17% > GBP500k"],
            index=0,
            help="Select the actual tax treatment for the buyer. Reliefs and special cases are not inferred automatically.",
        )
    if default_finance == "Bridge / debt":
        d1, d2, d3, d4, d5 = st.columns(5)
        with d1:
            default_ltv = st.number_input("Default LTV %", min_value=0.0, max_value=100.0, value=70.0, step=5.0)
        with d2:
            default_interest = st.number_input("Annual interest %", min_value=0.0, value=10.0, step=0.5)
        with d3:
            default_term = st.number_input("Term months", min_value=1, value=6, step=1)
        with d4:
            default_arrangement = st.number_input("Arrangement fee %", min_value=0.0, value=2.0, step=0.25)
        with d5:
            default_valuation = st.number_input("Lender valuation GBP", min_value=0, value=1000, step=250)
    else:
        default_ltv, default_interest, default_term, default_arrangement, default_valuation = 70.0, 10.0, 6, 2.0, 1000

underwriting_defaults = UnderwritingDefaults(
    auction_admin_fee=float(default_auction_fee),
    buyer_premium_pct=float(default_buyer_pct),
    legal_cost=float(default_legal),
    survey_cost=float(default_survey),
    finance_mode=default_finance,
    ltv_pct=float(default_ltv),
    annual_interest_pct=float(default_interest),
    term_months=int(default_term),
    arrangement_fee_pct=float(default_arrangement),
    valuation_fee=float(default_valuation),
    target_residential_profit_margin_pct=float(default_res_margin),
    target_commercial_equity_margin_pct=float(default_com_margin),
    residential_sdlt_mode=default_sdlt_mode,
)

rows = db.list_properties()
history_map = db.history_map() if rows else {}
underwriting_map = db.underwriting_map() if rows else {}
comparable_map = db.comparable_summary_map() if rows else {}
planning_map = db.planning_summary_map() if rows else {}
legal_map = db.legal_summary_map() if rows else {}
for row in rows:
    analysis = score_property(row, history_map.get(row["id"], []), strategy=profile, config=config)
    row.update(analysis)
    comp = comparable_map.get(row["id"], {})
    comp_confidence = int(comp.get("confidence") or 0)
    if comp.get("status") == "error" and comp_confidence:
        comp_confidence = max(0, comp_confidence - 15)
    row.update({
        "comparable_provider": comp.get("provider"),
        "comparable_status": comp.get("status"),
        "comparable_updated_at": comp.get("updated_at"),
        "comparable_valuation_low": comp.get("valuation_low"),
        "comparable_valuation_mid": comp.get("valuation_mid"),
        "comparable_valuation_high": comp.get("valuation_high"),
        "comparable_unit_psf_mid": comp.get("unit_psf_mid"),
        "comparable_count": comp.get("comp_count") or 0,
        "comparable_confidence": comp_confidence,
        "comparable_guide_discount_pct": comp.get("guide_discount_pct"),
        "comparable_methodology": comp.get("methodology"),
        "comparable_warnings": comp.get("warnings") or [],
        "comparable_attribution": comp.get("attribution"),
        "comparable_error": comp.get("error"),
    })
    planning = planning_map.get(row["id"], {})
    legal = legal_map.get(row["id"], {})
    row.update({
        "planning_provider": planning.get("provider"),
        "planning_status": planning.get("status"),
        "planning_updated_at": planning.get("updated_at"),
        "planning_risk_score": float(planning.get("risk_score") or 0),
        "planning_opportunity_score": float(planning.get("opportunity_score") or 0),
        "planning_constraint_count": int(planning.get("constraint_count") or 0),
        "planning_application_count": int(planning.get("application_count") or 0),
        "planning_subject_application_count": int(planning.get("subject_application_count") or 0),
        "planning_warnings": planning.get("warnings") or [],
        "planning_attribution": planning.get("attribution"),
        "planning_error": planning.get("error"),
        "legal_provider": legal.get("provider"),
        "legal_status": legal.get("status"),
        "legal_updated_at": legal.get("updated_at"),
        "legal_risk_score": float(legal.get("risk_score") or 0),
        "legal_document_count": int(legal.get("document_count") or 0),
        "legal_parsed_document_count": int(legal.get("parsed_document_count") or 0),
        "legal_completion_days": legal.get("completion_days"),
        "legal_deposit_pct": legal.get("deposit_pct"),
        "legal_lease_years": legal.get("lease_years"),
        "legal_buyer_fee_detected": legal.get("buyer_fee_detected"),
        "legal_vat_flag": bool(legal.get("vat_flag")),
        "legal_has_addendum": bool(legal.get("has_addendum")),
        "legal_risk_flags": legal.get("risk_flags") or [],
        "legal_warnings": legal.get("warnings") or [],
        "legal_attribution": legal.get("attribution"),
        "legal_error": legal.get("error"),
    })
    uw = underwrite_property(
        row,
        row,
        assumptions=underwriting_map.get(row["id"], {}),
        defaults=underwriting_defaults,
        strategy=profile,
    )
    row.update(uw)


def is_actionable(row):
    return (row.get("status") or "").lower() not in {"sold", "sold prior", "sold after"}


def is_unsold(row):
    return row.get("status") in {"Available post-auction", "No Bids", "Last Bid"}


def is_commercial(row):
    return (row.get("property_type") or "").lower() in {"industrial", "commercial", "mixed use", "development", "land"}


def money(value):
    if value is None or value == "":
        return "-"
    try:
        return f"GBP {float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def pct(value):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


if rows:
    actionable = [r for r in rows if is_actionable(r)]
    pursue = [r for r in actionable if r.get("recommendation") == "PURSUE"]
    watch = [r for r in actionable if r.get("recommendation") == "WATCH"]
    best = [r for r in actionable if r["deal_score"] >= config.hot_score]
    unsold = [r for r in actionable if is_unsold(r)]
    reductions = [r for r in actionable if r.get("price_reduction_events", 0) > 0]
    relisted = [r for r in actionable if r.get("status") == "Relisted"]
    underwritten = [r for r in actionable if r.get("market_value")]
    new_today = []
    today = datetime.now(timezone.utc).date()
    for r in rows:
        try:
            if datetime.fromisoformat(r.get("first_seen", "").replace("Z", "+00:00")).date() == today:
                new_today.append(r)
        except (TypeError, ValueError):
            pass

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("PURSUE now", len(pursue))
    k2.metric("WATCH", len(watch))
    k3.metric("Underwritten", len(underwritten))
    k4.metric("Unsold signals", len(unsold))
    k5, k6, k7, k8 = st.columns(4)
    comp_ready = [r for r in actionable if (r.get("comparable_count") or 0) > 0]
    auto_valued = [r for r in actionable if r.get("auto_comparable_used")]
    k5.metric("Hot sourcing opportunities", len(best))
    k6.metric("Comparable evidence", len(comp_ready))
    k7.metric("Auto-valued", len(auto_valued))
    k8.metric("New today", len(new_today))
    dd1, dd2, dd3, dd4 = st.columns(4)
    dd1.metric("Legal packs parsed", len([r for r in actionable if r.get("legal_status") == "parsed"]))
    dd2.metric("Planning checked", len([r for r in actionable if r.get("planning_status") == "ok"]))
    dd3.metric("High legal risk", len([r for r in actionable if (r.get("legal_risk_score") or 0) >= 6]))
    dd4.metric("Planning upside", len([r for r in actionable if (r.get("planning_opportunity_score") or 0) >= 3]))
    st.caption(f"Guide reductions: {len(reductions)} · Relisted: {len(relisted)}")

    st.subheader("Filters")
    f1, f2, f3, f4 = st.columns(4)
    f5, f6, f7, f8 = st.columns(4)
    statuses = sorted({r.get("status") or "Unknown" for r in rows})
    houses = sorted({r.get("source") or "Unknown" for r in rows})
    areas = sorted({r.get("area") or "North West" for r in rows})
    types = sorted({r.get("property_type") or "Other" for r in rows})
    recommendations = sorted({r.get("recommendation") or "WATCH" for r in rows})
    with f1:
        recommendation_filter = st.multiselect("Decision", recommendations, key="recommendation_filter")
    with f2:
        status = st.multiselect("Status", statuses, key="status_filter")
    with f3:
        house = st.multiselect("Auction house", houses, key="house_filter")
    with f4:
        area = st.multiselect("Area", areas, key="area_filter")
    with f5:
        typ = st.multiselect("Property type", types, key="type_filter")
    with f6:
        maxp = st.number_input("Max guide GBP", min_value=0, value=0, step=25_000, key="max_price", help="0 = no maximum")
    with f7:
        max_motorway = st.number_input("Max motorway miles", min_value=0.0, value=0.0, step=1.0, key="max_motorway", help="0 = no maximum")
    with f8:
        min_score = st.slider("Minimum sourcing score", 0.0, 10.0, 0.0, 0.5, key="min_score")
    search = st.text_input("Search address / postcode / keyword", key="search")

    shown = []
    for r in rows:
        if recommendation_filter and r.get("recommendation") not in recommendation_filter:
            continue
        if status and r.get("status") not in status:
            continue
        if house and r.get("source") not in house:
            continue
        if area and r.get("area") not in area:
            continue
        if typ and r.get("property_type") not in typ:
            continue
        if maxp and (r.get("guide_price") or 0) > maxp:
            continue
        if max_motorway:
            miles = r.get("motorway_distance_miles")
            if miles is None or miles > max_motorway:
                continue
        if r.get("deal_score", 0) < min_score:
            continue
        if search and search.lower() not in (
            f"{r.get('title', '')} {r.get('address', '')} {r.get('postcode', '')} {r.get('raw_text', '')}"
        ).lower():
            continue
        shown.append(r)

    tabs = st.tabs([
        "PURSUE now",
        "WATCH / needs underwriting",
        "Best sourcing opportunities",
        "Unsold now",
        "Reductions and relists",
        "Commercial",
        "Residential",
        "All tracked",
        "Source health",
    ])

    def table(data):
        data = sorted(
            data,
            key=lambda x: (
                {"PURSUE": 0, "WATCH": 1, "PASS": 2}.get(x.get("recommendation"), 3),
                -x.get("overall_opportunity_score", 0),
                -x.get("motivation_score", 0),
                -x.get("deal_score", 0),
                x.get("guide_price") or 10**12,
            ),
        )
        frame = pd.DataFrame([
            {
                "Decision": r.get("recommendation"),
                "Overall": r.get("overall_opportunity_score"),
                "Sourcing": r.get("deal_score"),
                "Motivation": r.get("motivation_score"),
                "Risk": r.get("risk_score"),
                "Legal risk": r.get("legal_risk_score"),
                "Planning risk": r.get("planning_risk_score"),
                "Planning upside": r.get("planning_opportunity_score"),
                "Legal status": r.get("legal_status"),
                "Legal docs parsed": r.get("legal_parsed_document_count"),
                "Planning apps": r.get("planning_application_count"),
                "UW conf %": r.get("underwriting_confidence"),
                "Status": r.get("status"),
                "Auction house": r.get("source"),
                "Address / listing": r.get("address") or r.get("title"),
                "Postcode": r.get("postcode"),
                "Type": r.get("property_type"),
                "Guide": r.get("guide_price"),
                "Opening offer": r.get("opening_offer"),
                "Maximum bid": r.get("max_bid"),
                "Market value / GDV": r.get("market_value"),
                "Comp range low": r.get("comparable_valuation_low"),
                "Comp midpoint": r.get("comparable_valuation_mid"),
                "Comp range high": r.get("comparable_valuation_high"),
                "Comp conf %": r.get("comparable_confidence"),
                "Comp count": r.get("comparable_count"),
                "Guide discount to comp %": r.get("comparable_guide_discount_pct"),
                "Comp source": r.get("comparable_provider"),
                "Auto comp used": bool(r.get("auto_comparable_used")),
                "All-in @ working price": r.get("all_in_cost"),
                "Profit / equity spread": r.get("profit"),
                "ROI %": r.get("roi_pct"),
                "Gross yield %": r.get("gross_yield_pct"),
                "Guide reduction %": r.get("price_reduction_pct"),
                "Failures": r.get("failure_count"),
                "Size sq ft": r.get("size_sqft"),
                "GBP/sq ft": r.get("price_per_sqft"),
                "Nearest junction": r.get("nearest_junction"),
                "Motorway miles": r.get("motorway_distance_miles"),
                "Auction date": r.get("auction_date"),
                "Source": r.get("url"),
            }
            for r in data
        ])
        if frame.empty:
            st.info("No properties match this view and the current filters.")
            return
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Overall": st.column_config.NumberColumn(format="%.1f / 10"),
                "Sourcing": st.column_config.NumberColumn(format="%.1f / 10"),
                "Motivation": st.column_config.NumberColumn(format="%.1f / 10"),
                "Risk": st.column_config.NumberColumn(format="%.1f / 10"),
                "Legal risk": st.column_config.NumberColumn(format="%.1f / 10"),
                "Planning risk": st.column_config.NumberColumn(format="%.1f / 10"),
                "Planning upside": st.column_config.NumberColumn(format="%.1f / 10"),
                "Guide": st.column_config.NumberColumn(format="GBP %d"),
                "Opening offer": st.column_config.NumberColumn(format="GBP %d"),
                "Maximum bid": st.column_config.NumberColumn(format="GBP %d"),
                "Market value / GDV": st.column_config.NumberColumn(format="GBP %d"),
                "Comp range low": st.column_config.NumberColumn(format="GBP %d"),
                "Comp midpoint": st.column_config.NumberColumn(format="GBP %d"),
                "Comp range high": st.column_config.NumberColumn(format="GBP %d"),
                "Comp conf %": st.column_config.NumberColumn(format="%d%%"),
                "Guide discount to comp %": st.column_config.NumberColumn(format="%.1f%%"),
                "All-in @ working price": st.column_config.NumberColumn(format="GBP %d"),
                "Profit / equity spread": st.column_config.NumberColumn(format="GBP %d"),
                "ROI %": st.column_config.NumberColumn(format="%.1f%%"),
                "Gross yield %": st.column_config.NumberColumn(format="%.1f%%"),
                "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"),
                "Size sq ft": st.column_config.NumberColumn(format="%d"),
                "GBP/sq ft": st.column_config.NumberColumn(format="GBP %.2f"),
                "Motorway miles": st.column_config.NumberColumn(format="%.1f mi"),
                "Source": st.column_config.LinkColumn("Source"),
            },
        )

    with tabs[0]:
        table([r for r in shown if is_actionable(r) and r.get("recommendation") == "PURSUE"])
    with tabs[1]:
        table([r for r in shown if is_actionable(r) and r.get("recommendation") == "WATCH"])
    with tabs[2]:
        table([r for r in shown if is_actionable(r) and r["deal_score"] >= config.hot_score])
    with tabs[3]:
        table([r for r in shown if is_actionable(r) and is_unsold(r)])
    with tabs[4]:
        table([
            r for r in shown if is_actionable(r)
            and (r.get("price_reduction_events", 0) > 0 or r.get("status") == "Relisted")
        ])
    with tabs[5]:
        table([r for r in shown if is_actionable(r) and is_commercial(r)])
    with tabs[6]:
        table([r for r in shown if is_actionable(r) and not is_commercial(r)])
    with tabs[7]:
        table(shown)
    with tabs[8]:
        st.dataframe(pd.DataFrame(db.latest_runs()), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Deal underwriting")
    choices = {
        f"{r.get('recommendation')} | {r.get('overall_opportunity_score', 0):.1f}/10 | {r.get('source')} | {r.get('postcode')} | {(r.get('address') or r.get('title', ''))[:80]}": r
        for r in sorted(
            shown,
            key=lambda x: (
                {"PURSUE": 0, "WATCH": 1, "PASS": 2}.get(x.get("recommendation"), 3),
                -x.get("overall_opportunity_score", 0),
            ),
        )
    }
    if choices:
        label = st.selectbox("Select a tracked property", list(choices), key="deal_selector")
        chosen = choices[label]

        decision_col, score_col, motiv_col, max_col, guide_col, value_col = st.columns(6)
        decision_col.metric("Decision", chosen.get("recommendation") or "WATCH")
        score_col.metric("Overall", f"{chosen.get('overall_opportunity_score', 0):.1f}/10")
        motiv_col.metric("Vendor motivation", f"{chosen.get('motivation_score', 0):.1f}/10")
        max_col.metric("Maximum bid", money(chosen.get("max_bid")))
        guide_col.metric("Guide", money(chosen.get("guide_price")))
        value_col.metric("Market value / GDV", money(chosen.get("market_value")))

        if chosen.get("recommended_action"):
            if chosen.get("recommendation") == "PURSUE":
                st.success(chosen["recommended_action"])
            elif chosen.get("recommendation") == "PASS":
                st.error(chosen["recommended_action"])
            else:
                st.warning(chosen["recommended_action"])

        summary1, summary2, summary3, summary4, summary5 = st.columns(5)
        summary1.metric("Working purchase", money(chosen.get("working_purchase_price")))
        summary2.metric("All-in cost", money(chosen.get("all_in_cost")))
        summary3.metric("Profit / equity spread", money(chosen.get("profit")))
        summary4.metric("ROI / equity uplift", pct(chosen.get("roi_pct")))
        summary5.metric("UW confidence", f"{chosen.get('underwriting_confidence', 0)}%")

        st.markdown("### Comparable evidence")
        comp_action, comp_note = st.columns([1.25, 3.75])
        with comp_action:
            if st.button("Refresh this deal's comparables", key=f"refresh_comp_{chosen['id']}", use_container_width=True):
                with st.spinner("Refreshing sold comparable evidence for this property..."):
                    result = refresh_property_comparables(db, chosen)
                if result.get("status") == "error":
                    st.session_state["single_comp_error"] = result.get("error")
                else:
                    st.session_state.pop("single_comp_error", None)
                st.rerun()
        with comp_note:
            if chosen.get("comparable_updated_at"):
                st.caption(
                    f"Provider: {chosen.get('comparable_provider') or '-'} · Last refreshed: {chosen.get('comparable_updated_at')} · "
                    f"Method: {chosen.get('comparable_methodology') or '-'}"
                )
            else:
                st.caption("No comparable evidence has been stored for this deal yet. Refresh this deal or use the global comparable refresh button.")

        if chosen.get("comparable_count"):
            cv1, cv2, cv3, cv4, cv5 = st.columns(5)
            cv1.metric("Comparable low", money(chosen.get("comparable_valuation_low")))
            cv2.metric("Comparable midpoint", money(chosen.get("comparable_valuation_mid")))
            cv3.metric("Comparable high", money(chosen.get("comparable_valuation_high")))
            cv4.metric("Evidence confidence", f"{chosen.get('comparable_confidence', 0)}%")
            cv5.metric("Usable comps", int(chosen.get("comparable_count") or 0))
            if chosen.get("comparable_guide_discount_pct") is not None:
                discount = float(chosen.get("comparable_guide_discount_pct") or 0)
                message = f"Guide is {abs(discount):.1f}% {'below' if discount >= 0 else 'above'} the automated comparable midpoint."
                (st.success if discount >= 15 else st.info)(message)
            comp_rows = db.comparables_for(chosen["id"])
            if comp_rows:
                comp_frame = pd.DataFrame([{
                    "Address": c.get("address"),
                    "Postcode": c.get("postcode"),
                    "Sold price": c.get("sale_price"),
                    "Sold date": c.get("sale_date"),
                    "Type": c.get("property_type"),
                    "Tenure": c.get("tenure"),
                    "Distance miles": c.get("distance_miles"),
                    "Size sq ft": c.get("size_sqft"),
                    "Sold GBP/sq ft": c.get("price_per_sqft"),
                    "Match %": c.get("match_score"),
                    "Prior sale of subject": bool(c.get("same_property")),
                    "Source": c.get("source_ref"),
                } for c in comp_rows])
                st.dataframe(
                    comp_frame, use_container_width=True, hide_index=True,
                    column_config={
                        "Sold price": st.column_config.NumberColumn(format="GBP %d"),
                        "Distance miles": st.column_config.NumberColumn(format="%.2f mi"),
                        "Size sq ft": st.column_config.NumberColumn(format="%d"),
                        "Sold GBP/sq ft": st.column_config.NumberColumn(format="GBP %.2f"),
                        "Match %": st.column_config.NumberColumn(format="%.0f%%"),
                        "Source": st.column_config.LinkColumn("Source / record"),
                    },
                )
            for warning in chosen.get("comparable_warnings") or []:
                st.caption(f"Evidence note: {warning}")
            if chosen.get("comparable_attribution"):
                st.caption(chosen.get("comparable_attribution"))
        elif chosen.get("comparable_status") == "error":
            st.warning(f"Comparable refresh error: {chosen.get('comparable_error') or 'Unknown public-data error'}")
        else:
            st.info("Comparable evidence not available yet for this deal. The underwriting engine will remain conservative until evidence is refreshed or a manual valuation is entered.")

        st.markdown("### Planning + legal due diligence")
        dd_a, dd_b, dd_c, dd_d = st.columns(4)
        dd_a.metric("Legal-pack risk", f"{chosen.get('legal_risk_score', 0):.1f}/10")
        dd_b.metric("Planning risk", f"{chosen.get('planning_risk_score', 0):.1f}/10")
        dd_c.metric("Planning upside", f"{chosen.get('planning_opportunity_score', 0):.1f}/10")
        dd_d.metric("Legal docs parsed", f"{chosen.get('legal_parsed_document_count', 0)}/{chosen.get('legal_document_count', 0)}")

        dda, ddb = st.columns(2)
        with dda:
            if st.button("Refresh planning for this deal", key=f"refresh_planning_{chosen['id']}", use_container_width=True):
                with st.spinner("Checking official Planning Data constraints and nearby applications..."):
                    try:
                        refresh_property_planning(db, chosen)
                        st.session_state.pop("single_planning_error", None)
                    except Exception as exc:
                        st.session_state["single_planning_error"] = str(exc)
                st.rerun()
        with ddb:
            if st.button("Refresh public legal pack", key=f"refresh_legal_{chosen['id']}", use_container_width=True):
                with st.spinner("Discovering public legal-pack/addendum links and parsing accessible documents..."):
                    try:
                        refresh_property_legal(db, chosen)
                        st.session_state.pop("single_legal_error", None)
                    except Exception as exc:
                        st.session_state["single_legal_error"] = str(exc)
                st.rerun()

        if st.session_state.get("single_planning_error"):
            st.warning(f"Planning refresh error: {st.session_state['single_planning_error']}")
        if st.session_state.get("single_legal_error"):
            st.warning(f"Legal-pack refresh error: {st.session_state['single_legal_error']}")

        planning_items = db.planning_items_for(chosen["id"])
        constraints = [x for x in planning_items if x.get("kind") == "constraint"]
        applications = [x for x in planning_items if x.get("kind") == "application"]
        legal_docs = db.legal_documents_for(chosen["id"])

        plan_tab, legal_tab = st.tabs(["Planning intelligence", "Legal-pack intelligence"] )
        with plan_tab:
            if chosen.get("planning_updated_at"):
                st.caption(
                    f"Official Planning Data screen last refreshed {chosen.get('planning_updated_at')} · "
                    f"{chosen.get('planning_constraint_count', 0)} point constraints · "
                    f"{chosen.get('planning_application_count', 0)} nearby applications · "
                    f"{chosen.get('planning_subject_application_count', 0)} likely subject-property matches."
                )
            if constraints:
                st.markdown("**Constraints / designations affecting the geocoded point**")
                pframe = pd.DataFrame([{
                    "Constraint": x.get("label"),
                    "Severity": x.get("severity"),
                    "Reference": x.get("reference"),
                    "Source": x.get("source_url"),
                } for x in constraints])
                st.dataframe(
                    pframe, use_container_width=True, hide_index=True,
                    column_config={
                        "Severity": st.column_config.NumberColumn(format="%d / 5"),
                        "Source": st.column_config.LinkColumn("Official record"),
                    },
                )
            else:
                st.info("No official point constraint was returned by the current Planning Data screen. Coverage varies by authority, so this is not a clean-planning certificate.")
            if applications:
                st.markdown("**Nearby / subject planning applications**")
                aframe = pd.DataFrame([{
                    "Likely subject": bool(x.get("likely_subject")),
                    "Reference": x.get("reference"),
                    "Address": x.get("name"),
                    "Description": (x.get("metadata") or {}).get("description"),
                    "Decision": (x.get("metadata") or {}).get("planning-decision"),
                    "Submitted": (x.get("metadata") or {}).get("start-date"),
                    "Decision date": (x.get("metadata") or {}).get("decision-date"),
                    "Distance miles": x.get("distance_miles"),
                    "Record": x.get("source_url"),
                } for x in applications])
                st.dataframe(
                    aframe, use_container_width=True, hide_index=True,
                    column_config={
                        "Distance miles": st.column_config.NumberColumn(format="%.2f mi"),
                        "Record": st.column_config.LinkColumn("Planning record"),
                    },
                )
            for warning in chosen.get("planning_warnings") or []:
                st.caption(f"Planning note: {warning}")
            if chosen.get("planning_attribution"):
                st.caption(chosen.get("planning_attribution"))
            if chosen.get("planning_error"):
                st.warning(chosen.get("planning_error"))

        with legal_tab:
            l1, l2, l3, l4, l5 = st.columns(5)
            l1.metric("Pack status", chosen.get("legal_status") or "not checked")
            l2.metric("Completion", f"{chosen.get('legal_completion_days'):g} days" if chosen.get("legal_completion_days") else "-")
            l3.metric("Deposit", f"{chosen.get('legal_deposit_pct'):g}%" if chosen.get("legal_deposit_pct") is not None else "-")
            l4.metric("Lease term found", f"{chosen.get('legal_lease_years'):g} yrs" if chosen.get("legal_lease_years") else "-")
            l5.metric("Buyer fee found", money(chosen.get("legal_buyer_fee_detected")))
            if chosen.get("legal_vat_flag"):
                st.warning("VAT / option-to-tax wording detected. Confirm the actual VAT treatment and cash-flow impact before setting the bid ceiling.")
            if chosen.get("legal_has_addendum"):
                st.warning("An addendum was detected. Re-check the latest version immediately before bidding because it forms part of the auction contract.")
            if chosen.get("legal_risk_flags"):
                st.markdown("**Legal triage flags**")
                for flag in chosen.get("legal_risk_flags") or []:
                    st.write(f"- {flag.get('label')} (severity {flag.get('severity')}/5)")
            if legal_docs:
                lframe = pd.DataFrame([{
                    "Document": d.get("name"),
                    "Type": d.get("doc_type"),
                    "Access / parse": d.get("access_status"),
                    "Source": d.get("url"),
                    "Origin": (d.get("metadata") or {}).get("origin") or "auctioneer/public",
                } for d in legal_docs])
                st.dataframe(
                    lframe, use_container_width=True, hide_index=True,
                    column_config={"Source": st.column_config.LinkColumn("Open document / pack")},
                )
            else:
                st.info("No legal-pack documents have been stored yet. Refresh the public pack or upload the pack you downloaded from the auctioneer.")

            uploads = st.file_uploader(
                "Upload legal pack PDFs or TXT files for local analysis",
                type=["pdf", "txt"], accept_multiple_files=True, key=f"legal_upload_{chosen['id']}",
                help="Useful when the auctioneer requires registration/login before the pack can be downloaded. The app analyses the files locally and stores extracted text, not the original files.",
            )
            if uploads and st.button("Analyse uploaded legal pack", key=f"analyse_upload_{chosen['id']}", type="primary", use_container_width=True):
                parsed = []
                errors = []
                for upload in uploads:
                    try:
                        parsed.append(uploaded_document(upload.name, upload.getvalue()))
                    except Exception as exc:
                        errors.append(f"{upload.name}: {exc}")
                if parsed:
                    save_uploaded_legal_documents(db, chosen, parsed)
                if errors:
                    st.session_state["legal_upload_errors"] = errors
                else:
                    st.session_state.pop("legal_upload_errors", None)
                st.rerun()
            for err in st.session_state.get("legal_upload_errors", []) or []:
                st.warning(err)
            for warning in chosen.get("legal_warnings") or []:
                st.caption(f"Legal note: {warning}")
            if chosen.get("legal_attribution"):
                st.caption(chosen.get("legal_attribution"))
            if chosen.get("legal_error"):
                st.warning(chosen.get("legal_error"))

        saved = db.underwriting_for(chosen["id"])
        inferred_strategy = "commercial" if is_commercial(chosen) else "residential"
        active_strategy = str(saved.get("strategy") or inferred_strategy).lower()
        if active_strategy not in {"commercial", "residential"}:
            active_strategy = inferred_strategy
        saved_auto = saved.get("use_auto_comps")
        default_use_auto = (active_strategy == "residential") if saved_auto is None else bool(saved_auto)

        st.markdown("### Underwriting inputs")
        st.caption(
            "Saved against this property. Blank market-value fields deliberately leave the lot at WATCH rather than inventing a valuation."
        )
        with st.form(f"uw_form_{chosen['id']}"):
            b1, b2, b3 = st.columns(3)
            with b1:
                strategy_input = st.selectbox(
                    "Underwriting strategy",
                    ["commercial", "residential"],
                    index=0 if active_strategy == "commercial" else 1,
                )
                purchase_price = st.number_input(
                    "Working purchase / offer GBP",
                    min_value=0.0,
                    value=float(saved.get("purchase_price") or chosen.get("opening_offer") or chosen.get("guide_price") or 0),
                    step=1000.0,
                )
                use_auto_comps = st.checkbox(
                    "Use automatic comparable valuation",
                    value=default_use_auto,
                    help=(
                        "Residential: high-confidence HM Land Registry sold comparables can seed GDV when no manual GDV is entered. "
                        "Commercial: this is off by default because the automated evidence is auction-sale benchmarking rather than open-market valuation."
                    ),
                )
            with b2:
                auction_admin_fee = st.number_input(
                    "Auction/admin fee GBP", min_value=0.0,
                    value=float(saved.get("auction_admin_fee") if saved.get("auction_admin_fee") is not None else underwriting_defaults.auction_admin_fee),
                    step=250.0,
                )
                buyer_premium_pct = st.number_input(
                    "Buyer premium %", min_value=0.0,
                    value=float(saved.get("buyer_premium_pct") if saved.get("buyer_premium_pct") is not None else underwriting_defaults.buyer_premium_pct),
                    step=0.25,
                )
            with b3:
                legal_cost = st.number_input(
                    "Legal cost GBP", min_value=0.0,
                    value=float(saved.get("legal_cost") if saved.get("legal_cost") is not None else underwriting_defaults.legal_cost),
                    step=250.0,
                )
                survey_cost = st.number_input(
                    "Survey / due diligence GBP", min_value=0.0,
                    value=float(saved.get("survey_cost") if saved.get("survey_cost") is not None else underwriting_defaults.survey_cost),
                    step=250.0,
                )

            if active_strategy == "commercial":
                c1, c2, c3 = st.columns(3)
                with c1:
                    market_psf = st.number_input("Market value GBP/sq ft", min_value=0.0, value=float(saved.get("market_psf") or 0), step=5.0)
                    manual_market_value = st.number_input("Manual market value GBP", min_value=0.0, value=float(saved.get("manual_market_value") or 0), step=10_000.0)
                with c2:
                    erv_annual = st.number_input("ERV / annual rent GBP", min_value=0.0, value=float(saved.get("erv_annual") or 0), step=5_000.0)
                    exit_yield_pct = st.number_input("Exit / capitalisation yield %", min_value=0.0, value=float(saved.get("exit_yield_pct") or 0), step=0.25)
                with c3:
                    capex_cost = st.number_input("Commercial capex GBP", min_value=0.0, value=float(saved.get("capex_cost") or 0), step=5_000.0)
                    target_equity_margin_pct = st.number_input(
                        "Target equity uplift %", min_value=0.0, max_value=80.0,
                        value=float(saved.get("target_equity_margin_pct") if saved.get("target_equity_margin_pct") is not None else underwriting_defaults.target_commercial_equity_margin_pct),
                        step=1.0,
                    )
                gdv = 0.0
                target_profit_margin_pct = underwriting_defaults.target_residential_profit_margin_pct
                residential_sdlt_mode = underwriting_defaults.residential_sdlt_mode
                refurb_cost = st.number_input("Refurb / fit-out GBP", min_value=0.0, value=float(saved.get("refurb_cost") or 0), step=5_000.0)
            else:
                r1, r2, r3 = st.columns(3)
                with r1:
                    gdv = st.number_input("GDV / resale value GBP", min_value=0.0, value=float(saved.get("gdv") or saved.get("manual_market_value") or 0), step=5_000.0)
                    refurb_cost = st.number_input("Refurbishment GBP", min_value=0.0, value=float(saved.get("refurb_cost") or 0), step=2_500.0)
                with r2:
                    target_profit_margin_pct = st.number_input(
                        "Target profit margin % of GDV", min_value=0.0, max_value=80.0,
                        value=float(saved.get("target_profit_margin_pct") if saved.get("target_profit_margin_pct") is not None else underwriting_defaults.target_residential_profit_margin_pct),
                        step=1.0,
                    )
                    residential_sdlt_mode = st.selectbox(
                        "Residential SDLT treatment",
                        ["Additional dwelling", "Standard residential", "Corporate 17% > GBP500k"],
                        index=["Additional dwelling", "Standard residential", "Corporate 17% > GBP500k"].index(
                            saved.get("residential_sdlt_mode") if saved.get("residential_sdlt_mode") in ["Additional dwelling", "Standard residential", "Corporate 17% > GBP500k"] else underwriting_defaults.residential_sdlt_mode
                        ),
                    )
                with r3:
                    st.info("Residential maximum bid is solved backwards from GDV after SDLT, fees, finance, refurbishment and your target profit margin.")
                market_psf = 0.0
                manual_market_value = 0.0
                erv_annual = 0.0
                exit_yield_pct = 0.0
                capex_cost = 0.0
                target_equity_margin_pct = underwriting_defaults.target_commercial_equity_margin_pct

            shared1, shared2, shared3 = st.columns(3)
            with shared1:
                contingency_pct = st.number_input("Works contingency %", min_value=0.0, value=float(saved.get("contingency_pct") if saved.get("contingency_pct") is not None else 10.0), step=1.0)
                purchase_vat_pct = st.number_input(
                    "Purchase VAT % (if applicable)", min_value=0.0, max_value=20.0,
                    value=float(saved.get("purchase_vat_pct") or 0), step=1.0,
                    help="Commercial legal packs may state that VAT is payable. SDLT is then calculated on VAT-inclusive consideration.",
                )
                vat_recoverable = st.checkbox(
                    "Purchase VAT recoverable",
                    value=bool(saved.get("vat_recoverable", False)),
                    help="If selected, VAT is excluded from permanent all-in cost but still increases SDLT consideration.",
                )
            with shared2:
                finance_mode = st.selectbox(
                    "Funding",
                    ["Cash", "Bridge / debt"],
                    index=1 if str(saved.get("finance_mode") or underwriting_defaults.finance_mode).lower() != "cash" else 0,
                )
                ltv_pct = st.number_input("LTV %", min_value=0.0, max_value=100.0, value=float(saved.get("ltv_pct") if saved.get("ltv_pct") is not None else underwriting_defaults.ltv_pct), step=5.0)
                holding_cost_monthly = st.number_input("Holding / rates / utilities per month GBP", min_value=0.0, value=float(saved.get("holding_cost_monthly") or 0), step=250.0)
            with shared3:
                annual_interest_pct = st.number_input("Annual interest %", min_value=0.0, value=float(saved.get("annual_interest_pct") if saved.get("annual_interest_pct") is not None else underwriting_defaults.annual_interest_pct), step=0.5)
                term_months = st.number_input("Hold / finance term months", min_value=1, value=int(saved.get("term_months") or underwriting_defaults.term_months), step=1)
                default_sale_pct = underwriting_defaults.residential_sale_cost_pct if active_strategy == "residential" else 0.0
                sale_cost_pct = st.number_input("Exit / sale agent cost %", min_value=0.0, value=float(saved.get("sale_cost_pct") if saved.get("sale_cost_pct") is not None else default_sale_pct), step=0.25)
                default_exit_legal = underwriting_defaults.residential_exit_legal_cost if active_strategy == "residential" else 0.0
                exit_legal_cost = st.number_input("Exit legal cost GBP", min_value=0.0, value=float(saved.get("exit_legal_cost") if saved.get("exit_legal_cost") is not None else default_exit_legal), step=250.0)

            fin1, fin2, fin3 = st.columns(3)
            with fin1:
                arrangement_fee_pct = st.number_input("Arrangement fee %", min_value=0.0, value=float(saved.get("arrangement_fee_pct") if saved.get("arrangement_fee_pct") is not None else underwriting_defaults.arrangement_fee_pct), step=0.25)
            with fin2:
                exit_fee_pct = st.number_input("Exit fee %", min_value=0.0, value=float(saved.get("exit_fee_pct") if saved.get("exit_fee_pct") is not None else underwriting_defaults.exit_fee_pct), step=0.25)
            with fin3:
                valuation_fee = st.number_input("Lender valuation fee GBP", min_value=0.0, value=float(saved.get("valuation_fee") if saved.get("valuation_fee") is not None else underwriting_defaults.valuation_fee), step=250.0)

            underwriting_notes = st.text_area(
                "Deal notes / evidence",
                value=str(saved.get("underwriting_notes") or ""),
                placeholder="e.g. agent says vendor will consider offers; local agent ERV evidence; works quote; comparable sale reference...",
            )
            save = st.form_submit_button("Save & recalculate underwriting", type="primary", use_container_width=True)
            if save:
                db.save_underwriting(chosen["id"], {
                    "strategy": strategy_input,
                    "purchase_price": purchase_price or None,
                    "market_psf": market_psf or None,
                    "manual_market_value": manual_market_value or None,
                    "gdv": gdv or None,
                    "erv_annual": erv_annual or None,
                    "exit_yield_pct": exit_yield_pct or None,
                    "refurb_cost": refurb_cost or 0,
                    "capex_cost": capex_cost or 0,
                    "contingency_pct": contingency_pct,
                    "auction_admin_fee": auction_admin_fee,
                    "buyer_premium_pct": buyer_premium_pct,
                    "legal_cost": legal_cost,
                    "survey_cost": survey_cost,
                    "purchase_vat_pct": purchase_vat_pct,
                    "vat_recoverable": 1 if vat_recoverable else 0,
                    "holding_cost_monthly": holding_cost_monthly,
                    "sale_cost_pct": sale_cost_pct,
                    "exit_legal_cost": exit_legal_cost,
                    "finance_mode": finance_mode,
                    "ltv_pct": ltv_pct,
                    "annual_interest_pct": annual_interest_pct,
                    "term_months": term_months,
                    "arrangement_fee_pct": arrangement_fee_pct,
                    "exit_fee_pct": exit_fee_pct,
                    "valuation_fee": valuation_fee,
                    "target_profit_margin_pct": target_profit_margin_pct,
                    "target_equity_margin_pct": target_equity_margin_pct,
                    "residential_sdlt_mode": residential_sdlt_mode,
                    "underwriting_notes": underwriting_notes,
                    "use_auto_comps": 1 if use_auto_comps else 0,
                })
                st.rerun()

        st.markdown("### Cost stack at working purchase price")
        cost_frame = pd.DataFrame([
            ["Purchase price", chosen.get("working_purchase_price")],
            ["SDLT", chosen.get("sdlt")],
            ["Auction/admin", chosen.get("auction_admin_fee")],
            ["Buyer premium", chosen.get("buyer_premium")],
            ["Legal", chosen.get("legal_cost")],
            ["Survey / DD", chosen.get("survey_cost")],
            ["Purchase VAT", chosen.get("purchase_vat")],
            ["VAT retained as cost", chosen.get("vat_cash_cost")],
            ["Finance cost", chosen.get("finance_cost")],
            ["Works / capex", chosen.get("works_cost")],
            ["Works contingency", chosen.get("works_contingency")],
            ["Holding / rates / utilities", chosen.get("holding_cost")],
            ["Exit / sale agent", chosen.get("sale_cost")],
            ["Exit legal", chosen.get("exit_legal_cost")],
            ["TOTAL ALL-IN", chosen.get("all_in_cost")],
        ], columns=["Cost", "GBP"])
        st.dataframe(
            cost_frame,
            use_container_width=True,
            hide_index=True,
            column_config={"GBP": st.column_config.NumberColumn(format="GBP %d")},
        )

        left, mid, right = st.columns([1.15, 1, 1])
        with left:
            st.markdown("**Why the sourcing score is strong/weak**")
            for reason in chosen.get("reasons") or []:
                st.write(f"- {reason}")
            st.markdown("**Vendor motivation**")
            st.write(f"**{chosen.get('motivation_label')} - {chosen.get('motivation_score', 0):.1f}/10**")
            for reason in chosen.get("motivation_reasons") or []:
                st.write(f"- {reason}")
        with mid:
            st.markdown("**Underwriting decision**")
            st.write(f"Property / asset quality: **{chosen.get('asset_quality_score', 0):.1f}/10**")
            st.write(f"Financial return: **{chosen.get('financial_score', 0):.1f}/10**")
            st.write(f"Known listing risk: **{chosen.get('risk_score', 0):.1f}/10**")
            st.write(f"Value basis: **{chosen.get('market_value_basis', '-')}**")
            if chosen.get("gross_yield_pct") is not None:
                st.write(f"Gross yield on all-in cost: **{chosen.get('gross_yield_pct'):.1f}%**")
            if chosen.get("max_bid"):
                st.write(f"Maximum bid all-in cost: **{money(chosen.get('max_bid_all_in'))}**")
            for reason in chosen.get("underwriting_reasons") or []:
                st.write(f"- {reason}")
        with right:
            st.markdown("**Risk / evidence flags**")
            if chosen.get("risk_flags"):
                for flag in chosen["risk_flags"]:
                    st.write(f"- {flag['label']} (severity {flag['severity']}/5)")
            else:
                st.write("No specific high-risk wording detected in captured listing text.")
            for warning in (chosen.get("underwriting_warnings") or []) + (chosen.get("warnings") or []):
                st.write(f"- {warning}")
            if chosen.get("url"):
                st.link_button("Open auction listing", chosen["url"], use_container_width=True)

        hist = db.history_for(chosen["id"])
        with st.expander("Price and auction history"):
            if hist:
                st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)
            else:
                st.caption("No change history yet.")

        with st.expander("Reset saved underwriting for this property"):
            st.warning("This removes only your underwriting assumptions. Auction history is retained.")
            if st.button("Clear property underwriting", key=f"clear_uw_{chosen['id']}"):
                db.clear_underwriting(chosen["id"])
                st.rerun()

    st.caption(
        "PURSUE / WATCH / PASS is acquisition triage, not regulated valuation, legal or tax advice. "
        "High-confidence residential sold comparables can seed a desktop GDV; commercial auction benchmarks require explicit opt-in. "
        "Replace automated evidence and allowances with the legal pack, inspection/RICS or local-agent evidence, lender quote and works estimate before bidding."
    )
else:
    st.markdown(
        """
### First refresh
Click **Refresh live data**. The app will pull the public catalogue/results pages from all four auction houses,
keep North West England lots, enrich detail pages and start a local property/status history.

The sourcing engine ranks seller motivation and property characteristics. The underwriting layer then lets you save
property-specific GDV/market value, ERV, works and finance assumptions and calculates acquisition costs, maximum bid
and a **PURSUE / WATCH / PASS** decision.
"""
    )

st.caption(
    "Public-source intelligence only. Auction sites remain the authority for guide price, legal pack and sale status. "
    "No login, bidding or anti-bot bypass is performed by this tool."
)
