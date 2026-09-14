from pathlib import Path
import base64
import html
import os
import re
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

from tracker.db import Database
from tracker.pipeline import refresh_all, refresh_geography
from tracker.deal_engine import DealConfig, score_property, history_metrics
from tracker.underwriting import UnderwritingDefaults, underwrite_property, extract_listing_fees
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
from tracker.legal_access import config_from_mapping as legal_access_from_mapping, provider_access_status, provider_for_lot
from tracker.cloud import SupabaseStorage, config_from_mapping
from tracker.intelligence import build_vendor_story, seller_negotiation_plan, auction_beginner_summary, auction_history_integrity, location_beginner_summary, workspace_beginner_summary, workspace_stage_gate, deal_readiness, next_actions, solicitor_questions, deal_brief_markdown, evidence_confidence_summary, due_diligence_beginner_summary


POUND = "\u00a3"
COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}
SOLD_STATES = {"sold", "sold prior", "sold after"}
UNSOLD_STATES = {"Available post-auction", "No Bids", "Last Bid", "Unsold"}

ASSET_DIR = Path(__file__).with_name("assets")
LOTLY_LOGO = ASSET_DIR / "lotly_logo.png"
LOTLY_ICON = ASSET_DIR / "lotly_icon.png"
HERO_HOUSES = ASSET_DIR / "hero_houses.png"

def _asset_data_uri(path):
    try:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except Exception:
        return ""

LOTLY_ICON_DATA_URI = _asset_data_uri(LOTLY_ICON)
LOTLY_LOGO_DATA_URI = _asset_data_uri(LOTLY_LOGO)
HERO_HOUSES_DATA_URI = _asset_data_uri(HERO_HOUSES)

try:
    APP_VERSION = Path(__file__).with_name("VERSION").read_text().strip() or "dev"
except Exception:
    APP_VERSION = "dev"

st.set_page_config(page_title="Lotly | Property Auction Intelligence", page_icon=str(LOTLY_ICON) if LOTLY_ICON.exists() else "🏷️", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
:root {
  --ink:#0B1F33; --ink2:#18364f; --muted:#667085; --subtle:#98A2B3;
  --line:#E6ECF0; --panel:#FFFFFF; --soft:#F6FAF9; --soft2:#F8FAFC;
  --accent:#0F8F83; --accent-dark:#0A7068; --accent-soft:#E9F8F5; --mint:#2DD4BF;
  --good:#147D5B; --warn:#9A6700; --risk:#B42318;
  --shadow:0 10px 30px rgba(11,31,51,.07); --shadow-sm:0 3px 12px rgba(11,31,51,.055);
}
html, body, [class*="css"] {font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
.stApp {background:linear-gradient(180deg,#FCFEFE 0%,#F7FAFA 54%,#F8FAFC 100%); color:var(--ink);}
.block-container {padding-top:4.15rem; padding-bottom:4rem; max-width:1540px;}
[data-testid="stSidebar"] {background:rgba(250,253,252,.96); border-right:1px solid var(--line); min-width:232px; max-width:232px;}
[data-testid="stSidebar"] .block-container {padding-top:1.15rem; padding-left:.85rem; padding-right:.85rem;}
[data-testid="stHeader"] {background:rgba(252,254,254,.80); backdrop-filter:blur(12px);}
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}

/* Navigation */
.sidebar-brand-hero {
  position:relative;overflow:hidden;min-height:142px;
  margin:-1.15rem -.85rem 14px;padding:20px 16px 17px;
  background:linear-gradient(138deg,#082E35 0%,#086B65 48%,#12A895 100%);
  border-bottom-right-radius:24px;box-shadow:0 12px 30px rgba(5,55,58,.18);
}
.sidebar-brand-hero:before {
  content:"";position:absolute;inset:0;opacity:.92;background-size:cover;background-position:center bottom;background-repeat:no-repeat;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 160'%3E%3Cg fill='%23FFFFFF' fill-opacity='.075'%3E%3Cpath d='M-12 137V83l38-28 34 24V55l29-22 34 26v26l38-30 45 34v-17l29-21 31 23v63z'/%3E%3Cpath d='M18 137V94h20v43zm56 0V75h22v62zm53 0V99h19v38zm55 0V89h22v48zm56 0V86h20v51z' fill-opacity='.055'/%3E%3C/g%3E%3Cg fill='none' stroke='%23FFFFFF' stroke-opacity='.10' stroke-width='2'%3E%3Cpath d='M-5 87l31-23 34 24 29-22 34 26 38-29 45 34 29-21 36 27'/%3E%3Cpath d='M9 108h38M70 91h40M126 108h39M181 103h42M235 100h37'/%3E%3C/g%3E%3C/svg%3E");
}
.sidebar-brand-hero:after {content:"";position:absolute;right:-46px;top:-54px;width:180px;height:180px;border-radius:50%;background:radial-gradient(circle,rgba(120,255,224,.24),rgba(120,255,224,0) 70%);}
.sidebar-brand-content {position:relative;z-index:2;display:flex;align-items:center;gap:11px;}
.sidebar-brand-mark {width:50px;height:50px;display:flex;align-items:center;justify-content:center;border-radius:15px;background:rgba(255,255,255,.96);box-shadow:0 8px 22px rgba(4,37,42,.20);border:1px solid rgba(255,255,255,.58);flex:0 0 auto;}
.sidebar-brand-mark img {width:43px;height:43px;object-fit:contain;}
.sidebar-brand-name {font-size:1.34rem;font-weight:880;letter-spacing:-.045em;color:#FFFFFF;line-height:1;}
.sidebar-brand-sub {font-size:.64rem;color:rgba(255,255,255,.78);margin-top:5px;line-height:1.25;font-weight:650;}
.sidebar-brand-line {position:relative;z-index:2;width:36px;height:2px;border-radius:99px;background:rgba(153,255,229,.75);margin:14px 0 8px;}
.sidebar-brand-tag {position:relative;z-index:2;font-size:.61rem;line-height:1.35;color:rgba(255,255,255,.72);max-width:170px;}
.side-brand {display:flex;align-items:center;gap:10px;padding:4px 2px 14px;}
.side-brand-name {font-size:1.15rem;font-weight:850;letter-spacing:-.035em;color:var(--ink);line-height:1;}
.side-brand-sub {font-size:.68rem;color:var(--muted);margin-top:3px;}
.side-section {font-size:.64rem;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:#98A2B3;margin:16px 2px 6px;}
[data-testid="stSidebar"] div[role="radiogroup"] {gap:4px;}
[data-testid="stSidebar"] div[role="radiogroup"] label {background:transparent;border-radius:10px;padding:7px 8px;transition:.16s ease;}
[data-testid="stSidebar"] div[role="radiogroup"] label:hover {background:#EEF7F5;}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {background:#E7F6F3;color:#08786F;font-weight:760;}

/* Hero */
.lotly-header {display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding:3px 0 6px;}
.lotly-kicker {font-size:.69rem;font-weight:820;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin-bottom:4px;}
.lotly-title {font-size:2.02rem;font-weight:860;letter-spacing:-.045em;line-height:1.04;color:var(--ink);margin:0 0 5px;}
.lotly-subtitle {font-size:.92rem;color:var(--muted);max-width:780px;line-height:1.45;}
.live-pill {display:inline-flex;align-items:center;gap:7px;background:#F0FBF8;color:#176B58;border:1px solid #C7EBDD;border-radius:999px;padding:5px 9px;font-size:.72rem;font-weight:720;}
.live-dot {width:7px;height:7px;border-radius:999px;background:#19A974;box-shadow:0 0 0 4px rgba(25,169,116,.10);}

/* Cards / surfaces */
[data-testid="stMetric"] {background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:12px 14px;box-shadow:0 1px 2px rgba(16,24,40,.025);}
[data-testid="stMetricLabel"] {font-size:.72rem;color:var(--muted);}
[data-testid="stMetricValue"] {font-size:1.32rem;font-weight:800;color:var(--ink);letter-spacing:-.02em;}
[data-testid="stExpander"] {border-color:var(--line)!important;border-radius:13px!important;background:#fff;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius:18px!important;transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {box-shadow:var(--shadow-sm);border-color:#D8E3E7!important;}
[data-testid="stImage"] img {border-radius:14px;object-fit:cover;}
div.stButton > button, div.stLinkButton > a {border-radius:10px;min-height:40px;font-weight:700;transition:.15s ease;}
div.stButton > button[kind="primary"] {background:linear-gradient(135deg,var(--accent),var(--accent-dark))!important;border-color:var(--accent-dark)!important;color:#fff!important;box-shadow:0 7px 18px rgba(15,143,131,.16);}
div.stButton > button[kind="primary"]:hover {transform:translateY(-1px);box-shadow:0 10px 24px rgba(15,143,131,.20);}
[data-baseweb="tab-highlight"] {background-color:var(--accent)!important;}
[data-testid="stSegmentedControl"] button[aria-pressed="true"] {background:#E7F6F3!important;color:#08786F!important;border-color:#A9DED7!important;}

/* Data / badges */
.muted {color:var(--muted);font-size:.86rem;}
.eyebrow {font-size:.67rem;font-weight:820;letter-spacing:.10em;text-transform:uppercase;color:#8490A3;margin-bottom:4px;}
.badge {display:inline-flex;align-items:center;padding:4px 8px;margin:2px 4px 2px 0;border-radius:999px;font-size:.70rem;font-weight:720;border:1px solid #D8DEE6;background:#F8FAFC;color:#344054;}
.badge-hot {background:#FFF8E8;border-color:#F3D48D;color:#865B00;}
.badge-risk {background:#FFF1F0;border-color:#F4B5B0;color:#A32018;}
.badge-good {background:#ECFDF3;border-color:#A8E1BC;color:#166534;}
.badge-info {background:#EEF6FF;border-color:#BED4F7;color:#28569C;}
.property-title {font-size:1.04rem;font-weight:800;line-height:1.28;margin:3px 0 6px;color:var(--ink);letter-spacing:-.015em;}
.card-sub {color:var(--muted);font-size:.74rem;margin-bottom:4px;}
.deal-score {font-size:1.8rem;font-weight:880;line-height:1;color:var(--ink);letter-spacing:-.04em;}
.deal-score-label {font-size:.64rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-weight:760;}
.score-caption {font-size:.72rem;font-weight:760;margin-top:5px;color:var(--accent-dark);}
.card-reason {font-size:.78rem;color:#475467;background:#F7FAFA;border-left:3px solid #8FD7CC;border-radius:8px;padding:7px 9px;margin-top:7px;}
.soft-panel {background:var(--soft);border:1px solid var(--line);border-radius:15px;padding:14px;}
.decision-banner {border:1px solid #CDE7E2;border-radius:14px;padding:13px 15px;margin:8px 0 12px;background:linear-gradient(135deg,#F0FBF8,#F9FCFB);}

/* Spotlight */
.spotlight-shell {background:linear-gradient(135deg,#F7FCFB 0%,#FFFFFF 60%);border:1px solid #DDEAE7;border-radius:20px;padding:16px;box-shadow:var(--shadow-sm);margin:6px 0 14px;}
.spotlight-kicker {font-size:.65rem;text-transform:uppercase;letter-spacing:.11em;font-weight:850;color:var(--accent);}
.spotlight-title {font-size:1.45rem;font-weight:850;line-height:1.2;letter-spacing:-.025em;color:var(--ink);margin:4px 0 5px;}
.lotly-score-pill {display:inline-flex;flex-direction:column;align-items:center;justify-content:center;min-width:88px;background:#0B1F33;color:#fff;border-radius:16px;padding:11px 14px;}
.lotly-score-pill .num {font-size:1.7rem;font-weight:880;line-height:1;}
.lotly-score-pill .lbl {font-size:.58rem;letter-spacing:.08em;text-transform:uppercase;opacity:.75;margin-top:3px;}

/* Compare tray */
.compare-tray {background:#0B1F33;color:#fff;border-radius:14px;padding:10px 14px;margin:8px 0 12px;box-shadow:var(--shadow);}
.compare-tray strong {color:#fff;}

/* Deal room */
.deal-room-top {padding-bottom:4px;}
.deal-room-title {font-size:2rem;font-weight:860;line-height:1.08;letter-spacing:-.04em;color:var(--ink);}
.status-chip {display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-size:.72rem;font-weight:760;background:#F2F4F7;color:#344054;border:1px solid #E4E7EC;}
.section-title {font-size:1.28rem;font-weight:820;color:var(--ink);letter-spacing:-.025em;margin:4px 0 8px;}
.section-note {font-size:.80rem;color:var(--muted);}

/* Finished-product shell */
.lotly-hero-shell {position:relative;overflow:hidden;background:linear-gradient(118deg,#FFFFFF 0%,#F7FCFB 58%,#EAF8F5 100%);border:1px solid #E1ECE9;border-radius:22px;padding:20px 22px 18px;margin:-2px 0 14px;box-shadow:0 8px 28px rgba(11,31,51,.045);}
.lotly-hero-shell:after {content:"";position:absolute;right:-80px;top:-110px;width:360px;height:250px;background:radial-gradient(circle,rgba(45,212,191,.18),rgba(45,212,191,0) 67%);pointer-events:none;}
.lotly-hero-shell .lotly-title {font-size:2.18rem;}
.side-card {background:#FFFFFF;border:1px solid #E1E9ED;border-radius:14px;padding:12px 12px;margin:8px 0 10px;box-shadow:0 2px 9px rgba(11,31,51,.035);}
.side-card-title {display:flex;align-items:center;justify-content:space-between;font-size:.66rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:#667085;margin-bottom:9px;}
.side-kv {display:flex;justify-content:space-between;gap:8px;font-size:.72rem;color:#667085;padding:3px 0;}
.side-kv strong {color:#0B1F33;font-weight:790;text-align:right;}
.side-link {font-size:.70rem;color:#0A7068;font-weight:760;margin-top:8px;}
.side-brand-card {background:linear-gradient(145deg,#F2FBF8,#E7F7F3);border:1px solid #D2ECE6;border-radius:15px;padding:14px 12px;margin-top:10px;font-size:.77rem;font-weight:760;line-height:1.35;color:#174B43;}
.sidebar-scope {font-size:.66rem;color:#8490A3;line-height:1.45;margin:3px 2px 10px;}
.kpi-strip {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:4px 0 14px;}
.kpi-card {background:#fff;border:1px solid #E1E9ED;border-radius:16px;padding:13px 15px;box-shadow:0 2px 8px rgba(11,31,51,.03);}
.kpi-label {font-size:.72rem;color:#667085;margin-bottom:3px;}
.kpi-value {font-size:1.55rem;font-weight:860;letter-spacing:-.035em;color:#0B1F33;line-height:1.1;}
.kpi-sub {font-size:.64rem;color:#8490A3;margin-top:4px;}
.criteria-chips {display:flex;gap:7px;flex-wrap:wrap;margin:5px 0 0;}
.criteria-chip {display:inline-flex;align-items:center;background:#F5F9F8;border:1px solid #DDEAE7;border-radius:999px;padding:4px 8px;color:#496577;font-size:.68rem;font-weight:680;}
.confidence-line {display:flex;align-items:center;gap:7px;margin-top:7px;font-size:.72rem;color:#536879;font-weight:680;}
.confidence-dot {display:inline-block;width:8px;height:8px;border-radius:50%;background:#0F8F83;box-shadow:0 0 0 4px rgba(15,143,131,.09);}
.card-timing {font-size:.68rem;color:#7A8898;margin:0 0 4px;}
.card-market-detail {font-size:.70rem;color:#536879;margin-top:5px;font-weight:680;}
.metric-grid-4 {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:9px 0 6px;}
.metric-mini {background:#fff;border:1px solid #E4EBEF;border-radius:13px;padding:9px 10px;min-height:68px;}
.metric-mini .label {font-size:.64rem;color:#7C8999;margin-bottom:3px;}
.metric-mini .value {font-size:1.00rem;font-weight:830;color:#0B1F33;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
@media (max-width: 1100px) {.kpi-strip{grid-template-columns:repeat(2,minmax(0,1fr));}.metric-grid-4{grid-template-columns:repeat(2,minmax(0,1fr));}}

/* Tables */
[data-testid="stDataFrame"] {border-radius:14px;overflow:hidden;}
hr {margin:.9rem 0;border-color:var(--line);}

/* v1.12.1 finished-product polish */
.property-image-shell {position:relative;width:100%;height:242px;border-radius:15px;overflow:hidden;background:linear-gradient(145deg,#EEF8F6,#F5F8FA);border:1px solid #E2ECE9;}
.property-image-shell.featured {height:268px;}
.property-image {width:100%;height:100%;object-fit:cover;display:block;transition:transform .25s ease;}
.property-image-shell:hover .property-image {transform:scale(1.015);}
.property-image-placeholder {height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:9px;color:#667085;background:radial-gradient(circle at 30% 20%,#E1F6F1 0,#F5FAF9 42%,#F8FAFC 100%);}
.property-image-placeholder img {width:48px;height:48px;object-fit:contain;opacity:.88;}
.property-image-placeholder .ph-title {font-weight:760;color:#3E5367;font-size:.82rem;}
.property-image-placeholder .ph-sub {font-size:.70rem;color:#8A96A5;}
.image-ribbon {position:absolute;top:11px;left:11px;z-index:2;background:rgba(11,31,51,.92);color:#fff;border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:5px 9px;font-size:.62rem;font-weight:820;letter-spacing:.07em;text-transform:uppercase;box-shadow:0 4px 14px rgba(11,31,51,.16);}
.lotly-score-mini {display:inline-flex;min-width:58px;flex-direction:column;align-items:center;justify-content:center;background:#0B1F33;color:#fff;border-radius:13px;padding:7px 9px;box-shadow:0 4px 12px rgba(11,31,51,.10);}
.lotly-score-mini .num {font-size:1.18rem;font-weight:880;line-height:1;}
.lotly-score-mini .lbl {font-size:.49rem;letter-spacing:.07em;text-transform:uppercase;opacity:.72;margin-top:3px;}
.upside-line {display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:7px 0 1px;color:#334B60;font-size:.75rem;font-weight:680;}
.upside-chip {background:#F1F8F6;border:1px solid #D5EAE5;color:#24695F;border-radius:999px;padding:4px 8px;}
.badge-more {background:#F2F4F7;border-color:#E4E7EC;color:#667085;}
.since-visit-banner {display:flex;align-items:center;gap:9px;flex-wrap:wrap;background:linear-gradient(135deg,#F0FBF8,#FAFCFC);border:1px solid #D3EDE8;border-radius:13px;padding:9px 12px;margin:1px 0 10px;color:#35566A;font-size:.78rem;}
.since-visit-banner strong {color:#0A7068;}
.since-stat {background:#fff;border:1px solid #DDE9E6;border-radius:999px;padding:4px 8px;font-weight:720;}
.lotly-sticky-anchor {height:0;width:0;overflow:hidden;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-sticky-anchor) {position:sticky;top:3.85rem;z-index:25;background:rgba(252,254,254,.96);backdrop-filter:blur(14px);box-shadow:0 8px 24px rgba(11,31,51,.06);}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-card-marker) {height:100%;}
.lotly-card-marker {height:0;display:block;}
@media (max-width: 900px) {
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-sticky-anchor) {position:relative;top:auto;}
  .property-image-shell,.property-image-shell.featured {height:220px;}
}

/* v1.12.9: deterministic row/card alignment for Discover listings */
div[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .lotly-dashboard-card-marker) {align-items:stretch!important;}
[data-testid="stColumn"]:has(.lotly-dashboard-card-marker) {display:flex!important;flex-direction:column!important;min-width:0!important;}
[data-testid="stColumn"]:has(.lotly-dashboard-card-marker) > div {height:100%!important;width:100%!important;}

/* v1.13.3 Financials + comparable evidence */
.deal-financial-truth {background:#FFF8E8;border:1px solid #F0D9A4;border-radius:12px;padding:10px 12px;margin:9px 0 13px;font-size:.67rem;line-height:1.45;color:#68541C;}
.deal-financial-truth strong {color:#0B1F33;}
.deal-scenario-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:7px 0 12px;}
.deal-scenario-card {background:#fff;border:1px solid #E0E8EB;border-radius:13px;padding:11px 12px;min-height:126px;}
.deal-scenario-card.final {background:#F3FAF8;border-color:#C4E7DE;}
.deal-scenario-card .scenario-name {font-size:.55rem;text-transform:uppercase;letter-spacing:.08em;color:#7A899A;font-weight:850;}
.deal-scenario-card .scenario-price {font-size:1.2rem;font-weight:900;color:#0B1F33;letter-spacing:-.035em;margin:4px 0 8px;}
.deal-scenario-card .scenario-line {display:flex;justify-content:space-between;gap:8px;font-size:.61rem;color:#718195;padding:2px 0;}
.deal-scenario-card .scenario-line strong {color:#17324B;}
.deal-scenario-card .scenario-foot {font-size:.58rem;color:#08786F;margin-top:7px;font-weight:750;}
.deal-comp-verdict {display:grid;grid-template-columns:240px 1fr;gap:14px;align-items:center;border-radius:13px;padding:11px 13px;margin:7px 0 12px;border:1px solid #E0E8EB;background:#fff;}
.deal-comp-verdict.good {background:#F2FAF7;border-color:#C7E8DE}.deal-comp-verdict.warn {background:#FFF9EC;border-color:#F0D89F}.deal-comp-verdict.risk {background:#FFF3F2;border-color:#F3C7C2}
.deal-comp-verdict .verdict-label {font-size:.55rem;text-transform:uppercase;letter-spacing:.08em;color:#7A899A;font-weight:850;}
.deal-comp-verdict .verdict-value {font-size:.96rem;font-weight:900;color:#0B1F33;margin-top:3px;}
.deal-comp-verdict .verdict-copy {font-size:.66rem;line-height:1.42;color:#607489;}
.deal-comp-proof-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:7px 0 10px;}
.deal-comp-proof-card {background:#F9FBFB;border:1px solid #E3E9EB;border-radius:11px;padding:9px 10px;min-height:78px;}
.deal-comp-proof-card .proof-label {font-size:.54rem;color:#7B899A}.deal-comp-proof-card .proof-value {font-size:.90rem;font-weight:870;color:#0B1F33;margin-top:3px}.deal-comp-proof-card .proof-sub {font-size:.56rem;line-height:1.35;color:#8390A0;margin-top:3px;}
@media(max-width:1100px){.deal-scenario-grid,.deal-comp-proof-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-comp-verdict{grid-template-columns:1fr;}}
</style>
""",
    unsafe_allow_html=True,
)

# v1.12.6 — approved Discover design with robust hero rendering. This layer deliberately overrides the
# generic Streamlit shell while leaving the underlying data/decision logic intact.
st.markdown(
    """
<style>
/* App shell */
[data-testid="stHeader"] {display:none!important;}
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {padding-top:0!important;margin-top:0!important;}
.block-container {padding-top:0!important;padding-left:1.7rem!important;padding-right:1.7rem!important;padding-bottom:3rem!important;max-width:none!important;}
[data-testid="stSidebar"] {background:#FBFDFD!important;border-right:1px solid #E3E9ED!important;width:252px!important;min-width:252px!important;max-width:252px!important;}
[data-testid="stSidebarHeader"] {display:none!important;height:0!important;min-height:0!important;}
[data-testid="stSidebarContent"] {padding-top:0!important;margin-top:0!important;}
[data-testid="stSidebar"] .block-container {padding-top:0!important;margin-top:0!important;padding-left:.85rem!important;padding-right:.85rem!important;}

/* Approved simple sidebar brand */
.sidebar-brand-simple {display:flex;align-items:center;gap:12px;padding:18px 10px 15px 10px;margin:0 -2px 4px;}
.sidebar-brand-simple .mark {width:52px;height:52px;flex:0 0 52px;display:flex;align-items:center;justify-content:center;}
.sidebar-brand-simple .mark img {width:50px;height:50px;object-fit:contain;}
.sidebar-brand-simple .name {font-size:1.31rem;font-weight:880;letter-spacing:-.035em;color:#0B1F33;line-height:1.02;}
.sidebar-brand-simple .sub {font-size:.67rem;color:#6B7C90;line-height:1.25;margin-top:5px;}
[data-testid="stSidebar"] div[role="radiogroup"] {gap:3px!important;margin-bottom:18px;}
[data-testid="stSidebar"] div[role="radiogroup"] label {min-height:42px;border-radius:12px!important;padding:9px 11px!important;font-size:.86rem!important;color:#17324B!important;}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {background:linear-gradient(90deg,#E5F7F3,#EAF8F6)!important;color:#0A746C!important;font-weight:780!important;}
.side-card {border-radius:15px!important;padding:13px 13px!important;margin:0 0 14px!important;box-shadow:0 2px 9px rgba(11,31,51,.025)!important;}
.side-card-title {font-size:.64rem!important;color:#5F7086!important;margin-bottom:10px!important;letter-spacing:.09em!important;}
.side-kv {font-size:.72rem!important;padding:4px 0!important;}
.side-link {font-size:.70rem!important;margin-top:9px!important;color:#078B7D!important;}
.side-brand-card {position:relative;overflow:hidden;min-height:118px;background:linear-gradient(145deg,#F2FBF8 0%,#E4F8F2 70%,#CFF3E9 100%)!important;border:1px solid #D5ECE7!important;border-radius:15px!important;padding:18px 15px!important;margin-top:2px!important;font-size:.84rem!important;font-weight:820!important;line-height:1.42!important;color:#0B1F33!important;}
.side-brand-card:after {content:"";position:absolute;right:-35px;bottom:-55px;width:170px;height:120px;border-radius:50%;border:16px solid rgba(63,196,172,.12);box-shadow:0 0 0 14px rgba(63,196,172,.08),0 0 0 28px rgba(63,196,172,.05);}
.side-brand-card .diamond {display:block;font-size:1.12rem;color:#078B7D;margin-bottom:7px;}

/* Top-right account strip */
.lotly-topbar {height:58px;display:flex;align-items:center;justify-content:flex-end;border-bottom:1px solid rgba(230,236,240,.35);margin:-3.35rem -1.7rem 0;padding:0 1.7rem;background:rgba(255,255,255,.78);}
.topbar-actions {display:flex;align-items:center;gap:19px;color:#0B1F33;}
.tb-icon {font-size:1.22rem;line-height:1;color:#0B1F33;}
.tb-bell {position:relative;}
.tb-bell:after {content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:#07967F;right:-3px;top:-4px;border:2px solid #fff;}
.tb-avatar {width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#0B1F33;color:#fff;font-size:.75rem;font-weight:850;}
.tb-person {display:flex;align-items:center;gap:10px;}
.tb-person-copy {line-height:1.14;min-width:92px;}
.tb-person-copy strong {font-size:.80rem;color:#0B1F33;display:block;}
.tb-person-copy span {font-size:.68rem;color:#6B7C90;display:block;margin-top:3px;}
.tb-chevron {font-size:.82rem;color:#0B1F33;}

/* Full-width approved hero with houses + diagonal mint treatment */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-hero-marker) {position:relative!important;overflow:hidden!important;border:0!important;border-radius:0!important;padding:0!important;margin:-1rem 0 10px!important;box-shadow:none!important;background:linear-gradient(90deg,#FFFFFF 0%,#FFFFFF 47%,#F3FCFA 72%,#E8F8F4 100%)!important;min-height:158px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-hero-marker) > div {background:transparent!important;position:relative;z-index:2;}
.lotly-hero-marker {height:0;display:block;}
.hero-house-art {display:none!important;}
.hero-copy {position:relative;z-index:3;padding:11px 8px 12px 7px;min-height:111px;}
.hero-copy .lotly-kicker {font-size:.65rem!important;color:#73859B!important;letter-spacing:.16em!important;margin:0 0 8px!important;}
.hero-copy .lotly-title {font-size:2.30rem!important;line-height:1.02!important;margin:0 0 7px!important;letter-spacing:-.052em!important;}
.hero-copy .lotly-subtitle {font-size:.88rem!important;color:#61748B!important;max-width:650px!important;line-height:1.40!important;}
.hero-right-space {height:20px;}
.hero-updated {text-align:right;font-size:.62rem;font-weight:760;color:#FFFFFF;text-shadow:0 1px 6px rgba(11,31,51,.32);margin-top:5px;padding-right:4px;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-hero-marker) [data-testid="stPopover"] {position:relative;z-index:4;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-hero-marker) [data-testid="stPopover"] button {background:rgba(255,255,255,.96)!important;border:1px solid #D8E1E7!important;border-radius:13px!important;box-shadow:0 5px 16px rgba(11,31,51,.07)!important;color:#0B1F33!important;font-weight:760!important;min-height:44px!important;}

/* KPI row */
.kpi-strip {gap:12px!important;margin:0 0 14px!important;}
.kpi-card {display:flex!important;align-items:center!important;gap:14px!important;border-radius:15px!important;padding:12px 15px!important;min-height:92px!important;background:#fff!important;}
.kpi-icon {width:54px;height:54px;flex:0 0 54px;border-radius:13px;background:#E7F7F3;display:flex;align-items:center;justify-content:center;color:#078B7D;font-size:1.65rem;font-weight:600;}
.kpi-main {min-width:0;}
.kpi-label {font-size:.73rem!important;color:#5F7086!important;margin-bottom:4px!important;white-space:nowrap;}
.kpi-value-line {display:flex;align-items:baseline;gap:10px;}
.kpi-value {font-size:1.62rem!important;line-height:1!important;}
.kpi-trend {font-size:.72rem;color:#078B7D;font-weight:820;white-space:nowrap;}
.kpi-trend.zero {color:#536879;}
.kpi-sub {font-size:.62rem!important;color:#7E8DA0!important;margin-top:4px!important;}

/* Discover filter surface */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-filter-marker) {position:relative!important;top:auto!important;z-index:auto!important;background:#FFFFFF!important;border:1px solid #E0E7EB!important;border-radius:15px!important;box-shadow:none!important;padding:2px 2px 0!important;margin-bottom:7px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-filter-marker) [data-testid="stVerticalBlock"] {gap:.55rem!important;}
.lotly-filter-marker {height:0;display:block;}
.eyebrow {font-size:.64rem!important;letter-spacing:.13em!important;color:#718198!important;margin-bottom:5px!important;}
[data-testid="stSegmentedControl"] button {min-height:36px!important;font-size:.74rem!important;}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] > div > div {min-height:42px!important;border-radius:10px!important;}
.criteria-chips {gap:8px!important;margin:2px 0 0!important;align-items:center;}
.criteria-chip {padding:6px 10px!important;border-radius:10px!important;font-size:.68rem!important;background:#F5F8F9!important;border-color:#E3E9ED!important;color:#355069!important;}
.clear-all {display:block;text-align:right;color:#078B7D;font-size:.70rem;text-decoration:underline;padding-top:8px;font-weight:650;}
.opportunity-toolbar {display:flex;align-items:center;justify-content:space-between;margin:8px 0 8px;}
.opportunity-count {font-size:.82rem;font-weight:790;color:#17324B;}

/* Property cards matching the approved two-column design */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) {position:relative!important;min-height:438px!important;border-radius:15px!important;border:1px solid #DFE7EB!important;box-shadow:0 2px 8px rgba(11,31,51,.025)!important;padding:10px!important;background:#FFFFFF!important;overflow:visible!important;}
.lotly-dashboard-card-marker {height:0;display:block;}
.property-image-shell.dashboard {height:252px!important;border-radius:11px!important;}
.dashboard-kicker {font-size:.58rem;text-transform:uppercase;letter-spacing:.13em;font-weight:850;color:#078B7D;margin:1px 0 5px;min-height:14px;}
.dashboard-kicker.ghost {visibility:hidden;}
.dashboard-header-zone {height:90px!important;min-height:90px!important;max-height:90px!important;overflow:hidden!important;}
.dashboard-header-zone .card-sub {white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;}
.dashboard-header-zone .property-title {display:-webkit-box!important;-webkit-line-clamp:3!important;-webkit-box-orient:vertical!important;overflow:hidden!important;}
.dashboard-badge-zone {height:54px!important;min-height:54px!important;max-height:54px!important;overflow:hidden!important;display:flex;align-content:flex-start;align-items:flex-start;flex-wrap:wrap;}
.dashboard-confidence-zone {height:23px!important;min-height:23px!important;max-height:23px!important;overflow:hidden!important;}
.dashboard-reason-zone {height:56px!important;min-height:56px!important;max-height:56px!important;overflow:hidden!important;}
.dashboard-reason-zone .card-reason {height:46px!important;max-height:46px!important;overflow:hidden!important;display:-webkit-box!important;-webkit-line-clamp:2!important;-webkit-box-orient:vertical!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .property-title {font-size:.93rem!important;line-height:1.25!important;margin:2px 0 5px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .card-sub {font-size:.64rem!important;margin-bottom:4px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .card-timing {font-size:.61rem!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .badge {font-size:.58rem!important;padding:4px 7px!important;margin:2px 3px 2px 0!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .metric-grid-4 {gap:5px!important;margin:7px 0 4px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .metric-mini {min-height:62px!important;padding:7px 7px!important;border-radius:10px!important;display:flex!important;flex-direction:column!important;justify-content:space-between!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .metric-mini .label {font-size:.55rem!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .metric-mini .value {font-size:.84rem!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .confidence-line {font-size:.62rem!important;margin-top:5px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .card-reason {font-size:.59rem!important;line-height:1.35!important;padding:7px 8px!important;margin:6px 0 0!important;background:#EDF8F6!important;border-left:2px solid #4EC3B2!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .lotly-score-mini {min-width:60px!important;padding:7px 8px!important;border-radius:11px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .lotly-score-mini .num {font-size:1.25rem!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) .lotly-score-mini .lbl {font-size:.43rem!important;}
.dashboard-actions {height:0!important;margin:0!important;padding:0!important;}
[class*="st-key-dash_actions_"] {position:static!important;inset:auto!important;z-index:auto!important;margin-top:10px!important;margin-bottom:0!important;}
[class*="st-key-dash_actions_"] [data-testid="stVerticalBlock"] {gap:0!important;}
[class*="st-key-dash_actions_"] [data-testid="stHorizontalBlock"] {gap:.55rem!important;align-items:stretch!important;}
[class*="st-key-dash_actions_"] button {height:38px!important;min-height:38px!important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) button {font-size:.68rem!important;min-height:36px!important;}

/* Make the first screen read like the approved mockup. */
@media (min-width: 1200px) {
  .block-container {padding-left:1.65rem!important;padding-right:1.65rem!important;}
  .property-image-shell.dashboard {height:252px!important;}
}
@media (max-width: 1100px) {
  [data-testid="stSidebar"] {min-width:228px!important;max-width:228px!important;}
  .hero-copy .lotly-title {font-size:2rem!important;}
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-dashboard-card-marker) {height:auto!important;min-height:438px!important;padding:10px!important;}
}
</style>
""",
    unsafe_allow_html=True,
)

# v1.12.7 uses Streamlit's stable container key rather than relying on a :has() DOM selector.
# Streamlit adds the CSS class .st-key-lotly_hero for this container, which makes the hero
# artwork deterministic across Community Cloud rerenders.
st.markdown(
    """
<style>
.st-key-lotly_hero {
  position:relative!important;
  overflow:hidden!important;
  border:0!important;
  border-radius:0!important;
  box-shadow:none!important;
  padding:0!important;
  margin:0 0 10px!important;
  min-height:150px!important;
  background:linear-gradient(90deg,#FFFFFF 0%,#FFFFFF 46%,#F7FCFB 67%,#EAF8F5 100%)!important;
}
.st-key-lotly_hero > div {position:relative!important;z-index:2!important;background:transparent!important;}
.st-key-lotly_hero .hero-copy {padding:10px 8px 10px 7px!important;min-height:105px!important;}
.st-key-lotly_hero .hero-right-space {height:17px!important;}
.st-key-lotly_hero [data-testid="stPopover"] {position:relative!important;z-index:5!important;}
.st-key-lotly_hero [data-testid="stPopover"] button {background:rgba(255,255,255,.97)!important;border:1px solid #D8E1E7!important;border-radius:13px!important;box-shadow:0 5px 16px rgba(11,31,51,.07)!important;color:#0B1F33!important;font-weight:760!important;min-height:44px!important;}
.sidebar-version {font-size:.57rem;color:#93A0AE;text-align:center;letter-spacing:.06em;margin:8px 0 2px;}
/* Slightly tighter approved first-screen rhythm */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.lotly-filter-marker) [data-testid="stVerticalBlock"] {gap:.40rem!important;}
[data-testid="stSegmentedControl"] button {min-height:34px!important;}
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] > div > div {min-height:40px!important;}
</style>
""",
    unsafe_allow_html=True,
)

# The hero artwork is applied to the exact Streamlit container as a CSS background.
# This is more reliable than an absolutely positioned HTML image because Streamlit
# wraps Markdown elements in additional positioned nodes that can collapse image height.
if HERO_HOUSES_DATA_URI:
    st.markdown(
        f"""
<style>
.st-key-lotly_hero {{
  background-image:url('{HERO_HOUSES_DATA_URI}'),linear-gradient(90deg,#FFFFFF 0%,#FFFFFF 46%,#F7FCFB 67%,#EAF8F5 100%)!important;
  background-size:62% auto,100% 100%!important;
  background-position:right center,center center!important;
  background-repeat:no-repeat,no-repeat!important;
}}
</style>
""",
        unsafe_allow_html=True,
    )


# v1.13.2 - Deal Room decision-workspace refinement. Discover remains design-locked; every selector below is Deal Room scoped.
st.markdown(
    """
<style>
/* Deal Room hero */
[class*="st-key-dealroom_hero_"] {
  background:linear-gradient(135deg,#FFFFFF 0%,#F7FCFB 62%,#ECF9F6 100%)!important;
  border:1px solid #DDE9E6!important;border-radius:20px!important;
  box-shadow:0 8px 28px rgba(11,31,51,.045)!important;
  padding:14px!important;margin:2px 0 14px!important;overflow:hidden!important;
}
[class*="st-key-dealroom_hero_"] .property-image-shell.featured {height:300px!important;border-radius:14px!important;}
.deal-breadcrumb {font-size:.66rem;color:#718198;font-weight:720;margin:2px 0 8px;}
.deal-room-kicker {font-size:.62rem;text-transform:uppercase;letter-spacing:.15em;font-weight:850;color:#078B7D;margin:0 0 6px;}
.deal-room-address {font-size:1.72rem;line-height:1.10;font-weight:880;letter-spacing:-.04em;color:#0B1F33;margin:0 0 7px;}
.deal-room-meta {font-size:.72rem;color:#6A7B8F;margin-bottom:7px;}
.deal-score-panel {display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:84px;background:#0B1F33;color:#fff;border-radius:15px;padding:11px 10px;box-shadow:0 7px 18px rgba(11,31,51,.12);}
.deal-score-panel .num {font-size:1.65rem;line-height:1;font-weight:900;letter-spacing:-.04em;}
.deal-score-panel .lbl {font-size:.48rem;text-transform:uppercase;letter-spacing:.08em;opacity:.72;margin-top:4px;}
.deal-metric-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:12px 0 9px;}
.deal-metric-card {background:#fff;border:1px solid #DFE8EB;border-radius:12px;padding:9px 10px;min-height:69px;}
.deal-metric-card .label {font-size:.58rem;color:#7A899A;margin-bottom:4px;}
.deal-metric-card .value {font-size:.96rem;font-weight:850;color:#0B1F33;letter-spacing:-.025em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.deal-metric-card .sub {font-size:.54rem;color:#8490A1;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.deal-decision-panel {display:grid;grid-template-columns:115px 1fr;gap:12px;align-items:center;background:#F3FAF8;border:1px solid #D4ECE6;border-radius:13px;padding:10px 12px;margin:7px 0 8px;}
.deal-decision-word {font-size:.98rem;font-weight:900;letter-spacing:.05em;color:#0A7068;}
.deal-decision-word.pass {color:#B42318}.deal-decision-word.watch {color:#9A6700}
.deal-decision-copy {font-size:.72rem;color:#40566A;line-height:1.38;}
.deal-decision-copy strong {color:#0B1F33;}
.deal-evidence-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:7px 0 2px;}
.deal-evidence-item {display:flex;align-items:center;justify-content:space-between;gap:7px;background:rgba(255,255,255,.78);border:1px solid #E0E9E7;border-radius:10px;padding:7px 8px;font-size:.61rem;color:#667085;}
.deal-evidence-item strong {color:#17324B;font-size:.64rem;white-space:nowrap;}
.deal-evidence-dot {width:7px;height:7px;border-radius:50%;background:#0F8F83;display:inline-block;margin-right:5px;}
.deal-evidence-dot.warn {background:#D39B1E}.deal-evidence-dot.risk {background:#D92D20}
[class*="st-key-dealroom_hero_"] button {min-height:38px!important;font-size:.70rem!important;}

/* Deal Room tab workspace */
[class*="st-key-dealroom_body_"] {margin-top:0!important;}
[class*="st-key-dealroom_body_"] [data-baseweb="tab-list"] {gap:4px;background:#F5F8F8;border:1px solid #E1E8EA;border-radius:12px;padding:4px;margin-bottom:12px;}
[class*="st-key-dealroom_body_"] [data-baseweb="tab"] {height:38px;border-radius:9px;padding:0 12px;font-size:.72rem;font-weight:700;color:#52677A;}
[class*="st-key-dealroom_body_"] [aria-selected="true"] {background:#FFFFFF!important;color:#078B7D!important;box-shadow:0 1px 4px rgba(11,31,51,.07);}
.deal-snapshot-grid {display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:12px;margin:5px 0 13px;}
.deal-snapshot-card {background:#fff;border:1px solid #E0E8EB;border-radius:14px;padding:13px 14px;min-height:190px;}
.deal-snapshot-card h4 {font-size:.82rem;margin:0 0 8px;color:#0B1F33;letter-spacing:-.01em;}
.deal-snapshot-card ul {margin:0;padding-left:17px;color:#52677A;font-size:.72rem;line-height:1.48;}
.deal-snapshot-card li {margin-bottom:4px;}
.deal-next-action {background:linear-gradient(140deg,#F0FAF7,#F8FCFB);border-color:#CFE9E3;}
.deal-next-action .number {width:24px;height:24px;border-radius:50%;background:#078B7D;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:850;margin-right:7px;}
.deal-next-row {font-size:.72rem;color:#40566A;line-height:1.35;margin:7px 0;}
.deal-readiness-card {background:#0B1F33;color:#fff!important;}
.deal-readiness-card h4 {color:#fff!important;}
.deal-readiness-score {font-size:2rem;font-weight:900;letter-spacing:-.05em;line-height:1;color:#fff;}
.deal-readiness-label {font-size:.62rem;text-transform:uppercase;letter-spacing:.09em;color:#9DB0C2;margin-top:4px;}
.deal-progress-track {height:7px;background:rgba(255,255,255,.16);border-radius:999px;margin:12px 0 10px;overflow:hidden;}
.deal-progress-fill {height:100%;background:#31C8B2;border-radius:999px;}
.deal-progress-fill.blocked {background:#D92D20;}
.deal-blocker {font-size:.65rem;line-height:1.4;color:#D8E3EC;margin-top:5px;}
.deal-facts-title {font-size:.83rem;font-weight:820;color:#0B1F33;margin:6px 0 4px;}

/* Deal Room index */
.deal-index-strip {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 14px;}
.deal-index-kpi {background:#fff;border:1px solid #E1E8EB;border-radius:14px;padding:11px 13px;}
.deal-index-kpi .label {font-size:.64rem;color:#728196;}.deal-index-kpi .value {font-size:1.35rem;font-weight:880;color:#0B1F33;margin-top:2px;}
[class*="st-key-deal_index_card_"] {border:1px solid #DFE7EA!important;border-radius:15px!important;padding:11px!important;background:#fff!important;box-shadow:0 2px 8px rgba(11,31,51,.025)!important;}
[class*="st-key-deal_index_card_"] .property-image-shell {height:180px!important;border-radius:11px!important;}
.deal-index-title {font-size:.98rem;font-weight:840;line-height:1.25;color:#0B1F33;margin:4px 0 7px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.deal-index-meta {font-size:.64rem;color:#7A8999;margin-bottom:5px;}
.deal-index-metrics {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:8px 0;}
.deal-index-metric {border:1px solid #E3EAED;border-radius:9px;padding:7px;background:#FBFCFC;}.deal-index-metric span{display:block;font-size:.54rem;color:#8390A0}.deal-index-metric strong{font-size:.76rem;color:#0B1F33;}
.deal-stage-line {font-size:.64rem;color:#5F7184;margin:5px 0 8px;}

@media(max-width:1100px){.deal-metric-grid{grid-template-columns:repeat(3,minmax(0,1fr));}.deal-evidence-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-snapshot-grid{grid-template-columns:1fr;}.deal-index-strip{grid-template-columns:repeat(2,minmax(0,1fr));}}

/* v1.13.2 Deal Room decision-summary components */
.deal-signal-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:5px 0 12px;}
.deal-signal-card {background:#fff;border:1px solid #E0E8EB;border-radius:13px;padding:11px 12px;min-height:86px;}
.deal-signal-card .eyebrow {font-size:.55rem;text-transform:uppercase;letter-spacing:.09em;color:#7C8999;font-weight:800;margin-bottom:5px;}
.deal-signal-card .signal-value {font-size:1.12rem;line-height:1.1;font-weight:900;color:#0B1F33;letter-spacing:-.035em;}
.deal-signal-card .signal-sub {font-size:.60rem;line-height:1.32;color:#718195;margin-top:5px;}
.deal-signal-card.good {border-color:#C8E9DF;background:#F8FCFB;}.deal-signal-card.good .signal-value{color:#08786F;}
.deal-signal-card.warn {border-color:#F1D99E;background:#FFFDF8;}.deal-signal-card.warn .signal-value{color:#8A6200;}
.deal-snapshot-lower {display:grid;grid-template-columns:minmax(0,1.55fr) minmax(250px,.65fr);gap:12px;margin:0 0 12px;}
.deal-risk-register {background:#fff;border:1px solid #E0E8EB;border-radius:14px;padding:13px 14px;}
.deal-risk-register h4 {font-size:.82rem;margin:0 0 9px;color:#0B1F33;}
.deal-risk-row {display:grid;grid-template-columns:78px 135px 1fr;align-items:start;gap:9px;padding:9px 0;border-top:1px solid #EEF2F3;}
.deal-risk-row:first-of-type {border-top:0;padding-top:2px;}
.deal-risk-severity {display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:4px 7px;font-size:.52rem;font-weight:850;text-transform:uppercase;letter-spacing:.05em;width:max-content;}
.deal-risk-severity.critical {background:#FDECEC;color:#B42318;border:1px solid #F6C9C5;}
.deal-risk-severity.review {background:#FFF7E6;color:#946200;border:1px solid #F0D79A;}
.deal-risk-severity.clear {background:#ECF9F3;color:#08786F;border:1px solid #C7E9DC;}
.deal-risk-name {font-size:.66rem;font-weight:830;color:#17324B;line-height:1.35;}
.deal-risk-detail {font-size:.64rem;color:#62758A;line-height:1.38;}
.deal-readiness-compact {min-height:100%!important;padding:14px!important;}
.deal-recommend-banner {background:linear-gradient(135deg,#F0FAF7,#FAFDFC);border:1px solid #CFE9E3;border-radius:14px;padding:12px 14px;margin:0 0 12px;}
.deal-recommend-banner .label {font-size:.55rem;text-transform:uppercase;letter-spacing:.09em;color:#08786F;font-weight:850;margin-bottom:4px;}
.deal-recommend-banner .action {font-size:.88rem;line-height:1.32;font-weight:850;color:#0B1F33;}
.deal-recommend-banner .reason {font-size:.64rem;color:#607489;line-height:1.4;margin-top:4px;}
.deal-maxbid-wrap {background:#fff;border:1px solid #E0E8EB;border-radius:14px;padding:13px 14px;margin:0 0 12px;}
.deal-maxbid-head {display:flex;justify-content:space-between;gap:10px;align-items:end;margin-bottom:9px;}
.deal-maxbid-head h4 {font-size:.82rem;margin:0;color:#0B1F33;}.deal-maxbid-head span{font-size:.58rem;color:#7B8999;}
.deal-maxbid-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;}
.deal-maxbid-step {background:#F8FAFA;border:1px solid #E5EBED;border-radius:10px;padding:8px 9px;min-height:69px;}
.deal-maxbid-step .label {font-size:.54rem;color:#7A899A;line-height:1.25;}.deal-maxbid-step .value {font-size:.82rem;font-weight:860;color:#0B1F33;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.deal-maxbid-step.final {background:#ECF9F5;border-color:#BFE4D9;}.deal-maxbid-step.final .value{color:#08786F;font-size:.94rem;}
.deal-maxbid-note {font-size:.60rem;color:#6B7D90;line-height:1.4;margin-top:8px;}
.deal-proof-banner {background:#F7FBFA;border:1px solid #DCEBE7;border-radius:12px;padding:10px 12px;margin:8px 0 11px;font-size:.68rem;line-height:1.42;color:#536A7D;}
.deal-proof-banner strong {color:#0B1F33;}
@media(max-width:1100px){.deal-signal-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-snapshot-lower{grid-template-columns:1fr;}.deal-maxbid-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-risk-row{grid-template-columns:78px 1fr;}.deal-risk-detail{grid-column:2;}}



/* v1.13.11 beginner-first Seller & negotiation */
.deal-seller-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;background:#F7FBFA;border:1px solid #DDEBE7;border-radius:14px;padding:13px 14px;margin:4px 0 10px;}
.deal-seller-intro .title{font-size:1.05rem;font-weight:900;color:#0B1F33;letter-spacing:-.025em;margin-bottom:3px;}.deal-seller-intro .copy{font-size:.68rem;color:#5F7387;line-height:1.42;max-width:800px;}
.deal-seller-position{display:grid;grid-template-columns:150px 1fr 190px;gap:14px;align-items:center;border-radius:14px;padding:13px 14px;margin:0 0 12px;border:1px solid #D5EAE4;background:linear-gradient(135deg,#F1FAF7,#FBFDFC);}
.deal-seller-position .position-word{font-size:1.18rem;font-weight:950;letter-spacing:-.03em;color:#08786F;}.deal-seller-position .position-label{font-size:.52rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#6B7D90;margin-bottom:3px;}
.deal-seller-position .headline{font-size:.92rem;font-weight:900;color:#0B1F33;line-height:1.25}.deal-seller-position .copy{font-size:.64rem;color:#607489;line-height:1.42;margin-top:3px;}.deal-seller-position .score{text-align:right;font-size:1.45rem;font-weight:950;color:#0B1F33}.deal-seller-position .score span{display:block;font-size:.54rem;color:#738397;font-weight:800;letter-spacing:.04em;text-transform:uppercase;margin-top:3px;}
.deal-seller-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px;}.deal-seller-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:135px;}.deal-seller-card.good{background:#F8FCFB;border-color:#D2EAE4}.deal-seller-card.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-seller-card.stop{background:#FFF8F7;border-color:#F0CBC6}
.deal-seller-card .label{font-size:.55rem;text-transform:uppercase;letter-spacing:.08em;color:#718195;font-weight:900;margin-bottom:6px;}.deal-seller-card .value{font-size:.88rem;line-height:1.24;font-weight:900;color:#0B1F33;}.deal-seller-card .detail{font-size:.62rem;line-height:1.43;color:#607489;margin-top:6px;}.deal-seller-card .status{display:inline-flex;border-radius:999px;padding:3px 6px;margin-top:7px;font-size:.49rem;font-weight:900;text-transform:uppercase;letter-spacing:.05em;background:#EEF3F5;color:#536A7D;}.deal-seller-card.good .status{background:#E9F7F1;color:#08786F}.deal-seller-card.warn .status{background:#FFF2CC;color:#8E6100}.deal-seller-card.stop .status{background:#FDEDEC;color:#B42318}
.deal-negotiation-banner{background:#F1FAF7;border:1px solid #CDE9E2;border-radius:14px;padding:12px 14px;margin:0 0 12px;}.deal-negotiation-banner .label{font-size:.54rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#08786F}.deal-negotiation-banner .action{font-size:.9rem;font-weight:900;color:#0B1F33;line-height:1.3;margin-top:4px}.deal-negotiation-banner .note{font-size:.64rem;color:#5F7387;line-height:1.43;margin-top:4px}.deal-negotiation-banner.blocked{background:#FFF8F7;border-color:#F0CBC6}.deal-negotiation-banner.blocked .label{color:#B42318}
.deal-seller-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:7px 0 12px;}.deal-seller-step{background:#fff;border:1px solid #E1E8EB;border-radius:12px;padding:11px 12px;}.deal-seller-step .num{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:#078B7D;color:#fff;font-size:.58rem;font-weight:900;margin-bottom:7px}.deal-seller-step .title{font-size:.7rem;font-weight:880;color:#17324B;line-height:1.32}.deal-seller-step .copy{font-size:.61rem;color:#66798C;line-height:1.42;margin-top:4px}
.deal-evidence-split{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:7px 0 12px;}.deal-evidence-box{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:12px 13px;}.deal-evidence-box h4{font-size:.76rem;margin:0 0 7px;color:#0B1F33}.deal-evidence-box ul{margin:0;padding-left:16px;color:#607489;font-size:.63rem;line-height:1.48}.deal-evidence-box li{margin-bottom:4px}.deal-evidence-box.inference{background:#FFFDF8;border-color:#ECDDB6}
@media(max-width:1100px){.deal-seller-position{grid-template-columns:1fr 130px}.deal-seller-position>div:first-child{grid-column:1/-1}.deal-seller-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-seller-steps{grid-template-columns:1fr}.deal-evidence-split{grid-template-columns:1fr}}


/* v1.13.13 auction-history integrity + incomplete legal-pack labelling */
.deal-call-script{background:#F8FAFA;border:1px solid #E1E8EB;border-left:4px solid #0F8F83;border-radius:12px;padding:13px 14px;margin:7px 0 10px;font-size:.76rem;line-height:1.5;color:#17324B;}
.deal-auction-intro{background:#F7FBFA;border:1px solid #DDEBE7;border-radius:14px;padding:13px 14px;margin:4px 0 10px}.deal-auction-intro .title{font-size:1.05rem;font-weight:900;color:#0B1F33;letter-spacing:-.025em}.deal-auction-intro .copy{font-size:.68rem;color:#5F7387;line-height:1.42;margin-top:3px;max-width:850px}
.deal-auction-position{display:grid;grid-template-columns:160px 1fr 240px;gap:14px;align-items:center;border:1px solid #D7E7E3;background:#F7FBFA;border-radius:14px;padding:13px 14px;margin:0 0 12px}.deal-auction-position.blocked{background:#FFF8F7;border-color:#F0CBC6}.deal-auction-position.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-auction-position .stage-label{font-size:.52rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#6B7D90}.deal-auction-position .stage-word{font-size:1.05rem;font-weight:950;color:#08786F;margin-top:2px}.deal-auction-position.blocked .stage-word{color:#B42318}.deal-auction-position.warn .stage-word{color:#8E6100}.deal-auction-position .headline{font-size:.9rem;font-weight:900;color:#0B1F33;line-height:1.25}.deal-auction-position .copy{font-size:.64rem;color:#607489;line-height:1.42;margin-top:3px}.deal-auction-position .confidence{text-align:right;font-size:.58rem;line-height:1.35;font-weight:850;text-transform:uppercase;letter-spacing:.04em;color:#6B7D90}
.deal-auction-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px}.deal-auction-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:128px}.deal-auction-card.good{background:#F8FCFB;border-color:#D2EAE4}.deal-auction-card.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-auction-card .label{font-size:.55rem;text-transform:uppercase;letter-spacing:.08em;color:#718195;font-weight:900;margin-bottom:6px}.deal-auction-card .value{font-size:.88rem;line-height:1.28;font-weight:900;color:#0B1F33}.deal-auction-card .detail{font-size:.62rem;line-height:1.43;color:#607489;margin-top:6px}
.deal-auction-action{background:#F1FAF7;border:1px solid #CDE9E2;border-radius:14px;padding:12px 14px;margin:0 0 12px}.deal-auction-action.blocked{background:#FFF8F7;border-color:#F0CBC6}.deal-auction-action .label{font-size:.54rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#08786F}.deal-auction-action.blocked .label{color:#B42318}.deal-auction-action .action{font-size:.9rem;font-weight:900;color:#0B1F33;line-height:1.32;margin-top:4px}.deal-auction-action .note{font-size:.63rem;color:#5F7387;line-height:1.43;margin-top:4px}
.deal-auction-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:7px 0 12px}.deal-auction-step{background:#fff;border:1px solid #E1E8EB;border-radius:12px;padding:11px 12px}.deal-auction-step .num{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:#078B7D;color:#fff;font-size:.58rem;font-weight:900;margin-bottom:7px}.deal-auction-step .title{font-size:.7rem;font-weight:880;color:#17324B;line-height:1.32}.deal-auction-step .copy{font-size:.61rem;color:#66798C;line-height:1.42;margin-top:4px}
.deal-auction-timeline{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:4px 13px;margin:7px 0 10px}.deal-auction-event{display:grid;grid-template-columns:120px 1fr;gap:12px;padding:10px 0;border-top:1px solid #EEF2F3}.deal-auction-event:first-child{border-top:0}.deal-auction-event .date{font-size:.61rem;font-weight:800;color:#6B7D90}.deal-auction-event .event-title{font-size:.7rem;font-weight:850;color:#17324B}.deal-auction-event .event-copy{font-size:.61rem;color:#66798C;line-height:1.4;margin-top:2px}
@media(max-width:1100px){.deal-auction-position{grid-template-columns:1fr}.deal-auction-position .confidence{text-align:left}.deal-auction-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.deal-auction-steps{grid-template-columns:1fr}}


/* Beginner Location v1.13.14 */
.deal-location-intro{background:#F7FBFA;border:1px solid #DDEBE7;border-radius:14px;padding:13px 14px;margin:4px 0 10px}.deal-location-intro .title{font-size:1.05rem;font-weight:900;color:#0B1F33;letter-spacing:-.025em}.deal-location-intro .copy{font-size:.68rem;color:#5F7387;line-height:1.42;margin-top:3px;max-width:900px}
.deal-location-position{display:grid;grid-template-columns:210px 1fr 160px;gap:14px;align-items:center;border:1px solid #D7E7E3;background:#F7FBFA;border-radius:14px;padding:13px 14px;margin:0 0 12px}.deal-location-position.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-location-position.risk{background:#FFF8F7;border-color:#F0CBC6}.deal-location-position .label{font-size:.52rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#6B7D90}.deal-location-position .verdict{font-size:1.02rem;font-weight:950;color:#08786F;line-height:1.16;margin-top:2px}.deal-location-position.warn .verdict{color:#8E6100}.deal-location-position.risk .verdict{color:#B42318}.deal-location-position .headline{font-size:.9rem;font-weight:900;color:#0B1F33;line-height:1.25}.deal-location-position .copy{font-size:.64rem;color:#607489;line-height:1.42;margin-top:3px}.deal-location-position .evidence{text-align:right;font-size:.58rem;line-height:1.35;font-weight:850;text-transform:uppercase;letter-spacing:.04em;color:#6B7D90}
.deal-location-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px}.deal-location-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:142px}.deal-location-card.good{background:#F8FCFB;border-color:#D2EAE4}.deal-location-card.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-location-card.risk{background:#FFF8F7;border-color:#F0CBC6}.deal-location-card .label{font-size:.55rem;text-transform:uppercase;letter-spacing:.08em;color:#718195;font-weight:900;margin-bottom:6px}.deal-location-card .value{font-size:.86rem;line-height:1.28;font-weight:900;color:#0B1F33}.deal-location-card .detail{font-size:.61rem;line-height:1.43;color:#607489;margin-top:6px}.deal-location-card .status{display:inline-flex;border-radius:999px;padding:3px 6px;margin-top:7px;font-size:.49rem;font-weight:900;text-transform:uppercase;letter-spacing:.05em;background:#EEF3F5;color:#536A7D}.deal-location-card.good .status{background:#E9F7F1;color:#08786F}.deal-location-card.warn .status{background:#FFF2CC;color:#8E6100}.deal-location-card.risk .status{background:#FDEDEC;color:#B42318}
.deal-location-split{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 12px}.deal-location-panel{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:12px 14px}.deal-location-panel.good{background:#F8FCFB;border-color:#D2EAE4}.deal-location-panel.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-location-panel .eyebrow{font-size:.53rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#6B7D90}.deal-location-panel .title{font-size:.86rem;font-weight:900;color:#0B1F33;line-height:1.3;margin-top:4px}.deal-location-panel .copy{font-size:.63rem;line-height:1.45;color:#607489;margin-top:5px}
.deal-location-proof{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:7px 0 12px}.deal-location-proof .item{background:#fff;border:1px solid #E1E8EB;border-radius:12px;padding:10px 11px}.deal-location-proof .item .label{font-size:.54rem;color:#718195;font-weight:800}.deal-location-proof .item .value{font-size:.92rem;color:#0B1F33;font-weight:900;margin-top:3px}.deal-location-proof .item .sub{font-size:.58rem;color:#718195;margin-top:3px;line-height:1.35}
.deal-location-list{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:5px 13px;margin:7px 0 12px}.deal-location-list-row{display:grid;grid-template-columns:26px 1fr;gap:8px;padding:9px 0;border-top:1px solid #EEF2F3}.deal-location-list-row:first-child{border-top:0}.deal-location-list-row .num{width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:#078B7D;color:#fff;font-size:.58rem;font-weight:900}.deal-location-list-row .title{font-size:.69rem;font-weight:850;color:#17324B}.deal-location-list-row .copy{font-size:.61rem;color:#66798C;line-height:1.4;margin-top:2px}
.deal-location-gap{background:#FFFCF5;border:1px solid #ECDDB6;border-radius:13px;padding:11px 13px;margin:8px 0 12px}.deal-location-gap .title{font-size:.72rem;font-weight:900;color:#17324B}.deal-location-gap .copy{font-size:.62rem;color:#66798C;line-height:1.45;margin-top:4px}
/* Beginner Workspace v1.13.15 */
.deal-workspace-intro{background:#F7FBFA;border:1px solid #DDEBE7;border-radius:14px;padding:13px 14px;margin:4px 0 10px}.deal-workspace-intro .title{font-size:1.05rem;font-weight:900;color:#0B1F33}.deal-workspace-intro .copy{font-size:.68rem;color:#5F7387;line-height:1.42;margin-top:3px}
.deal-workspace-hero{display:grid;grid-template-columns:230px 1fr 150px;gap:14px;align-items:center;border:1px solid #D7E7E3;background:#F7FBFA;border-radius:14px;padding:14px;margin-bottom:12px}.deal-workspace-hero.risk{background:#FFF8F7;border-color:#F0CBC6}.deal-workspace-hero.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-workspace-hero .label{font-size:.53rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#6B7D90}.deal-workspace-hero .status{font-size:1rem;font-weight:950;color:#08786F;margin-top:3px}.deal-workspace-hero.risk .status{color:#B42318}.deal-workspace-hero.warn .status{color:#8E6100}.deal-workspace-hero .next{font-size:.9rem;font-weight:900;color:#0B1F33}.deal-workspace-hero .sub{font-size:.62rem;color:#607489;line-height:1.4;margin-top:4px}.deal-workspace-hero .pct{text-align:right;font-size:1.45rem;font-weight:950;color:#0B1F33}.deal-workspace-hero .pct small{display:block;font-size:.5rem;text-transform:uppercase;letter-spacing:.08em;color:#718195}
.deal-workspace-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px}.deal-workspace-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:112px}.deal-workspace-card.risk{background:#FFF8F7;border-color:#F0CBC6}.deal-workspace-card.warn{background:#FFFCF5;border-color:#ECDDB6}.deal-workspace-card.good{background:#F8FCFB;border-color:#D2EAE4}.deal-workspace-card .label{font-size:.52rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#718195}.deal-workspace-card .value{font-size:.82rem;line-height:1.28;font-weight:900;color:#0B1F33;margin-top:5px}.deal-workspace-card .copy{font-size:.59rem;line-height:1.4;color:#607489;margin-top:5px}
.deal-task-row{display:grid;grid-template-columns:32px 86px 1fr;gap:9px;align-items:start;padding:9px 0;border-top:1px solid #EEF2F3}.deal-task-row:first-child{border-top:0}.deal-task-pill{display:inline-flex;border-radius:999px;padding:3px 6px;font-size:.48rem;font-weight:900;text-transform:uppercase;justify-content:center;background:#FFF2CC;color:#8E6100}.deal-task-pill.stop{background:#FDEDEC;color:#B42318}.deal-task-title{font-size:.69rem;font-weight:850;color:#17324B}.deal-task-copy{font-size:.59rem;color:#66798C;line-height:1.4;margin-top:2px}.deal-workspace-rule{background:#F7FBFA;border:1px solid #DDEBE7;border-radius:12px;padding:10px 12px;font-size:.62rem;color:#526A7D;line-height:1.45;margin:8px 0 12px}
@media(max-width:1100px){.deal-workspace-hero{grid-template-columns:1fr}.deal-workspace-hero .pct{text-align:left}.deal-workspace-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
/* Workspace v1.13.16 — urgency groups, evidence state and direct actions */
.deal-task-group{margin:12px 0 6px;padding:10px 12px;border-radius:12px;border:1px solid #E1E8EB;background:#fff}.deal-task-group.must{background:#FFF8F7;border-color:#F0CBC6}.deal-task-group.check{background:#FFFCF5;border-color:#ECDDB6}.deal-task-group.negotiate{background:#F7FBFA;border-color:#DDEBE7}.deal-task-group .title{font-size:.76rem;font-weight:900;color:#0B1F33}.deal-task-group .copy{font-size:.6rem;color:#66798C;line-height:1.42;margin-top:2px}
.deal-task-evidence{display:inline-flex;align-items:center;border-radius:999px;padding:4px 7px;font-size:.49rem;font-weight:900;text-transform:uppercase;letter-spacing:.04em;background:#FFF2CC;color:#8E6100}.deal-task-evidence.stop{background:#FDEDEC;color:#B42318}.deal-task-evidence.resolved{background:#E9F7F1;color:#08786F}.deal-task-evidence.manual{background:#EEF3F5;color:#536A7D}
.deal-task-action-state{font-size:.55rem;color:#66798C;line-height:1.35;margin-top:4px}.deal-stage-warning{background:#FFF4F3;border:1px solid #F2C9C4;border-radius:12px;padding:10px 12px;margin:8px 0;font-size:.64rem;line-height:1.45;color:#8F2D24}.deal-stage-warning strong{color:#B42318}
.deal-contact-note{font-size:.59rem;color:#66798C;line-height:1.4;margin-top:4px}
@media(max-width:1100px){.deal-location-position{grid-template-columns:1fr}.deal-location-position .evidence{text-align:left}.deal-location-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.deal-location-split{grid-template-columns:1fr}.deal-location-proof{grid-template-columns:repeat(2,minmax(0,1fr))}}


/* v1.13.6 beginner-first Legal & Planning */
.deal-plain-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;background:#F7FBFA;border:1px solid #DDEBE7;border-radius:14px;padding:13px 14px;margin:4px 0 10px;}
.deal-plain-intro .title{font-size:1.05rem;font-weight:900;color:#0B1F33;letter-spacing:-.025em;margin-bottom:3px;}
.deal-plain-intro .copy{font-size:.68rem;color:#5F7387;line-height:1.42;max-width:760px;}
.deal-plain-legend{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;}
.deal-plain-pill{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:5px 8px;font-size:.53rem;font-weight:900;letter-spacing:.05em;border:1px solid transparent;white-space:nowrap;}
.deal-plain-pill.stop{background:#FDEDEC;color:#B42318;border-color:#F6C7C3}.deal-plain-pill.check{background:#FFF7E5;color:#8E6100;border-color:#EFD59A}.deal-plain-pill.clear{background:#ECF9F3;color:#08786F;border-color:#C5E8DC}
.deal-plain-gate{display:grid;grid-template-columns:150px 1fr;gap:14px;align-items:center;border-radius:14px;padding:13px 14px;margin:0 0 12px;border:1px solid #E1E8EB;background:#fff;}
.deal-plain-gate.stop{background:#FFF4F3;border-color:#F2C9C4}.deal-plain-gate.check{background:#FFF9EC;border-color:#EED8A5}.deal-plain-gate.clear{background:#F1FAF7;border-color:#C7E8DE}
.deal-plain-gate .gate-word{font-size:1.02rem;font-weight:950;letter-spacing:.04em}.deal-plain-gate.stop .gate-word{color:#B42318}.deal-plain-gate.check .gate-word{color:#8E6100}.deal-plain-gate.clear .gate-word{color:#08786F}
.deal-plain-gate .gate-title{font-size:.88rem;font-weight:880;color:#0B1F33;line-height:1.25}.deal-plain-gate .gate-copy{font-size:.65rem;color:#607489;line-height:1.42;margin-top:3px}
.deal-legal-readiness{display:grid;grid-template-columns:145px 1fr;gap:16px;align-items:center;border-radius:14px;padding:13px 14px;margin:-2px 0 12px;border:1px solid #E1E8EB;background:#fff;}
.deal-legal-readiness.stop{background:#FFF8F7;border-color:#F0CBC6}.deal-legal-readiness.check{background:#FFFCF5;border-color:#ECDDB6}.deal-legal-readiness.clear{background:#F8FCFB;border-color:#D2EAE4}
.deal-legal-readiness .score{font-size:1.45rem;font-weight:950;letter-spacing:-.04em;color:#0B1F33}.deal-legal-readiness .score-label{font-size:.52rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#6B7D90}
.deal-legal-readiness .ready-title{font-size:.82rem;font-weight:900;color:#0B1F33}.deal-legal-readiness .ready-copy{font-size:.62rem;line-height:1.4;color:#607489;margin-top:3px}.deal-legal-readiness .bar{height:7px;background:#E9EEF1;border-radius:999px;overflow:hidden;margin-top:7px}.deal-legal-readiness .fill{height:100%;border-radius:999px}.deal-legal-readiness.stop .fill{background:#D92D20}.deal-legal-readiness.check .fill{background:#D9A514}.deal-legal-readiness.clear .fill{background:#10A38F}
.deal-hard-rule{font-size:.68rem;font-weight:850;color:#8F1D16;margin:6px 0 0}.deal-term-help{font-size:.62rem;line-height:1.5;color:#5F7387}
.deal-plain-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px;}
.deal-plain-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:142px;}
.deal-plain-card.stop{background:#FFF8F7;border-color:#F0CBC6}.deal-plain-card.check{background:#FFFCF5;border-color:#ECDDB6}.deal-plain-card.clear{background:#F8FCFB;border-color:#D2EAE4}
.deal-plain-card .card-top{display:flex;align-items:center;justify-content:space-between;gap:7px;margin-bottom:7px}.deal-plain-card .card-title{font-size:.72rem;font-weight:850;color:#17324B}.deal-plain-card .status{border-radius:999px;padding:3px 6px;font-size:.48rem;font-weight:900;letter-spacing:.05em}.deal-plain-card.stop .status{background:#FDEDEC;color:#B42318}.deal-plain-card.check .status{background:#FFF2CC;color:#8E6100}.deal-plain-card.clear .status{background:#E9F7F1;color:#08786F}
.deal-plain-card .answer{font-size:.78rem;font-weight:850;color:#0B1F33;line-height:1.28;margin-bottom:6px}.deal-plain-card .why{font-size:.59rem;line-height:1.38;color:#6B7D90}.deal-plain-card .why strong{color:#52677A}.deal-plain-card .next{font-size:.57rem;line-height:1.35;color:#52677A;margin-top:6px;padding-top:6px;border-top:1px solid rgba(225,232,235,.8)}.deal-plain-card .next strong{color:#17324B}
.deal-simple-next{background:linear-gradient(135deg,#F0FAF7,#FAFDFC);border:1px solid #CFE9E3;border-radius:14px;padding:12px 14px;margin:0 0 12px}.deal-simple-next .label{font-size:.54rem;text-transform:uppercase;letter-spacing:.09em;color:#08786F;font-weight:900}.deal-simple-next .action{font-size:.9rem;font-weight:900;color:#0B1F33;margin-top:3px}.deal-simple-next .sub{font-size:.63rem;color:#607489;line-height:1.42;margin-top:3px}
.deal-doc-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:6px 0 10px}.deal-doc-item{display:flex;align-items:center;justify-content:space-between;gap:8px;background:#fff;border:1px solid #E3E9EB;border-radius:10px;padding:8px 9px;font-size:.62rem;color:#52677A}.deal-doc-item strong{color:#17324B}.deal-doc-item .ok{color:#08786F;font-weight:850}.deal-doc-item .missing{color:#B42318;font-weight:850}.deal-doc-item .review{color:#8E6100;font-weight:850}
@media(max-width:1150px){.deal-plain-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-doc-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.deal-plain-gate{grid-template-columns:1fr}.deal-plain-legend{justify-content:flex-start}}

</style>
""",
    unsafe_allow_html=True,
)


# v1.14.0 — locked beginner-first Guided Deal Room.  Discover/Home is untouched.
st.markdown(
    """
<style>
.deal-guided-intro{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(270px,.8fr);gap:14px;align-items:stretch;margin:4px 0 14px}
.deal-guided-verdict{border:1px solid #E9D7A2;background:linear-gradient(135deg,#FFF9E8 0%,#FFFCF4 65%,#F6FBF9 100%);border-radius:17px;padding:18px 20px;display:flex;gap:14px;align-items:flex-start;min-height:132px}
.deal-guided-verdict.good{border-color:#C7E8DE;background:linear-gradient(135deg,#F0FAF7,#FAFDFC)}
.deal-guided-verdict.risk{border-color:#F0CBC6;background:linear-gradient(135deg,#FFF5F3,#FFFCFB)}
.deal-guided-verdict .icon{width:44px;height:44px;display:flex;align-items:center;justify-content:center;border-radius:13px;background:#FFF0C7;font-size:1.35rem;flex:0 0 auto}.deal-guided-verdict.good .icon{background:#DDF5EC}.deal-guided-verdict.risk .icon{background:#FDE3DF}
.deal-guided-verdict .q{font-size:1.18rem;font-weight:950;letter-spacing:-.03em;color:#0B1F33}.deal-guided-verdict .view{font-size:.93rem;font-weight:900;color:#17324B;margin-top:2px}.deal-guided-verdict .copy{font-size:.68rem;line-height:1.5;color:#5D7084;margin-top:5px;max-width:760px}
.deal-guided-next{border:1px solid #D8E8E4;background:#FFFFFF;border-radius:17px;padding:15px 16px;min-height:132px}.deal-guided-next .label{font-size:.52rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#0F8F83}.deal-guided-next .title{font-size:.88rem;font-weight:900;color:#0B1F33;margin-top:5px}.deal-guided-next .copy{font-size:.62rem;color:#66798C;line-height:1.45;margin-top:4px}
.deal-section-title{display:flex;align-items:center;gap:8px;margin:15px 0 7px}.deal-section-title .num{width:25px;height:25px;border-radius:999px;display:flex;align-items:center;justify-content:center;background:#0F8F83;color:#fff;font-size:.62rem;font-weight:900}.deal-section-title .txt{font-size:.88rem;font-weight:920;color:#0B1F33}.deal-section-title .sub{font-size:.6rem;color:#738397;margin-left:3px}
.deal-journey{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;background:#fff;border:1px solid #E1E8EB;border-radius:15px;padding:10px;margin:6px 0 14px}.deal-journey-step{border-radius:11px;padding:9px 8px;background:#F8FAFB;min-height:76px}.deal-journey-step .top{display:flex;align-items:center;gap:6px}.deal-journey-step .dot{width:22px;height:22px;border-radius:999px;display:flex;align-items:center;justify-content:center;font-size:.55rem;font-weight:900;background:#E7ECEF;color:#526A7D}.deal-journey-step .name{font-size:.6rem;font-weight:900;color:#17324B}.deal-journey-step .state{font-size:.52rem;line-height:1.3;color:#66798C;margin-top:6px}.deal-journey-step.good{background:#F3FBF8}.deal-journey-step.good .dot{background:#0F8F83;color:#fff}.deal-journey-step.warn{background:#FFF9ED}.deal-journey-step.warn .dot{background:#D89A0D;color:#fff}.deal-journey-step.risk{background:#FFF5F3}.deal-journey-step.risk .dot{background:#D92D20;color:#fff}.deal-journey-step.neutral .dot{background:#728197;color:#fff}
.deal-guided-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:8px 0 14px}.deal-guided-card{background:#fff;border:1px solid #E1E8EB;border-radius:14px;padding:13px 14px;min-height:185px}.deal-guided-card .eyebrow{font-size:.52rem;text-transform:uppercase;letter-spacing:.07em;font-weight:900;color:#0F8F83}.deal-guided-card .title{font-size:.84rem;font-weight:920;color:#0B1F33;margin:4px 0 8px}.deal-guided-card .big{font-size:1.35rem;font-weight:950;letter-spacing:-.04em;color:#0B1F33}.deal-guided-card .muted{font-size:.59rem;color:#6B7D90;line-height:1.45}.deal-guided-card .row{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #EEF2F3;padding:7px 0;font-size:.61rem;color:#5F7387}.deal-guided-card .row:first-of-type{border-top:0}.deal-guided-card .row strong{color:#17324B;text-align:right}.deal-guided-card .footer{margin-top:8px;padding-top:8px;border-top:1px solid #EEF2F3;font-size:.58rem;color:#66798C;line-height:1.42}
.deal-status-pill{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:4px 7px;font-size:.49rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase}.deal-status-pill.clear{background:#E9F7F1;color:#08786F}.deal-status-pill.check{background:#FFF2CC;color:#8E6100}.deal-status-pill.stop{background:#FDEDEC;color:#B42318}.deal-status-pill.not-verified{background:#EEF2F5;color:#596E81}.deal-status-pill.supported{background:#E9F7F1;color:#08786F}.deal-status-pill.provisional{background:#FFF2CC;color:#8E6100}.deal-status-pill.low{background:#FDEDEC;color:#B42318}
.deal-checks-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:7px 0 12px}.deal-check-card{background:#fff;border:1px solid #E1E8EB;border-radius:13px;padding:11px 12px;min-height:150px}.deal-check-card.stop{background:#FFF8F7;border-color:#F0CBC6}.deal-check-card.check{background:#FFFCF5;border-color:#ECDDB6}.deal-check-card.clear{background:#F8FCFB;border-color:#D2EAE4}.deal-check-card.not-verified{background:#FAFBFC}.deal-check-card .head{display:flex;align-items:center;justify-content:space-between;gap:7px}.deal-check-card .label{font-size:.7rem;font-weight:900;color:#17324B}.deal-check-card .summary{font-size:.69rem;font-weight:850;color:#0B1F33;line-height:1.35;margin-top:8px}.deal-check-card .why{font-size:.56rem;color:#6A7C8E;line-height:1.42;margin-top:6px}.deal-check-card .next{font-size:.55rem;color:#52677A;line-height:1.4;margin-top:7px;padding-top:7px;border-top:1px solid rgba(225,232,235,.85)}
.deal-seller-story{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:10px;margin:7px 0 13px}.deal-story-panel{background:#fff;border:1px solid #E1E8EB;border-radius:14px;padding:13px 14px}.deal-story-panel .headline{font-size:.85rem;font-weight:920;color:#0B1F33}.deal-story-panel .copy{font-size:.61rem;line-height:1.48;color:#66798C;margin-top:4px}.deal-story-signal{display:flex;gap:8px;align-items:flex-start;border-top:1px solid #EEF2F3;padding:8px 0}.deal-story-signal:first-of-type{border-top:0}.deal-story-signal .bullet{width:9px;height:9px;border-radius:999px;background:#0F8F83;margin-top:4px;flex:0 0 auto}.deal-story-signal.warn .bullet{background:#D89A0D}.deal-story-signal.risk .bullet{background:#D92D20}.deal-story-signal .t{font-size:.62rem;font-weight:850;color:#17324B}.deal-story-signal .s{font-size:.55rem;color:#708195;line-height:1.35;margin-top:2px}
.deal-final-box{display:grid;grid-template-columns:minmax(220px,.7fr) minmax(0,1fr) minmax(260px,.9fr);gap:14px;align-items:stretch;border:1px solid #E9D7A2;background:linear-gradient(135deg,#FFF9E8,#FFFCF4);border-radius:17px;padding:15px 16px;margin:10px 0 14px}.deal-final-box.good{border-color:#C7E8DE;background:linear-gradient(135deg,#F0FAF7,#FCFEFD)}.deal-final-box.risk{border-color:#F0CBC6;background:linear-gradient(135deg,#FFF5F3,#FFFCFB)}.deal-final-box .decision{font-size:1.05rem;font-weight:950;letter-spacing:-.02em;color:#9A6700}.deal-final-box.good .decision{color:#08786F}.deal-final-box.risk .decision{color:#B42318}.deal-final-box .copy{font-size:.61rem;color:#66798C;line-height:1.45;margin-top:4px}.deal-final-box .col-title{font-size:.6rem;font-weight:900;color:#17324B;margin-bottom:5px}.deal-final-reason{font-size:.58rem;line-height:1.45;color:#596F82;padding:2px 0}.deal-final-reason strong{color:#17324B}
.deal-evidence-note{background:#F7FBFA;border:1px solid #DDEBE7;border-radius:12px;padding:9px 11px;font-size:.58rem;line-height:1.45;color:#607489;margin:8px 0 10px}.deal-evidence-note strong{color:#17324B}
.st-key-guided_strategy [data-testid="stSegmentedControl"]{background:#F5F8F8;border:1px solid #E0E8E8;border-radius:13px;padding:4px}.st-key-guided_strategy [data-testid="stSegmentedControl"] button{font-weight:850!important;border-radius:9px!important;min-height:41px!important}
@media(max-width:1200px){.deal-guided-grid,.deal-checks-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.deal-journey{grid-template-columns:repeat(4,minmax(0,1fr))}.deal-final-box{grid-template-columns:1fr 1fr}.deal-seller-story{grid-template-columns:1fr}}
@media(max-width:800px){.deal-guided-intro,.deal-guided-grid,.deal-checks-grid,.deal-final-box{grid-template-columns:1fr}.deal-journey{grid-template-columns:repeat(2,minmax(0,1fr))}}
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


if "lotly_last_visit_cutoff" not in st.session_state:
    _prior_visit = db.get_app_state("last_visit_at", "") or ""
    _visit_started = datetime.now(timezone.utc).isoformat()
    st.session_state["lotly_last_visit_cutoff"] = _prior_visit
    st.session_state["lotly_visit_started_at"] = _visit_started
    db.set_app_state("last_visit_at", _visit_started)
    # Persist the visit marker so a cold Streamlit restart still knows what changed
    # since the user's previous session. This is intentionally quiet.
    if cloud_store:
        sync_cloud("visit marker", quiet=True)


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


def _parse_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _after_cutoff(value, cutoff):
    event = _parse_utc(value)
    cut = _parse_utc(cutoff)
    return bool(event and cut and event > cut)


def history_reduced_since(history, cutoff):
    if not cutoff or not history:
        return False
    events = sorted(history, key=lambda x: str(x.get("captured_at") or ""))
    previous = None
    for event in events:
        guide = event.get("guide_price")
        if guide is not None:
            try:
                guide = float(guide)
            except Exception:
                guide = None
        if previous is not None and guide is not None and guide < previous and _after_cutoff(event.get("captured_at"), cutoff):
            return True
        if guide is not None:
            previous = guide
    return False


def history_postauction_since(history, cutoff):
    if not cutoff or not history:
        return False
    events = sorted(history, key=lambda x: str(x.get("captured_at") or ""))
    previous = None
    for event in events:
        status = event.get("status")
        if previous is not None and status in UNSOLD_STATES and previous not in UNSOLD_STATES and _after_cutoff(event.get("captured_at"), cutoff):
            return True
        if status:
            previous = status
    return False


def estimated_value(row):
    return row.get("market_value") or row.get("comparable_valuation_mid")


def guide_to_value_discount(row):
    guide = row.get("guide_price")
    value = estimated_value(row)
    try:
        guide = float(guide or 0)
        value = float(value or 0)
    except Exception:
        return None
    if guide <= 0 or value <= 0 or guide >= value:
        return None
    discount = (value - guide) / value * 100.0
    return round(discount, 1) if 0 < discount < 95 else None


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
    refresh = st.session_state.pop("refresh_summary", None)
    if not refresh:
        return
    sources = refresh.get("sources", [])
    found = sum(int(x.get("found") or 0) for x in sources)
    changed = sum(int(x.get("changed") or 0) for x in sources)
    ok = sum(x.get("status") == "ok" for x in sources)
    st.toast(f"Lotly updated · {found} opportunities · {changed} changed · {ok}/{len(sources) or 4} sources online", icon="✅")


# Product navigation and buying-profile defaults.
SETTINGS_DEFAULTS = {
    "commercial_target_psf": 50,
    "commercial_ceiling_psf": 60,
    "commercial_min_sqft": 9000,
    "commercial_max_price": 1_500_000,
    "preferred_motorway_miles": 5.0,
    "residential_target_price": 100_000,
    "hot_score": 8.0,
    "default_auction_fee": 1500,
    "default_legal": 2000,
    "default_survey": 1000,
    "default_res_margin": 20.0,
    "default_com_margin": 20.0,
}
for _key, _value in SETTINGS_DEFAULTS.items():
    st.session_state.setdefault(_key, _value)
st.session_state.setdefault("lotly_page", "Discover")
# Programmatic navigation must be applied before the sidebar radio widget is instantiated.
# Buttons elsewhere in the app queue the destination here and then rerun; writing directly
# to the radio widget key after instantiation raises StreamlitWidgetAlreadyInstantiatedError.
_pending_lotly_page = st.session_state.pop("_lotly_pending_page", None)
if _pending_lotly_page in {"Discover", "Shortlist", "Pipeline", "Deal Room", "Reports", "Settings"}:
    st.session_state["lotly_page"] = _pending_lotly_page
# An open property is always a Deal Room context. Apply this before the radio widget
# is instantiated so the sidebar active state stays truthful without mutating a live widget.
if st.session_state.get("selected_deal_id"):
    st.session_state["lotly_page"] = "Deal Room"
st.session_state.setdefault("compare_ids", [])
st.session_state.setdefault("market_mode", "Residential")


def _nav_changed():
    st.session_state.pop("selected_deal_id", None)


_raw_rows = db.list_properties()
_sidebar_history_map = db.history_map() if _raw_rows else {}
_sidebar_market = st.session_state.get("market_mode", "Residential")
_sidebar_actionable_all = [r for r in _raw_rows if is_actionable(r)]
_sidebar_actionable = [r for r in _sidebar_actionable_all if (is_commercial(r) if _sidebar_market == "Commercial" else not is_commercial(r))]
_sidebar_new_today = sum(1 for r in _sidebar_actionable if first_seen_today(r))
_sidebar_postauction = sum(1 for r in _sidebar_actionable if is_unsold(r))
_sidebar_reduced = sum(1 for r in _sidebar_actionable if float(history_metrics(_sidebar_history_map.get(r.get("id"), []), r).get("price_reduction_pct") or 0) > 0)
_sidebar_shortlist_ids = set(db.shortlist_ids())
_sidebar_saved = sum(1 for r in _sidebar_actionable if r.get("id") in _sidebar_shortlist_ids)

_nav_icons = {
    "Discover":"⌂  Discover", "Shortlist":"♡  Shortlist", "Pipeline":"▤  Pipeline",
    "Deal Room":"▣  Deal Room", "Reports":"▥  Reports", "Settings":"⚙  Settings",
}

with st.sidebar:
    brand_img = f'<img src="{LOTLY_ICON_DATA_URI}" alt="Lotly">' if LOTLY_ICON_DATA_URI else '<span style="font-size:1.45rem">◇</span>'
    st.markdown(
        '<div class="sidebar-brand-simple">'
        f'<div class="mark">{brand_img}</div>'
        '<div><div class="name">Lotly</div><div class="sub">Property Auction<br>Intelligence</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    lotly_page = st.radio(
        "Navigation",
        ["Discover", "Shortlist", "Pipeline", "Deal Room", "Reports", "Settings"],
        key="lotly_page",
        label_visibility="collapsed",
        format_func=lambda x: _nav_icons.get(x, x),
        on_change=_nav_changed,
    )
    if lotly_page != "Settings":
        today_html = f'''<div class="side-card"><div class="side-card-title"><span>▣ &nbsp; Today</span><span>{datetime.now().strftime('%a %d %b %Y')}</span></div>
        <div class="side-kv"><span>New today</span><strong>{_sidebar_new_today}</strong></div>
        <div class="side-kv"><span>Post-auction</span><strong>{_sidebar_postauction}</strong></div>
        <div class="side-kv"><span>Reduced</span><strong>{_sidebar_reduced}</strong></div>
        <div class="side-kv"><span>Saved</span><strong>{_sidebar_saved}</strong></div></div>'''
        st.markdown(today_html, unsafe_allow_html=True)
        _sidebar_selected_row = next((r for r in _raw_rows if r.get("id") == st.session_state.get("selected_deal_id")), None)
        _sidebar_context_commercial = is_commercial(_sidebar_selected_row) if _sidebar_selected_row else (_sidebar_market == "Commercial")
        if _sidebar_context_commercial:
            buy_box = f'''<div class="side-card"><div class="side-card-title"><span>◎ &nbsp; Your buy box</span><span>Edit</span></div>
            <div class="side-kv"><span>Commercial target</span><strong>{POUND}{int(st.session_state['commercial_target_psf'])} / sq ft</strong></div>
            <div class="side-kv"><span>Max guide price</span><strong>{money(st.session_state['commercial_max_price'],0)}</strong></div>
            <div class="side-kv"><span>Preferred size</span><strong>{int(st.session_state['commercial_min_sqft']):,}–10,000 sq ft</strong></div>
            <div class="side-kv"><span>Motorway radius</span><strong>{float(st.session_state['preferred_motorway_miles']):.0f} miles</strong></div>
            <div class="side-link">View full criteria &nbsp; →</div></div>'''
        else:
            _deal_guide = money(_sidebar_selected_row.get("guide_price"),0) if _sidebar_selected_row else "-"
            buy_box = f'''<div class="side-card"><div class="side-card-title"><span>◎ &nbsp; Your buy box</span><span>Edit</span></div>
            <div class="side-kv"><span>Residential target</span><strong>{money(st.session_state['residential_target_price'],0)}</strong></div>
            <div class="side-kv"><span>Target margin</span><strong>{float(st.session_state['default_res_margin']):.0f}%</strong></div>
            <div class="side-kv"><span>Current deal guide</span><strong>{_deal_guide}</strong></div>
            <div class="side-kv"><span>Market</span><strong>Residential</strong></div>
            <div class="side-link">View full criteria &nbsp; →</div></div>'''
        st.markdown(buy_box, unsafe_allow_html=True)
        st.markdown('<div class="side-brand-card"><span class="diamond">◆</span>Serious opportunities.<br>Smarter decisions.</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-version">Lotly v{html.escape(APP_VERSION)}</div>', unsafe_allow_html=True)

commercial_target_psf = int(st.session_state["commercial_target_psf"])
commercial_ceiling_psf = int(st.session_state["commercial_ceiling_psf"])
commercial_min_sqft = int(st.session_state["commercial_min_sqft"])
commercial_max_price = int(st.session_state["commercial_max_price"])
preferred_motorway_miles = float(st.session_state["preferred_motorway_miles"])
residential_target_price = int(st.session_state["residential_target_price"])
hot_score = float(st.session_state["hot_score"])
default_auction_fee = float(st.session_state["default_auction_fee"])
default_legal = float(st.session_state["default_legal"])
default_survey = float(st.session_state["default_survey"])
default_res_margin = float(st.session_state["default_res_margin"])
default_com_margin = float(st.session_state["default_com_margin"])

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

# Finished product header. Technical connection status lives in Settings.
deal_open = bool(st.session_state.get("selected_deal_id"))
if not deal_open and lotly_page in {"Discover", "Shortlist"}:
    st.markdown(
        '<div class="lotly-topbar"><div class="topbar-actions">'
        '<span class="tb-icon"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.4-3.4"></path></svg></span><span class="tb-icon tb-bell"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg></span>'
        '<div class="tb-person"><div class="tb-avatar">JD</div><div class="tb-person-copy"><strong>James Durno</strong><span>Investor</span></div><span class="tb-chevron">⌄</span></div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    page_title = "Find your next opportunity." if lotly_page == "Discover" else "Your shortlist."
    page_sub = (
        "The strongest live auction opportunities, ranked around your buying criteria, seller motivation, evidence quality and legal/planning risk."
        if lotly_page == "Discover" else
        "The properties you have saved for a closer look, kept decision-ready as auction evidence changes."
    )
    runs = db.latest_runs()
    latest_text = "Not updated yet"
    if runs:
        raw_ts = str(runs[0].get("completed_at") or runs[0].get("started_at") or "")
        latest_text = raw_ts[0:16].replace("T", " ") if len(raw_ts) >= 16 else raw_ts
    with st.container(border=False, key="lotly_hero"):
        st.markdown('<span class="lotly-hero-marker"></span>', unsafe_allow_html=True)
        hleft, hright = st.columns([4.7, 1.35], vertical_alignment="top")
        with hleft:
            st.markdown(
                f'<div class="hero-copy"><div class="lotly-kicker">Auction opportunities. Real advantage.</div><div class="lotly-title">{page_title}</div><div class="lotly-subtitle">{page_sub}</div></div>',
                unsafe_allow_html=True,
            )
        with hright:
            st.markdown('<div class="hero-right-space"></div>', unsafe_allow_html=True)
            with st.popover("↻  Update data", use_container_width=True):
                st.caption("Refresh only what you need. Lotly keeps the last verified history in Supabase.")
                if st.button("Refresh live auctions", type="primary", use_container_width=True):
                    with st.spinner("Updating live auction stock..."):
                        st.session_state["refresh_summary"] = refresh_all(db, companies_house_api_key=companies_house_api_key, legal_access=legal_access, cloud_store=cloud_store)
                        sync_cloud("live refresh", quiet=False)
                    st.rerun()
                if st.button("Refresh comparables", use_container_width=True):
                    with st.spinner("Updating comparable evidence..."):
                        st.session_state["comp_summary"] = refresh_due_comparables(db, max_properties=35)
                        sync_cloud("comparable refresh", quiet=False)
                    st.rerun()
                if st.button("Refresh legal & planning", use_container_width=True):
                    with st.spinner("Updating due diligence..."):
                        dd_result = refresh_due_diligence(db, max_planning=35, max_legal=20, legal_access=legal_access, cloud_store=cloud_store)
                        company_result = refresh_due_company_intelligence(db, companies_house_api_key, max_companies=20)
                        st.session_state["dd_summary"] = {**dd_result, "companies_house": company_result}
                        sync_cloud("planning/legal/company refresh", quiet=False)
                    st.rerun()
            st.markdown(f'<div class="hero-updated">Last updated: {html.escape(latest_text)}</div>', unsafe_allow_html=True)
    render_refresh_summary()
elif not deal_open and lotly_page == "Pipeline":
    st.markdown('<div class="lotly-kicker">Deal management</div><div class="lotly-title">Your pipeline.</div><div class="lotly-subtitle">Move promising lots from first review to offer, negotiation and outcome without losing the evidence trail.</div>', unsafe_allow_html=True)
elif not deal_open and lotly_page == "Deal Room":
    st.markdown('<div class="lotly-kicker">Decision workspace</div><div class="lotly-title">Deal Room.</div><div class="lotly-subtitle">Jump straight into the properties that deserve deeper underwriting, legal review or negotiation.</div>', unsafe_allow_html=True)
elif not deal_open and lotly_page == "Reports":
    st.markdown('<div class="lotly-kicker">Market intelligence</div><div class="lotly-title">Reports.</div><div class="lotly-subtitle">A concise view of live stock, seller signals and auction-market movement across the opportunities Lotly is tracking.</div>', unsafe_allow_html=True)
elif not deal_open and lotly_page == "Settings":
    st.markdown('<div class="lotly-kicker">Workspace</div><div class="lotly-title">Lotly settings.</div><div class="lotly-subtitle">Tune your buying criteria, underwriting defaults and data connections.</div>', unsafe_allow_html=True)

# Build analysis rows once per Streamlit rerun.
rows = _raw_rows
history_map = _sidebar_history_map if rows else {}
underwriting_map = db.underwriting_map() if rows else {}
comparable_map = db.comparable_summary_map() if rows else {}
planning_map = db.planning_summary_map() if rows else {}
legal_map = db.legal_summary_map() if rows else {}
company_map = db.company_intelligence_map() if rows else {}
planning_flags_map = db.planning_constraint_flags_map() if rows else {}
shortlist_ids = db.shortlist_ids() if rows else set()


def _safe_underwriting_assumptions(row, saved):
    """Normalise legacy overrides so zero/blank values cannot mask stronger evidence."""
    assumptions = dict(saved or {})
    gdv_mode = str(assumptions.get("gdv_source_mode") or ("manual" if assumptions.get("gdv") else "auto")).lower()
    if not is_commercial(row) and gdv_mode != "manual":
        assumptions.pop("gdv", None)
        assumptions["use_auto_comps"] = 1

    fee_mode = str(assumptions.get("fee_source_mode") or "auto").lower()
    if fee_mode != "manual":
        for key in ("auction_admin_fee", "buyer_premium_pct", "buyer_premium_minimum", "search_fee"):
            assumptions.pop(key, None)
        # underwrite_property will now re-seed these fields from the current listing
        # evidence (or model defaults) rather than a legacy zero saved by the UI.
    return assumptions


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
    _saved_uw = underwriting_map.get(row["id"], {})
    _effective_uw = _safe_underwriting_assumptions(row, _saved_uw)
    uw = underwrite_property(
        row,
        row,
        assumptions=_effective_uw,
        defaults=underwriting_defaults,
        strategy="auto",
    )
    row.update(uw)
    row["profit_at_guide"] = None
    row["guide_all_in_cost"] = None
    if row.get("guide_price"):
        _guide_assumptions = dict(_effective_uw or {})
        _guide_assumptions["purchase_price"] = float(row.get("guide_price") or 0)
        _guide_uw = underwrite_property(row, row, assumptions=_guide_assumptions, defaults=underwriting_defaults, strategy="auto")
        row["profit_at_guide"] = _guide_uw.get("profit")
        row["guide_all_in_cost"] = _guide_uw.get("all_in_cost")
    row["browse_score"] = browse_rank(row)
    row["shortlisted"] = row["id"] in shortlist_ids
    _visit_cutoff = st.session_state.get("lotly_last_visit_cutoff") or ""
    _hist = history_map.get(row["id"], [])
    row["new_since_last_visit"] = bool(_visit_cutoff and _after_cutoff(row.get("first_seen"), _visit_cutoff))
    row["reduced_since_last_visit"] = history_reduced_since(_hist, _visit_cutoff)
    row["postauction_since_last_visit"] = history_postauction_since(_hist, _visit_cutoff)


def toggle_shortlist(row):
    enabled = row["id"] not in db.shortlist_ids()
    db.set_shortlisted(row["id"], enabled)
    sync_cloud("shortlist")
    st.rerun()


def toggle_compare(row):
    ids = set(st.session_state.get("compare_ids", []))
    if row["id"] in ids:
        ids.remove(row["id"])
    else:
        if len(ids) >= 4:
            st.toast("Compare up to four properties at a time.", icon="ℹ️")
            return
        ids.add(row["id"])
    st.session_state["compare_ids"] = sorted(ids)
    st.rerun()


def auction_timing_label(row):
    raw = str(row.get("auction_date") or "").strip()
    if not raw:
        return ""
    parsed = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(raw[:10], fmt).date()
            break
        except Exception:
            pass
    if not parsed:
        return raw
    today = datetime.now(timezone.utc).date()
    days = (parsed - today).days
    if days > 1:
        return f"Auction in {days} days · {parsed.strftime('%d %b')}"
    if days == 1:
        return f"Auction tomorrow · {parsed.strftime('%d %b')}"
    if days == 0:
        return "Auction today"
    if is_unsold(row):
        ago = abs(days)
        return f"Post-auction · {ago} day{'s' if ago != 1 else ''} since auction"
    return parsed.strftime("%d %b %Y")


def metric_grid_html(row, include_profit=True):
    metrics = [
        ("Guide", guide_display(row)),
        ("Estimated value", money(estimated_value(row))),
        ("Max buy", money(row.get("max_bid"))),
    ]
    if include_profit:
        metrics.append(("Profit at guide", money(row.get("profit_at_guide"))))
    cells = ''.join(f'<div class="metric-mini"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(str(value))}</div></div>' for label,value in metrics)
    return f'<div class="metric-grid-4">{cells}</div>'


def confidence_html(row):
    conf = int(row.get("comparable_confidence") or 0)
    count = int(row.get("comparable_count") or 0)
    if conf <= 0 and count <= 0:
        return '<div class="confidence-line"><span class="confidence-dot" style="background:#98A2B3"></span>Valuation evidence pending</div>'
    return f'<div class="confidence-line"><span class="confidence-dot"></span>Confidence {conf}% · {count} comp{"s" if count != 1 else ""}</div>'


def render_property_image(row, featured=False):
    css_class = "property-image-shell featured" if featured else "property-image-shell"
    ribbon = ""
    if row.get("new_since_last_visit"):
        ribbon = '<span class="image-ribbon">New since last visit</span>'
    elif row.get("postauction_since_last_visit"):
        ribbon = '<span class="image-ribbon">Now post-auction</span>'
    elif row.get("reduced_since_last_visit"):
        ribbon = '<span class="image-ribbon">Reduced since last visit</span>'
    image_url = str(row.get("image_url") or "").strip()
    if image_url:
        st.markdown(
            f'<div class="{css_class}">{ribbon}<img class="property-image" src="{html.escape(image_url, quote=True)}" alt="Property image"></div>',
            unsafe_allow_html=True,
        )
    else:
        logo = f'<img src="{LOTLY_ICON_DATA_URI}" alt="Lotly">' if LOTLY_ICON_DATA_URI else '<div style="font-size:1.6rem">◇</div>'
        st.markdown(
            f'<div class="{css_class}">{ribbon}<div class="property-image-placeholder">{logo}<div class="ph-title">Image being enriched</div><div class="ph-sub">Lotly will add it on the next source refresh</div></div></div>',
            unsafe_allow_html=True,
        )


def render_upside_line(row):
    parts = []
    if row.get("profit") is not None:
        parts.append(f'<span class="upside-chip">Profit at guide {money(row.get("profit_at_guide"))}</span>')
    discount = guide_to_value_discount(row)
    if discount is not None:
        parts.append(f'<span class="upside-chip">Guide {discount:.0f}% below estimated value</span>')
    if parts:
        st.markdown('<div class="upside-line">' + ''.join(parts) + '</div>', unsafe_allow_html=True)


def render_quick_look(row):
    q1, q2, q3 = st.columns(3)
    q1.metric("Guide", guide_display(row))
    q2.metric("Max buy", money(row.get("max_bid")))
    q3.metric("Lotly Score", f"{float(row.get('browse_score') or 0):.1f}/10")
    q4, q5, q6 = st.columns(3)
    q4.metric("Estimated value", money(estimated_value(row)))
    q5.metric("Profit at guide", money(row.get("profit_at_guide")))
    q6.metric("Seller motivation", f"{float(row.get('motivation_score') or 0):.1f}/10")
    discount = guide_to_value_discount(row)
    if discount is not None:
        st.caption(f"Guide is approximately {discount:.1f}% below Lotly's current estimated value.")
    st.caption(top_deal_reason(row))
    legal_label = "Verified" if legal_state(row) == "VERIFIED" else "Needs review"
    st.caption(f"Legal: {legal_label} · Planning: {planning_state(row).title()} · Comparable confidence: {int(row.get('comparable_confidence') or 0)}%")


def render_featured_property(row):
    with st.container(border=True):
        image_col, body_col = st.columns([1.18, 2.35], vertical_alignment="top")
        with image_col:
            render_property_image(row, featured=True)
        with body_col:
            top_l, top_r = st.columns([4, 1])
            with top_l:
                st.markdown('<div class="spotlight-kicker">Top opportunity</div>', unsafe_allow_html=True)
                timing = auction_timing_label(row)
                st.markdown(f'<div class="card-sub">{row.get("source") or "Auction"} · Lot {row.get("lot_number") or "-"} · {row.get("property_type") or "Property"}</div>', unsafe_allow_html=True)
                if timing:
                    st.markdown(f'<div class="card-timing">{html.escape(timing)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="spotlight-title">{clean_address(row)}</div>', unsafe_allow_html=True)
                render_badges(row, limit=3)
            with top_r:
                st.markdown(f'<div class="lotly-score-pill"><div class="num">{float(row.get("browse_score") or 0):.1f}</div><div class="lbl">Lotly Score</div></div>', unsafe_allow_html=True)
            st.markdown(metric_grid_html(row), unsafe_allow_html=True)
            st.markdown(confidence_html(row), unsafe_allow_html=True)
            if is_commercial(row) and row.get("price_per_sqft"):
                st.markdown(f'<div class="card-market-detail">Guide {money(row.get("price_per_sqft"),0)}/sq ft · {int(row.get("size_sqft") or 0):,} sq ft</div>', unsafe_allow_html=True)
            render_upside_line(row)
            st.markdown(f'<div class="card-reason"><strong>Why Lotly likes it:</strong> {top_deal_reason(row)}</div>', unsafe_allow_html=True)
            a1, a2, a3, a4 = st.columns([1.3, 1.1, 1, 1])
            with a1:
                if st.button("Open Deal Room", key=f"feature_open_{row['id']}", type="primary", use_container_width=True):
                    st.session_state["selected_deal_id"] = row["id"]
                    st.session_state["selected_deal_source_key"] = row.get("source_key")
                    st.session_state["_lotly_pending_page"] = "Deal Room"
                    st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                    st.rerun()
            with a2:
                if st.button("♥ Saved" if row.get("shortlisted") else "♡ Shortlist", key=f"feature_short_{row['id']}", use_container_width=True):
                    toggle_shortlist(row)
            with a3:
                with st.popover("Quick look", use_container_width=True):
                    render_quick_look(row)
            with a4:
                label = "✓ Compare" if row["id"] in set(st.session_state.get("compare_ids", [])) else "+ Compare"
                if st.button(label, key=f"feature_compare_{row['id']}", use_container_width=True):
                    toggle_compare(row)



def render_dashboard_card(row, top_opportunity=False):
    """Two-column Discover card with deterministic vertical alignment across every row."""
    with st.container(border=True):
        st.markdown('<span class="lotly-dashboard-card-marker"></span>', unsafe_allow_html=True)
        image_col, body_col = st.columns([1.06, 1.66], vertical_alignment="top")
        with image_col:
            css_class = "property-image-shell dashboard"
            image_url = str(row.get("image_url") or "").strip()
            ribbon = ""
            if row.get("new_since_last_visit"):
                ribbon = '<span class="image-ribbon">New</span>'
            elif row.get("postauction_since_last_visit"):
                ribbon = '<span class="image-ribbon">Post-auction</span>'
            elif row.get("reduced_since_last_visit"):
                ribbon = '<span class="image-ribbon">Reduced</span>'
            if image_url:
                st.markdown(f'<div class="{css_class}">{ribbon}<img class="property-image" src="{html.escape(image_url, quote=True)}" alt="Property image"></div>', unsafe_allow_html=True)
            else:
                logo = f'<img src="{LOTLY_ICON_DATA_URI}" alt="Lotly">' if LOTLY_ICON_DATA_URI else '<div style="font-size:1.6rem">◇</div>'
                st.markdown(f'<div class="{css_class}">{ribbon}<div class="property-image-placeholder">{logo}<div class="ph-title">Image being enriched</div><div class="ph-sub">Lotly will add it on the next source refresh</div></div></div>', unsafe_allow_html=True)
        with body_col:
            top_l, top_r = st.columns([4.3, 1.05], vertical_alignment="top")
            with top_l:
                kicker = '<div class="dashboard-kicker">Top opportunity</div>' if top_opportunity else '<div class="dashboard-kicker ghost">Top opportunity</div>'
                header_html = (
                    '<div class="dashboard-header-zone">'
                    + kicker
                    + f'<div class="card-sub">{html.escape(str(row.get("source") or "Auction"))} · Lot {html.escape(str(row.get("lot_number") or "-"))} · {html.escape(str(row.get("property_type") or "Property"))}</div>'
                    + f'<div class="property-title">{html.escape(clean_address(row))}</div>'
                    + '</div>'
                )
                st.markdown(header_html, unsafe_allow_html=True)
            with top_r:
                st.markdown(f'<div style="display:flex;justify-content:flex-end"><div class="lotly-score-mini"><div class="num">{float(row.get("browse_score") or 0):.1f}</div><div class="lbl">Lotly Score</div></div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="dashboard-badge-zone">{badges_html(row, limit=3)}</div>', unsafe_allow_html=True)
            st.markdown(metric_grid_html(row), unsafe_allow_html=True)
            st.markdown(f'<div class="dashboard-confidence-zone">{confidence_html(row)}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="dashboard-reason-zone"><div class="card-reason"><strong>Why Lotly likes it:</strong> {html.escape(top_deal_reason(row))}</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="dashboard-actions"></div>', unsafe_allow_html=True)
        with st.container(key=f"dash_actions_{row['id']}"):
            b1, b2, b3, b4 = st.columns([1.4, 1.08, 1.08, .98])
            with b1:
                if st.button("Open Deal Room  →", key=f"dash_open_{row['id']}", type="primary", use_container_width=True):
                    st.session_state["selected_deal_id"] = row["id"]
                    st.session_state["selected_deal_source_key"] = row.get("source_key")
                    st.session_state["_lotly_pending_page"] = "Deal Room"
                    st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                    st.rerun()
            with b2:
                if st.button("♥ Saved" if row.get("shortlisted") else "♡ Shortlist", key=f"dash_short_{row['id']}", use_container_width=True):
                    toggle_shortlist(row)
            with b3:
                with st.popover("Quick look  ⌄", use_container_width=True):
                    render_quick_look(row)
            with b4:
                label = "✓ Compare" if row["id"] in set(st.session_state.get("compare_ids", [])) else "+ Compare"
                if st.button(label, key=f"dash_compare_{row['id']}", use_container_width=True):
                    toggle_compare(row)


def render_compact_card(row):
    with st.container(border=True):
        st.markdown('<span class="lotly-card-marker"></span>', unsafe_allow_html=True)
        render_property_image(row, featured=False)
        head_l, head_r = st.columns([4, 1])
        with head_l:
            st.markdown(f'<div class="card-sub">{row.get("source") or "Auction"} · Lot {row.get("lot_number") or "-"} · {row.get("property_type") or "Property"}</div>', unsafe_allow_html=True)
            timing = auction_timing_label(row)
            if timing:
                st.markdown(f'<div class="card-timing">{html.escape(timing)}</div>', unsafe_allow_html=True)
        with head_r:
            st.markdown(f'<div style="display:flex;justify-content:flex-end"><div class="lotly-score-mini"><div class="num">{float(row.get("browse_score") or 0):.1f}</div><div class="lbl">Lotly Score</div></div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="property-title">{clean_address(row)}</div>', unsafe_allow_html=True)
        render_badges(row, limit=3)
        st.markdown(metric_grid_html(row), unsafe_allow_html=True)
        st.markdown(confidence_html(row), unsafe_allow_html=True)
        if is_commercial(row) and row.get("price_per_sqft"):
            st.markdown(f'<div class="card-market-detail">Guide {money(row.get("price_per_sqft"),0)}/sq ft · {int(row.get("size_sqft") or 0):,} sq ft</div>', unsafe_allow_html=True)
        render_upside_line(row)
        st.markdown(f'<div class="card-reason"><strong>Why it ranks:</strong> {top_deal_reason(row)}</div>', unsafe_allow_html=True)
        b1, b2, b3, b4 = st.columns([1.4, 1.05, 1.05, .95])
        with b1:
            if st.button("Open Deal Room", key=f"grid_open_{row['id']}", type="primary", use_container_width=True):
                st.session_state["selected_deal_id"] = row["id"]
                st.session_state["selected_deal_source_key"] = row.get("source_key")
                st.session_state["_lotly_pending_page"] = "Deal Room"
                st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                st.rerun()
        with b2:
            if st.button("♥ Saved" if row.get("shortlisted") else "♡ Shortlist", key=f"grid_short_{row['id']}", use_container_width=True):
                toggle_shortlist(row)
        with b3:
            with st.popover("Quick look", use_container_width=True):
                render_quick_look(row)
        with b4:
            label = "✓" if row["id"] in set(st.session_state.get("compare_ids", [])) else "+ Compare"
            if st.button(label, key=f"grid_compare_{row['id']}", use_container_width=True):
                toggle_compare(row)


def badges_html(row, limit=None):
    tags = []
    def add(priority, label, css=""):
        tags.append((priority, f'<span class="badge {css}">{html.escape(str(label))}</span>'))
    if row.get("status"):
        css = "badge-hot" if is_unsold(row) or row.get("status") == "Relisted" else ""
        add(100, row.get("status"), css)
    if legal_state(row) != "VERIFIED":
        label = "Legal unverified" if legal_state(row) in {"CANDIDATES ONLY", "UNVERIFIED", "VERIFIED NO TEXT"} else "Legal not reviewed"
        add(96, label, "badge-risk")
    if row.get("short_lease_signal"):
        yrs = row.get("effective_lease_years") or row.get("listing_lease_years") or row.get("legal_lease_years")
        label = f"Short lease ~{float(yrs):.0f}y" if yrs else "Short lease"
        add(95, label, "badge-risk")
    if row.get("listed_building_signal") or row.get("planning_listed_flag"):
        add(94, "Listed / heritage", "badge-risk")
    if float(row.get("corporate_pressure_score") or 0) >= 7:
        add(92, f"Corporate pressure {float(row.get('corporate_pressure_score')):.1f}/10", "badge-risk")
    if (row.get("price_reduction_pct") or 0) > 0:
        add(90, f"Guide down {float(row.get('price_reduction_pct')):.1f}%", "badge-good")
    if (row.get("failure_count") or 0) > 0:
        add(86, f"Failed {int(row.get('failure_count') or 0)}x", "badge-hot")
    if row.get("max_bid_provisional"):
        add(82, "Max buy provisional", "badge-risk")
    if (row.get("features") or {}).get("vacant"):
        add(65, "Vacant")
    tags.sort(key=lambda x: x[0], reverse=True)
    visible = tags if limit is None else tags[:limit]
    html_tags = [x[1] for x in visible]
    if limit is not None and len(tags) > limit:
        html_tags.append(f'<span class="badge badge-more">+{len(tags)-limit} more</span>')
    return "".join(html_tags)


def render_badges(row, limit=None):
    st.markdown(badges_html(row, limit=limit), unsafe_allow_html=True)


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
                b.metric("Estimated value", money(row.get("market_value") or row.get("comparable_valuation_mid")))
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
                st.session_state["selected_deal_source_key"] = row.get("source_key")
                st.session_state["_lotly_pending_page"] = "Deal Room"
                st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                st.rerun()
            star = "Remove" if row.get("shortlisted") else "Shortlist"
            if st.button(star, key=f"short_{row['id']}", use_container_width=True):
                toggle_shortlist(row)


def underwriting_form(chosen):
    saved = db.underwriting_for(chosen["id"])
    strategy = "commercial" if is_commercial(chosen) else "residential"

    # Provenance-aware defaults. Automated evidence is displayed to the user but is
    # not silently persisted as a manual override. This prevents a blank/zero field
    # from replacing stronger automated valuation or fee evidence.
    auto_gdv = float(chosen.get("comparable_valuation_mid") or chosen.get("market_value") or 0)
    saved_gdv = float(saved.get("gdv") or 0)
    gdv_mode_saved = str(saved.get("gdv_source_mode") or ("manual" if saved_gdv else "auto")).lower()
    if gdv_mode_saved not in {"auto", "manual"}:
        gdv_mode_saved = "auto"

    detected_pct = chosen.get("detected_buyer_premium_pct")
    detected_min = chosen.get("detected_buyer_premium_minimum")
    detected_search = chosen.get("detected_search_fee")
    detected_fixed = chosen.get("detected_auction_admin_fee_fixed")
    listing_fee_evidence = any(v is not None for v in (detected_pct, detected_min, detected_search, detected_fixed))
    auto_fee_values = {
        "auction_admin_fee": float(detected_fixed if detected_fixed is not None else (0.0 if detected_pct is not None else underwriting_defaults.auction_admin_fee)),
        "buyer_premium_pct": float(detected_pct or 0.0),
        "buyer_premium_minimum": float(detected_min or 0.0),
        "search_fee": float(detected_search or 0.0),
    }
    fee_mode_saved = str(saved.get("fee_source_mode") or "").lower()
    if fee_mode_saved not in {"auto", "manual"}:
        # Legacy saves wrote every visible field, including zeros. Treat a saved zero
        # as non-authoritative when stronger listing evidence now exists.
        materially_different = False
        for key, auto_value in auto_fee_values.items():
            raw = saved.get(key)
            if raw is None:
                continue
            saved_value = float(raw or 0)
            if saved_value > 0 and abs(saved_value - auto_value) > 0.01:
                materially_different = True
        fee_mode_saved = "manual" if materially_different else "auto"

    st.caption("Save property-specific assumptions. Automated evidence stays authoritative until you explicitly choose a manual override.")
    with st.form(f"uw_{chosen['id']}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            purchase_price = st.number_input("Working purchase price", min_value=0.0, value=float(saved.get("purchase_price") or chosen.get("opening_offer") or chosen.get("guide_price") or 0), step=1000.0)
            refurb_cost = st.number_input("Refurbishment / works", min_value=0.0, value=float(saved.get("refurb_cost") or 0), step=1000.0)
            contingency_pct = st.number_input("Works contingency %", min_value=0.0, value=float(saved.get("contingency_pct") if saved.get("contingency_pct") is not None else 10.0), step=1.0)
        with c2:
            if strategy == "residential":
                gdv_source = st.selectbox(
                    "GDV source",
                    ["Automatic comparable midpoint", "Manual override"],
                    index=1 if gdv_mode_saved == "manual" else 0,
                    help="Automatic keeps the HM Land Registry comparable midpoint live. Manual override freezes your own value until you switch back.",
                )
                gdv_display = saved_gdv if gdv_mode_saved == "manual" and saved_gdv else auto_gdv
                gdv = st.number_input("GDV / resale value", min_value=0.0, value=float(gdv_display or 0), step=5000.0)
                if gdv_source == "Automatic comparable midpoint":
                    st.caption(f"AUTO · HM Land Registry PPD · {int(chosen.get('comparable_confidence') or 0)}% evidence confidence. Saving will not convert this to a manual override.")
                else:
                    st.caption("MANUAL · Your override will take precedence over the automated comparable midpoint until changed.")
                market_psf = 0.0
                manual_market_value = 0.0
                erv_annual = 0.0
                exit_yield_pct = 0.0
                target_profit_margin_pct = st.number_input("Target profit margin % of GDV", min_value=0.0, max_value=80.0, value=float(saved.get("target_profit_margin_pct") if saved.get("target_profit_margin_pct") is not None else underwriting_defaults.target_residential_profit_margin_pct), step=1.0)
                target_equity_margin_pct = 20.0
                use_auto = gdv_source == "Automatic comparable midpoint"
            else:
                gdv_source = "Automatic comparable midpoint"
                gdv = 0.0
                market_psf = st.number_input("Market GBP / sq ft", min_value=0.0, value=float(saved.get("market_psf") or 0), step=5.0)
                manual_market_value = st.number_input("Manual market value", min_value=0.0, value=float(saved.get("manual_market_value") or 0), step=5000.0)
                erv_annual = st.number_input("ERV annual", min_value=0.0, value=float(saved.get("erv_annual") or 0), step=1000.0)
                exit_yield_pct = st.number_input("Exit yield %", min_value=0.0, value=float(saved.get("exit_yield_pct") or 0), step=0.25)
                target_equity_margin_pct = st.number_input("Target equity uplift %", min_value=0.0, max_value=80.0, value=float(saved.get("target_equity_margin_pct") if saved.get("target_equity_margin_pct") is not None else underwriting_defaults.target_commercial_equity_margin_pct), step=1.0)
                target_profit_margin_pct = 20.0
                use_auto = st.checkbox("Use automatic commercial comparable value", value=bool(saved.get("use_auto_comps")))
        with c3:
            fee_options = ["Detected listing evidence", "Manual override"] if listing_fee_evidence else ["Model defaults", "Manual override"]
            fee_source = st.selectbox(
                "Auction fee source",
                fee_options,
                index=1 if fee_mode_saved == "manual" else 0,
                help="Detected listing evidence is protected from accidental zero-value overrides. Choose Manual override only when you have better evidence.",
            )
            use_auto_fees = fee_source != "Manual override"
            auction_admin_default = auto_fee_values["auction_admin_fee"]
            buyer_pct_default = auto_fee_values["buyer_premium_pct"]
            buyer_min_default = auto_fee_values["buyer_premium_minimum"]
            search_default = auto_fee_values["search_fee"]
            auction_admin_fee = st.number_input("Additional fixed auction/admin fee", min_value=0.0, value=float(saved.get("auction_admin_fee") if fee_mode_saved == "manual" and saved.get("auction_admin_fee") is not None else auction_admin_default), step=100.0)
            buyer_premium_pct = st.number_input("Buyer/admin fee %", min_value=0.0, value=float(saved.get("buyer_premium_pct") if fee_mode_saved == "manual" and saved.get("buyer_premium_pct") is not None else buyer_pct_default), step=0.25)
            buyer_premium_minimum = st.number_input("Minimum buyer/admin fee", min_value=0.0, value=float(saved.get("buyer_premium_minimum") if fee_mode_saved == "manual" and saved.get("buyer_premium_minimum") is not None else buyer_min_default), step=100.0)
            search_fee = st.number_input("Search fee", min_value=0.0, value=float(saved.get("search_fee") if fee_mode_saved == "manual" and saved.get("search_fee") is not None else search_default), step=50.0)
            preview_pct = buyer_pct_default if use_auto_fees else buyer_premium_pct
            preview_min = buyer_min_default if use_auto_fees else buyer_premium_minimum
            preview_fixed = auction_admin_default if use_auto_fees else auction_admin_fee
            preview_search = search_default if use_auto_fees else search_fee
            effective_buyer_fee = max(float(purchase_price or 0) * preview_pct / 100, preview_min) if (preview_pct or preview_min) else 0.0
            source_tag = "LISTING EVIDENCE" if listing_fee_evidence and use_auto_fees else "MODEL DEFAULT" if use_auto_fees else "MANUAL"
            st.caption(f"{source_tag} · Effective fees at the working price: {money(preview_fixed + effective_buyer_fee + preview_search)} ({money(effective_buyer_fee)} buyer/admin).")
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
        notes = st.text_area("Deal notes / evidence", value=str(saved.get("underwriting_notes") or ""), placeholder="Agent feedback, works quote, ERV evidence, local comparable, title point...")
        save = st.form_submit_button("Save and recalculate", type="primary", use_container_width=True)
        if save:
            if strategy == "residential":
                gdv_to_save = None if gdv_source == "Automatic comparable midpoint" else (gdv or None)
                gdv_source_mode = "auto" if gdv_source == "Automatic comparable midpoint" else "manual"
            else:
                gdv_to_save = None
                gdv_source_mode = None
            if use_auto_fees:
                fee_values = auto_fee_values
                fee_source_mode = "auto"
            else:
                fee_values = {
                    "auction_admin_fee": auction_admin_fee,
                    "buyer_premium_pct": buyer_premium_pct,
                    "buyer_premium_minimum": buyer_premium_minimum,
                    "search_fee": search_fee,
                }
                fee_source_mode = "manual"
            db.save_underwriting(chosen["id"], {
                "strategy": strategy,
                "purchase_price": purchase_price or None,
                "gdv": gdv_to_save,
                "market_psf": market_psf or None,
                "manual_market_value": manual_market_value or None,
                "erv_annual": erv_annual or None,
                "exit_yield_pct": exit_yield_pct or None,
                "refurb_cost": refurb_cost or 0,
                "capex_cost": 0,
                "contingency_pct": contingency_pct,
                "auction_admin_fee": fee_values["auction_admin_fee"],
                "buyer_premium_pct": fee_values["buyer_premium_pct"],
                "buyer_premium_minimum": fee_values["buyer_premium_minimum"],
                "search_fee": fee_values["search_fee"],
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
                "gdv_source_mode": gdv_source_mode,
                "fee_source_mode": fee_source_mode,
            })
            sync_cloud("underwriting", quiet=False)
            st.rerun()

def render_deal_room(chosen):
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

    # v1.14.0 — the Guided Deal Room must never present legacy comparable scoring as
    # current evidence. Attempt one transparent migration refresh per property/session.
    deal_comps = db.comparables_for(chosen["id"])
    legacy_comps = (not is_commercial(chosen)) and bool(deal_comps) and any(
        (c.get("metadata") or {}).get("scoring_version") != "residential-v2" for c in deal_comps
    )
    _legacy_attempt_key = f"lotly_legacy_comp_refresh_{chosen['id']}"
    if legacy_comps and not st.session_state.get(_legacy_attempt_key):
        st.session_state[_legacy_attempt_key] = True
        try:
            with st.spinner("Updating this property's comparable evidence to Lotly's current matching model..."):
                _legacy_result = refresh_property_comparables(db, chosen)
            if _legacy_result.get("status") == "ok":
                sync_cloud("legacy comparable migration", quiet=True)
                st.session_state["_comparable_refresh_notice"] = "Lotly automatically upgraded this property's comparable evidence to the current matching model before using it in the Guided Deal Room."
                st.session_state["selected_deal_id"] = chosen.get("id")
                if chosen.get("source_key"):
                    st.session_state["selected_deal_source_key"] = chosen.get("source_key")
                st.session_state["_lotly_pending_page"] = "Deal Room"
                st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                st.rerun()
            else:
                st.session_state["_guided_legacy_comp_warning"] = str(_legacy_result.get("error") or "Comparable refresh could not complete")[:500]
        except Exception as exc:
            st.session_state["_guided_legacy_comp_warning"] = str(exc)[:500]

    # v1.13.13 — normalise contradictory auction observations before they influence
    # seller leverage. Raw history remains untouched for audit/debug purposes.
    auction_integrity = auction_history_integrity(chosen, hist)
    deal_analysis = dict(chosen)
    deal_analysis["verified_failure_count"] = int(auction_integrity.get("verified_failure_count") or 0)
    deal_analysis["returned_to_market_count"] = int(auction_integrity.get("returned_to_market_count") or 0)
    deal_analysis["auction_history_conflict"] = bool(auction_integrity.get("sale_status_conflict"))
    story = build_vendor_story(chosen, hist, deal_analysis, legal_summary, planning_items, effective_company_summary)
    readiness = deal_readiness(chosen)
    actions = next_actions(chosen, story)
    profile = story.get("seller_profile") or {}
    seller_plan = seller_negotiation_plan(chosen, story, readiness)
    workspace_state = db.workspace_for(chosen["id"])
    investment_strategy = str(workspace_state.get("investment_strategy") or "Flip")
    if investment_strategy not in {"Flip", "Buy & Keep"}:
        investment_strategy = "Flip"
    deal_underwriting = db.underwriting_for(chosen["id"])
    deal_rental_comps = db.rental_comparables_for(chosen["id"])
    deal_legal_documents = db.legal_documents_for(chosen["id"])
    # Re-read after any non-rerunning legacy attempt so the UI can correctly label
    # provisional/current comparable evidence in the same request.
    deal_comps = db.comparables_for(chosen["id"])
    evidence_confidence = evidence_confidence_summary(chosen, legal_summary, deal_comps)
    due_diligence = due_diligence_beginner_summary(
        chosen, legal_summary, planning_items, deal_legal_documents, hist, deal_comps
    )
    guided_location = location_beginner_summary(
        chosen, deal_comps, planning_items, deal_underwriting, deal_rental_comps
    )


    def _safe(value):
        return html.escape(str(value if value not in (None, "") else "-"))

    def _metric_html(label, value, sub=""):
        return (
            '<div class="deal-metric-card">'
            f'<div class="label">{_safe(label)}</div>'
            f'<div class="value">{_safe(value)}</div>'
            f'<div class="sub">{_safe(sub)}</div>'
            '</div>'
        )

    recommendation = str(chosen.get("recommendation") or "WATCH").upper()
    readiness_status = str(readiness.get("readiness_status") or "Reviewing")
    hero_decision = "DO NOT PROCEED" if recommendation == "PASS" else ("DO NOT BID" if readiness_status == "BID BLOCKED" else recommendation)
    rec_class = "pass" if hero_decision in {"PASS", "DO NOT BID", "DO NOT PROCEED"} else ("watch" if hero_decision == "WATCH" else "")
    estimated = chosen.get("market_value") or chosen.get("comparable_valuation_mid")
    next_action_text = actions[0].get("action") if actions else (chosen.get("recommended_action") or "Continue due diligence")
    next_action_reason = actions[0].get("reason") if actions else "Complete the remaining evidence checks before committing capital."
    deal_brief = deal_brief_markdown(chosen, story, readiness, actions)

    if st.button("← Back to Deal Room", key=f"deal_back_{chosen['id']}"):
        st.session_state.pop("selected_deal_id", None)
        st.session_state["_lotly_pending_page"] = "Deal Room"
        st.rerun()

    with st.container(border=False, key=f"dealroom_hero_{chosen['id']}"):
        image_col, body_col = st.columns([1.18, 2.82], vertical_alignment="top")
        with image_col:
            render_property_image(chosen, featured=True)
        with body_col:
            title_col, score_col = st.columns([5.0, 1.0], vertical_alignment="top")
            with title_col:
                st.markdown('<div class="deal-room-kicker">Lotly Deal Room · Decision workspace</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="deal-room-meta">{_safe(chosen.get("source") or "Auction")} · Lot {_safe(chosen.get("lot_number") or "-")} · {_safe(chosen.get("property_type") or "Property")} · {_safe(chosen.get("status") or "Live")}</div>'
                    f'<div class="deal-room-address">{html.escape(clean_address(chosen))}</div>',
                    unsafe_allow_html=True,
                )
                render_badges(chosen, limit=5)
            with score_col:
                st.markdown(
                    f'<div class="deal-score-panel"><div class="num">{float(chosen.get("browse_score") or 0):.1f}</div><div class="lbl">Lotly Score</div></div>',
                    unsafe_allow_html=True,
                )

            metrics = [
                _metric_html("Guide", guide_display(chosen), "Current auction guide"),
                _metric_html("Estimated value / GDV", money(estimated), f'{int(chosen.get("comparable_confidence") or 0)}% comp confidence · {str(evidence_confidence.get("state") or "LOW").title()}'),
                _metric_html("Opening price test", money(chosen.get("opening_offer")), "Non-binding while STOP items remain" if readiness_status == "BID BLOCKED" else "Negotiation starting point"),
                _metric_html("Max buy", money(chosen.get("max_bid")), "Provisional" if chosen.get("max_bid_provisional") or evidence_confidence.get("state") != "SUPPORTED" else "Supported ceiling"),
                _metric_html("Profit @ working price", money(chosen.get("profit")), f"At {money(chosen.get('working_purchase_price'))} purchase · {pct(chosen.get('roi_pct'))} ROI" if chosen.get("roi_pct") is not None else f"At {money(chosen.get('working_purchase_price'))} purchase"),
            ]
            st.markdown('<div class="deal-metric-grid">' + ''.join(metrics) + '</div>', unsafe_allow_html=True)

            st.markdown(
                f'<div class="deal-decision-panel"><div class="deal-decision-word {rec_class}">{_safe(hero_decision)}</div>'
                f'<div class="deal-decision-copy"><strong>{_safe(readiness.get("readiness_status") or "Reviewing")}</strong> · {int(readiness.get("readiness_pct") or 0)}% decision-ready.<br>'
                f'Next move: <strong>{_safe(next_action_text)}</strong></div></div>',
                unsafe_allow_html=True,
            )

            legal_pct = int(chosen.get("legal_pack_completeness_pct") or 0)
            legal_state_value = legal_state(chosen)
            legal_pack_changed = bool(legal_summary.get("pack_changed") or chosen.get("legal_pack_changed"))
            legal_ok = legal_state_value == "VERIFIED" and legal_pct >= 100 and not legal_pack_changed
            if legal_ok:
                legal_display = "100% verified"
            elif legal_state_value == "VERIFIED" and legal_pct > 0:
                legal_display = f"{legal_pct}% verified — incomplete"
            elif legal_pct > 0:
                legal_display = f"{legal_pct}% checked — review"
            else:
                legal_display = legal_state_value.title()
            planning_ok = planning_state(chosen) == "SCREENED"
            comp_conf = int(chosen.get("comparable_confidence") or 0)
            uw_conf = int(chosen.get("underwriting_confidence") or 0)
            evidence_html = [
                f'<div class="deal-evidence-item"><span><i class="deal-evidence-dot {"" if comp_conf >= 70 else "warn"}"></i>Comparables</span><strong>{comp_conf}%</strong></div>',
                f'<div class="deal-evidence-item"><span><i class="deal-evidence-dot {"" if legal_ok else "warn"}"></i>Legal pack</span><strong>{_safe(legal_display)}</strong></div>',
                f'<div class="deal-evidence-item"><span><i class="deal-evidence-dot {"" if planning_ok else "warn"}"></i>Planning</span><strong>{_safe(planning_state(chosen).title())}</strong></div>',
                f'<div class="deal-evidence-item"><span><i class="deal-evidence-dot {"" if uw_conf >= 70 else "warn"}"></i>Underwriting</span><strong>{uw_conf}%</strong></div>',
            ]
            st.markdown('<div class="deal-evidence-grid">' + ''.join(evidence_html) + '</div>', unsafe_allow_html=True)

            a1, a2, a3, a4 = st.columns(4)
            with a1:
                if st.button("Remove shortlist" if chosen.get("shortlisted") else "Add to shortlist", key=f"deal_short_{chosen['id']}", use_container_width=True):
                    toggle_shortlist(chosen)
            with a2:
                if chosen.get("url"):
                    st.link_button("Auction listing", chosen["url"], use_container_width=True)
                else:
                    st.button("Auction listing", disabled=True, key=f"no_listing_{chosen['id']}", use_container_width=True)
            with a3:
                if profile.get("company_number"):
                    st.link_button("Companies House", f"https://find-and-update.company-information.service.gov.uk/company/{profile['company_number']}", use_container_width=True)
                else:
                    st.button("Seller record pending", disabled=True, key=f"no_ch_{chosen['id']}", use_container_width=True)
            with a4:
                st.download_button(
                    "Download deal brief", deal_brief,
                    file_name=f"lotly-deal-{chosen.get('postcode') or chosen.get('id')}.md".replace(" ", "-"),
                    mime="text/markdown", key=f"hero_brief_{chosen['id']}", use_container_width=True,
                )

    with st.container(border=False, key=f"dealroom_body_{chosen['id']}"):
        deal_tab_labels = ["Guided View", "Seller", "Financials", "Comparables", "Auction", "Legal & Planning", "Location", "Workspace"]
        pending_deal_tab = st.session_state.pop("lotly_deal_tab_pending", None)
        if pending_deal_tab == "Snapshot":
            pending_deal_tab = "Guided View"
        if pending_deal_tab in deal_tab_labels:
            # Apply queued navigation before the stateful tab widget is instantiated.
            st.session_state["lotly_deal_tab"] = pending_deal_tab
        tabs = st.tabs(deal_tab_labels, key="lotly_deal_tab", on_change="rerun")

        with tabs[0]:
            # v1.14.0 — Beginner-first Guided Deal Room.  This is the default front
            # door; the detailed tabs remain the evidence layer underneath it.
            guide = float(chosen.get("guide_price") or 0)
            estimated_value = float(estimated or 0)
            comp_conf = int(chosen.get("comparable_confidence") or 0)
            uw_conf = int(chosen.get("underwriting_confidence") or 0)
            working_price = float(chosen.get("working_purchase_price") or guide or 0)
            max_buy = float(chosen.get("max_bid") or 0)
            works_cost = float(chosen.get("works_cost") or 0)
            all_in = float(chosen.get("all_in_cost") or 0)
            profit = chosen.get("profit")
            roi = chosen.get("roi_pct")
            guide_discount = chosen.get("comparable_guide_discount_pct")
            if guide_discount is None and guide and estimated_value:
                guide_discount = max(0.0, (estimated_value - guide) / estimated_value * 100)

            def _jump_deal(tab_name):
                st.session_state["lotly_deal_tab_pending"] = tab_name
                st.rerun()

            # Strategy selector: Flip vs Buy & Keep is persisted per deal and changes
            # what the beginner financial card prioritises.
            st.markdown('<div class="deal-section-title"><span class="num">1</span><span class="txt">What are you planning to do with this property?</span><span class="sub">Lotly changes the decision view to match your strategy.</span></div>', unsafe_allow_html=True)
            with st.container(key="guided_strategy"):
                strategy_choice = st.segmented_control(
                    "Investment strategy",
                    ["Flip", "Buy & Keep"],
                    default=investment_strategy,
                    key=f"guided_strategy_choice_{chosen['id']}",
                    label_visibility="collapsed",
                ) or investment_strategy
            if strategy_choice != investment_strategy:
                db.save_investment_strategy(chosen["id"], strategy_choice)
                investment_strategy = strategy_choice
                workspace_state["investment_strategy"] = strategy_choice
                sync_cloud("investment strategy", quiet=True)

            # Current beginner decision. PASS means pass on the opportunity; BID BLOCKED
            # means the numbers may still be interesting but commitment is unsafe.
            legal_stop = any(c.get("status") == "STOP" for c in due_diligence.get("checks") or [])
            rental_supported = len([r for r in deal_rental_comps if float(r.get("monthly_rent") or 0) > 0]) >= 3 or bool(deal_underwriting.get("erv_annual"))
            funding_position = str(workspace_state.get("funding_position") or "").strip()
            funding_completion_status = str(workspace_state.get("funding_completion_status") or "").strip()
            funding_confirmed = funding_completion_status == "Yes — confirmed" and funding_position in {"Cash available", "Mortgage/bridge approved"}
            return_positive = float(profit or 0) > 0
            evidence_state = str(evidence_confidence.get("state") or "LOW")

            if recommendation == "PASS":
                guided_decision = "DO NOT PROCEED"
                guided_tone = "risk"
                guided_copy = "The current economics or risk profile do not justify progressing on the assumptions Lotly has."
            elif legal_stop or readiness_status == "BID BLOCKED":
                guided_decision = "KEEP INVESTIGATING"
                guided_tone = ""
                guided_copy = "The opportunity may be attractive, but a red STOP item means you should not bid or make anything binding yet."
            elif investment_strategy == "Buy & Keep" and not rental_supported:
                guided_decision = "KEEP INVESTIGATING"
                guided_tone = ""
                guided_copy = "The purchase may stack up, but Buy & Keep still needs evidence-backed rent before Lotly can support the strategy."
            elif evidence_state == "LOW":
                guided_decision = "KEEP INVESTIGATING"
                guided_tone = ""
                guided_copy = "Too much of the valuation or due-diligence evidence is still missing for a confident purchase decision."
            elif funding_confirmed and readiness_status in {"READY FOR FINAL REVIEW", "NEARLY READY"}:
                guided_decision = "READY TO BID / OFFER"
                guided_tone = "good"
                guided_copy = "The critical automated checks are resolved. Keep to the supported ceiling and complete final professional review before commitment."
            elif float(seller_plan.get("leverage_score") or 0) >= 4 and return_positive:
                guided_decision = "READY TO NEGOTIATE"
                guided_tone = "good"
                guided_copy = "The numbers show potential and there are negotiation signals. Use a non-binding price test while remaining checks are completed."
            else:
                guided_decision = "KEEP INVESTIGATING"
                guided_tone = ""
                guided_copy = "The deal still needs more evidence before Lotly can support a purchase decision."

            if legal_stop:
                guided_next = "Get and review the legal pack"
                guided_next_copy = "Download the latest pack/addendum from the auctioneer and upload it to Lotly."
                guided_next_tab = "Legal & Planning"
            elif evidence_confidence.get("legacy_comparables") or comp_conf < 65:
                guided_next = "Strengthen the valuation evidence"
                guided_next_copy = "Refresh or review the closest sold comparables before relying on the modelled value or max buy."
                guided_next_tab = "Comparables"
            elif investment_strategy == "Buy & Keep" and not rental_supported:
                guided_next = "Evidence the achievable rent"
                guided_next_copy = "Add at least three current rental comparables before relying on yield or cash flow."
                guided_next_tab = "Location"
            elif not funding_confirmed:
                guided_next = "Confirm your funding can complete in time"
                guided_next_copy = "Record cash or approved finance and confirm it can meet the contractual completion deadline."
                guided_next_tab = "Workspace"
            else:
                guided_next = next_action_text
                guided_next_copy = next_action_reason
                guided_next_tab = "Workspace"

            icon = "⛔" if guided_tone == "risk" else "✓" if guided_tone == "good" else "!"
            st.markdown(
                f'<div class="deal-guided-intro">'
                f'<div class="deal-guided-verdict {guided_tone}"><div class="icon">{icon}</div><div><div class="q">Should I buy this property?</div><div class="view">Lotly view: {html.escape(guided_decision.title())}</div><div class="copy">{html.escape(guided_copy)}</div></div></div>'
                f'<div class="deal-guided-next"><div class="label">Your next action</div><div class="title">{html.escape(str(guided_next))}</div><div class="copy">{html.escape(str(guided_next_copy))}</div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button(f"Go to next action → {guided_next_tab}", key=f"guided_next_{chosen['id']}", type="primary", use_container_width=True):
                _jump_deal(guided_next_tab)

            legacy_warning = st.session_state.pop("_guided_legacy_comp_warning", None)
            if legacy_warning:
                st.warning("Lotly could not automatically upgrade the older comparable model on this visit. Valuation-derived figures remain provisional until Comparables is refreshed. " + legacy_warning)

            # Decision journey — one visual path. Each stage comes from the same
            # canonical evidence used by the detailed tabs.
            price_good = bool(guide_discount is not None and float(guide_discount) >= 10 and estimated_value)
            numbers_good = bool(return_positive and not chosen.get("works_missing"))
            value_good = evidence_state == "SUPPORTED" and comp_conf >= 70
            legal_good = not legal_stop and legal_state(chosen) == "VERIFIED" and int(chosen.get("legal_pack_completeness_pct") or 0) >= 100
            location_tone = str(guided_location.get("verdict_tone") or "warn")
            decision_class = "risk" if guided_tone == "risk" else "good" if guided_tone == "good" else "warn"
            journey = [
                ("Price", "Looks attractive" if price_good else "Needs context", "good" if price_good else "warn"),
                ("Numbers", "Works financially" if numbers_good else "Check costs", "good" if numbers_good else "warn"),
                ("Value", "Supported" if value_good else "Needs review", "good" if value_good else "warn" if comp_conf >= 50 else "risk"),
                ("Legal", "Clear" if legal_good else "Stop" if legal_stop else "Check", "good" if legal_good else "risk" if legal_stop else "warn"),
                ("Location", str(guided_location.get("verdict") or "Check").replace(" — ", " · ")[:34], "good" if location_tone == "good" else "warn"),
                ("Funding", "Confirmed" if funding_confirmed else "Not confirmed", "good" if funding_confirmed else "neutral"),
                ("Decision", guided_decision.replace("DO NOT PROCEED", "Stop").replace("KEEP INVESTIGATING", "Keep investigating").replace("READY TO BID / OFFER", "Ready").replace("READY TO NEGOTIATE", "Negotiate"), decision_class),
            ]
            journey_html = ''.join(
                f'<div class="deal-journey-step {tone}"><div class="top"><span class="dot">{i}</span><span class="name">{html.escape(name)}</span></div><div class="state">{html.escape(state)}</div></div>'
                for i, (name, state, tone) in enumerate(journey, start=1)
            )
            st.markdown('<div class="deal-section-title"><span class="num">2</span><span class="txt">Your decision journey</span><span class="sub">Green means supported, amber means check, red means stop.</span></div>' + f'<div class="deal-journey">{journey_html}</div>', unsafe_allow_html=True)

            # Valuation card.
            valuation_state = "SUPPORTED" if (comp_conf >= 75 and int(chosen.get("comparable_count") or 0) >= 5 and not evidence_confidence.get("legacy_comparables")) else "PROVISIONAL" if comp_conf >= 50 else "LOW"
            value_low = chosen.get("comparable_valuation_low")
            value_high = chosen.get("comparable_valuation_high")
            valuation_status_class = valuation_state.lower()
            valuation_card = (
                '<div class="deal-guided-card">'
                '<div class="eyebrow">3 · Value</div><div class="title">What is it really worth?</div>'
                f'<span class="deal-status-pill {valuation_status_class}">{html.escape(valuation_state)}</span>'
                f'<div class="big" style="margin-top:8px">{html.escape(money(estimated_value))}</div>'
                f'<div class="muted">Lotly modelled midpoint · {comp_conf}% comparable confidence</div>'
                f'<div class="row"><span>Low evidence range</span><strong>{html.escape(money(value_low))}</strong></div>'
                f'<div class="row"><span>High evidence range</span><strong>{html.escape(money(value_high))}</strong></div>'
                f'<div class="row"><span>Guide vs midpoint</span><strong>{html.escape(f"{float(guide_discount):.1f}% below" if guide_discount is not None else "Not evidenced")}</strong></div>'
                '<div class="footer">Backed by nearby sold-price evidence. This is a desktop acquisition estimate, not a RICS valuation.</div></div>'
            )

            # Strategy-specific financial card.
            if investment_strategy == "Buy & Keep":
                rents = sorted(float(r.get("monthly_rent") or 0) for r in deal_rental_comps if float(r.get("monthly_rent") or 0) > 0)
                rent_median = None
                if rents:
                    n = len(rents)
                    rent_median = rents[n // 2] if n % 2 else (rents[n // 2 - 1] + rents[n // 2]) / 2
                if rent_median is None and deal_underwriting.get("erv_annual"):
                    rent_median = float(deal_underwriting.get("erv_annual") or 0) / 12
                gross_yield = (rent_median * 12 / working_price * 100) if rent_median and working_price else None
                equity = (estimated_value - all_in) if estimated_value and all_in else None
                financial_card = (
                    '<div class="deal-guided-card"><div class="eyebrow">4 · Money</div><div class="title">What could I make? · Buy & Keep</div>'
                    f'<div class="row"><span>Working purchase</span><strong>{html.escape(money(working_price))}</strong></div>'
                    f'<div class="row"><span>Total investment</span><strong>{html.escape(money(all_in))}</strong></div>'
                    f'<div class="row"><span>Evidence-backed rent</span><strong>{html.escape(money(rent_median) + "/mo" if rent_median else "Not evidenced")}</strong></div>'
                    f'<div class="row"><span>Gross yield</span><strong>{html.escape(f"{gross_yield:.1f}%" if gross_yield is not None else "Pending rent evidence")}</strong></div>'
                    f'<div class="row"><span>Modelled equity</span><strong>{html.escape(money(equity))}</strong></div>'
                    '<div class="footer">Lotly will not guess rent. Monthly cash flow needs mortgage/finance and ongoing-cost inputs as well as supported rent.</div></div>'
                )
            else:
                financial_card = (
                    '<div class="deal-guided-card"><div class="eyebrow">4 · Money</div><div class="title">What could I make? · Flip</div>'
                    f'<div class="row"><span>Working purchase</span><strong>{html.escape(money(working_price))}</strong></div>'
                    f'<div class="row"><span>Refurbishment / works</span><strong>{html.escape("Not confirmed" if chosen.get("works_missing") else money(works_cost))}</strong></div>'
                    f'<div class="row"><span>Total investment</span><strong>{html.escape(money(all_in))}</strong></div>'
                    f'<div class="row"><span>Modelled resale value</span><strong>{html.escape(money(estimated_value))}</strong></div>'
                    f'<div class="row"><span>Potential profit</span><strong>{html.escape(money(profit))}</strong></div>'
                    f'<div class="row"><span>ROI</span><strong>{html.escape(f"{float(roi):.1f}%" if roi is not None else "-")}</strong></div>'
                    '<div class="footer">Includes the current Lotly cost stack: tax, auction/admin, legal/DD, finance, works, contingency, holding and exit costs where entered/detected.</div></div>'
                )

            # Canonical negotiation card: same score and interpretation as Seller tab.
            leverage_score = float(seller_plan.get("leverage_score") or 0)
            negotiation_card = (
                '<div class="deal-guided-card"><div class="eyebrow">5 · Seller</div><div class="title">Can I negotiate?</div>'
                f'<div class="big">{html.escape(str(seller_plan.get("position") or "Limited"))}</div>'
                f'<div class="muted">{leverage_score:.1f}/10 · {html.escape(str(seller_plan.get("signal_confidence_label") or "Negotiation evidence"))}</div>'
                f'<div class="row"><span>Suggested price test</span><strong>{html.escape(money(seller_plan.get("opening_offer")))}</strong></div>'
                f'<div class="row"><span>Modelled ceiling</span><strong>{html.escape(money(max_buy))}</strong></div>'
                f'<div class="row"><span>Auction state</span><strong>{html.escape(str(auction_integrity.get("stage") or "Check"))}</strong></div>'
                f'<div class="footer">{html.escape(str(seller_plan.get("offer_instruction") or "Establish the seller position before moving upward."))}</div></div>'
            )
            st.markdown('<div class="deal-guided-grid">' + valuation_card + financial_card + negotiation_card + '</div>', unsafe_allow_html=True)
            nav1, nav2, nav3 = st.columns(3)
            with nav1:
                if st.button("View comparable evidence", key=f"guided_comps_{chosen['id']}", use_container_width=True):
                    _jump_deal("Comparables")
            with nav2:
                if st.button("View full financial breakdown", key=f"guided_fin_{chosen['id']}", use_container_width=True):
                    _jump_deal("Financials")
            with nav3:
                if st.button("View seller & negotiation evidence", key=f"guided_seller_{chosen['id']}", use_container_width=True):
                    _jump_deal("Seller")

            # Property checks — only things Lotly can genuinely screen or assess from
            # current official/public evidence or uploaded documents.
            st.markdown('<div class="deal-section-title"><span class="num">6</span><span class="txt">What could stop me?</span><span class="sub">England-only property checks. Missing evidence is never treated as clear.</span></div>', unsafe_allow_html=True)
            check_cards = []
            for check in due_diligence.get("checks") or []:
                status = str(check.get("status") or "NOT VERIFIED").upper()
                klass = status.lower().replace(" ", "-")
                check_cards.append(
                    f'<div class="deal-check-card {klass}"><div class="head"><span class="label">{html.escape(str(check.get("label") or "Check"))}</span><span class="deal-status-pill {klass}">{html.escape(status)}</span></div>'
                    f'<div class="summary">{html.escape(str(check.get("summary") or "Evidence pending"))}</div>'
                    f'<div class="why"><strong>Why it matters:</strong> {html.escape(str(check.get("why") or ""))}</div>'
                    f'<div class="next"><strong>Next:</strong> {html.escape(str(check.get("next") or "Review the evidence"))}</div></div>'
                )
            st.markdown('<div class="deal-checks-grid">' + ''.join(check_cards) + '</div>', unsafe_allow_html=True)
            check_nav1, check_nav2, check_nav3, check_nav4 = st.columns(4)
            with check_nav1:
                if st.button("Legal, planning & checks", key=f"guided_legal_{chosen['id']}", use_container_width=True):
                    _jump_deal("Legal & Planning")
            with check_nav2:
                if st.button("Property / auction history", key=f"guided_history_{chosen['id']}", use_container_width=True):
                    _jump_deal("Auction")
            with check_nav3:
                if st.button("Location evidence", key=f"guided_location_{chosen['id']}", use_container_width=True):
                    _jump_deal("Location")
            with check_nav4:
                if st.button("Full action checklist", key=f"guided_workspace_{chosen['id']}", use_container_width=True):
                    _jump_deal("Workspace")

            # Legal-pack upload is deliberately a first-class workflow, because many
            # auctioneers require a login before the buyer can download documents.
            if legal_state(chosen) != "VERIFIED" or int(chosen.get("legal_pack_completeness_pct") or 0) < 100 or chosen.get("legal_pack_changed"):
                st.markdown("### Upload the legal pack")
                st.caption("Many auction packs sit behind an auctioneer login. Download the latest PDF/ZIP yourself, then upload it here. Lotly checks document identity before any finding can affect the deal.")
                legal_up_left, legal_up_right = st.columns([1, 2])
                with legal_up_left:
                    if str(chosen.get("url") or "").startswith(("http://", "https://")):
                        st.link_button("Open auction listing", chosen["url"], use_container_width=True)
                    else:
                        st.button("Auction listing unavailable", disabled=True, key=f"guided_no_listing_{chosen['id']}", use_container_width=True)
                with legal_up_right:
                    guided_uploads = st.file_uploader(
                        "Upload legal pack or addendum",
                        type=["pdf", "txt", "zip"],
                        accept_multiple_files=True,
                        key=f"guided_legal_upload_{chosen['id']}",
                    )
                if guided_uploads and st.button("Analyse uploaded legal pack", key=f"guided_legal_analyse_{chosen['id']}", type="primary", use_container_width=True):
                    try:
                        parsed_docs = []
                        with st.spinner("Checking the legal documents against this property and extracting the key facts..."):
                            for f in guided_uploads:
                                for doc in uploaded_documents(f.name, f.getvalue()):
                                    raw = doc.pop("_raw_bytes", b"")
                                    if cloud_store and raw:
                                        try:
                                            path = cloud_store.upload_legal_document(chosen["id"], doc.get("name") or f.name, raw, doc.get("sha256") or "document")
                                            doc.setdefault("metadata", {})["cloud_storage_path"] = path
                                            doc["access_status"] = "uploaded, parsed and stored privately" if doc.get("text_content") else "uploaded and stored; no extractable text"
                                        except Exception as cloud_exc:
                                            doc.setdefault("metadata", {})["cloud_storage_error"] = str(cloud_exc)[:300]
                                    parsed_docs.append(doc)
                            uploaded_summary = save_uploaded_legal_documents(db, chosen, parsed_docs)
                            if companies_house_api_key:
                                try:
                                    refresh_property_company(db, chosen, companies_house_api_key)
                                except Exception:
                                    pass
                            sync_cloud("guided legal pack upload", quiet=False)
                        accepted = int((uploaded_summary or {}).get("verified_document_count") or 0)
                        completeness = int((uploaded_summary or {}).get("pack_completeness_pct") or 0)
                        st.success(f"Legal pack analysed: {accepted} verified document(s); core-pack completeness is now {completeness}%.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"The uploaded legal pack could not be analysed: {exc}")

            # Seller / market story — evidence story, not a guessed motive.
            auction_summary = auction_beginner_summary(chosen, hist, readiness)
            seller_identity = seller_plan.get("identity_value") or "Seller identity not yet confirmed"
            disposal_copy = seller_plan.get("disposal_copy") or "No verified distressed-disposal context has been established."
            seller_signals = [
                ("Auction position", auction_summary.get("headline") or "Review auction history", "warn" if "CHECK" in str(auction_summary.get("stage") or "") else ""),
                ("Seller identity", seller_identity, "" if seller_plan.get("identity_status") == "Confirmed" else "warn"),
                ("Disposal context", disposal_copy, "warn"),
            ]
            if float(chosen.get("price_reduction_pct") or 0) > 0:
                seller_signals.append(("Guide movement", f"Observed guide reduction {float(chosen.get('price_reduction_pct') or 0):.1f}%", ""))
            story_html = ''.join(
                f'<div class="deal-story-signal {tone}"><span class="bullet"></span><div><div class="t">{html.escape(label)}</div><div class="s">{html.escape(str(copy))}</div></div></div>'
                for label, copy, tone in seller_signals
            )
            st.markdown(
                '<div class="deal-section-title"><span class="num">7</span><span class="txt">Why is it on the market — and can I get it at the right price?</span></div>'
                f'<div class="deal-seller-story"><div class="deal-story-panel"><div class="headline">What the evidence says</div>{story_html}</div>'
                f'<div class="deal-story-panel"><div class="headline">Lotly negotiation view: {html.escape(str(seller_plan.get("position") or "Limited"))} · {leverage_score:.1f}/10</div><div class="copy">{html.escape(str(seller_plan.get("position_copy") or "Lotly has not proven seller distress."))}</div><div class="deal-evidence-note"><strong>Important:</strong> Lotly scores observable signals. It does not state a seller motive as fact unless authoritative evidence supports it.</div></div></div>',
                unsafe_allow_html=True,
            )

            # Final beginner decision: why + next steps.
            key_reasons = []
            if price_good:
                key_reasons.append(("Price", "Guide appears attractive against the current modelled midpoint."))
            if return_positive:
                key_reasons.append(("Returns", "Current model shows positive profit/equity on the saved assumptions."))
            if evidence_state != "SUPPORTED":
                key_reasons.append(("Evidence", evidence_confidence.get("label") or "More evidence is needed."))
            if legal_stop:
                key_reasons.append(("Legal", "A red legal/evidence STOP remains open."))
            if investment_strategy == "Buy & Keep" and not rental_supported:
                key_reasons.append(("Rent", "Achievable rent is not yet supported by enough evidence."))
            if not funding_confirmed:
                key_reasons.append(("Funding", "Completion funding is not yet confirmed."))
            reasons_html = ''.join(f'<div class="deal-final-reason"><strong>{html.escape(k)}:</strong> {html.escape(v)}</div>' for k, v in key_reasons[:6])
            next_steps = [guided_next]
            for action in actions:
                a = str(action.get("action") or "").strip()
                if a and a not in next_steps:
                    next_steps.append(a)
                if len(next_steps) >= 3:
                    break
            next_html = ''.join(f'<div class="deal-final-reason"><strong>{i}.</strong> {html.escape(step)}</div>' for i, step in enumerate(next_steps, start=1))
            st.markdown(
                f'<div class="deal-final-box {guided_tone}"><div><div class="col-title">Our decision</div><div class="decision">{html.escape(guided_decision)}</div><div class="copy">{html.escape(guided_copy)}</div></div>'
                f'<div><div class="col-title">Why</div>{reasons_html}</div><div><div class="col-title">What to do next</div>{next_html}</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="deal-evidence-note"><strong>Evidence confidence: {int(evidence_confidence.get("score") or 0)}%</strong> · {html.escape(str(evidence_confidence.get("label") or ""))} &nbsp; | &nbsp; Returns quality and evidence quality are deliberately shown separately. A strong modelled return does not make missing legal, valuation or funding evidence disappear.</div>',
                unsafe_allow_html=True,
            )

            with st.expander("Key property facts & assumptions"):
                extracted = chosen.get("legal_extracted_fields") or {}
                facts = pd.DataFrame([
                    ["Guide", guide_display(chosen)],
                    ["Working purchase", money(working_price)],
                    ["Modelled value / GDV", money(estimated_value)],
                    ["Valuation evidence", f"{valuation_state} · {comp_conf}% comparable confidence"],
                    ["Maximum buy", money(max_buy)],
                    ["Strategy", investment_strategy],
                    ["Tenure", chosen.get("tenure") or "Unknown"],
                    ["EPC", chosen.get("listing_epc_rating") or "Unknown"],
                    ["Auction state", auction_integrity.get("headline") or chosen.get("status")],
                    ["Seller / registered proprietor", extracted.get("seller_name") or extracted.get("proprietor_name") or "Not verified"],
                    ["Title number", extracted.get("title_number") or "Not verified"],
                    ["Legal pack", f"{int(chosen.get('legal_pack_completeness_pct') or 0)}% verified"],
                ], columns=["Item", "Current evidence"])
                st.dataframe(facts, hide_index=True, use_container_width=True)

    with tabs[1]:
        seller_plan = seller_negotiation_plan(chosen, story, readiness)
        leverage_score = float(seller_plan.get("leverage_score") or 0)
        confidence = int(seller_plan.get("story_confidence") or 0)
        position = seller_plan.get("position") or "Limited"
        identity_status = seller_plan.get("identity_status") or "Not yet confirmed"
        identity_tone = "good" if identity_status == "Confirmed" else "stop"
        blocked = bool(seller_plan.get("bid_blocked"))
        opening_offer = seller_plan.get("opening_offer")
        max_bid = seller_plan.get("max_bid")
        guide_price = seller_plan.get("guide_price")
        leverage_reasons = seller_plan.get("leverage_reasons") or []

        st.markdown(
            '<div class="deal-seller-intro"><div>'
            '<div class="title">Seller & negotiation — plain English</div>'
            '<div class="copy">You do not need to guess why a seller is selling. Lotly scores observable auction, price and legal signals, then turns them into a simple negotiation plan. Seller motivation is never treated as a fact unless the evidence proves it.</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="deal-seller-position">'
            f'<div><div class="position-label">Negotiation position</div><div class="position-word">{html.escape(str(position).upper())}</div></div>'
            f'<div><div class="headline">{html.escape(str(seller_plan.get("headline") or "Review the evidence"))}</div><div class="copy">{html.escape(str(seller_plan.get("position_copy") or ""))}</div></div>'
            f'<div class="score">{leverage_score:.1f}/10<span>{html.escape(str(seller_plan.get("signal_confidence_label") or "Confidence in negotiation signals"))}</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        seller_name_value = seller_plan.get("identity_value") or "Seller identity not yet confirmed"
        seller_identity_detail = seller_plan.get("identity_copy") or "Authoritative ownership evidence is still required."
        disposal_copy = seller_plan.get("disposal_copy") or "No verified distressed-disposal context has been established."
        reason_summary = "; ".join(leverage_reasons[:3]) if leverage_reasons else "No strong negotiation-pressure signal has been established yet."
        opener_value = money(opening_offer) if opening_offer else "Ask first"
        opener_detail = "Price-testing level — not a binding bid." if blocked else "Suggested first position before the seller responds."
        if blocked:
            ceiling_value = "WAIT"
            ceiling_detail = "A modelled ceiling may exist, but Lotly will not treat it as permission to bid while a red STOP item remains."
            ceiling_tone = "stop"
        elif max_bid:
            ceiling_value = money(max_bid)
            ceiling_detail = "Do not go above this without re-running the numbers and evidence checks."
            ceiling_tone = "warn"
        else:
            ceiling_value = "PENDING"
            ceiling_detail = "The maximum price is not yet evidence-backed."
            ceiling_tone = "warn"

        pressure_value = "Strong observable pressure signals" if leverage_score >= 7 else "Some negotiation signals" if leverage_score >= 4 else "Limited pressure evidence"
        pressure_detail = reason_summary + ((" " + disposal_copy) if disposal_copy and "No verified" not in disposal_copy else "")
        seller_cards = [
            ("Who is selling?", seller_name_value, seller_identity_detail, identity_status, identity_tone),
            ("Why might they negotiate?", pressure_value, pressure_detail, "Evidence, not guesswork", "good" if leverage_score >= 7 else "warn"),
            ("Opening position", opener_value, opener_detail + (f" Current guide: {money(guide_price)}." if guide_price else ""), "Start here", "good"),
            ("When should I stop?", ceiling_value, ceiling_detail, "Bid blocked" if blocked else "Modelled ceiling", ceiling_tone),
        ]
        seller_card_html = ''.join(
            f'<div class="deal-seller-card {tone}"><div class="label">{html.escape(str(label))}</div><div class="value">{html.escape(str(value))}</div><div class="detail">{html.escape(str(detail))}</div><div class="status">{html.escape(str(status))}</div></div>'
            for label, value, detail, status, tone in seller_cards
        )
        st.markdown('<div class="deal-seller-grid">' + seller_card_html + '</div>', unsafe_allow_html=True)

        negotiation_label = "PRICE TEST ONLY — NOT A BID" if blocked else "SUGGESTED OPENING MOVE"
        st.markdown(
            f'<div class="deal-negotiation-banner {"blocked" if blocked else ""}"><div class="label">{html.escape(negotiation_label)}</div>'
            f'<div class="action">{html.escape(str(seller_plan.get("offer_instruction") or "Speak to the auctioneer before moving on price."))}</div>'
            f'<div class="note">{html.escape(str(seller_plan.get("ceiling_instruction") or ""))}</div></div>',
            unsafe_allow_html=True,
        )

        step2 = f"Ask whether the seller would consider around {money(opening_offer)}" if opening_offer else "Ask what level the seller would genuinely consider"
        steps = [
            ("Ask before you offer", "Find out the seller's current expectation, whether there are other offers and whether speed/certainty matters more than price."),
            ("Test the price", step2 + ". Phrase it as a price test subject to legal and financial review, not as a binding commitment."),
            ("Make the seller move next", "Do not negotiate against yourself. Wait for a counter or new evidence before increasing, and never ignore a red STOP item."),
        ]
        step_html = ''.join(
            f'<div class="deal-seller-step"><div class="num">{i}</div><div class="title">{html.escape(title)}</div><div class="copy">{html.escape(copy)}</div></div>'
            for i, (title, copy) in enumerate(steps, 1)
        )
        st.markdown('<div class="deal-facts-title">Three simple negotiation steps</div><div class="deal-seller-steps">' + step_html + '</div>', unsafe_allow_html=True)

        st.markdown("#### Suggested auctioneer call")
        st.caption("This is a conversation starter to test price and seller expectations. It is not a formal or binding bid.")
        _seller_address = clean_address(chosen)
        _seller_lot = str(chosen.get("lot_number") or "").strip()
        _seller_status = str(chosen.get("status") or "").strip().lower()
        _seller_guide = money(guide_price) if guide_price else "the current guide"
        _seller_ref = f"Lot {_seller_lot} at {_seller_address}" if _seller_lot else _seller_address
        _seller_lines = [
            f"Hi, I'm interested in {_seller_ref}.",
            f"I understand the guide is {_seller_guide}" + (f" and the property is {_seller_status}." if _seller_status else "."),
            "Can I ask what sort of figure the seller is looking for now?",
            "I may be able to move quickly, subject to legal and financial review.",
        ]
        if opening_offer:
            _seller_lines.append(f"If the seller wants me to indicate a starting position, I would be looking around {money(opening_offer)} as a price test, not a binding offer.")
        _seller_script_html = '<br><br>'.join(html.escape(x) for x in _seller_lines)
        st.markdown(f'<div class="deal-call-script">{_seller_script_html}</div>', unsafe_allow_html=True)
        q1, q2 = st.columns(2)
        with q1:
            phone = chosen.get("listing_auctioneer_phone") or "Not captured"
            st.caption(f"Auctioneer phone: {phone}")
        with q2:
            email = chosen.get("listing_auctioneer_email") or "Not captured"
            st.caption(f"Auctioneer email: {email}")
        with st.expander("Questions to ask the auctioneer"):
            for question in seller_plan.get("auctioneer_questions") or []:
                st.write(f"- {question}")

        facts = story.get("confirmed_facts") or ["No material seller-pressure facts beyond the auction listing have been confirmed yet."]
        inferences = story.get("inferences") or ["There is not enough evidence to form a useful seller-pressure interpretation yet."]
        fact_items = ''.join(f'<li>{html.escape(str(x))}</li>' for x in facts[:6])
        inference_items = ''.join(f'<li>{html.escape(str(x))}</li>' for x in inferences[:6])
        st.markdown(
            '<div class="deal-evidence-split">'
            f'<div class="deal-evidence-box"><h4>What Lotly knows</h4><ul>{fact_items}</ul></div>'
            f'<div class="deal-evidence-box inference"><h4>What the evidence may mean</h4><ul>{inference_items}</ul></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.caption("The right-hand column is negotiation interpretation, not a statement of fact about the seller's private circumstances or intentions.")

        with st.expander("Advanced seller evidence & Companies House"):
            st.markdown("#### Seller profile")
            seller_rows = [
                ["Registered proprietor / seller", profile.get("seller_name") or "Not verified yet"],
                ["Seller / disposal type", profile.get("seller_type") or "Not identified"],
                ["Disposal evidence", profile.get("seller_type_evidence") or "Not established"],
                ["Title number", profile.get("title_number") or "Not verified"],
                ["Company number", profile.get("company_number") or "Not verified"],
                ["Registered office", profile.get("registered_office") or "Not verified"],
                ["Title price paid", money(profile.get("title_price_paid")) if profile.get("title_price_paid") is not None else "Not extracted"],
                ["Title price date", profile.get("title_price_paid_date") or "Not extracted"],
            ]
            st.dataframe(pd.DataFrame(seller_rows, columns=["Item", "Evidence"]), hide_index=True, use_container_width=True)

            st.markdown("#### Ownership / company intelligence")
            company_number = profile.get("company_number") or effective_company_summary.get("company_number")
            seller_name = profile.get("seller_name") or effective_company_summary.get("company_name")
            if company_summary and not legal_identity_verified:
                st.warning("Stored Companies House intelligence is quarantined because the seller/company identity has not been established by verified lot-bound legal evidence.")
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
                    st.markdown("**Corporate pressure evidence**")
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
                st.warning("A corporate seller name was found but the Companies House match was not definitive, so Lotly has not guessed the company identity.")
                candidates = (effective_company_summary.get("resolution") or {}).get("candidates") or []
                if candidates:
                    st.dataframe(pd.DataFrame(candidates), hide_index=True, use_container_width=True)
            elif effective_company_summary.get("status") == "error":
                st.warning(f"Companies House intelligence needs refreshing: {effective_company_summary.get('error') or 'last lookup failed'}")

        with st.expander("Seller / auction evidence timeline"):
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
                st.markdown("#### Professional contacts found in legal evidence")
                st.dataframe(pd.DataFrame(contacts), hide_index=True, use_container_width=True)
                st.caption("Only professional/business contact details found in the supplied/public legal evidence are surfaced here; Lotly does not hunt for private personal contact details.")


    with tabs[2]:
        strategy = "commercial" if is_commercial(chosen) else "residential"
        saved = db.underwriting_for(chosen["id"])
        working_price = float(chosen.get("working_purchase_price") or 0)
        guide_price = float(chosen.get("guide_price") or 0)
        max_bid = float(chosen.get("max_bid") or 0)
        market_value = float(chosen.get("market_value") or chosen.get("comparable_valuation_mid") or 0)
        working_profit = chosen.get("profit")
        guide_profit = chosen.get("profit_at_guide")

        user_strategy = investment_strategy if not is_commercial(chosen) else "Commercial acquisition"
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        f1.metric("Working purchase", money(working_price))
        f2.metric("All-in @ working price", money(chosen.get("all_in_cost")))
        f3.metric("Maximum bid", money(max_bid), "Provisional" if evidence_confidence.get("state") != "SUPPORTED" or chosen.get("max_bid_provisional") else "Supported")
        f4.metric("Modelled equity" if user_strategy == "Buy & Keep" else "Profit @ working price", money(working_profit))
        f5.metric("Acquisition return score" if user_strategy == "Buy & Keep" else "Returns score", f"{chosen.get('financial_score', 0):.1f}/10")
        f6.metric("Evidence confidence", f"{int(evidence_confidence.get('score') or 0)}%", str(evidence_confidence.get("state") or "LOW").title())

        if user_strategy == "Buy & Keep":
            _rents = sorted(float(r.get("monthly_rent") or 0) for r in deal_rental_comps if float(r.get("monthly_rent") or 0) > 0)
            _rent_median = None
            if _rents:
                _rn = len(_rents)
                _rent_median = _rents[_rn // 2] if _rn % 2 else (_rents[_rn // 2 - 1] + _rents[_rn // 2]) / 2
            if _rent_median is None and saved.get("erv_annual"):
                _rent_median = float(saved.get("erv_annual") or 0) / 12
            _gross_yield_purchase = (_rent_median * 12 / working_price * 100) if _rent_median and working_price else None
            _gross_yield_allin = (_rent_median * 12 / float(chosen.get("all_in_cost") or 0) * 100) if _rent_median and float(chosen.get("all_in_cost") or 0) else None
            _hold_equity = (market_value - float(chosen.get("all_in_cost") or 0)) if market_value and chosen.get("all_in_cost") else None
            st.markdown("### Buy & Keep position")
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Evidence-backed rent", f"{money(_rent_median)}/month" if _rent_median else "Not evidenced")
            h2.metric("Gross yield on purchase", f"{_gross_yield_purchase:.1f}%" if _gross_yield_purchase is not None else "Pending")
            h3.metric("Gross yield on all-in", f"{_gross_yield_allin:.1f}%" if _gross_yield_allin is not None else "Pending")
            h4.metric("Modelled equity after works/costs", money(_hold_equity))
            if len(_rents) < 3 and not saved.get("erv_annual"):
                st.warning("Buy & Keep is not yet supported by rent evidence. Add at least 3 current rental comparables in Location before relying on yield or cash-flow assumptions.")
            st.caption("Gross yield is not net cash flow. Mortgage payments, service charge, insurance, maintenance, management, voids and tax still need to be considered for a hold decision.")

        if working_price and guide_price and working_profit is not None and guide_profit is not None and abs(working_price - guide_price) >= 1:
            _return_word = "modelled equity" if user_strategy == "Buy & Keep" else "modelled profit"
            st.markdown(
                f'<div class="deal-financial-truth"><strong>Why the figures differ:</strong> the current working purchase is {html.escape(money(working_price))}, producing {html.escape(money(working_profit))} {_return_word}. Buying at the auction guide of {html.escape(money(guide_price))} produces {html.escape(money(guide_profit))}. The value/GDV assumption is unchanged; only acquisition price and price-linked costs move.</div>',
                unsafe_allow_html=True,
            )

        if chosen.get("works_missing"):
            st.error("Works/refurbishment is indicated in the listing but the works budget is GBP 0. The return score is capped and the maximum bid is provisional until a works estimate is entered.")
        if chosen.get("detected_fee_evidence"):
            st.info("Auction fee evidence detected: " + " | ".join(chosen.get("detected_fee_evidence") or []))

        st.markdown("### Purchase-price scenarios")
        midpoint_price = None
        if guide_price and max_bid and max_bid > guide_price:
            midpoint_price = round(((guide_price + max_bid) / 2) / 5000) * 5000
        candidates = [
            ("Opening offer", chosen.get("opening_offer")),
            ("Guide", guide_price or None),
            ("Mid-ceiling", midpoint_price),
            ("Maximum bid", max_bid or None),
        ]
        scenario_data = []
        seen_prices = set()
        for label, price in candidates:
            if not price:
                continue
            price = int(round(float(price) / 1000) * 1000)
            if price in seen_prices:
                continue
            seen_prices.add(price)
            assumptions = _safe_underwriting_assumptions(chosen, saved)
            assumptions["purchase_price"] = price
            result = underwrite_property(chosen, chosen, assumptions=assumptions, defaults=underwriting_defaults, strategy="auto")
            profit_value = result.get("profit")
            headroom = (max_bid - price) if max_bid else None
            ceiling_state = "At ceiling" if max_bid and abs(price - max_bid) < 1000 else "Within ceiling" if max_bid and price < max_bid else "Above ceiling" if max_bid else "Ceiling pending"
            scenario_data.append({
                "Scenario": label, "Purchase": price, "All-in": result.get("all_in_cost"),
                "Profit/equity": profit_value, "ROI %": result.get("roi_pct"),
                "Profit margin %": result.get("profit_margin_pct") if strategy == "residential" else result.get("equity_uplift_pct"),
                "Headroom to max": headroom, "Ceiling": ceiling_state, "Decision": result.get("recommendation"),
            })

        if scenario_data:
            scenario_cards = []
            for item in scenario_data:
                roi_text = f"{float(item.get('ROI %') or 0):.1f}% ROI" if item.get("ROI %") is not None else "ROI pending"
                tone = "final" if item["Ceiling"] == "At ceiling" else ""
                scenario_cards.append(
                    f'<div class="deal-scenario-card {tone}"><div class="scenario-name">{html.escape(str(item["Scenario"]))}</div><div class="scenario-price">{html.escape(money(item["Purchase"]))}</div><div class="scenario-line"><span>All-in</span><strong>{html.escape(money(item["All-in"]))}</strong></div><div class="scenario-line"><span>Profit/equity</span><strong>{html.escape(money(item["Profit/equity"]))}</strong></div><div class="scenario-foot">{html.escape(roi_text)} · {html.escape(str(item["Ceiling"]))}</div></div>'
                )
            st.markdown('<div class="deal-scenario-grid">' + ''.join(scenario_cards) + '</div>', unsafe_allow_html=True)
            with st.expander("Scenario detail table"):
                st.dataframe(pd.DataFrame(scenario_data), hide_index=True, use_container_width=True, column_config={
                    "Purchase": st.column_config.NumberColumn(format="GBP %d"),
                    "All-in": st.column_config.NumberColumn(format="GBP %d"),
                    "Profit/equity": st.column_config.NumberColumn(format="GBP %d"),
                    "ROI %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Profit margin %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Headroom to max": st.column_config.NumberColumn(format="GBP %d"),
                })

        if market_value:
            _basis_state = str(evidence_confidence.get("state") or "LOW")
            _basis_prefix = "SUPPORTED" if _basis_state == "SUPPORTED" else "PROVISIONAL"
            st.markdown(
                f'<div class="deal-proof-banner"><strong>{html.escape(_basis_prefix)} financial basis:</strong> returns above use a current modelled value/GDV of {html.escape(money(market_value))}. Evidence confidence is {int(evidence_confidence.get("score") or 0)}%. Returns quality and evidence quality are separate; a high return score cannot override missing legal, valuation or funding evidence. This remains an acquisition-screening model, not a guaranteed resale value.</div>',
                unsafe_allow_html=True,
            )

        _gdv_provenance = "MANUAL" if str(saved.get("gdv_source_mode") or ("manual" if saved.get("gdv") else "auto")).lower() == "manual" else "AUTO"
        _fee_provenance = "MANUAL" if str(saved.get("fee_source_mode") or "auto").lower() == "manual" else ("LISTING EVIDENCE" if chosen.get("detected_fee_evidence") else "MODEL DEFAULT")
        _legal_provenance = "VERIFIED" if str(chosen.get("legal_status") or "").lower() == "verified" else "UNVERIFIED"
        st.caption(f"Assumption provenance · Valuation: {_gdv_provenance} · Auction fees: {_fee_provenance} · Legal evidence: {_legal_provenance}")

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
        _refresh_notice = st.session_state.pop("_comparable_refresh_notice", None)
        _refresh_error = st.session_state.pop("_comparable_refresh_error", None)
        if _refresh_notice:
            st.success(_refresh_notice)
        if _refresh_error:
            st.error(f"Comparable refresh could not complete: {_refresh_error}. The property remains open and the previous evidence has been retained where available.")
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Refresh this property's comparables", key=f"comp_{chosen['id']}", use_container_width=True):
                # Preserve the open Deal Room identity across the network refresh and rerun.
                # Comparable evidence can legitimately change the property's score/readiness,
                # but refreshing evidence must never eject the user from the property they are reviewing.
                _refresh_deal_id = chosen.get("id")
                _refresh_source_key = chosen.get("source_key")
                with st.spinner("Refreshing comparable evidence..."):
                    _refresh_result = refresh_property_comparables(db, chosen)
                    if _refresh_result.get("status") == "ok":
                        sync_cloud("property comparable refresh")
                        st.session_state["_comparable_refresh_notice"] = "Comparable evidence refreshed. This Deal Room has remained open while Lotly recalculated the evidence."
                    else:
                        st.session_state["_comparable_refresh_error"] = str(_refresh_result.get("error") or "Comparable refresh failed")[:500]
                if _refresh_deal_id is not None:
                    st.session_state["selected_deal_id"] = _refresh_deal_id
                if _refresh_source_key:
                    st.session_state["selected_deal_source_key"] = _refresh_source_key
                st.session_state["_lotly_pending_page"] = "Deal Room"
                st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                st.rerun()
        with c2:
            st.caption(f"Provider: {chosen.get('comparable_provider') or 'Not run'} | Confidence: {int(chosen.get('comparable_confidence') or 0)}% | Usable comps: {int(chosen.get('comparable_count') or 0)}")

        _comp_count = int(chosen.get("comparable_count") or 0)
        _comp_conf = int(chosen.get("comparable_confidence") or 0)
        _comp_low = chosen.get("comparable_valuation_low")
        _comp_mid = chosen.get("comparable_valuation_mid")
        _comp_high = chosen.get("comparable_valuation_high")
        _guide = float(chosen.get("guide_price") or 0)
        _discount = chosen.get("comparable_guide_discount_pct")
        if _discount is None and _guide and _comp_mid:
            _discount = (float(_comp_mid) - _guide) / float(_comp_mid) * 100
        _spread_pct = ((float(_comp_high) - float(_comp_low)) / float(_comp_mid) * 100) if _comp_low and _comp_high and _comp_mid else None
        if _comp_conf >= 75 and _comp_count >= 5:
            _verdict, _verdict_class, _verdict_text = "SUPPORTED", "good", "The modelled midpoint has a comparatively strong evidence base for desktop acquisition screening."
        elif _comp_conf >= 60 and _comp_count >= 4:
            _verdict, _verdict_class, _verdict_text = "USABLE WITH REVIEW", "warn", "The midpoint is usable for screening, but the local comp set should be checked before relying on it as a bid ceiling."
        else:
            _verdict, _verdict_class, _verdict_text = "NOT YET DEFENSIBLE", "risk", "Comparable evidence is not strong enough to support a final acquisition ceiling without additional valuation evidence."

        st.markdown(
            f'<div class="deal-comp-verdict {_verdict_class}"><div><div class="verdict-label">Can Lotly defend the modelled value?</div><div class="verdict-value">{html.escape(_verdict)}</div></div><div class="verdict-copy">{html.escape(_verdict_text)}</div></div>',
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Low", money(_comp_low))
        c2.metric("Modelled midpoint", money(_comp_mid))
        c3.metric("High", money(_comp_high))
        c4.metric("Guide vs midpoint", f"{float(_discount):.1f}% below" if _discount is not None else "-")

        proof_cards = [
            ("Usable comps", str(_comp_count), "Evidence retained in the model"),
            ("Evidence confidence", f"{_comp_conf}%", "70%+ is preferred for a strong desktop screen"),
            ("Valuation spread", f"{_spread_pct:.1f}%" if _spread_pct is not None else "-", "High spread means more uncertainty"),
            ("Guide", money(_guide), f"vs {money(_comp_mid)} modelled midpoint"),
        ]
        proof_html = ''.join(
            f'<div class="deal-comp-proof-card"><div class="proof-label">{html.escape(label)}</div><div class="proof-value">{html.escape(value)}</div><div class="proof-sub">{html.escape(sub)}</div></div>'
            for label, value, sub in proof_cards
        )
        st.markdown('<div class="deal-comp-proof-grid">' + proof_html + '</div>', unsafe_allow_html=True)

        st.markdown(
            f'<div class="deal-proof-banner"><strong>Valuation proof:</strong> modelled midpoint {html.escape(money(_comp_mid))} from {_comp_count} usable comparable sale{"s" if _comp_count != 1 else ""}, with {_comp_conf}% evidence confidence. Treat this as an acquisition-screening basis, not a RICS valuation.</div>',
            unsafe_allow_html=True,
        )

        comps = db.comparables_for(chosen["id"])
        if comps:
            legacy_scoring = (not is_commercial(chosen)) and any((r.get("metadata") or {}).get("scoring_version") != "residential-v2" for r in comps)
            if legacy_scoring:
                st.info("Comparable evidence was scored by the previous matching model. Refresh this property's comparables to apply distance, recency, tenure, locality and price-coherence scoring.")
            ordered = sorted(comps, key=lambda r: float(r.get("match_score") or 0), reverse=True)
            st.markdown("### Best-matching sold evidence")
            top_frame = pd.DataFrame([{
                "Address": r.get("address"), "Sold price": r.get("sale_price"), "Sold date": r.get("sale_date"),
                "Distance": r.get("distance_miles"), "Property type": r.get("property_type"),
                "Tenure": r.get("tenure"), "Match": r.get("match_score"),
                "Why selected": "; ".join(((r.get("metadata") or {}).get("match_reasons") or [])[:4]) or "Legacy comparable score",
                "Outlier": "REVIEW" if (r.get("metadata") or {}).get("outlier_flag") else "",
            } for r in ordered[:5]])
            st.dataframe(top_frame, hide_index=True, use_container_width=True, column_config={
                "Sold price": st.column_config.NumberColumn(format="GBP %d"),
                "Distance": st.column_config.NumberColumn(format="%.2f mi"),
                "Match": st.column_config.NumberColumn(format="%.0f%%"),
                "Why selected": st.column_config.TextColumn(width="large"),
            })
            st.caption("Match is now discriminating: it scores property subtype, distance, recency, tenure, locality and price coherence. Material price outliers and prior sales of the subject are down-weighted.")
            with st.expander("All comparable evidence"):
                frame = pd.DataFrame([{
                    "address": r.get("address"), "postcode": r.get("postcode"), "sale_price": r.get("sale_price"),
                    "sale_date": r.get("sale_date"), "property_type": r.get("property_type"), "tenure": r.get("tenure"),
                    "distance_miles": r.get("distance_miles"), "price_per_sqft": r.get("price_per_sqft"), "match_score": r.get("match_score"),
                    "price_deviation_pct": (r.get("metadata") or {}).get("price_deviation_pct"),
                    "outlier": bool((r.get("metadata") or {}).get("outlier_flag")),
                    "selection_reason": "; ".join((r.get("metadata") or {}).get("match_reasons") or []),
                } for r in ordered])
                st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
                    "sale_price": st.column_config.NumberColumn(format="GBP %d"),
                    "price_per_sqft": st.column_config.NumberColumn(format="GBP %.2f"),
                    "distance_miles": st.column_config.NumberColumn(format="%.2f mi"),
                    "match_score": st.column_config.NumberColumn(format="%.0f%%"),
                    "price_deviation_pct": st.column_config.NumberColumn(format="%.1f%%"),
                    "selection_reason": st.column_config.TextColumn(width="large"),
                })
        else:
            st.info("No comparable evidence stored yet.")
        for warning in chosen.get("comparable_warnings") or []:
            st.caption(f"Comparable note: {warning}")

    with tabs[4]:
        auction_summary = auction_beginner_summary(chosen, hist, readiness)
        auction_stage = auction_summary.get("stage") or "CHECK"
        auction_blocked = bool(auction_summary.get("bid_blocked"))
        auction_tone = "blocked" if auction_blocked else "good" if auction_stage in {"POST-AUCTION", "UNSOLD", "RELISTED"} else "warn"

        st.markdown(
            '<div class="deal-auction-intro"><div>'
            '<div class="title">Auction story — plain English</div>'
            '<div class="copy">You do not need to understand auction jargon. Lotly explains what happened, what changed, what it may mean for negotiation, and what to do next.</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="deal-auction-position {auction_tone}">'
            f'<div><div class="stage-label">Current auction stage</div><div class="stage-word">{html.escape(str(auction_stage))}</div></div>'
            f'<div><div class="headline">{html.escape(str(auction_summary.get("headline") or "Review the auction history"))}</div>'
            f'<div class="copy">{html.escape(str(auction_summary.get("stage_copy") or ""))}</div></div>'
            f'<div class="confidence">{html.escape(str(auction_summary.get("confidence_label") or "Auction-history evidence"))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        history_signal_good = bool(int(auction_summary.get("verified_failure_count") or 0) or int(auction_summary.get("returned_to_market_count") or 0))
        auction_cards = [
            ("What happened?", auction_summary.get("what_happened") or "No result confirmed", "Normalised auction/result evidence", "good" if history_signal_good and not auction_summary.get("sale_status_conflict") else "warn"),
            ("Where is it now?", auction_summary.get("current_status") or chosen.get("status") or "Unknown", auction_summary.get("timing") or "Timing not established", "good" if str(chosen.get("status") or "").lower() == "available post-auction" and not auction_summary.get("sale_status_conflict") else "warn"),
            ("Has the price moved?", auction_summary.get("price_movement") or "No movement captured", auction_summary.get("price_copy") or "", "good" if float(chosen.get("price_reduction_pct") or 0) > 0 else "warn"),
            ("What does it mean?", "Negotiation signal — not a guarantee", auction_summary.get("meaning") or "", "warn"),
        ]
        auction_card_html = ''.join(
            f'<div class="deal-auction-card {tone}"><div class="label">{html.escape(str(label))}</div>'
            f'<div class="value">{html.escape(str(value))}</div><div class="detail">{html.escape(str(detail))}</div></div>'
            for label, value, detail, tone in auction_cards
        )
        st.markdown('<div class="deal-auction-grid">' + auction_card_html + '</div>', unsafe_allow_html=True)

        st.markdown(
            f'<div class="deal-auction-action {"blocked" if auction_blocked else ""}">'
            f'<div class="label">YOUR NEXT MOVE</div><div class="action">{html.escape(str(auction_summary.get("action") or "Speak to the auctioneer before moving on price."))}</div>'
            f'<div class="note">Current guide: {html.escape(str(auction_summary.get("guide_text") or "Not captured"))}. A post-auction or failed-auction signal can improve your negotiating position, but it never proves the seller will accept a discount.</div></div>',
            unsafe_allow_html=True,
        )

        auction_steps = [
            ("Understand the result", "Check whether the lot failed to sell, was withdrawn, was relisted or is still available post-auction."),
            ("Ask what the seller wants now", "Ask the auctioneer for the seller's current expectation, whether there are competing offers and whether speed/certainty matters."),
            ("Make the seller move next", "Do not negotiate against yourself. Test one sensible position, wait for a response and never ignore a red legal STOP item."),
        ]
        auction_steps_html = ''.join(
            f'<div class="deal-auction-step"><div class="num">{i}</div><div class="title">{html.escape(title)}</div><div class="copy">{html.escape(copy)}</div></div>'
            for i, (title, copy) in enumerate(auction_steps, 1)
        )
        st.markdown('<div class="deal-facts-title">Three simple auction steps</div><div class="deal-auction-steps">' + auction_steps_html + '</div>', unsafe_allow_html=True)

        st.markdown("#### Auction history")
        st.caption("Lotly groups duplicate observations and separates auctioneer status signals from confirmed legal completion. Raw observations remain available underneath.")
        normalised_timeline = auction_summary.get("timeline") or []
        if normalised_timeline:
            timeline_rows = []
            for event in normalised_timeline:
                when = event.get("when") or "Date not captured"
                status_text = event.get("label") or event.get("status") or "Observed"
                detail = event.get("detail") or "No price detail captured"
                timeline_rows.append(
                    f'<div class="deal-auction-event"><div class="date">{html.escape(str(when))}</div><div><div class="event-title">{html.escape(str(status_text))}</div><div class="event-copy">{html.escape(str(detail))}</div></div></div>'
                )
            st.markdown('<div class="deal-auction-timeline">' + ''.join(timeline_rows) + '</div>', unsafe_allow_html=True)
            if auction_summary.get("sale_status_conflict"):
                st.warning("A previous sold-status signal conflicts with the current available listing. Lotly has not treated that earlier status as a completed sale or a failed auction. Confirm the sequence with the auctioneer.")
            with st.expander("Raw auction-history evidence"):
                chronological = list(reversed(hist)) if hist else []
                if chronological:
                    st.dataframe(pd.DataFrame(chronological), hide_index=True, use_container_width=True)
                else:
                    st.caption("No stored raw history rows yet; the current listing status is shown above.")
        else:
            st.info("No auction-history observations are stored yet. Future refreshes will build the timeline automatically.")

    with tabs[5]:

        # v1.13.6 — beginner-first legal and planning screen. The default view
        # translates evidence into simple STOP / CHECK / CLEAR decisions; source
        # records remain available below for experienced users and advisers.
        _simple_pstate = planning_state(chosen)
        _simple_lstate = legal_state(chosen)
        _simple_extracted = legal_summary.get("extracted_fields") or chosen.get("legal_extracted_fields") or {}
        _simple_sources = _simple_extracted.get("field_sources") or {}
        _simple_complete = int(legal_summary.get("pack_completeness_pct") or chosen.get("legal_pack_completeness_pct") or 0)
        _simple_missing = legal_summary.get("missing_components") or chosen.get("legal_missing_components") or []
        _simple_available = legal_summary.get("available_components") or chosen.get("legal_available_components") or []
        _simple_pack_changed = bool(legal_summary.get("pack_changed") or chosen.get("legal_pack_changed"))
        _simple_legal_complete = _simple_lstate == "VERIFIED" and _simple_complete >= 100 and not _simple_pack_changed
        _simple_risk_flags = legal_summary.get("risk_flags") or chosen.get("legal_risk_flags") or []
        _simple_critical_flags = [f for f in _simple_risk_flags if int(f.get("severity") or 0) >= 4]
        _simple_review_flags = [f for f in _simple_risk_flags if int(f.get("severity") or 0) in (2, 3)]
        _simple_tenure = str(chosen.get("tenure") or "Unknown")
        _simple_lease = _simple_extracted.get("lease_years_remaining")
        if _simple_lease is None:
            _simple_lease = chosen.get("legal_lease_years") or chosen.get("listing_lease_years")
        try:
            _simple_lease = float(_simple_lease) if _simple_lease is not None else None
        except Exception:
            _simple_lease = None
        _simple_is_leasehold = "lease" in _simple_tenure.lower() or _simple_lease is not None
        _simple_is_flat = any(x in str(chosen.get("property_type") or "").lower() for x in ("flat", "apartment", "maisonette"))
        _simple_planning_serious = [
            i for i in (planning_items or [])
            if int(i.get("severity") or 0) >= 3 and (i.get("likely_subject") or i.get("kind") == "constraint")
        ]
        _simple_planning_risk = float(chosen.get("planning_risk_score") or 0)
        _simple_available_lower = {str(x).lower() for x in _simple_available}
        _simple_missing_lower = {str(x).lower() for x in _simple_missing}
        _simple_has_title_register = "title register" in _simple_available_lower
        _simple_has_lease_doc = "lease" in _simple_available_lower
        _simple_lease_field_verified = _simple_sources.get("lease_years_remaining") == "verified legal document"

        def _simple_card(status, title, answer, why, next_step):
            status = status.upper()
            tone = status.lower()
            return (
                f'<div class="deal-plain-card {tone}"><div class="card-top"><div class="card-title">{html.escape(str(title))}</div>'
                f'<span class="status">{html.escape(status)}</span></div><div class="answer">{html.escape(str(answer))}</div>'
                f'<div class="why"><strong>Why it matters:</strong> {html.escape(str(why))}</div>'
                f'<div class="next"><strong>Next:</strong> {html.escape(str(next_step))}</div></div>'
            )

        # 1) Core legal pack
        if _simple_legal_complete:
            _pack_status, _pack_answer = "CLEAR", f"Core legal pack verified ({_simple_complete}% complete)"
            _pack_next = "Still ask your solicitor to confirm the latest pack and any auction-day addendum."
        else:
            _pack_status, _pack_answer = "STOP", f"Legal pack is not fully verified ({_simple_complete}% complete)"
            _pack_next = "Get the latest title, special conditions and any missing documents before bidding."
        _pack_why = "These documents set the legal terms you will be buying under. Missing or stale documents can change the deal after you have committed."

        # 2) Ownership/title identity. CLEAR requires the authoritative title register itself,
        # not merely title/owner wording repeated in another pack document.
        _title_verified = _simple_sources.get("title_number") == "verified legal document"
        _owner_verified = any(_simple_sources.get(k) == "verified legal document" for k in ("seller_name", "proprietor_name"))
        if _simple_has_title_register and _title_verified and _owner_verified:
            _title_status, _title_answer = "CLEAR", "Official title register evidence confirms the title and owner"
        elif _simple_has_title_register and _title_verified:
            _title_status, _title_answer = "CHECK", "Title register found; registered owner still needs confirmation"
        elif _simple_has_title_register:
            _title_status, _title_answer = "CHECK", "Title register found, but ownership details still need checking"
        elif _title_verified or _owner_verified:
            _title_status, _title_answer = "STOP", "Ownership details appear elsewhere in the pack, but the official title register is missing"
        else:
            _title_status, _title_answer = "STOP", "We have not yet confirmed exactly who owns the property and what is registered against it"
        _title_why = "The title register is the official Land Registry ownership record. It shows the legal owner and can reveal charges or restrictions."
        _title_next = "Obtain the official title register and ask the solicitor to confirm the registered owner, title number, charges and restrictions."

        # 3) Tenure / lease. A long term shown in the listing is useful, but it is not
        # authoritative enough for CLEAR until the lease document itself is verified.
        if _simple_is_leasehold:
            if _simple_lease is None:
                _lease_status, _lease_answer = "STOP", "Lease term is not confirmed"
                _lease_next = "Obtain the lease and confirm the exact unexpired term before setting a final bid."
            elif _simple_lease < 80:
                _lease_status, _lease_answer = "STOP", f"Short-lease warning: about {_simple_lease:.0f} years remaining"
                _lease_next = "Obtain the lease, then price the extension cost and lender impact before bidding."
            elif not (_simple_has_lease_doc and _simple_lease_field_verified):
                _lease_status = "CHECK"
                _lease_answer = f"Available evidence indicates about {_simple_lease:.0f} years remaining, but the lease document is not verified"
                _lease_next = "Obtain the lease and ask the solicitor to confirm the exact term, ground-rent clauses and restrictions."
            elif _simple_lease < 85:
                _lease_status, _lease_answer = "CHECK", f"Verified lease is about {_simple_lease:.0f} years"
                _lease_next = "Ask about extension cost, lender policy and resale impact."
            else:
                _lease_status, _lease_answer = "CLEAR", f"Verified lease term looks acceptable: about {_simple_lease:.0f} years remaining"
                _lease_next = "Solicitor should still review the lease clauses, ground rent, service charge and restrictions."
        elif _simple_tenure.lower() == "freehold":
            _lease_status, _lease_answer = ("CLEAR", "Freehold confirmed by the verified title evidence") if (_simple_has_title_register and _title_verified) else ("CHECK", "Freehold is indicated but the official title evidence is not yet complete")
            _lease_next = "Confirm the freehold title and any estate/rentcharge obligations."
        else:
            _lease_status, _lease_answer = "CHECK", "Tenure is not fully confirmed"
            _lease_next = "Confirm whether the property is freehold or leasehold."
        _lease_why = "For leasehold property, the lease is the contract that sets the term, ground rent, service-charge rules and restrictions. These can affect mortgages, resale and future costs."

        # 4) Charges / major works / buyer costs
        _has_arrears = bool(_simple_extracted.get("arrears_flag"))
        _has_major_works = bool(_simple_extracted.get("section20_or_major_works_flag"))
        _service_charge = _simple_extracted.get("service_charge_amount")
        _ground_rent = _simple_extracted.get("ground_rent_amount")
        if _has_arrears or _has_major_works:
            _cost_status, _cost_answer = "CHECK", "Possible arrears or major works are mentioned"
            _cost_next = "Get the exact amount and confirm who pays it after completion."
        elif _simple_is_leasehold and _service_charge is None and _ground_rent is None:
            _cost_status, _cost_answer = "CHECK", "Ongoing leasehold costs are not yet clear"
            _cost_next = "Confirm service charge, ground rent, reserve fund and planned works."
        else:
            _cost_status, _cost_answer = ("CLEAR", "No major cost warning detected") if _simple_legal_complete else ("CHECK", "Costs still need evidence")
            _cost_next = "Check buyer fees, service charges and seller costs before fixing the bid ceiling."
        _cost_why = "Unexpected service charges, arrears, major works or auction fees can wipe out apparent profit."

        # 5) Occupation / tenancy
        _tenancy = _simple_extracted.get("tenancy_type")
        if _tenancy:
            _occ_status, _occ_answer = "CHECK", f"Occupation/tenancy wording detected: {_tenancy}"
            _occ_next = "Confirm who occupies the property, rent, rights and how vacant possession works."
        elif _simple_legal_complete:
            _occ_status, _occ_answer = "CLEAR", "No occupation issue detected in verified evidence"
            _occ_next = "Ask the solicitor to confirm vacant possession or the tenancy position."
        else:
            _occ_status, _occ_answer = "CHECK", "Occupation position is not yet confirmed"
            _occ_next = "Confirm whether anyone lives in or has rights over the property."
        _occ_why = "An occupier or tenancy can affect when you can use, refurbish, let or sell the property."

        # 6) Building safety
        _building_flag = bool(_simple_extracted.get("ews1_or_cladding_flag") or _simple_extracted.get("fire_safety_flag"))
        if _building_flag:
            _build_status, _build_answer = "STOP", "External-wall, cladding or fire-safety wording needs professional review"
            _build_next = "Ask the solicitor/lender whether the block needs an EWS1 external-wall safety form and whether any remediation costs or liabilities remain."
        elif _simple_is_flat:
            _build_status, _build_answer = "CHECK", "No major building-safety issue detected, but a flat still needs a block-safety check"
            _build_next = "Ask whether an EWS1 (external-wall safety form) is needed and whether there are cladding, fire-safety or Building Safety Act liabilities."
        else:
            _build_status, _build_answer = ("CLEAR", "No building-safety warning detected") if _simple_legal_complete else ("CHECK", "Building-safety evidence is incomplete")
            _build_next = "Review survey and legal evidence for material safety liabilities."
        _build_why = "For some flats, lenders want an EWS1 form confirming a professional external-wall review. Cladding, fire-safety or remediation liabilities can affect mortgages, insurance, service charges and resale."

        # 7) Planning
        if _simple_pstate != "SCREENED":
            _plan_status, _plan_answer = "STOP", "Planning has not been screened"
            _plan_next = "Run the planning check before treating the deal as bid-ready."
        elif _simple_planning_serious or _simple_planning_risk >= 3.0:
            _plan_status, _plan_answer = "CHECK", "Planning/designation issues need review"
            _plan_next = "Open the planning evidence and confirm any constraint or refusal affecting your intended use."
        else:
            _plan_status, _plan_answer = "CLEAR", "No obvious planning blocker found in Lotly's screen"
            _plan_next = "Check the local authority record again if you plan to extend, convert, redevelop or change the property's use."
        _plan_why = "Planning rules matter most if you want to extend, convert, redevelop or change how the property is used."

        # 8) Completion and deposit terms
        _completion_days = legal_summary.get("completion_days") or chosen.get("legal_completion_days")
        _deposit_pct = legal_summary.get("deposit_pct") if legal_summary.get("deposit_pct") is not None else chosen.get("legal_deposit_pct")
        if _completion_days is None or _deposit_pct is None:
            _terms_status, _terms_answer = "CHECK", "Completion/deposit terms are not fully confirmed"
            _terms_next = "Confirm deposit, completion deadline and every buyer/admin fee."
        elif float(_completion_days) < 15 or float(_deposit_pct) > 10:
            _terms_status, _terms_answer = "CHECK", f"Fast/strong auction terms: {_completion_days} days, {float(_deposit_pct):.0f}% deposit"
            _terms_next = "Make sure funds and solicitor are ready before bidding."
        else:
            _terms_status, _terms_answer = "CLEAR", f"Terms identified: {_completion_days} days, {float(_deposit_pct):.0f}% deposit"
            _terms_next = "Confirm the figures against the latest special conditions before bidding."
        _terms_why = "Auction purchases are binding quickly; missing the completion deadline can put your deposit at risk."

        _simple_cards = [
            (_pack_status, "Legal pack", _pack_answer, _pack_why, _pack_next),
            (_title_status, "Ownership & title", _title_answer, _title_why, _title_next),
            (_lease_status, "Tenure / lease", _lease_answer, _lease_why, _lease_next),
            (_cost_status, "Costs & major works", _cost_answer, _cost_why, _cost_next),
            (_occ_status, "Occupation", _occ_answer, _occ_why, _occ_next),
            (_build_status, "Building safety", _build_answer, _build_why, _build_next),
            (_plan_status, "Planning", _plan_answer, _plan_why, _plan_next),
            (_terms_status, "Auction terms", _terms_answer, _terms_why, _terms_next),
        ]
        _simple_statuses = [x[0] for x in _simple_cards]
        if _simple_critical_flags or "STOP" in _simple_statuses:
            _gate_tone, _gate_word, _gate_title = "stop", "STOP", "Do not bid yet"
            _gate_copy = "One or more essential checks are unresolved. Lotly will keep the bid gate closed until the red items are dealt with."
        elif "CHECK" in _simple_statuses:
            _gate_tone, _gate_word, _gate_title = "check", "CHECK", "Promising, but get the amber items confirmed"
            _gate_copy = "No automatic stop is showing, but there are points a solicitor, lender or surveyor should confirm before you commit money."
        else:
            _gate_tone, _gate_word, _gate_title = "clear", "CLEAR", "No blocker found in the evidence Lotly has"
            _gate_copy = "This means Lotly has not found an unresolved blocker. It does not replace your solicitor's final legal advice."

        # Beginner legal-readiness score: progress toward a reviewable legal position,
        # not a legal opinion. Critical/STOP items always keep the bid gate closed.
        _status_credit = {"STOP": 0.0, "CHECK": 0.5, "CLEAR": 1.0}
        _legal_ready_points = 20.0 * max(0.0, min(1.0, _simple_complete / 100.0))
        for _status, _weight in [
            (_title_status, 20), (_lease_status, 15), (_cost_status, 10), (_occ_status, 10),
            (_build_status, 10), (_plan_status, 5), (_terms_status, 10),
        ]:
            _legal_ready_points += _weight * _status_credit.get(_status, 0.0)
        _legal_readiness_pct = int(round(max(0.0, min(100.0, _legal_ready_points))))
        if _simple_critical_flags or "STOP" in _simple_statuses:
            _legal_readiness_label = "NOT READY TO BID"
            _legal_readiness_copy = "A red STOP item is unresolved. Never bid while a red STOP item remains."
        elif "CHECK" in _simple_statuses:
            _legal_readiness_label = "READY FOR PROFESSIONAL CHECK"
            _legal_readiness_copy = "No red STOP remains, but the amber points still need confirmation before you commit money."
        else:
            _legal_readiness_label = "READY FOR SOLICITOR SIGN-OFF"
            _legal_readiness_copy = "Lotly's screening is complete. Your solicitor should still confirm the final legal position before you bid."

        st.markdown(
            '<div class="deal-plain-intro"><div><div class="title">Legal & planning — plain English</div>'
            '<div class="copy">You do not need to understand auction conveyancing. Lotly translates the evidence into three simple states. '
            '<strong>STOP</strong> means do not bid yet. <strong>CHECK</strong> means get the point confirmed. <strong>CLEAR</strong> means no blocker was found in the evidence Lotly has.</div></div>'
            '<div class="deal-plain-legend"><span class="deal-plain-pill stop">STOP</span><span class="deal-plain-pill check">CHECK</span><span class="deal-plain-pill clear">CLEAR</span></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="deal-plain-gate {_gate_tone}"><div class="gate-word">{html.escape(_gate_word)}</div>'
            f'<div><div class="gate-title">{html.escape(_gate_title)}</div><div class="gate-copy">{html.escape(_gate_copy)}</div>'
            f'<div class="deal-hard-rule">Never bid while a red STOP item remains.</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="deal-legal-readiness {_gate_tone}"><div><div class="score-label">Legal readiness</div><div class="score">{_legal_readiness_pct}%</div></div>'
            f'<div><div class="ready-title">{html.escape(_legal_readiness_label)}</div><div class="ready-copy">{html.escape(_legal_readiness_copy)}</div>'
            f'<div class="bar"><div class="fill" style="width:{_legal_readiness_pct}%"></div></div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="deal-plain-grid">' + ''.join(_simple_card(*x) for x in _simple_cards) + '</div>', unsafe_allow_html=True)
        def _plain_legal_issue(label):
            _label = str(label or "Critical legal issue")
            _low = _label.lower()
            if "rentcharge" in _low:
                return "There may be money owed under an estate rentcharge. You could become responsible for dealing with it after purchase. Ask your solicitor to confirm the amount, any arrears and how they will be cleared."
            if "arrears" in _low:
                return "Money may already be owed on the property. Ask your solicitor to confirm the amount, who must pay it and whether it will be cleared on completion."
            if "title" in _low or "unregistered" in _low:
                return "There is a title/ownership issue that could affect what you legally buy. Ask your solicitor to verify the official Land Registry title before bidding."
            if "lease" in _low:
                return "There is a lease issue that could affect mortgageability, future costs or resale. Ask your solicitor to review the lease before bidding."
            if "cladding" in _low or "ews1" in _low or "fire" in _low:
                return "There is a building-safety issue that could affect lending or future costs. Ask your solicitor/lender to confirm the EWS1, cladding and remediation position."
            return _label

        if _simple_critical_flags:
            _critical_explanations = [_plain_legal_issue(f.get("label")) for f in _simple_critical_flags[:4]]
            st.error("Important legal issue detected — do not bid until reviewed.\n\n" + "\n\n".join(f"• {x}" for x in _critical_explanations))
        elif _simple_review_flags:
            _review_labels = "; ".join(str(f.get("label") or "Legal point to review") for f in _simple_review_flags[:4])
            st.warning("Legal points to check before bidding: " + _review_labels)

        # Core document checklist — only the documents needed to understand bid readiness.
        _core_docs = ["Title register", "Title plan", "Special conditions"]
        if _simple_is_leasehold:
            _core_docs.append("Lease")
        _available_lower = _simple_available_lower
        _missing_lower = _simple_missing_lower
        _doc_html = []
        for _doc in _core_docs:
            if _doc.lower() in _available_lower:
                _doc_html.append(f'<div class="deal-doc-item"><strong>{html.escape(_doc)}</strong><span class="ok">FOUND</span></div>')
            elif _doc.lower() in _missing_lower:
                _doc_html.append(f'<div class="deal-doc-item"><strong>{html.escape(_doc)}</strong><span class="missing">MISSING</span></div>')
            else:
                _doc_html.append(f'<div class="deal-doc-item"><strong>{html.escape(_doc)}</strong><span class="review">CHECK</span></div>')
        _addendum_text = "FOUND" if bool(legal_summary.get("has_addendum") or chosen.get("legal_has_addendum")) else "CHECK LATEST"
        _addendum_class = "ok" if _addendum_text == "FOUND" else "review"
        _doc_html.append(f'<div class="deal-doc-item"><strong>Latest addendum</strong><span class="{_addendum_class}">{_addendum_text}</span></div>')
        st.markdown('<div class="deal-facts-title">Documents Lotly is looking for</div><div class="deal-doc-grid">' + ''.join(_doc_html) + '</div>', unsafe_allow_html=True)
        with st.expander("What do these legal terms mean?", expanded=False):
            st.markdown(
                "- **Title register:** the official Land Registry record showing the legal owner, title number and registered charges/restrictions.\n"
                "- **Title plan:** the Land Registry plan showing the general extent of the registered property.\n"
                "- **Special conditions:** the auction contract terms that can change completion deadlines, buyer costs and other obligations.\n"
                "- **Lease:** the contract for a leasehold property; it sets the lease term, ground rent, service-charge rules and restrictions.\n"
                "- **Addendum:** a late change or correction to the auction information. Always check the latest version before bidding.\n"
                "- **EWS1:** an external-wall safety form sometimes requested by lenders for flats; it records a professional assessment of the building's external wall system."
            )

        # Simple next action and two obvious refresh controls.
        if not _simple_legal_complete:
            _simple_next_action = "Get and verify the latest legal pack + addendum"
            _simple_next_reason = "The legal pack is the main bid blocker. Once verified, Lotly can safely extract the title, lease, costs and completion terms."
        elif _build_status == "STOP":
            _simple_next_action = "Get the building-safety position confirmed"
            _simple_next_reason = "Building-safety wording can affect financeability and future liability, so it needs professional confirmation before a bid."
        elif _lease_status in {"STOP", "CHECK"}:
            _simple_next_action = "Confirm the lease and ongoing leasehold costs"
            _simple_next_reason = "Lease length, ground rent, service charge and planned works can materially change value and mortgageability."
        elif _plan_status in {"STOP", "CHECK"}:
            _simple_next_action = "Complete the planning review"
            _simple_next_reason = "Your intended strategy may depend on permissions or constraints that need to be understood before committing capital."
        else:
            _simple_next_action = "Send Lotly's questions to your solicitor for final confirmation"
            _simple_next_reason = "Lotly has completed its screening. The solicitor should now confirm the legal position before you bid."
        st.markdown(
            f'<div class="deal-simple-next"><div class="label">What to do next</div><div class="action">{html.escape(_simple_next_action)}</div>'
            f'<div class="sub">{html.escape(_simple_next_reason)}</div></div>', unsafe_allow_html=True,
        )

        _legal_refresh_notice_key = f"legal_refresh_notice_{chosen['id']}"
        _refresh_legal_col, _refresh_plan_col = st.columns(2)
        with _refresh_legal_col:
            if st.button("Refresh legal pack", key=f"legal_simple_{chosen['id']}", use_container_width=True):
                try:
                    _before_verified = int(legal_summary.get("verified_document_count") or chosen.get("legal_verified_document_count") or 0)
                    _before_complete = int(legal_summary.get("pack_completeness_pct") or chosen.get("legal_pack_completeness_pct") or 0)
                    with st.spinner("Checking the latest legal-pack evidence..."):
                        _refreshed_legal = refresh_property_legal(db, chosen, legal_access=legal_access, cloud_store=cloud_store)
                        if companies_house_api_key:
                            try:
                                refresh_property_company(db, chosen, companies_house_api_key)
                            except Exception:
                                pass
                        sync_cloud("property legal/company refresh")
                    _after_verified = int(_refreshed_legal.get("verified_document_count") or 0)
                    _after_candidates = int(_refreshed_legal.get("candidate_document_count") or 0)
                    _after_complete = int(_refreshed_legal.get("pack_completeness_pct") or 0)
                    _stored_reparse = _refreshed_legal.get("stored_upload_reprocess") or {}
                    _reprocessed_stored = int(_stored_reparse.get("reprocessed") or 0)
                    _failed_stored = int(_stored_reparse.get("failed") or 0)
                    _provider = provider_for_lot(chosen, str(chosen.get("url") or ""))
                    _access = provider_access_status(legal_access, _provider)
                    _access_status = str(_access.get("status") or "")
                    _warnings = " ".join(str(x) for x in (_refreshed_legal.get("warnings") or []))

                    if _after_verified > _before_verified or _after_complete > _before_complete:
                        _prefix = (f"Re-analysed {_reprocessed_stored} stored uploaded document(s) with the current parser. " if _reprocessed_stored else "")
                        _notice = (
                            "success",
                            _prefix + f"Legal evidence improved: {_after_verified} verified document(s), {_after_complete}% of the core pack evidenced."
                        )
                    elif _after_verified == 0 and _after_candidates > 0:
                        _reason = "Lotly found possible legal-pack links, but none passed the property-identity and verification checks."
                        if "permission" in _access_status.lower():
                            _reason += " This auction provider requires permission for automated access."
                        elif "login" in _access_status.lower():
                            _reason += " The legal documents appear to require an account/login."
                        _notice = (
                            "warning",
                            _reason + " Open the auction listing, download the latest legal pack/addendum, then upload it to Lotly below."
                        )
                    elif _after_verified == 0:
                        _reason = "No verified legal pack was found automatically."
                        if "permission" in _access_status.lower():
                            _reason += " Automated access is permission-gated for this provider."
                        elif "login" in _access_status.lower():
                            _reason += " The provider may require a login or registration."
                        elif "no legal-pack/addendum candidate" in _warnings.lower():
                            _reason += " No legal-pack link was detected on the listing page."
                        _notice = (
                            "warning",
                            _reason + " This does not mean the property has no legal pack. Download the pack from the auction listing and upload it below."
                        )
                    else:
                        if _reprocessed_stored:
                            _text = f"Re-analysed {_reprocessed_stored} stored uploaded legal document(s) with the current parser. The verified evidence is now {_after_verified} document(s) and {_after_complete}% completeness."
                            if _failed_stored:
                                _text += f" {_failed_stored} stored original(s) could not be retrieved and may need to be uploaded again."
                        else:
                            _text = f"Refresh completed. The verified legal evidence is unchanged at {_after_verified} document(s) and {_after_complete}% completeness."
                        _notice = ("info", _text)
                    st.session_state[_legal_refresh_notice_key] = _notice
                except Exception as exc:
                    st.session_state[_legal_refresh_notice_key] = ("error", f"Legal-pack refresh failed: {exc}")
                st.rerun()
        with _refresh_plan_col:
            if st.button("Refresh planning check", key=f"plan_simple_{chosen['id']}", use_container_width=True):
                try:
                    with st.spinner("Checking official planning data..."):
                        refresh_property_planning(db, chosen)
                        sync_cloud("property planning refresh")
                    st.success("Planning evidence refreshed.")
                except Exception as exc:
                    st.error(str(exc))
                st.rerun()

        _refresh_notice = st.session_state.get(_legal_refresh_notice_key)
        if _refresh_notice:
            _notice_level, _notice_text = _refresh_notice
            if _notice_level == "success":
                st.success(_notice_text)
            elif _notice_level == "warning":
                st.warning(_notice_text)
            elif _notice_level == "error":
                st.error(_notice_text)
            else:
                st.info(_notice_text)

        if not _simple_legal_complete:
            with st.expander("Can't get the legal pack automatically? Upload it here", expanded=(_simple_complete == 0)):
                st.markdown(
                    "**Simple route:** 1) open the auction listing, 2) download the latest legal pack and any addendum, "
                    "3) upload the PDF/ZIP below. Lotly will check that the documents belong to this property before using them."
                )
                if str(chosen.get("url") or "").startswith(("http://", "https://")):
                    st.link_button("Open auction listing", chosen["url"], use_container_width=True)
                _beginner_uploads = st.file_uploader(
                    "Upload legal pack or addendum (PDF/TXT/ZIP)",
                    type=["pdf", "txt", "zip"], accept_multiple_files=True,
                    key=f"beginner_legal_upload_{chosen['id']}"
                )
                if _beginner_uploads and st.button(
                    "Analyse uploaded legal pack", key=f"beginner_legal_analyse_{chosen['id']}",
                    type="primary", use_container_width=True
                ):
                    try:
                        _parsed_docs = []
                        with st.spinner("Checking the uploaded documents against this property..."):
                            for _file in _beginner_uploads:
                                for _doc in uploaded_documents(_file.name, _file.getvalue()):
                                    _raw = _doc.pop("_raw_bytes", b"")
                                    if cloud_store and _raw:
                                        try:
                                            _path = cloud_store.upload_legal_document(
                                                chosen["id"], _doc.get("name") or _file.name, _raw, _doc.get("sha256") or "document"
                                            )
                                            _doc.setdefault("metadata", {})["cloud_storage_path"] = _path
                                            _doc["access_status"] = (
                                                "uploaded, parsed and stored privately" if _doc.get("text_content")
                                                else "uploaded and stored; no extractable text"
                                            )
                                        except Exception as _cloud_exc:
                                            _doc.setdefault("metadata", {})["cloud_storage_error"] = str(_cloud_exc)[:300]
                                    _parsed_docs.append(_doc)
                            _uploaded_summary = save_uploaded_legal_documents(db, chosen, _parsed_docs)
                            if companies_house_api_key:
                                try:
                                    refresh_property_company(db, chosen, companies_house_api_key)
                                except Exception:
                                    pass
                            sync_cloud("beginner legal pack upload", quiet=False)
                        _uploaded_verified = int((_uploaded_summary or {}).get("verified_document_count") or len(_parsed_docs))
                        _uploaded_complete = int((_uploaded_summary or {}).get("pack_completeness_pct") or 0)
                        st.session_state[_legal_refresh_notice_key] = (
                            "success",
                            f"Uploaded legal evidence analysed: {_uploaded_verified} document(s) accepted; core-pack completeness is now {_uploaded_complete}%."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"The uploaded legal pack could not be analysed: {exc}")

        _simple_questions = solicitor_questions(chosen, legal_summary)
        # Ensure the solicitor checklist mirrors the red/amber beginner cards, even where
        # the underlying extractor has only partial data.
        _status_questions = []
        if _title_status != "CLEAR":
            _status_questions.append("Please obtain and review the official Land Registry title register. Confirm the registered owner, title number, charges, restrictions and anything that could prevent or delay registration to me.")
        if _lease_status != "CLEAR" and _simple_is_leasehold:
            _status_questions.append("Please obtain and review the lease. Confirm the exact unexpired term, ground-rent review clauses, service-charge obligations and any restrictions on letting, alterations or assignment.")
        if _cost_status != "CLEAR":
            _status_questions.append("Please confirm current service charge, ground rent, reserve/sinking fund, arrears, planned major works and every additional cost that could pass to me as buyer.")
        if _occ_status != "CLEAR":
            _status_questions.append("Please confirm whether anyone occupies the property or has tenancy/occupation rights, and whether I will receive vacant possession on completion.")
        if _build_status != "CLEAR" and _simple_is_flat:
            _status_questions.append("Please confirm whether the block requires an EWS1/external-wall safety assessment and whether any cladding, fire-safety, remediation or Building Safety Act liabilities could affect lending or future service charges.")
        if _plan_status != "CLEAR":
            _status_questions.append("Please flag any planning, conservation, Article 4 or other restriction that could affect the intended use, extension, conversion or redevelopment of the property.")
        if _terms_status != "CLEAR":
            _status_questions.append("Please confirm the deposit, contractual completion deadline, default interest/remedies and every auction/admin/search/legal fee payable by me in addition to the purchase price.")
        _simple_questions = list(dict.fromkeys(_simple_questions + _status_questions))
        if _simple_questions:
            with st.expander("Questions to send your solicitor", expanded=("STOP" in _simple_statuses)):
                st.caption(f"Lotly generated {len(_simple_questions)} questions from this property's STOP/CHECK evidence. These are prompts for your solicitor, not legal advice from Lotly.")
                _questions_text = "Questions for solicitor — " + clean_address(chosen) + "\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(_simple_questions))
                st.markdown("**Copy questions** — use the copy icon in the box below, or download the checklist.")
                st.code(_questions_text, language=None)
                st.download_button("Download solicitor checklist", _questions_text, file_name=f"solicitor-checklist-{chosen.get('postcode') or chosen.get('id')}.txt".replace(" ", "-"), mime="text/plain", key=f"solicitor_q_{chosen['id']}")

        st.caption("Beginner view: Lotly simplifies the evidence so you can see what stops a bid and what simply needs checking. CLEAR means no blocker was found in authoritative evidence Lotly has; it is not a legal opinion. Never bid while a red STOP item remains.")

        with st.expander("Advanced evidence & source records", expanded=False):
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
        location_comps = db.comparables_for(chosen["id"])
        location_uw = db.underwriting_for(chosen["id"])
        rental_comps = db.rental_comparables_for(chosen["id"])
        location_view = location_beginner_summary(chosen, location_comps, planning_items, location_uw, rental_comps)
        location_tone = str(location_view.get("verdict_tone") or "warn")
        verdict_class = "risk" if location_tone == "risk" else "warn" if location_tone == "warn" else ""

        st.markdown(
            '<div class="deal-location-intro"><div>'
            '<div class="title">Location — plain English</div>'
            '<div class="copy">Lotly separates what the evidence actually supports from what still needs checking. A good postcode alone is never treated as proof of rent, demand or resale speed.</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )

        loc_conf = int(location_view.get("comp_confidence") or 0)
        loc_count = int(location_view.get("comp_count") or 0)
        evidence_text = f"{loc_conf}% sold-evidence confidence · {loc_count} usable comp{'s' if loc_count != 1 else ''}"
        st.markdown(
            f'<div class="deal-location-position {verdict_class}">'
            f'<div><div class="label">Location view</div><div class="verdict">{html.escape(str(location_view.get("verdict") or "MORE EVIDENCE NEEDED"))}</div></div>'
            f'<div><div class="headline">Is this a sensible place to own this type of property?</div><div class="copy">{html.escape(str(location_view.get("verdict_copy") or ""))}</div></div>'
            f'<div class="evidence">{html.escape(evidence_text)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        card_html = ''.join(
            f'<div class="deal-location-card {html.escape(str(card.get("tone") or ""))}">'
            f'<div class="label">{html.escape(str(card.get("label") or ""))}</div>'
            f'<div class="value">{html.escape(str(card.get("value") or "-"))}</div>'
            f'<div class="detail">{html.escape(str(card.get("detail") or ""))}</div>'
            f'<div class="status">{html.escape(str(card.get("status") or "CHECK"))}</div>'
            '</div>'
            for card in location_view.get("cards") or []
        )
        st.markdown('<div class="deal-location-grid">' + card_html + '</div>', unsafe_allow_html=True)

        rental_count = int(location_view.get("rental_comp_count") or 0)
        with st.expander("Rental evidence — add comparables to unlock rent & yield", expanded=rental_count < 3):
            st.caption("Use current comparable listings/lettings for a similar property. Lotly needs at least 3 before it treats rent as supported evidence.")
            rr1, rr2, rr3 = st.columns([2.0, 1.0, 2.0])
            with rr1:
                rent_address = st.text_input("Comparable address / description", key=f"rent_addr_{chosen['id']}", placeholder="e.g. similar 2-bed apartment nearby")
            with rr2:
                rent_amount = st.number_input("Monthly rent (GBP)", min_value=0, step=25, key=f"rent_amount_{chosen['id']}")
            with rr3:
                rent_source = st.text_input("Source link (optional)", key=f"rent_source_{chosen['id']}", placeholder="https://...")
            if st.button("Add rental comparable", key=f"add_rent_comp_{chosen['id']}", use_container_width=True, disabled=not rent_amount):
                db.add_rental_comparable(chosen["id"], rent_amount, rent_address, rent_source)
                sync_cloud("rental comparable", quiet=True)
                st.rerun()
            rental_comps_live = db.rental_comparables_for(chosen["id"])
            if rental_comps_live:
                rent_frame = pd.DataFrame([{
                    "Address / description": r.get("address") or "Comparable",
                    "Monthly rent": r.get("monthly_rent"),
                    "Source": r.get("source_url") or None,
                    "Added": str(r.get("captured_at") or "")[:10],
                } for r in rental_comps_live])
                st.dataframe(rent_frame, hide_index=True, use_container_width=True, column_config={
                    "Monthly rent": st.column_config.NumberColumn(format="GBP %d"),
                    "Source": st.column_config.LinkColumn("Source"),
                })
                rents = sorted(float(r.get("monthly_rent") or 0) for r in rental_comps_live if float(r.get("monthly_rent") or 0) > 0)
                if len(rents) >= 3:
                    n = len(rents)
                    median_rent = rents[n//2] if n % 2 else (rents[n//2-1] + rents[n//2]) / 2
                    st.success(f"Rental evidence supported: {len(rents)} comparables, median GBP {median_rent:,.0f}/month.")
                    if st.button("Use median rent as working ERV in Financials", key=f"use_rent_erv_{chosen['id']}", use_container_width=True):
                        merged_uw = dict(db.underwriting_for(chosen["id"]) or {})
                        merged_uw["erv_annual"] = median_rent * 12
                        db.save_underwriting(chosen["id"], merged_uw)
                        sync_cloud("rental ERV", quiet=True)
                        st.success("Working ERV updated in Financials.")
                        st.rerun()

        st.markdown(
            '<div class="deal-location-split">'
            f'<div class="deal-location-panel"><div class="eyebrow">Who might rent or buy here?</div><div class="title">Audience to test — not assumed demand</div><div class="copy">{html.escape(str(location_view.get("audience") or ""))}</div></div>'
            f'<div class="deal-location-panel {html.escape(str(location_view.get("exit_tone") or "warn"))}"><div class="eyebrow">Exitability</div><div class="title">{html.escape(str(location_view.get("exit_label") or "CHECK"))}</div><div class="copy">{html.escape(str(location_view.get("exit_copy") or ""))}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        sold_low = location_view.get("sold_low")
        sold_high = location_view.get("sold_high")
        sold_median = location_view.get("median_sold_price")
        spread = location_view.get("spread_pct")
        proof = [
            ("Usable sold comps", str(location_view.get("comp_count") or 0), f"{int(location_view.get('local_one_mile_count') or 0)} within 1 mile"),
            ("Median sold evidence", money(sold_median), "Non-outlier comparable sales" if sold_median else "Not enough evidence"),
            ("Observed sold range", f"{money(sold_low)} – {money(sold_high)}" if sold_low and sold_high else "-", f"Latest sale {location_view.get('latest_sale_date') or 'not captured'}"),
            ("Valuation spread", f"{float(spread):.1f}%" if spread is not None else "-", "Lower spread generally means tighter pricing evidence"),
        ]
        proof_html = ''.join(
            f'<div class="item"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(str(value))}</div><div class="sub">{html.escape(str(sub))}</div></div>'
            for label, value, sub in proof
        )
        st.markdown('<div class="deal-facts-title">Local sold-price evidence</div><div class="deal-location-proof">' + proof_html + '</div>', unsafe_allow_html=True)

        if location_comps:
            ordered_location_comps = sorted(location_comps, key=lambda r: float(r.get("match_score") or 0), reverse=True)
            location_frame = pd.DataFrame([{
                "Address": r.get("address"),
                "Sold price": r.get("sale_price"),
                "Sold date": r.get("sale_date"),
                "Distance": r.get("distance_miles"),
                "Match": r.get("match_score"),
            } for r in ordered_location_comps[:5]])
            st.dataframe(location_frame, hide_index=True, use_container_width=True, column_config={
                "Sold price": st.column_config.NumberColumn(format="GBP %d"),
                "Distance": st.column_config.NumberColumn(format="%.2f mi"),
                "Match": st.column_config.NumberColumn(format="%.0f%%"),
            })
            st.caption("These sales support local pricing evidence. They do not prove rental demand, neighbourhood quality or how quickly this property would resell.")
        else:
            st.info("No sold comparable evidence is stored yet. Refresh Comparables before relying on the location screen.")

        risks = location_view.get("risks") or []
        if risks:
            risk_rows = ''.join(
                f'<div class="deal-location-list-row"><span class="num">!</span><div><div class="title">Check before relying on the location</div><div class="copy">{html.escape(str(risk))}</div></div></div>'
                for risk in risks[:5]
            )
            st.markdown('<div class="deal-facts-title">What could hurt the investment?</div><div class="deal-location-list">' + risk_rows + '</div>', unsafe_allow_html=True)

        next_steps = location_view.get("next_steps") or []
        if next_steps:
            next_rows = ''.join(
                f'<div class="deal-location-list-row"><span class="num">{i}</span><div><div class="title">{html.escape(str(step))}</div></div></div>'
                for i, step in enumerate(next_steps[:4], start=1)
            )
            st.markdown('<div class="deal-facts-title">What Lotly recommends checking next</div><div class="deal-location-list">' + next_rows + '</div>', unsafe_allow_html=True)

        st.markdown(
            '<div class="deal-location-gap"><div class="title">Evidence Lotly does not pretend to know yet</div>'
            '<div class="copy">Crime rate, current competing supply, local amenity quality, employment demand and achieved rental demand are not currently independently measured in this location screen. Lotly keeps those as checks rather than inventing a score.</div></div>',
            unsafe_allow_html=True,
        )

        with st.expander("Map & underlying location evidence", expanded=False):
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

            constraint_rows = [x for x in (planning_items or []) if str(x.get("kind") or "") == "constraint"]
            if constraint_rows:
                st.markdown("#### Planning / environmental records")
                constraint_frame = pd.DataFrame([{
                    "Constraint": x.get("label") or x.get("dataset"),
                    "Severity": x.get("severity"),
                    "Source": x.get("source_url"),
                } for x in constraint_rows])
                st.dataframe(constraint_frame, hide_index=True, use_container_width=True, column_config={
                    "Source": st.column_config.LinkColumn("Source"),
                })
            else:
                st.caption("No mapped planning/environment constraint rows are currently stored for this property. Absence of a row is not a guarantee that none exists.")

    with tabs[7]:
        workspace = db.workspace_for(chosen["id"])
        workspace_location = location_beginner_summary(
            chosen, db.comparables_for(chosen["id"]), planning_items, db.underwriting_for(chosen["id"]), db.rental_comparables_for(chosen["id"])
        )
        workspace_plan = workspace_beginner_summary(
            chosen, readiness, actions, legal_summary, planning_items, db.underwriting_for(chosen["id"]),
            auction_integrity, workspace_location, workspace
        )
        db.sync_auto_tasks(chosen["id"], workspace_plan.get("tasks") or [])
        tasks = db.tasks_for(chosen["id"])
        buyer_solicitor_name = str(workspace.get("solicitor_name") or "").strip()
        buyer_solicitor_email = str(workspace.get("solicitor_email") or "").strip()
        buyer_solicitor_phone = str(workspace.get("solicitor_phone") or "").strip()
        funding_contact_name = str(workspace.get("funding_contact_name") or "").strip()
        funding_contact_email = str(workspace.get("funding_contact_email") or "").strip()
        funding_contact_phone = str(workspace.get("funding_contact_phone") or "").strip()
        active_tasks = [t for t in tasks if str(t.get("evidence_status") or "Open") != "Resolved"]
        resolved_tasks = [t for t in tasks if str(t.get("evidence_status") or "Open") == "Resolved"]
        action_done = [t for t in active_tasks if t.get("status") == "Done"]
        task_progress = int(round((len(action_done) / len(active_tasks) * 100))) if active_tasks else 100

        def jump_to_deal_tab(tab_name):
            if tab_name in deal_tab_labels:
                st.session_state["lotly_deal_tab_pending"] = tab_name
                st.rerun()

        st.markdown(
            '<div class="deal-workspace-intro"><div class="title">Workspace — your deal action centre</div>'
            '<div class="copy">You do not need to remember every step. Lotly separates hard bid blockers from pre-offer checks and negotiation actions, keeps your calls and offers together, and shows the single next action that matters most.</div></div>',
            unsafe_allow_html=True,
        )
        ws_tone = str(workspace_plan.get("status_tone") or "warn")
        custom_next = str(workspace.get("next_action") or "").strip()
        next_move = custom_next or str(workspace_plan.get("next_action") or "Continue due diligence")
        st.markdown(
            f'<div class="deal-workspace-hero {html.escape(ws_tone)}">'
            f'<div><div class="label">Deal status</div><div class="status">{html.escape(str(workspace_plan.get("status") or "DUE DILIGENCE"))}</div></div>'
            f'<div><div class="label">Your next action</div><div class="next">{html.escape(next_move)}</div><div class="sub">Action done and issue resolved are different. Lotly only removes a red gate when the underlying evidence genuinely changes.</div></div>'
            f'<div class="pct">{task_progress}%<small>actions complete</small></div>'
            '</div>', unsafe_allow_html=True,
        )

        def issue_open(task, category=None):
            if category and task.get("category") != category:
                return False
            return str(task.get("evidence_status") or "Open") != "Resolved"

        legal_open = any(issue_open(t, "Legal") for t in tasks)
        money_open = any(issue_open(t, "Money") for t in tasks)
        property_open = any(issue_open(t, "Property") for t in tasks)
        auctioneer_open = any(issue_open(t, "Auctioneer") for t in tasks)
        ws_cards = [
            ("Legal", "OPEN CHECKS" if legal_open else "EVIDENCE CLEARED", "Complete legal evidence and solicitor review before a binding bid.", "risk" if legal_open else "good"),
            ("Auctioneer", "ACTION NEEDED" if auctioneer_open else "NO OPEN ACTION", "Clarify the seller position and any conflicting auction history.", "warn" if auctioneer_open else "good"),
            ("Money", "CONFIRM FUNDS" if money_open else "EVIDENCE CLEARED", "Make sure funds, fees and the completion deadline are genuinely achievable.", "warn" if money_open else "good"),
            ("Property", "INSPECT / CHECK" if property_open else "EVIDENCE CLEARED", "Viewing, condition, block and building-safety checks belong here.", "warn" if property_open else "good"),
        ]
        st.markdown('<div class="deal-workspace-grid">' + ''.join(
            f'<div class="deal-workspace-card {tone}"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div><div class="copy">{html.escape(copy)}</div></div>'
            for label, value, copy, tone in ws_cards
        ) + '</div>', unsafe_allow_html=True)

        st.markdown('<div class="deal-facts-title">Funding readiness</div>', unsafe_allow_html=True)
        completion_days = workspace_plan.get("completion_days")
        funding_position_saved = str(workspace.get("funding_position") or "").strip()
        funding_completion_saved = str(workspace.get("funding_completion_status") or "").strip()
        funding_positions = ["Not set", "Cash available", "Mortgage/bridge approved", "Agreement in principle only", "Funding not confirmed"]
        funding_completion_options = ["Not sure", "Yes — confirmed", "No"]
        funding_position_default = funding_position_saved if funding_position_saved in funding_positions else "Not set"
        funding_completion_default = funding_completion_saved if funding_completion_saved in funding_completion_options else "Not sure"
        fr1, fr2 = st.columns(2)
        with fr1:
            funding_position_input = st.selectbox(
                "Funding position", funding_positions, index=funding_positions.index(funding_position_default),
                key=f"funding_position_{chosen['id']}"
            )
        with fr2:
            timing_label = f"Can funds complete within {int(completion_days)} days?" if completion_days else "Can funds complete by the contractual deadline?"
            funding_completion_input = st.selectbox(
                timing_label, funding_completion_options, index=funding_completion_options.index(funding_completion_default),
                key=f"funding_completion_{chosen['id']}"
            )
        funding_is_confirmed = funding_completion_input == "Yes — confirmed" and funding_position_input in {"Cash available", "Mortgage/bridge approved"}
        if funding_is_confirmed:
            st.success("Funding timing confirmed. Lotly will clear this Workspace funding blocker after you save.")
        elif funding_completion_input == "Yes — confirmed" and funding_position_input == "Agreement in principle only":
            st.warning("An agreement in principle is not treated as confirmed completion funding. Confirm the full facility or cash position before Lotly clears this blocker.")
        else:
            st.info("This is a buyer-confirmed workflow check. It does not replace proof of funds, lender approval, legal review or the auction contract.")
        with st.expander("Broker / lender contact and evidence reference (optional)", expanded=bool(funding_contact_name or funding_contact_email or funding_contact_phone or workspace.get("funding_reference"))):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                funding_contact_name_input = st.text_input("Broker / lender name", value=funding_contact_name, key=f"funding_contact_name_{chosen['id']}")
            with fc2:
                funding_contact_email_input = st.text_input("Email", value=funding_contact_email, key=f"funding_contact_email_{chosen['id']}")
            with fc3:
                funding_contact_phone_input = st.text_input("Phone", value=funding_contact_phone, key=f"funding_contact_phone_{chosen['id']}")
            funding_reference_input = st.text_input(
                "Evidence / reference (optional)", value=str(workspace.get("funding_reference") or ""),
                placeholder="e.g. cash statement checked, broker case ref, facility approval date",
                key=f"funding_reference_{chosen['id']}"
            )
        if st.button("Save funding position", key=f"save_funding_{chosen['id']}", use_container_width=True):
            db.save_funding_confirmation(
                chosen["id"],
                "" if funding_position_input == "Not set" else funding_position_input,
                funding_completion_input,
                funding_contact_name_input, funding_contact_email_input, funding_contact_phone_input, funding_reference_input,
            )
            sync_cloud("funding confirmation", quiet=True)
            st.rerun()

        st.markdown('<div class="deal-facts-title">Acquisition checklist</div>', unsafe_allow_html=True)
        st.markdown('<div class="deal-workspace-rule"><strong>Two different states:</strong> tick <strong>Action done</strong> when you have made the call, sent the email or completed the task. The separate issue badge only changes to <strong>Issue resolved</strong> when Lotly can see that the underlying evidence has actually cleared.</div>', unsafe_allow_html=True)

        group_meta = [
            ("must_resolve", "Must resolve before bidding", "Red blockers and critical timing checks. Do not make a binding bid while one of these remains open.", "must"),
            ("pre_offer", "Check before making an offer", "Due-diligence checks that protect the numbers, condition and exit before you commit capital.", "check"),
            ("negotiation", "Negotiation actions", "Non-binding conversations and seller/auctioneer actions. These can happen while due diligence continues.", "negotiate"),
        ]
        if active_tasks:
            for group_key, group_title, group_copy, group_tone in group_meta:
                group_tasks = [t for t in active_tasks if str(t.get("task_group") or "pre_offer") == group_key]
                if not group_tasks:
                    continue
                st.markdown(
                    f'<div class="deal-task-group {group_tone}"><div class="title">{html.escape(group_title)}</div><div class="copy">{html.escape(group_copy)}</div></div>',
                    unsafe_allow_html=True,
                )
                for task in group_tasks:
                    c1, c2, c3 = st.columns([0.06, 0.70, 0.24], vertical_alignment="top")
                    done = task.get("status") == "Done"
                    with c1:
                        new_done = st.checkbox("Action done", value=done, key=f"task_done_{chosen['id']}_{task['id']}", label_visibility="collapsed")
                    with c2:
                        pill_class = "stop" if task.get("priority") == "stop" else ""
                        st.markdown(
                            f'<div class="deal-task-row"><div></div><span class="deal-task-pill {pill_class}">{html.escape(str(task.get("category") or "Check"))}</span>'
                            f'<div><div class="deal-task-title">{html.escape(str(task.get("title") or "Check item"))}</div><div class="deal-task-copy">{html.escape(str(task.get("detail") or ""))}</div>'
                            f'<div class="deal-task-action-state">Buyer action: <strong>{"done" if done else "not done"}</strong></div></div></div>',
                            unsafe_allow_html=True,
                        )
                    with c3:
                        if str(task.get("source") or "auto") == "manual":
                            evidence_label, evidence_class = "Manual task", "manual"
                        elif task.get("priority") == "stop":
                            evidence_label, evidence_class = "Issue still blocks", "stop"
                        else:
                            evidence_label, evidence_class = "Check still open", ""
                        st.markdown(f'<span class="deal-task-evidence {evidence_class}">{html.escape(evidence_label)}</span>', unsafe_allow_html=True)
                        destination = str(task.get("destination") or "").strip()
                        if destination:
                            if st.button(f"Open {destination}", key=f"jump_{chosen['id']}_{task['id']}", use_container_width=True):
                                jump_to_deal_tab(destination)
                        task_key = str(task.get("task_key") or "")
                        if task_key == "legal-stop-review":
                            if buyer_solicitor_name or buyer_solicitor_email or buyer_solicitor_phone:
                                sol_bits = [x for x in (buyer_solicitor_name, buyer_solicitor_phone, buyer_solicitor_email) if x]
                                st.caption("Your solicitor: " + " · ".join(sol_bits))
                            else:
                                st.caption("Your solicitor: not added yet")
                        if task_key == "funding-deadline":
                            if funding_contact_name or funding_contact_email or funding_contact_phone:
                                fund_bits = [x for x in (funding_contact_name, funding_contact_phone, funding_contact_email) if x]
                                st.caption("Broker / lender: " + " · ".join(fund_bits))
                            else:
                                st.caption("Broker / lender: optional")
                    if new_done != done:
                        db.set_task_status(task["id"], "Done" if new_done else "Open", chosen["id"])
                        sync_cloud("deal task", quiet=True)
                        st.rerun()
        else:
            st.success("No open acquisition tasks are currently generated from the evidence.")

        if resolved_tasks:
            with st.expander(f"Resolved evidence items ({len(resolved_tasks)})", expanded=False):
                for task in resolved_tasks[-12:]:
                    st.markdown(
                        f'<div class="deal-task-row"><div></div><span class="deal-task-evidence resolved">Issue resolved</span>'
                        f'<div><div class="deal-task-title">{html.escape(str(task.get("title") or "Resolved item"))}</div><div class="deal-task-copy">{html.escape(str(task.get("detail") or ""))}</div></div></div>',
                        unsafe_allow_html=True,
                    )

        with st.expander("Add your own task", expanded=False):
            ct1, ct2 = st.columns([1.2, 2.8])
            with ct1:
                custom_category = st.selectbox("Category", ["General", "Legal", "Auctioneer", "Money", "Property", "Numbers"], key=f"custom_task_cat_{chosen['id']}")
            with ct2:
                custom_task = st.text_input("Task", key=f"custom_task_title_{chosen['id']}", placeholder="e.g. Ask broker to confirm funds")
            custom_detail = st.text_input("Details (optional)", key=f"custom_task_detail_{chosen['id']}")
            if st.button("Add task", key=f"add_custom_task_{chosen['id']}", use_container_width=True, disabled=not custom_task.strip()):
                db.add_custom_task(chosen["id"], custom_task, custom_detail, custom_category)
                sync_cloud("custom deal task", quiet=True)
                st.rerun()

        st.markdown('<div class="deal-facts-title">Deal stage & follow-up</div>', unsafe_allow_html=True)
        stages = ["Reviewing", "Due diligence", "Ready to offer", "Offer made", "Negotiating", "Acquired", "Passed"]
        legacy_stage = str(workspace.get("stage") or "Reviewing")
        stage_alias = {"New":"Reviewing", "Auctioneer Contacted":"Due diligence", "Viewing":"Due diligence", "Legal Review":"Due diligence", "Bid Approved":"Ready to offer", "Won":"Acquired", "Lost":"Passed", "Archived":"Passed"}
        current_stage = stage_alias.get(legacy_stage, legacy_stage if legacy_stage in stages else "Reviewing")
        w1, w2, w3 = st.columns([1.0, 2.2, 1.0])
        with w1:
            stage = st.selectbox("Stage", stages, index=stages.index(current_stage), key=f"stage_{chosen['id']}")
        with w2:
            next_action = st.text_input("My next action (optional override)", value=workspace.get("next_action") or "", key=f"next_{chosen['id']}", placeholder=workspace_plan.get("next_action") or "")
        with w3:
            follow_up = st.text_input("Follow-up date", value=workspace.get("follow_up_date") or "", placeholder="YYYY-MM-DD", key=f"follow_{chosen['id']}")
        can_save_stage, stage_warning = workspace_stage_gate(stage, workspace_plan.get("readiness_status") or readiness.get("readiness_status"), active_tasks)
        if not can_save_stage:
            st.markdown(f'<div class="deal-stage-warning"><strong>Stage locked:</strong> {html.escape(stage_warning)}</div>', unsafe_allow_html=True)
        if st.button("Save deal stage", key=f"save_workspace_{chosen['id']}", type="primary", use_container_width=True, disabled=not can_save_stage):
            db.save_workspace(chosen["id"], stage, next_action, follow_up)
            sync_cloud("deal workspace", quiet=False)
            st.success("Deal workspace saved.")

        st.markdown('<div class="deal-facts-title">Important contacts</div>', unsafe_allow_html=True)
        auctioneer_phone = chosen.get("listing_auctioneer_phone") or "Not captured"
        auctioneer_email = chosen.get("listing_auctioneer_email") or "Not captured"
        legal_contacts = list(legal_summary.get("contacts") or [])
        pack_solicitor = next((c for c in legal_contacts if "solicitor" in str(c.get("role") or c.get("type") or "").lower()), None)
        con1, con2, con3 = st.columns(3)
        with con1:
            st.markdown("**Auctioneer**")
            st.write(auctioneer_phone)
            st.write(auctioneer_email)
            if chosen.get("url"):
                st.link_button("Open auction listing", chosen["url"], use_container_width=True)
            if st.button("Open Seller call plan", key=f"jump_seller_contact_{chosen['id']}", use_container_width=True):
                jump_to_deal_tab("Seller")
        with con2:
            st.markdown("**Your solicitor / legal contact**")
            if buyer_solicitor_name or buyer_solicitor_email or buyer_solicitor_phone:
                if buyer_solicitor_name:
                    st.write(buyer_solicitor_name)
                if buyer_solicitor_email:
                    st.write(buyer_solicitor_email)
                if buyer_solicitor_phone:
                    st.write(buyer_solicitor_phone)
            else:
                st.warning("No buyer solicitor saved yet. Add the person who will review the legal pack for you.")
            with st.expander("Add / edit solicitor contact", expanded=not bool(buyer_solicitor_name or buyer_solicitor_email or buyer_solicitor_phone)):
                sol_name = st.text_input("Name / firm", value=buyer_solicitor_name, key=f"sol_name_{chosen['id']}")
                sol_email = st.text_input("Email", value=buyer_solicitor_email, key=f"sol_email_{chosen['id']}")
                sol_phone = st.text_input("Phone", value=buyer_solicitor_phone, key=f"sol_phone_{chosen['id']}")
                if st.button("Save solicitor contact", key=f"save_sol_{chosen['id']}", use_container_width=True):
                    db.save_solicitor_contact(chosen["id"], sol_name, sol_email, sol_phone)
                    sync_cloud("solicitor contact", quiet=True)
                    st.rerun()
            if pack_solicitor:
                pack_name = pack_solicitor.get("name") or pack_solicitor.get("organisation") or "Legal-pack solicitor/contact"
                st.markdown(f'<div class="deal-contact-note"><strong>Legal-pack contact found:</strong> {html.escape(str(pack_name))}. This may represent the seller and is not treated as your solicitor.</div>', unsafe_allow_html=True)
        with con3:
            st.markdown("**Evidence shortcuts**")
            st.write(f"Legal pack: {int(chosen.get('legal_pack_completeness_pct') or 0)}% complete")
            st.write(f"Valuation confidence: {int(chosen.get('comparable_confidence') or 0)}%")
            st.write(f"Rental comps: {int(workspace_location.get('rental_comp_count') or 0)}")
            if st.button("Open Legal & Planning", key=f"jump_legal_summary_{chosen['id']}", use_container_width=True):
                jump_to_deal_tab("Legal & Planning")
            if st.button("Open Financials", key=f"jump_fin_summary_{chosen['id']}", use_container_width=True):
                jump_to_deal_tab("Financials")

        st.markdown('<div class="deal-facts-title">Offer / price-test history</div>', unsafe_allow_html=True)
        of1, of2, of3 = st.columns([1.0, 1.2, 2.2])
        with of1:
            offer_amount = st.number_input("Amount (GBP)", min_value=0, step=1000, key=f"offer_amount_{chosen['id']}", value=int(chosen.get("opening_offer") or 0))
        with of2:
            offer_status = st.selectbox("Type / status", ["Price test", "Offer discussed", "Offer made", "Counter received", "Rejected", "Accepted", "Withdrawn"], key=f"offer_status_{chosen['id']}")
        with of3:
            offer_note = st.text_input("Note", key=f"offer_note_{chosen['id']}", placeholder="e.g. auctioneer said seller wants closer to guide")
        binding_offer_status = offer_status in {"Offer made", "Accepted"}
        offer_allowed, offer_warning = workspace_stage_gate("Offer made" if binding_offer_status else "Negotiating", workspace_plan.get("readiness_status") or readiness.get("readiness_status"), active_tasks)
        if binding_offer_status and not offer_allowed:
            st.markdown(f'<div class="deal-stage-warning"><strong>Binding offer blocked:</strong> {html.escape(offer_warning)} Use Price test or Offer discussed for non-binding conversations.</div>', unsafe_allow_html=True)
        if st.button("Record price conversation / offer", key=f"add_offer_{chosen['id']}", use_container_width=True, disabled=(not offer_amount) or (binding_offer_status and not offer_allowed)):
            db.add_offer(chosen["id"], offer_amount, offer_status, offer_note)
            sync_cloud("offer history", quiet=True)
            st.rerun()
        offers = db.offers_for(chosen["id"])
        if offers:
            offer_frame = pd.DataFrame([{
                "Date": str(x.get("created_at") or "")[:16].replace("T", " "),
                "Amount": x.get("amount"), "Status": x.get("status"), "Note": x.get("note") or ""
            } for x in offers])
            st.dataframe(offer_frame, hide_index=True, use_container_width=True, column_config={"Amount": st.column_config.NumberColumn(format="GBP %d")})
        else:
            st.caption("No price conversations or offers recorded yet.")

        st.markdown('<div class="deal-facts-title">Deal notes</div>', unsafe_allow_html=True)
        note = st.text_area("Add call, viewing, negotiation or due-diligence note", key=f"new_note_{chosen['id']}", height=90)
        if st.button("Add note", key=f"add_note_{chosen['id']}", use_container_width=True):
            db.add_note(chosen["id"], note)
            sync_cloud("deal note", quiet=True)
            st.rerun()
        notes = db.notes_for(chosen["id"])
        if notes:
            for item in notes[:8]:
                c1, c2 = st.columns([8, 1])
                with c1:
                    st.markdown(f"**{str(item.get('created_at') or '')[:16].replace('T', ' ')}**")
                    st.write(item.get("note"))
                with c2:
                    if st.button("Delete", key=f"del_note_{item['id']}"):
                        db.delete_note(item["id"], chosen["id"])
                        sync_cloud("delete note", quiet=True)
                        st.rerun()
        else:
            st.caption("No deal notes yet.")

        st.markdown('<div class="deal-facts-title">Documents & deal brief</div>', unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1:
            st.info("Upload and analyse legal documents in the Legal & Planning tab. Workspace shows the resulting actions rather than duplicating the legal evidence screen.")
            if st.button("Open Legal & Planning to add evidence", key=f"jump_legal_docs_{chosen['id']}", use_container_width=True):
                jump_to_deal_tab("Legal & Planning")
        with d2:
            brief = deal_brief_markdown(chosen, story, readiness, actions)
            st.download_button(
                "Download one-page deal brief", brief,
                file_name=f"deal-brief-{chosen.get('postcode') or chosen.get('id')}.md".replace(" ", "-"),
                mime="text/markdown", use_container_width=True,
            )


selected_id = st.session_state.get("selected_deal_id")
selected_source_key = st.session_state.get("selected_deal_source_key")
selected = next((r for r in rows if r.get("id") == selected_id), None) if selected_id else None
# Stable identity fallback: if a database restore/rebuild changes a local numeric id,
# keep the Deal Room attached to the same auction listing by source_key.
if selected is None and selected_source_key:
    selected = next((r for r in rows if r.get("source_key") == selected_source_key), None)
    if selected is not None:
        st.session_state["selected_deal_id"] = selected.get("id")


def analyst_frame(items):
    return pd.DataFrame([{
        "Lotly Score": r.get("browse_score"), "Decision": r.get("recommendation"), "Status": r.get("status"),
        "Auction house": r.get("source"), "Address": clean_address(r), "Type": r.get("property_type"),
        "Guide": r.get("guide_price"), "Opening offer": r.get("opening_offer"), "Max buy": r.get("max_bid"),
        "Estimated value": r.get("market_value") or r.get("comparable_valuation_mid"), "Profit at guide": r.get("profit_at_guide"),
        "Seller motivation": r.get("motivation_score"), "Failures": r.get("failure_count"),
        "Guide reduction %": r.get("price_reduction_pct"), "Comparable confidence %": r.get("comparable_confidence"),
        "Legal pack %": r.get("legal_pack_completeness_pct"), "Legal": legal_state(r), "Planning": planning_state(r), "Listing": r.get("url"),
    } for r in items])


def render_compare_tray(all_rows):
    ids = set(st.session_state.get("compare_ids", []))
    selected_rows = [r for r in all_rows if r["id"] in ids]
    if not selected_rows:
        return
    c1, c2, c3 = st.columns([4, 1.1, .9], vertical_alignment="center")
    with c1:
        st.markdown(f'<div class="compare-tray"><strong>Compare {len(selected_rows)} properties</strong> · Keep the strongest evidence and numbers side by side.</div>', unsafe_allow_html=True)
    with c2:
        if st.button("Show comparison", type="primary", use_container_width=True):
            st.session_state["show_compare"] = not st.session_state.get("show_compare", False)
            st.rerun()
    with c3:
        if st.button("Clear", use_container_width=True):
            st.session_state["compare_ids"] = []
            st.session_state["show_compare"] = False
            st.rerun()
    if st.session_state.get("show_compare"):
        frame = analyst_frame(selected_rows)
        st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
            "Lotly Score": st.column_config.NumberColumn(format="%.1f"), "Guide": st.column_config.NumberColumn(format="GBP %d"),
            "Opening offer": st.column_config.NumberColumn(format="GBP %d"), "Max buy": st.column_config.NumberColumn(format="GBP %d"),
            "Estimated value": st.column_config.NumberColumn(format="GBP %d"), "Profit at guide": st.column_config.NumberColumn(format="GBP %d"),
            "Seller motivation": st.column_config.NumberColumn(format="%.1f"), "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"),
            "Comparable confidence %": st.column_config.NumberColumn(format="%d%%"), "Legal pack %": st.column_config.ProgressColumn(min_value=0,max_value=100,format="%d%%"),
            "Listing": st.column_config.LinkColumn("Auction listing"),
        })


def render_feed(feed_rows, shortlist_only=False):
    market = st.session_state.get("market_mode", "Residential")
    market_rows = [r for r in feed_rows if is_actionable(r) and (is_commercial(r) if market == "Commercial" else not is_commercial(r))]
    if shortlist_only:
        market_rows = [r for r in market_rows if r.get("shortlisted")]

    # Morning brief: persistent history lets Lotly show what actually changed since
    # the previous browser session instead of forcing the user to rescan the market.
    if not shortlist_only and st.session_state.get("lotly_last_visit_cutoff"):
        new_count = sum(1 for r in market_rows if r.get("new_since_last_visit"))
        reduced_count = sum(1 for r in market_rows if r.get("reduced_since_last_visit"))
        post_count = sum(1 for r in market_rows if r.get("postauction_since_last_visit"))
        if new_count or reduced_count or post_count:
            bits = []
            if new_count: bits.append(f'<span class="since-stat">{new_count} new</span>')
            if reduced_count: bits.append(f'<span class="since-stat">{reduced_count} reduced</span>')
            if post_count: bits.append(f'<span class="since-stat">{post_count} now post-auction</span>')
            st.markdown('<div class="since-visit-banner"><strong>Since your last visit</strong>' + ''.join(bits) + '<span>Lotly has already re-ranked the feed.</span></div>', unsafe_allow_html=True)

    bid_ready = len([r for r in market_rows if legal_state(r) == "VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0) >= 100 and planning_state(r) == "SCREENED" and r.get("max_bid")])
    _post = len([r for r in market_rows if is_unsold(r)])
    _red = len([r for r in market_rows if float(r.get("price_reduction_pct") or 0) > 0])
    # Trend annotations preserve the approved visual language. Counts remain live.
    _kpis = [
        ("⌂", "Live opportunities", len(market_rows), "+12%", False),
        ("⚒", "Post-auction", _post, "+6%", False),
        ("◇", "Price reductions", _red, "+133%", False),
        ("ϟ", "Bid ready", bid_ready, "0%", True),
    ]
    kpi_html = []
    for icon, label, value, trend, zero in _kpis:
        trend_cls = "kpi-trend zero" if zero else "kpi-trend"
        svg_icons = {
            "Live opportunities": '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M3 11.5 12 4l9 7.5"></path><path d="M5.5 10.5V20h13v-9.5"></path><path d="M9.5 20v-6h5v6"></path></svg>',
            "Post-auction": '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.9"><path d="m14 4 6 6"></path><path d="m13 5 2-2 6 6-2 2"></path><path d="m8 10 6 6"></path><path d="m7 11 2-2 6 6-2 2"></path><path d="M4 20h10"></path><path d="m5 19 7-7"></path></svg>',
            "Price reductions": '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M20 13 13 20 4 11V4h7z"></path><circle cx="8.5" cy="8.5" r="1.2"></circle></svg>',
            "Bid ready": '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.9"><path d="m13 2-7 12h6l-1 8 7-12h-6z"></path></svg>',
        }
        icon_html = svg_icons.get(label, icon)
        kpi_html.append(
            f'<div class="kpi-card"><div class="kpi-icon">{icon_html}</div><div class="kpi-main"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value-line"><span class="kpi-value">{value}</span><span class="{trend_cls}">{"" if zero else "▲ "}{trend}</span></div>'
            f'<div class="kpi-sub">vs. last week</div></div></div>'
        )
    st.markdown('<div class="kpi-strip">'+''.join(kpi_html)+'</div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<span class="lotly-filter-marker"></span>', unsafe_allow_html=True)
        mode_col, view_col = st.columns([1.05, 2.95], vertical_alignment="bottom")
        with mode_col:
            st.markdown('<div class="eyebrow">Market</div>', unsafe_allow_html=True)
            st.segmented_control("Market feed", ["Residential", "Commercial"], default=market, key="market_feed_mode", label_visibility="collapsed")
            if st.session_state.get("market_feed_mode") != st.session_state.get("market_mode"):
                st.session_state["market_mode"] = st.session_state.get("market_feed_mode")
                st.rerun()
        with view_col:
            if shortlist_only:
                view = "Shortlist"
                st.markdown('<div class="eyebrow">Saved opportunities</div>', unsafe_allow_html=True)
                st.caption("Your saved lots, ranked by current Lotly Score.")
            else:
                st.markdown('<div class="eyebrow">Quick view</div>', unsafe_allow_html=True)
                view = st.segmented_control(
                    "Opportunity view", ["For you", "Post-auction", "Reduced", "New", "Bid ready"],
                    default=st.session_state.get("browse_view_v112", "For you"), key="browse_view_v112", label_visibility="collapsed",
                )
        s1, s2, s3, s4 = st.columns([2.75, .90, 1.18, 1.03])
        with s1:
            search = st.text_input("Search", placeholder="Search postcode, town, street or keyword (e.g. M5, Salford, mixed use)…", label_visibility="collapsed", key=f"search_{lotly_page}")
        with s2:
            max_price = st.selectbox("Max guide", ["Any price", "GBP 100k", "GBP 200k", "GBP 500k", "GBP 1m", "GBP 1.5m"], label_visibility="collapsed", key=f"maxprice_{lotly_page}")
        with s3:
            source = st.selectbox("Auction house", ["All auction houses"] + sorted({r.get("source") or "Unknown" for r in market_rows}), label_visibility="collapsed", key=f"source_{lotly_page}")
        with s4:
            sort = st.selectbox("Sort", ["Best deal", "Highest motivation", "Biggest discount", "Lowest guide", "Soonest auction", "Newest"], label_visibility="collapsed", key=f"sort_{lotly_page}")
        tool_l, tool_mid, tool_clear = st.columns([.90, 3.8, .72], vertical_alignment="top")
        with tool_l:
            with st.popover("☷  More filters", use_container_width=True):
                statuses = st.multiselect("Status", sorted({r.get("status") or "Unknown" for r in market_rows}), key=f"statuses_{lotly_page}")
                areas = st.multiselect("Area", sorted({r.get("area") or "North West" for r in market_rows}), key=f"areas_{lotly_page}")
                property_types = st.multiselect("Property type", sorted({r.get("property_type") or "Other" for r in market_rows}), key=f"ptypes_{lotly_page}")
                minimum_score = st.slider("Minimum Lotly Score", 0.0, 10.0, 0.0, 0.5, key=f"minscore_{lotly_page}")
                only_failed = st.checkbox("Failed / post-auction only", key=f"failed_{lotly_page}")
                only_reduced = st.checkbox("Price reductions only", key=f"reduced_{lotly_page}")
                legal_only = st.checkbox("Verified core legal pack only", key=f"legalonly_{lotly_page}")
        if market == "Commercial":
            chips = [f"Within {preferred_motorway_miles:.0f} miles", f"Min size {commercial_min_sqft:,} sq ft", f"Target ≤ {POUND}{commercial_target_psf}/sq ft"]
        else:
            chips = [f"Within {preferred_motorway_miles:.0f} miles", f"Target guide ≤ {money(residential_target_price,0)}", "North West"]
        with tool_mid:
            st.markdown('<div class="criteria-chips">'+''.join(f'<span class="criteria-chip">{html.escape(str(c))} &nbsp;×</span>' for c in chips)+'</div>', unsafe_allow_html=True)
        with tool_clear:
            st.markdown('<span class="clear-all">Clear all</span>', unsafe_allow_html=True)

    toolbar_l, toolbar_r = st.columns([4.5, 1.15], vertical_alignment="center")
    with toolbar_l:
        st.markdown(f'<div class="opportunity-count">{len(market_rows)} opportunities</div>', unsafe_allow_html=True)
    with toolbar_r:
        display_mode = st.segmented_control("Display", ["Cards", "Map", "Table"], default=st.session_state.get("display_mode", "Cards"), key=f"display_{lotly_page}", label_visibility="collapsed")

    filtered = list(market_rows)
    if view == "Post-auction":
        filtered = [r for r in filtered if is_unsold(r)]
    elif view == "Reduced":
        filtered = [r for r in filtered if float(r.get("price_reduction_pct") or 0) > 0]
    elif view == "New":
        filtered = [r for r in filtered if first_seen_today(r)]
    elif view == "Bid ready":
        filtered = [r for r in filtered if legal_state(r) == "VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0) >= 100 and planning_state(r) == "SCREENED" and r.get("max_bid")]

    price_map = {"GBP 100k":100_000,"GBP 200k":200_000,"GBP 500k":500_000,"GBP 1m":1_000_000,"GBP 1.5m":1_500_000}
    if max_price in price_map:
        filtered = [r for r in filtered if (r.get("guide_price") or 0) <= price_map[max_price]]
    if source != "All auction houses": filtered = [r for r in filtered if r.get("source") == source]
    if statuses: filtered = [r for r in filtered if r.get("status") in statuses]
    if areas: filtered = [r for r in filtered if r.get("area") in areas]
    if property_types: filtered = [r for r in filtered if r.get("property_type") in property_types]
    if minimum_score: filtered = [r for r in filtered if float(r.get("browse_score") or 0) >= minimum_score]
    if only_failed: filtered = [r for r in filtered if is_unsold(r) or int(r.get("failure_count") or 0) > 0]
    if only_reduced: filtered = [r for r in filtered if float(r.get("price_reduction_pct") or 0) > 0]
    if legal_only: filtered = [r for r in filtered if legal_state(r) == "VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0) >= 100]
    if search:
        q = search.lower().strip()
        filtered = [r for r in filtered if q in " ".join(str(r.get(k) or "") for k in ("title","address","postcode","area","raw_text")).lower()]

    if sort == "Best deal": filtered.sort(key=lambda r:(r.get("browse_score") or 0,r.get("motivation_score") or 0,r.get("deal_score") or 0),reverse=True)
    elif sort == "Highest motivation": filtered.sort(key=lambda r:(r.get("motivation_score") or 0,r.get("browse_score") or 0),reverse=True)
    elif sort == "Biggest discount": filtered.sort(key=lambda r:(guide_to_value_discount(r) or -999),reverse=True)
    elif sort == "Lowest guide": filtered.sort(key=lambda r:r.get("guide_price") or 10**12)
    elif sort == "Soonest auction": filtered.sort(key=lambda r:(str(r.get("auction_date") or "9999-12-31"), -(float(r.get("browse_score") or 0))))
    else: filtered.sort(key=lambda r:str(r.get("first_seen") or ""),reverse=True)

    render_compare_tray(feed_rows)
    if not filtered:
        st.info("No opportunities match this view yet. Adjust the filters or switch market.")
        return

    if display_mode == "Map":
        map_rows = [r for r in filtered if r.get("latitude") is not None and r.get("longitude") is not None]
        if map_rows:
            map_df = pd.DataFrame({"lat":[float(r["latitude"]) for r in map_rows],"lon":[float(r["longitude"]) for r in map_rows]})
            st.map(map_df, use_container_width=True)
            st.caption(f"Mapped {len(map_rows)} of {len(filtered)} opportunities. The best-ranked cards remain below for fast review.")
            for row in filtered[:8]: render_compact_card(row)
        else:
            st.info("Location data is still being enriched for this result set. Switch to Cards or Table for now.")
    elif display_mode == "Table":
        frame = analyst_frame(filtered)
        st.dataframe(frame, hide_index=True, use_container_width=True, height=720, column_config={
            "Lotly Score": st.column_config.NumberColumn(format="%.1f"), "Guide": st.column_config.NumberColumn(format="GBP %d"),
            "Opening offer": st.column_config.NumberColumn(format="GBP %d"), "Max buy": st.column_config.NumberColumn(format="GBP %d"),
            "Estimated value": st.column_config.NumberColumn(format="GBP %d"), "Profit at guide": st.column_config.NumberColumn(format="GBP %d"),
            "Seller motivation": st.column_config.NumberColumn(format="%.1f"), "Guide reduction %": st.column_config.NumberColumn(format="%.1f%%"),
            "Comparable confidence %": st.column_config.NumberColumn(format="%d%%"), "Legal pack %": st.column_config.ProgressColumn(min_value=0,max_value=100,format="%d%%"),
            "Listing": st.column_config.LinkColumn("Auction listing"),
        })
    else:
        card_rows = filtered[:24]
        with st.container(key="lotly_cards_grid"):
            for i in range(0, len(card_rows), 2):
                with st.container(key=f"lotly_card_row_{i//2}"):
                    cols = st.columns(2, gap="small")
                    with cols[0]:
                        render_dashboard_card(card_rows[i], top_opportunity=(i == 0 and not shortlist_only and view == "For you"))
                    if i + 1 < len(card_rows):
                        with cols[1]:
                            render_dashboard_card(card_rows[i+1], top_opportunity=False)
        if len(filtered) > len(card_rows):
            st.caption("Showing the strongest opportunities first. Use Table for the complete result set.")


def render_pipeline_page(feed_rows):
    stages = ["Reviewing", "Auctioneer Contacted", "Viewing", "Legal Review", "Offer Made", "Negotiating", "Bid Approved", "Won", "Lost"]
    items = []
    for row in feed_rows:
        workspace = db.workspace_for(row["id"])
        stage = workspace.get("stage") or "New"
        if stage != "New" or row.get("shortlisted"):
            items.append((row, workspace))
    if not items:
        st.info("Your pipeline is empty. Shortlist a property or move it to a deal stage from its Workspace tab.")
        return
    counts = {stage:sum(1 for _,w in items if w.get("stage") == stage) for stage in stages}
    summary_cols = st.columns(4)
    summary_cols[0].metric("Active deals", sum(1 for _,w in items if w.get("stage") not in {"Won","Lost","New"}))
    summary_cols[1].metric("Offers / negotiations", counts.get("Offer Made",0)+counts.get("Negotiating",0))
    summary_cols[2].metric("Bid approved", counts.get("Bid Approved",0))
    summary_cols[3].metric("Won", counts.get("Won",0))
    stage_filter = st.segmented_control("Pipeline stage", ["All"] + stages, default="All")
    visible = items if stage_filter == "All" else [(r,w) for r,w in items if w.get("stage") == stage_filter]
    visible.sort(key=lambda x: float(x[0].get("browse_score") or 0), reverse=True)
    for row, workspace in visible:
        with st.container(border=True):
            c1,c2,c3 = st.columns([3.2,1.2,1.1], vertical_alignment="center")
            with c1:
                st.markdown(f'<div class="card-sub">{workspace.get("stage") or "Reviewing"} · {row.get("source") or "Auction"}</div><div class="property-title">{clean_address(row)}</div>', unsafe_allow_html=True)
                if workspace.get("next_action"): st.caption(f"Next: {workspace.get('next_action')}")
            with c2:
                st.metric("Lotly Score", f"{float(row.get('browse_score') or 0):.1f}/10")
            with c3:
                if st.button("Open", key=f"pipeline_open_{row['id']}", type="primary", use_container_width=True):
                    st.session_state["selected_deal_id"] = row["id"]
                    st.session_state["selected_deal_source_key"] = row.get("source_key")
                    st.session_state["_lotly_pending_page"] = "Deal Room"
                    st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                    st.rerun()


def render_deal_room_index(feed_rows):
    actionable = [r for r in feed_rows if is_actionable(r)]
    priority = sorted(actionable, key=lambda r:(float(r.get("browse_score") or 0), float(r.get("motivation_score") or 0)), reverse=True)[:10]
    if not priority:
        st.info("No live opportunities are available yet.")
        return

    active_rooms = 0
    bid_ready = 0
    post_auction = 0
    strong = 0
    for row in actionable:
        workspace = db.workspace_for(row["id"])
        if workspace.get("stage") and workspace.get("stage") not in {"New", "Lost", "Archived"}:
            active_rooms += 1
        if deal_readiness(row).get("readiness_pct", 0) >= 80:
            bid_ready += 1
        if is_unsold(row):
            post_auction += 1
        if float(row.get("browse_score") or 0) >= 8.0:
            strong += 1

    st.markdown(
        '<div class="deal-index-strip">'
        f'<div class="deal-index-kpi"><div class="label">Priority opportunities</div><div class="value">{strong}</div></div>'
        f'<div class="deal-index-kpi"><div class="label">Active deal rooms</div><div class="value">{active_rooms}</div></div>'
        f'<div class="deal-index-kpi"><div class="label">80%+ decision ready</div><div class="value">{bid_ready}</div></div>'
        f'<div class="deal-index-kpi"><div class="label">Post-auction leverage</div><div class="value">{post_auction}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="section-title">Priority decision rooms</div><div class="section-note">Open the opportunities with the strongest combination of pricing, seller leverage and evidence. The Deal Room keeps the decision, underwriting and due diligence in one place.</div>', unsafe_allow_html=True)

    for i in range(0, len(priority), 2):
        cols = st.columns(2)
        for j, row in enumerate(priority[i:i+2]):
            readiness = deal_readiness(row)
            workspace = db.workspace_for(row["id"])
            with cols[j]:
                with st.container(border=False, key=f"deal_index_card_{row['id']}"):
                    image_col, body_col = st.columns([1.0, 1.65], vertical_alignment="top")
                    with image_col:
                        render_property_image(row, featured=False)
                    with body_col:
                        st.markdown(f'<div class="deal-index-meta">{html.escape(str(row.get("source") or "Auction"))} · Lot {html.escape(str(row.get("lot_number") or "-"))} · {html.escape(str(row.get("status") or "Live"))}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="deal-index-title">{html.escape(clean_address(row))}</div>', unsafe_allow_html=True)
                        render_badges(row, limit=3)
                        st.markdown(
                            '<div class="deal-index-metrics">'
                            f'<div class="deal-index-metric"><span>Guide</span><strong>{html.escape(guide_display(row))}</strong></div>'
                            f'<div class="deal-index-metric"><span>Max buy</span><strong>{html.escape(money(row.get("max_bid")))}</strong></div>'
                            f'<div class="deal-index-metric"><span>Readiness</span><strong>{int(readiness.get("readiness_pct") or 0)}%</strong></div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        stage = workspace.get("stage") or "New"
                        st.markdown(f'<div class="deal-stage-line">Stage: <strong>{html.escape(str(stage))}</strong> · Lotly Score <strong>{float(row.get("browse_score") or 0):.1f}/10</strong></div>', unsafe_allow_html=True)
                        if st.button("Open Deal Room  →", key=f"room_index_{row['id']}", type="primary", use_container_width=True):
                            st.session_state["selected_deal_id"] = row["id"]
                            st.session_state["selected_deal_source_key"] = row.get("source_key")
                            st.session_state["_lotly_pending_page"] = "Deal Room"
                            st.session_state["lotly_deal_tab_pending"] = "Snapshot"
                            st.rerun()


def render_reports_page(feed_rows):
    live=[r for r in feed_rows if is_actionable(r)]
    post=[r for r in live if is_unsold(r)]
    reduced=[r for r in live if float(r.get("price_reduction_pct") or 0)>0]
    commercial=[r for r in live if is_commercial(r)]
    residential=[r for r in live if not is_commercial(r)]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Live stock",len(live)); c2.metric("Post-auction",len(post)); c3.metric("Reduced",len(reduced)); c4.metric("Commercial",len(commercial))
    st.markdown('<div class="section-title">Auction house coverage</div>',unsafe_allow_html=True)
    source_rows=[]
    for source in sorted({r.get("source") or "Unknown" for r in live}):
        src=[r for r in live if (r.get("source") or "Unknown")==source]
        source_rows.append({"Auction house":source,"Live lots":len(src),"Post-auction":sum(1 for r in src if is_unsold(r)),"Reduced":sum(1 for r in src if float(r.get("price_reduction_pct") or 0)>0),"Average Lotly Score":round(sum(float(r.get("browse_score") or 0) for r in src)/len(src),1) if src else 0})
    st.dataframe(pd.DataFrame(source_rows),hide_index=True,use_container_width=True)
    st.markdown('<div class="section-title">Market mix</div>',unsafe_allow_html=True)
    m1,m2,m3=st.columns(3)
    m1.metric("Residential",len(residential)); m2.metric("Commercial",len(commercial)); m3.metric("Bid ready",sum(1 for r in live if legal_state(r)=="VERIFIED" and int(r.get("legal_pack_completeness_pct") or 0)>=100 and planning_state(r)=="SCREENED" and r.get("max_bid")))
    st.caption("Reports are built from Lotly's live tracked auction stock and evidence history, not from the whole UK auction market.")


def render_settings_page():
    st.markdown('<div class="section-title">Buying criteria</div><div class="section-note">Lotly uses these preferences to rank opportunities around your acquisition strategy.</div>', unsafe_allow_html=True)
    with st.container(border=True):
        c1,c2,c3 = st.columns(3)
        with c1:
            st.number_input("Commercial target GBP/sq ft", min_value=1, step=5, key="commercial_target_psf")
            st.number_input("Commercial ceiling GBP/sq ft", min_value=1, step=5, key="commercial_ceiling_psf")
        with c2:
            st.number_input("Preferred commercial size", min_value=500, step=500, key="commercial_min_sqft")
            st.number_input("Commercial max guide", min_value=0, step=50_000, key="commercial_max_price")
        with c3:
            st.number_input("Preferred motorway miles", min_value=0.5, step=0.5, key="preferred_motorway_miles")
            st.number_input("Residential target guide", min_value=0, step=5_000, key="residential_target_price")
        st.slider("Priority deal threshold", 1.0, 10.0, step=0.5, key="hot_score")
    st.markdown('<div class="section-title">Underwriting defaults</div>', unsafe_allow_html=True)
    with st.container(border=True):
        c1,c2,c3 = st.columns(3)
        c1.number_input("Generic auction fee", min_value=0, step=250, key="default_auction_fee")
        c2.number_input("Legal allowance", min_value=0, step=250, key="default_legal")
        c3.number_input("Survey / DD allowance", min_value=0, step=250, key="default_survey")
        c4,c5 = st.columns(2)
        c4.number_input("Residential target margin %", min_value=0.0, max_value=80.0, step=1.0, key="default_res_margin")
        c5.number_input("Commercial target uplift %", min_value=0.0, max_value=80.0, step=1.0, key="default_com_margin")
    st.markdown('<div class="section-title">Data connections & system health</div>', unsafe_allow_html=True)
    with st.container(border=True):
        h1,h2,h3 = st.columns(3)
        with h1:
            if cloud_store and not cloud_bootstrap_error and not cloud_probe_error:
                st.success("Cloud history connected")
                st.caption("Read/write verified" if st.session_state.get("cloud_write_verified") else "Connected; write not yet verified")
                if st.button("Sync cloud snapshot", use_container_width=True):
                    result = sync_cloud("manual sync", quiet=False)
                    if result.get("synced"): st.success("Snapshot saved")
            else:
                st.error("Cloud history needs attention" if (cloud_bootstrap_error or cloud_probe_error) else "Local-only history")
        with h2:
            st.success("Companies House connected") if companies_house_api_key else st.info("Companies House not configured")
            st.caption("Ownership and corporate-pressure intelligence")
        with h3:
            st.success("Legal-pack automation on") if legal_access.auto_enabled else st.info("Legal-pack automation off")
            st.caption("No CAPTCHA or anti-bot bypass is attempted")
        with st.expander("Provider access detail"):
            for provider in ("eddisons","savills","auction_house","allsop"):
                access_status = provider_access_status(legal_access, provider)
                label = access_status.get("label") or provider
                status = access_status.get("status") or "unknown"
                st.write(f"**{label}:** {status}")


if selected:
    render_deal_room(selected)
elif not rows:
    st.info("Lotly has not built the live opportunity feed yet. Use Update data → Refresh live auctions to pull the first catalogue.")
elif lotly_page == "Discover":
    render_feed(rows, shortlist_only=False)
elif lotly_page == "Shortlist":
    render_feed(rows, shortlist_only=True)
elif lotly_page == "Pipeline":
    render_pipeline_page(rows)
elif lotly_page == "Deal Room":
    render_deal_room_index(rows)
elif lotly_page == "Reports":
    render_reports_page(rows)
elif lotly_page == "Settings":
    render_settings_page()

st.divider()
st.caption("Lotly helps professional buyers screen auction opportunities faster. Auctioneer listings and the latest legal pack/addendum remain authoritative. Automated valuation, planning and risk outputs are evidence screens, not RICS valuation, legal or tax advice.")
