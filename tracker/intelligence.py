"""Acquisition intelligence assembled from the tracker's existing evidence.

The functions in this module deliberately separate confirmed source evidence from
interpretation. They do not invent seller circumstances. Inferences are labelled as
such and are intended to help a deal sourcer decide what to verify next.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Iterable

FAILURE_STATUSES = {"no bids", "last bid", "unsold", "available post-auction"}
DISTRESS_SELLER_TYPES = {"receiver", "lpa receiver", "administrator", "liquidator", "mortgagee", "executor", "probate"}


def _num(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_key(value):
    if not value:
        return "9999-12-31"
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    return m.group(0) if m else text[:10]


def _clean(value, limit=180):
    return " ".join(str(value or "").split())[:limit]


def _planning_timeline(planning_items: Iterable[dict]) -> list[dict]:
    out = []
    for item in planning_items or []:
        if item.get("kind") != "application" or not item.get("likely_subject"):
            continue
        meta = item.get("metadata") or {}
        date = (
            meta.get("decision-date") or meta.get("decision_date") or meta.get("start-date")
            or meta.get("start_date") or meta.get("entry-date") or meta.get("entry_date")
        )
        decision = _clean(meta.get("planning-decision") or meta.get("decision") or meta.get("status"), 80)
        description = _clean(meta.get("description") or item.get("label"), 220)
        label = f"Planning {decision.lower()}" if decision else "Planning application"
        detail = description
        if item.get("reference"):
            detail = f"{item.get('reference')} - {detail}"
        out.append({
            "date": _date_key(date),
            "display_date": _clean(date) or "Date not captured",
            "type": "planning",
            "label": label,
            "detail": detail,
            "source_url": item.get("source_url") or "",
        })
    return out


def _auction_timeline(history: Iterable[dict]) -> list[dict]:
    """Build a human timeline while avoiding duplicate post-auction observations.

    A result and a later 'available post-auction' observation on the same auction date
    are kept as separate status events for narrative clarity but are not described as
    separate auction attempts.
    """
    rows = list(history or [])
    seen = set()
    out = []
    for event in rows:
        date = event.get("auction_date") or str(event.get("captured_at") or "")[:10]
        key = (
            _date_key(date),
            str(event.get("status") or "").lower(),
            int(event.get("guide_price") or 0),
            int(event.get("result_price") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        status = _clean(event.get("status") or "Observed", 60)
        bits = []
        if event.get("guide_text"):
            bits.append(f"Guide {_clean(event.get('guide_text'), 90)}")
        elif event.get("guide_price"):
            bits.append(f"Guide GBP {float(event['guide_price']):,.0f}")
        if event.get("result_text"):
            bits.append(_clean(event.get("result_text"), 110))
        elif event.get("result_price"):
            bits.append(f"Result GBP {float(event['result_price']):,.0f}")
        out.append({
            "date": _date_key(date),
            "display_date": _clean(date) or "Date not captured",
            "type": "auction",
            "label": status,
            "detail": " | ".join(bits),
            "source_url": "",
        })
    return out


def seller_profile(legal_summary: dict | None, lot: dict | None = None) -> dict:
    legal_summary = legal_summary or {}
    extracted = legal_summary.get("extracted_fields") or {}
    lot = lot or {}
    seller_type = _clean(extracted.get("seller_type"), 60)
    seller_name = _clean(extracted.get("seller_name") or extracted.get("proprietor_name"), 180)
    if not seller_type:
        text = " ".join(str(lot.get(k) or "") for k in ("title", "raw_text", "detail_text")).lower()
        for term, label in (
            ("lpa receiver", "LPA receiver"), ("receiver", "Receiver"), ("administrator", "Administrator"),
            ("liquidator", "Liquidator"), ("mortgagee", "Mortgagee"), ("executor", "Executor"),
            ("probate", "Probate"), ("fund disposal", "Fund disposal"),
        ):
            if term in text:
                seller_type = label
                break
    return {
        "seller_name": seller_name or None,
        "seller_type": seller_type or None,
        "title_number": extracted.get("title_number"),
        "company_number": extracted.get("company_number"),
        "registered_office": extracted.get("registered_office"),
        "title_price_paid": extracted.get("title_price_paid"),
        "title_price_paid_date": extracted.get("title_price_paid_date"),
        "contacts": legal_summary.get("contacts") or [],
    }


def buyer_leverage(lot: dict, deal_analysis: dict | None = None, legal_summary: dict | None = None,
                   planning_items: Iterable[dict] | None = None) -> dict:
    """Score negotiating leverage separately from seller motivation."""
    deal_analysis = deal_analysis or {}
    legal_summary = legal_summary or {}
    status = str(lot.get("status") or "").lower()
    points = {
        "available post-auction": 45,
        "no bids": 42,
        "unsold": 40,
        "last bid": 37,
        "relisted": 27,
        "withdrawn": 14,
        "postponed": 8,
        "live": 4,
    }.get(status, 3)
    reasons = []
    if status in FAILURE_STATUSES:
        reasons.append(f"Current status is {lot.get('status')}")

    failures = int(deal_analysis.get("failure_count") or 0)
    if failures:
        points += min(22, failures * 8)
        reasons.append(f"{failures} distinct failed-auction attempt(s) observed")

    reduction = _num(deal_analysis.get("price_reduction_pct"), 0) or 0
    if reduction >= 20:
        points += 18
    elif reduction >= 10:
        points += 12
    elif reduction >= 5:
        points += 7
    if reduction >= 5:
        reasons.append(f"Observed guide reduction {reduction:.1f}%")

    days = deal_analysis.get("days_since_failure")
    if days is not None:
        if 15 <= days <= 75:
            points += 10
            reasons.append(f"Post-auction exposure has continued for {int(days)} days")
        elif days > 75:
            points += 7
            reasons.append(f"Extended unresolved exposure of {int(days)} days")
        elif days <= 14:
            points += 5
            reasons.append("Fresh post-auction negotiation window")

    if (deal_analysis.get("features") or {}).get("vacant"):
        points += 5
        reasons.append("Vacant possession signal")

    profile = seller_profile(legal_summary, lot)
    seller_type = str(profile.get("seller_type") or "").lower()
    if any(term in seller_type for term in DISTRESS_SELLER_TYPES):
        points += 10
        reasons.append(f"Disposal context: {profile.get('seller_type')}")

    refused = 0
    for item in planning_items or []:
        if item.get("kind") == "application" and item.get("likely_subject"):
            meta = item.get("metadata") or {}
            decision = str(meta.get("planning-decision") or meta.get("decision") or "").lower()
            if "refus" in decision:
                refused += 1
    if refused:
        points += min(8, refused * 4)
        reasons.append(f"{refused} subject planning refusal(s) may have weakened the prior strategy")

    score = round(max(0, min(100, points)) / 10, 1)
    label = "Very High" if score >= 8.5 else "High" if score >= 7 else "Medium" if score >= 5 else "Low" if score >= 3 else "Very Low"
    return {"buyer_leverage_score": score, "buyer_leverage_label": label, "buyer_leverage_reasons": reasons}


def build_vendor_story(lot: dict, history: Iterable[dict] | None = None, deal_analysis: dict | None = None,
                       legal_summary: dict | None = None, planning_items: Iterable[dict] | None = None) -> dict:
    """Build an evidence-led seller story with clearly labelled inferences."""
    deal_analysis = deal_analysis or {}
    legal_summary = legal_summary or {}
    planning_items = list(planning_items or [])
    profile = seller_profile(legal_summary, lot)
    leverage = buyer_leverage(lot, deal_analysis, legal_summary, planning_items)

    timeline = _auction_timeline(history or []) + _planning_timeline(planning_items)
    if profile.get("title_price_paid"):
        paid_date = profile.get("title_price_paid_date") or ""
        timeline.append({
            "date": _date_key(paid_date),
            "display_date": _clean(paid_date) or "Date not captured",
            "type": "ownership",
            "label": "Recorded acquisition / price paid",
            "detail": f"Title evidence records GBP {float(profile['title_price_paid']):,.0f} paid",
            "source_url": "",
        })
    timeline.sort(key=lambda x: (x.get("date") or "9999", 0 if x.get("type") == "planning" else 1))

    facts = []
    if profile.get("seller_name"):
        facts.append(f"Legal evidence names the proprietor/seller as {profile['seller_name']}")
    if profile.get("seller_type"):
        facts.append(f"Disposal context identified as {profile['seller_type']}")
    if profile.get("title_price_paid"):
        when = f" on {profile.get('title_price_paid_date')}" if profile.get("title_price_paid_date") else ""
        facts.append(f"Title evidence records a prior price paid of GBP {float(profile['title_price_paid']):,.0f}{when}")
    failures = int(deal_analysis.get("failure_count") or 0)
    if failures:
        facts.append(f"{failures} distinct failed-auction attempt(s) are recorded")
    reduction = _num(deal_analysis.get("price_reduction_pct"), 0) or 0
    if reduction > 0:
        facts.append(f"Observed guide has reduced by {reduction:.1f}%")
    if (deal_analysis.get("features") or {}).get("vacant"):
        facts.append("Listing evidence indicates vacancy / vacant possession")
    days = deal_analysis.get("days_since_failure")
    if days is not None:
        facts.append(f"Latest failed/post-auction signal is approximately {int(days)} days old")

    subject_refusals = []
    subject_approvals = []
    for item in planning_items:
        if item.get("kind") != "application" or not item.get("likely_subject"):
            continue
        meta = item.get("metadata") or {}
        decision = str(meta.get("planning-decision") or meta.get("decision") or "")
        if re.search(r"refus", decision, re.I):
            subject_refusals.append(item)
        elif re.search(r"approv|grant|permitted", decision, re.I):
            subject_approvals.append(item)
    if subject_refusals:
        facts.append(f"{len(subject_refusals)} likely subject-property planning refusal(s) found")
    if subject_approvals:
        facts.append(f"{len(subject_approvals)} likely subject-property planning approval(s) found")

    inferences = []
    if failures >= 2:
        inferences.append("Repeated failed auction exposure suggests the seller may be increasingly receptive to a credible post-auction offer.")
    elif failures == 1 and str(lot.get("status") or "").lower() == "available post-auction":
        inferences.append("The lot is in an active post-auction negotiation window, which can create more flexibility than a competitive live sale.")
    if reduction >= 10:
        inferences.append("A material guide reduction is consistent with increased price flexibility, although the seller's reserve remains unconfirmed.")
    if subject_refusals:
        inferences.append("A refused planning strategy may have reduced the owner's preferred exit options; confirm whether the seller incurred development/planning costs and whether an alternative scheme remains viable.")
    if (deal_analysis.get("features") or {}).get("vacant"):
        inferences.append("If the asset is genuinely vacant, ongoing finance, rates, insurance, service-charge or security costs may increase pressure to transact; these costs are not confirmed unless evidenced separately.")
    if profile.get("seller_type") and any(term in str(profile["seller_type"]).lower() for term in DISTRESS_SELLER_TYPES):
        inferences.append("The identified disposal context can favour certainty and speed of execution, but it does not by itself prove that a discounted offer will be accepted.")

    confidence_points = 25
    if len(timeline) >= 2:
        confidence_points += 20
    if failures:
        confidence_points += 15
    if reduction > 0:
        confidence_points += 10
    if profile.get("seller_name") or profile.get("seller_type"):
        confidence_points += 15
    if subject_refusals or subject_approvals:
        confidence_points += 10
    if legal_summary.get("status") in {"parsed", "reviewed"}:
        confidence_points += 10
    confidence = max(0, min(100, confidence_points))
    confidence_label = "High" if confidence >= 75 else "Medium" if confidence >= 50 else "Low"

    return {
        "seller_profile": profile,
        "timeline": timeline,
        "confirmed_facts": facts,
        "inferences": inferences,
        "story_confidence": confidence,
        "story_confidence_label": confidence_label,
        **leverage,
    }


def deal_readiness(row: dict) -> dict:
    """Return a weighted acquisition-readiness score and explicit blockers."""
    legal_status = str(row.get("legal_status") or "").lower()
    planning_status = str(row.get("planning_status") or "").lower()
    comp_conf = int(row.get("comparable_confidence") or 0)
    market_value = _num(row.get("market_value") or row.get("gdv") or row.get("comparable_valuation_mid"))
    lease_years = _num(row.get("legal_lease_years"))
    if lease_years is None:
        lease_years = _num(row.get("listing_lease_years"))

    checks = []
    def add(name, weight, state, detail="", blocker=False):
        earned = weight if state == "complete" else weight * 0.5 if state == "partial" else 0
        checks.append({"name": name, "weight": weight, "state": state, "earned": earned, "detail": detail, "blocker": blocker})

    add("Auction status verified", 10, "complete" if row.get("status") else "missing", row.get("status") or "Status missing")
    add("Property detail page", 8, "complete" if row.get("detail_enriched") else "missing", "Detail/image enrichment" if row.get("detail_enriched") else "Detail page not enriched")
    add("Auction history", 8, "complete" if int(row.get("history_points") or row.get("failure_count") or 0) >= 2 else "partial" if int(row.get("history_points") or 0) else "missing", f"{int(row.get('failure_count') or 0)} failed attempt(s) observed")
    add("Comparable valuation", 14, "complete" if comp_conf >= 70 else "partial" if comp_conf >= 50 else "missing", f"Comparable confidence {comp_conf}%", blocker=comp_conf < 60)
    add("Market value / GDV", 12, "complete" if market_value else "missing", "Valuation basis present" if market_value else "Market value/GDV required", blocker=not bool(market_value))
    add("Planning screen", 10, "complete" if planning_status == "ok" else "missing", "Official screen run" if planning_status == "ok" else "Planning risk unknown")
    add("Legal pack", 20, "complete" if legal_status in {"parsed", "reviewed"} else "partial" if legal_status == "links-only" else "missing", "Legal evidence parsed/reviewed" if legal_status in {"parsed", "reviewed"} else "Legal pack not parsed", blocker=legal_status not in {"parsed", "reviewed"})
    works_missing = bool(row.get("works_missing"))
    add("Works / capex", 8, "missing" if works_missing else "complete", "Works estimate required" if works_missing else "No unresolved works-budget gate", blocker=works_missing)
    tenure = str(row.get("tenure") or "Unknown")
    if lease_years is not None and tenure.lower() == "leasehold":
        tenure_detail = f"Short lease: approximately {lease_years:.0f} years remaining" if lease_years < 80 else f"Leasehold - approximately {lease_years:.0f} years remaining"
    else:
        tenure_detail = tenure
    add("Tenure / lease", 5, "complete" if tenure != "Unknown" else "missing", tenure_detail, blocker=bool(lease_years and lease_years < 80))
    add("Location/access", 5, "complete" if row.get("latitude") is not None and row.get("longitude") is not None else "missing", row.get("nearest_junction") or "Coordinates/access pending")

    total = sum(x["weight"] for x in checks)
    earned = sum(x["earned"] for x in checks)
    percent = int(round(100 * earned / total)) if total else 0
    blockers = [x["detail"] or x["name"] for x in checks if x.get("blocker")]
    if blockers:
        status = "BID BLOCKED"
    else:
        status = "READY FOR FINAL REVIEW" if percent >= 85 else "NEARLY READY" if percent >= 70 else "IN PROGRESS" if percent >= 45 else "EARLY STAGE"
    return {"readiness_pct": percent, "readiness_status": status, "readiness_checks": checks, "readiness_blockers": list(dict.fromkeys(blockers))}


def next_actions(row: dict, story: dict | None = None) -> list[dict]:
    """Generate a short action queue from evidence gaps; no external action is taken."""
    story = story or {}
    actions = []
    def add(priority, action, reason):
        actions.append({"priority": priority, "action": action, "reason": reason})

    legal_status = str(row.get("legal_status") or "").lower()
    if legal_status not in {"parsed", "reviewed"}:
        add(1, "Obtain and review the latest legal pack + addendum", "Bid approval is blocked until legal evidence is parsed/reviewed.")
    if row.get("works_missing"):
        add(2, "Obtain a refurbishment / capex estimate", "The listing signals works but the model currently has no reliable works budget.")
    lease = _num(row.get("legal_lease_years"))
    if lease is None:
        lease = _num(row.get("listing_lease_years"))
    if lease and lease < 85:
        add(2, "Price the lease-extension / lender impact", f"Approximately {lease:.0f} years remaining can affect value and financeability.")
    if int(row.get("comparable_confidence") or 0) < 65:
        add(3, "Verify valuation with tighter local comparables", f"Automated comparable confidence is {int(row.get('comparable_confidence') or 0)}%.")
    if str(row.get("planning_status") or "").lower() != "ok":
        add(3, "Check the local planning authority record", "Official planning coverage is incomplete or has not been run.")
    if row.get("status") in {"Available post-auction", "No Bids", "Unsold", "Last Bid"}:
        opener = row.get("opening_offer")
        reason = "The property has a failed/post-auction signal. Test seller expectation before increasing price."
        action = f"Call the auctioneer and test an opening position around GBP {float(opener):,.0f}" if opener else "Call the auctioneer and establish current seller expectation"
        add(4, action, reason)
    elif row.get("auction_date"):
        add(4, "Confirm viewing, legal-pack deadline and bidding timetable", f"Auction date recorded as {row.get('auction_date')}.")
    actions.sort(key=lambda x: x["priority"])
    return actions[:6]


def solicitor_questions(row: dict, legal_summary: dict | None = None) -> list[str]:
    """Generate evidence-led questions for the buyer's solicitor.

    These are prompts for professional review, not answers or legal advice.
    """
    legal_summary = legal_summary or {}
    extracted = legal_summary.get("extracted_fields") or row.get("legal_extracted_fields") or {}
    questions = []
    status = str(legal_summary.get("status") or row.get("legal_status") or "").lower()
    if status not in {"parsed", "reviewed"}:
        questions.append("Please confirm we have the latest complete legal pack and every addendum, and identify any missing documents before exchange/bidding.")
    lease = _num(extracted.get("lease_years_remaining") or row.get("legal_lease_years") or row.get("listing_lease_years"))
    tenure = str(row.get("tenure") or "").lower()
    if lease is not None and lease < 85:
        questions.append(f"The lease appears to have approximately {lease:.1f} years remaining. Please confirm the exact unexpired term, statutory/informal extension options, likely premium/costs and lender implications.")
    elif "leasehold" in tenure:
        questions.append("Please confirm the exact lease term/unexpired years, ground-rent review pattern, service-charge position and any restrictions affecting letting, alterations or assignment.")
    if extracted.get("service_charge_amount") is not None or "leasehold" in tenure:
        questions.append("Please confirm current service charge, reserve/sinking fund, arrears, Section 20/major works and whether any sums transfer to the buyer.")
    if extracted.get("ground_rent_amount") is not None or "leasehold" in tenure:
        questions.append("Please confirm current ground rent and every review/escalation clause, including whether it creates any lender or AST-trap concern.")
    if int(extracted.get("registered_charge_count") or 0) > 0:
        questions.append("Registered charges are referenced. Please confirm which charges will be discharged on completion and whether any restriction could delay registration.")
    if extracted.get("arrears_flag"):
        questions.append("Arrears/outstanding sums are mentioned. Please confirm the amount, who is liable, the apportionment mechanism and whether completion monies must discharge them.")
    if extracted.get("ews1_or_cladding_flag") or extracted.get("fire_safety_flag"):
        questions.append("Please confirm the EWS1/cladding/fire-safety/building-safety position, any remediation liability, landlord certificates and likely mortgageability implications.")
    elif str(row.get("property_type") or "").lower() in {"flat", "apartment"}:
        questions.append("Please confirm whether the building requires an EWS1/formal external-wall or fire-safety review, and whether any remediation or Building Safety Act liabilities could affect mortgageability or service charges.")
    if bool(legal_summary.get("vat_flag") or row.get("legal_vat_flag")):
        questions.append("VAT/option-to-tax wording is present. Please confirm whether VAT is payable, whether TOGC treatment is intended and the SDLT consideration/tax implications for the buyer.")
    if extracted.get("seller_costs_amount") is not None or legal_summary.get("buyer_fee_detected"):
        questions.append("Please confirm every auction, seller legal/search and other contractual cost payable by the buyer in addition to the purchase price.")
    completion = _num(legal_summary.get("completion_days") or row.get("legal_completion_days"))
    if completion and completion <= 20:
        questions.append(f"Completion appears to be required within {completion:.0f} days. Please confirm the exact timetable, default interest/remedies and whether lender/funds timing is realistic.")
    if bool(legal_summary.get("has_addendum") or row.get("legal_has_addendum")):
        questions.append("An addendum is detected. Please confirm the latest version and explain every change that affects title, price, occupation, completion or buyer costs.")
    if not questions:
        questions.append("Please review title, special conditions, searches, tenancy/occupation, rights, restrictions, covenants, easements, completion mechanics and all buyer costs, and flag anything material to value or resale/mortgageability.")
    return list(dict.fromkeys(questions))[:12]


def deal_brief_markdown(row: dict, story: dict, readiness: dict, actions: list[dict]) -> str:
    """Create a concise portable acquisition brief from the current evidence."""
    profile = story.get("seller_profile") or {}
    lines = [
        f"# Deal Brief - {_clean(row.get('address') or row.get('title') or 'Property')}",
        "",
        f"- Auction house: {row.get('source') or '-'}",
        f"- Lot: {row.get('lot_number') or '-'}",
        f"- Status: {row.get('status') or '-'}",
        f"- Guide: GBP {float(row.get('guide_price') or 0):,.0f}" if row.get("guide_price") else "- Guide: -",
        f"- Deal potential: {float(row.get('browse_score') or 0):.1f}/10",
        f"- Vendor motivation: {float(row.get('motivation_score') or 0):.1f}/10",
        f"- Buyer leverage: {float(story.get('buyer_leverage_score') or 0):.1f}/10",
        f"- Deal readiness: {int(readiness.get('readiness_pct') or 0)}% ({readiness.get('readiness_status')})",
        f"- Opening offer: GBP {float(row.get('opening_offer') or 0):,.0f}" if row.get("opening_offer") else "- Opening offer: -",
        f"- Maximum bid: GBP {float(row.get('max_bid') or 0):,.0f}" if row.get("max_bid") else "- Maximum bid: not approved / unavailable",
        f"- Market value / GDV: GBP {float(row.get('market_value') or row.get('comparable_valuation_mid') or 0):,.0f}" if (row.get("market_value") or row.get("comparable_valuation_mid")) else "- Market value / GDV: -",
        f"- Recommendation: {row.get('recommendation') or 'WATCH'} - {row.get('recommended_action') or ''}",
        "",
        "## Seller / Vendor",
        f"- Registered proprietor / seller: {profile.get('seller_name') or 'Not extracted'}",
        f"- Disposal type: {profile.get('seller_type') or 'Not identified'}",
        f"- Title number: {profile.get('title_number') or 'Not extracted'}",
        "",
        "## Confirmed motivation evidence",
    ]
    for fact in story.get("confirmed_facts") or ["No additional confirmed seller evidence yet."]:
        lines.append(f"- {fact}")
    lines += ["", "## Interpretation (not confirmed fact)"]
    for item in story.get("inferences") or ["Insufficient evidence for a useful seller-pressure inference."]:
        lines.append(f"- {item}")
    lines += ["", "## Bid blockers / DD gaps"]
    for blocker in readiness.get("readiness_blockers") or ["No automated blocker recorded; normal legal and physical due diligence still required."]:
        lines.append(f"- {blocker}")
    lines += ["", "## Recommended next actions"]
    for idx, action in enumerate(actions or [], start=1):
        lines.append(f"{idx}. {action.get('action')} - {action.get('reason')}")
    lines += ["", "---", "Desktop acquisition triage only. Verify legal, valuation, tax, condition and funding evidence before bidding."]
    return "\n".join(lines)
