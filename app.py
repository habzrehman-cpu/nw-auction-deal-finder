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
HERO_HOUSES = ASSET_DIR / "hero_houses.png"

def _asset_data_uri(path):
    try:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except Exception:
        return ""

LOTLY_ICON_DATA_URI = _asset_data_uri(LOTLY_ICON)
LOTLY_LOGO_DATA_URI = _asset_data_uri(LOTLY_LOGO)
HERO_HOUSES_DATA_URI = _asset_data_uri(HERO_HOUSES)

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
        buy_box = f'''<div class="side-card"><div class="side-card-title"><span>◎ &nbsp; Your buy box</span><span>Edit</span></div>
        <div class="side-kv"><span>Commercial target</span><strong>{POUND}{int(st.session_state['commercial_target_psf'])} / sq ft</strong></div>
        <div class="side-kv"><span>Max guide price</span><strong>{money(st.session_state['commercial_max_price'],0)}</strong></div>
        <div class="side-kv"><span>Preferred size</span><strong>{int(st.session_state['commercial_min_sqft']):,}–10,000 sq ft</strong></div>
        <div class="side-kv"><span>Motorway radius</span><strong>{float(st.session_state['preferred_motorway_miles']):.0f} miles</strong></div>
        <div class="side-link">View full criteria &nbsp; →</div></div>'''
        st.markdown(buy_box, unsafe_allow_html=True)
        st.markdown('<div class="side-brand-card"><span class="diamond">◆</span>Serious opportunities.<br>Smarter decisions.</div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-version">Lotly v1.12.9</div>', unsafe_allow_html=True)

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
    uw = underwrite_property(
        row,
        row,
        assumptions=_saved_uw,
        defaults=underwriting_defaults,
        strategy="auto",
    )
    row.update(uw)
    row["profit_at_guide"] = None
    row["guide_all_in_cost"] = None
    if row.get("guide_price"):
        _guide_assumptions = dict(_saved_uw or {})
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
        render_property_image(chosen, featured=True)
    with right:
        st.markdown('<div class="eyebrow">Lotly Deal Room</div>', unsafe_allow_html=True)
        st.caption(f"{chosen.get('source')} · Lot {chosen.get('lot_number') or '-'} · {chosen.get('property_type')} · {chosen.get('status')}")
        st.header(clean_address(chosen))
        render_badges(chosen, limit=5)
        a, b, c, d = st.columns(4)
        a.metric("Lotly Score", f"{chosen.get('browse_score', 0):.1f}/10")
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

    tabs = st.tabs(["Snapshot", "Seller", "Financials", "Comparables", "Auction", "Legal & Planning", "Location", "Workspace"])

    with tabs[0]:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Opening offer", money(chosen.get("opening_offer")))
        m2.metric("Estimated value / GDV", money(chosen.get("market_value") or chosen.get("comparable_valuation_mid")))
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
                    st.rerun()


def render_deal_room_index(feed_rows):
    actionable = [r for r in feed_rows if is_actionable(r)]
    priority = sorted(actionable, key=lambda r:(float(r.get("browse_score") or 0), float(r.get("motivation_score") or 0)), reverse=True)[:12]
    if not priority:
        st.info("No live opportunities are available yet.")
        return
    st.markdown('<div class="section-title">Priority deal rooms</div><div class="section-note">Open the strongest live opportunities directly into underwriting, comparables, legal evidence and negotiation workspace.</div>', unsafe_allow_html=True)
    for i in range(0,len(priority),3):
        cols=st.columns(3)
        for j,row in enumerate(priority[i:i+3]):
            with cols[j]:
                with st.container(border=True):
                    st.markdown(f'<div class="card-sub">{row.get("source") or "Auction"} · {row.get("status") or "Live"}</div><div class="property-title">{clean_address(row)}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="lotly-score-mini"><div class="num">{float(row.get("browse_score") or 0):.1f}</div><div class="lbl">Lotly Score</div></div>', unsafe_allow_html=True)
                    st.caption(f"Guide {guide_display(row)} · Max buy {money(row.get('max_bid'))}")
                    if st.button("Open Deal Room",key=f"room_index_{row['id']}",type="primary",use_container_width=True):
                        st.session_state["selected_deal_id"]=row["id"]
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
