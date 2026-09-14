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

def _looks_like_date(value) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", text)
        or re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b", text)
    )


def _event_timestamp(event: dict):
    """Best-effort observation timestamp used only to order evidence."""
    for raw in (event.get("captured_at"), event.get("auction_date")):
        if not raw:
            continue
        text = str(raw).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:16] if "%H:%M" in fmt else text[:10], fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return datetime.min.replace(tzinfo=timezone.utc)


def auction_history_integrity(row: dict, history: Iterable[dict] | None = None) -> dict:
    """Normalise auction observations without rewriting the raw audit trail.

    Auction websites can temporarily report ``Sold`` / ``Sold Prior`` / ``Sold After``
    before a transaction later falls through or the lot returns to market.  For a
    novice investor we must not present those observations as a completed legal sale.
    This helper de-duplicates identical observations, separates concrete failed-auction
    results from sold *signals*, and treats the current listing status as the best
    evidence of where the opportunity sits now.
    """
    raw_rows = [dict(x) for x in (history or [])]
    current_status = str(row.get("status") or "Unknown").strip()
    current_status_low = current_status.lower()

    # Add the current listing snapshot to the evidence set so the timeline always
    # explains where the property is now.  This is display-only; the DB audit trail
    # remains unchanged.
    if current_status and current_status_low != "unknown":
        raw_rows.append({
            "captured_at": row.get("last_seen") or row.get("updated_at") or "",
            "auction_date": row.get("auction_date") or "",
            "guide_text": row.get("guide_text") or "",
            "guide_price": row.get("guide_price"),
            "guide_price_high": row.get("guide_price_high"),
            "result_text": row.get("result_text") or "",
            "result_price": row.get("result_price"),
            "status": current_status,
            "_current": True,
        })

    sold_statuses = {"sold", "sold prior", "sold after"}
    concrete_failure_statuses = {"no bids", "last bid", "unsold"}

    # Keep the latest copy of an identical observation.  Ignore captured_at in the
    # identity key so repeated crawler snapshots do not create duplicate timeline rows.
    dedup = {}
    for event in raw_rows:
        status = str(event.get("status") or "Observed").strip()
        status_low = status.lower()
        auction_date = str(event.get("auction_date") or "").strip()
        date_key = _date_key(auction_date) if _looks_like_date(auction_date) else ""
        guide = int(_num(event.get("guide_price"), 0) or 0)
        result = int(_num(event.get("result_price"), 0) or 0)
        key = (status_low, date_key, guide, result)
        existing = dedup.get(key)
        if existing is None or _event_timestamp(event) >= _event_timestamp(existing) or event.get("_current"):
            dedup[key] = event

    events = sorted(dedup.values(), key=_event_timestamp)
    sold_events = [e for e in events if str(e.get("status") or "").strip().lower() in sold_statuses]
    failure_events = [e for e in events if str(e.get("status") or "").strip().lower() in concrete_failure_statuses]

    # De-duplicate concrete failed attempts conservatively: same auction date, or the
    # same guide when one representation has no valid auction date.
    verified_failures = []
    for event in failure_events:
        auction_date = str(event.get("auction_date") or "").strip()
        date_key = _date_key(auction_date) if _looks_like_date(auction_date) else ""
        guide = int(_num(event.get("guide_price"), 0) or 0)
        duplicate = False
        for prior in verified_failures:
            p_date_raw = str(prior.get("auction_date") or "").strip()
            p_date = _date_key(p_date_raw) if _looks_like_date(p_date_raw) else ""
            p_guide = int(_num(prior.get("guide_price"), 0) or 0)
            if date_key and p_date and date_key == p_date:
                duplicate = True
                break
            if guide and p_guide == guide and (not date_key or not p_date):
                duplicate = True
                break
        if not duplicate:
            verified_failures.append(event)

    current_available = current_status_low in {"available post-auction", "relisted"}
    sale_status_conflict = bool(current_available and sold_events)
    returned_to_market = bool(sale_status_conflict)

    # Beginner-facing timeline: sold observations are explicitly labelled as signals,
    # not completed transfers.  When the property is now available again, say so.
    timeline = []
    for event in events:
        status = str(event.get("status") or "Observed").strip()
        status_low = status.lower()
        captured = str(event.get("captured_at") or "").strip()
        auction_date = str(event.get("auction_date") or "").strip()
        when = auction_date if _looks_like_date(auction_date) else captured[:10]
        when = when or "Date not captured"
        if status_low in sold_statuses:
            label = "Sale status reported — completion not confirmed"
            note = "Auctioneer status only; not proof of completed purchase or Land Registry transfer."
            if sale_status_conflict:
                note += " The property is currently available again, so the earlier sale may not have completed."
        elif status_low == "available post-auction":
            label = "Returned to market / available post-auction" if sale_status_conflict else "Available post-auction"
            note = "Current listing status." if event.get("_current") else "Observed post-auction availability."
        elif status_low == "relisted":
            label = "Relisted / returned to market"
            note = "The lot is being marketed again."
        elif status_low in concrete_failure_statuses:
            label = f"Failed-auction result: {status}"
            note = "Concrete auction-result signal."
        else:
            label = status or "Observed"
            note = "Observed auction status."
        detail_bits = []
        if event.get("guide_text"):
            detail_bits.append(f"Guide {_clean(event.get('guide_text'), 90)}")
        elif _num(event.get("guide_price")):
            detail_bits.append(f"Guide GBP {float(event['guide_price']):,.0f}")
        if event.get("result_text"):
            detail_bits.append(_clean(event.get("result_text"), 110))
        elif _num(event.get("result_price")):
            detail_bits.append(f"Reported result GBP {float(event['result_price']):,.0f}")
        if note:
            detail_bits.append(note)
        timeline.append({
            "when": when,
            "status": status,
            "status_low": status_low,
            "label": label,
            "detail": " · ".join(detail_bits),
            "is_current": bool(event.get("_current")),
            "is_sold_signal": status_low in sold_statuses,
        })

    verified_failure_count = len(verified_failures)
    # Backward-compatible fallback for callers that only have a previously scored
    # row and no raw history. The live Deal Room always supplies raw history, so
    # contradictory sold observations are still resolved by the stricter path above.
    if not history and not raw_rows[:-1] and int(row.get("failure_count") or 0) > 0:
        verified_failure_count = int(row.get("failure_count") or 0)
    returned_to_market_count = 1 if returned_to_market else 0
    negotiation_signal_count = verified_failure_count + returned_to_market_count

    if sale_status_conflict:
        stage = "POST-AUCTION / CHECK"
        headline = "Available post-auction — a previous sale status needs clarification"
        stage_copy = (
            "Lotly has seen an earlier sold-status signal, but the current auction listing shows the property available again. "
            "The earlier sale may have fallen through or the status may have changed. Confirm the sequence with the auctioneer."
        )
        happened = "A previous sale status was reported; the property is now back/available on the market"
        meaning = "A return to market can strengthen your negotiating position, but it does not prove seller distress or guarantee a discount."
        confidence_label = "Conflicting auction-history evidence — confirm with auctioneer"
    elif current_status_low == "available post-auction" and verified_failure_count:
        stage = "POST-AUCTION"
        headline = "A failed auction result was observed — it did not sell at that attempt and the property is still available"
        stage_copy = "The auction has ended without a confirmed completed sale, so the next conversation is about the seller's current price and certainty requirements."
        happened = f"{verified_failure_count} concrete failed-auction result{'s' if verified_failure_count != 1 else ''} observed"
        meaning = "Post-auction availability can create room to negotiate, but a discount is not guaranteed."
        confidence_label = "High confidence in auction-history signals"
    elif current_status_low == "available post-auction":
        stage = "POST-AUCTION / CHECK"
        headline = "Available post-auction — confirm what happened at the auction"
        stage_copy = "The current listing is available after the auction, but Lotly does not have a concrete failed-auction result to explain why."
        happened = "Post-auction availability observed; auction result not independently confirmed"
        meaning = "Availability is a useful negotiation signal, but do not call it a failed auction until the auctioneer confirms the result."
        confidence_label = "Medium confidence — current availability is clear, result history needs confirmation"
    elif current_status_low in sold_statuses:
        stage = "SOLD SIGNAL"
        headline = "The auctioneer currently records a sold status"
        stage_copy = "Treat this as an auctioneer result signal, not proof that legal completion or Land Registry transfer has occurred."
        happened = "Current sold-status signal observed"
        meaning = "This is not an active acquisition opportunity unless the auctioneer confirms the transaction has fallen through."
        confidence_label = "Auctioneer sold-status signal — completion not independently verified"
    elif current_status_low in concrete_failure_statuses:
        stage = "UNSOLD"
        headline = "The latest auction attempt did not produce a confirmed sale"
        stage_copy = "This is a concrete auction-result signal. Confirm whether the property remains available and what the seller expects now."
        happened = f"{max(1, verified_failure_count)} concrete failed-auction result{'s' if max(1, verified_failure_count) != 1 else ''} observed"
        meaning = "A failed auction can create leverage, but only the auctioneer can confirm the seller's current position."
        confidence_label = "High confidence in auction-history signals"
    elif current_status_low == "relisted":
        stage = "RELISTED"
        headline = "The property has returned to market"
        stage_copy = "The current listing is a relist. Confirm what happened previously and whether the guide or seller expectation has changed."
        happened = "Relisted / returned-to-market signal observed"
        meaning = "A relist can create a negotiation window, but it does not prove the seller will accept below the current guide."
        confidence_label = "High confidence in current returned-to-market signal"
    else:
        stage = "LIVE / CHECK"
        headline = "The property is still in the auction process"
        stage_copy = "Understand the guide, auction date and legal position before deciding whether to bid or wait."
        happened = "No failed or returned-to-market signal confirmed"
        meaning = "Live bidding can reduce your ability to negotiate, so set your ceiling before the auction starts."
        confidence_label = "Medium confidence in auction-history signals" if events else "Low confidence — little auction history captured"

    return {
        "stage": stage,
        "headline": headline,
        "stage_copy": stage_copy,
        "what_happened": happened,
        "meaning": meaning,
        "confidence_label": confidence_label,
        "current_status": current_status or "Unknown",
        "timeline": timeline,
        "sale_status_conflict": sale_status_conflict,
        "verified_failure_count": verified_failure_count,
        "returned_to_market_count": returned_to_market_count,
        "negotiation_signal_count": negotiation_signal_count,
        "sold_signal_count": len(sold_events),
    }



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
        status_low = status.lower()
        if status_low in {"sold", "sold prior", "sold after", "no bids", "last bid", "unsold", "withdrawn", "postponed"}:
            narrative_label = f"Auction result: {status}"
        elif status_low in {"available post-auction", "relisted", "live"}:
            narrative_label = f"Auction status: {status}"
        else:
            narrative_label = f"Auction observation: {status}"
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
            "label": narrative_label,
            "detail": " | ".join(bits) + (" | Auctioneer result status; not proof of Land Registry completion" if status_low in {"sold", "sold prior", "sold after"} else ""),
            "source_url": "",
        })
    return out


def seller_profile(legal_summary: dict | None, lot: dict | None = None, company_intelligence: dict | None = None) -> dict:
    """Return seller facts with a hard evidence boundary.

    Seller/company identity is only promoted to a confirmed profile when a current
    verified legal document is the provenance. Listing text may still contribute a
    *signal* such as probate/receiver wording, but cannot establish identity.
    """
    legal_summary = legal_summary or {}
    company_intelligence = company_intelligence or {}
    extracted = legal_summary.get("extracted_fields") or {}
    lot = lot or {}
    field_sources = extracted.get("field_sources") or {}
    legal_verified = str(legal_summary.get("status") or "").lower() == "verified"

    def verified_field(name: str):
        if not legal_verified:
            return None
        source = str(field_sources.get(name) or "").strip().lower()
        return extracted.get(name) if source == "verified legal document" else None

    seller_type = _clean(extracted.get("seller_type"), 60)
    seller_type_evidence = _clean(extracted.get("seller_type_evidence"), 120)
    seller_name = _clean(verified_field("seller_name") or verified_field("proprietor_name"), 180)

    # If a seller type came only from auctioneer/listing text keep it as a signal,
    # never as legal confirmation.
    if seller_type and not legal_verified and "confirmed" in str(seller_type_evidence or "").lower():
        seller_type_evidence = "auctioneer listing signal - legal confirmation outstanding"
    if not seller_type:
        text = " ".join(str(lot.get(k) or "") for k in ("title", "raw_text", "detail_text")).lower()
        for term, label in (
            ("lpa receiver", "LPA receiver"), ("receiver", "Receiver"), ("administrator", "Administrator"),
            ("liquidator", "Liquidator"), ("mortgagee", "Mortgagee"), ("executor", "Executor"),
            ("probate", "Probate"), ("fund disposal", "Fund disposal"),
        ):
            if term in text:
                seller_type = label
                seller_type_evidence = "auctioneer listing signal - legal confirmation outstanding"
                break

    company_identity_verified = bool(extracted.get("company_identity_verified")) and legal_verified
    if not company_identity_verified:
        # Stored corporate enrichment may pre-date the evidence firewall. Do not let
        # it back-fill ownership unless the legal identity gate has been satisfied.
        company_intelligence = {}

    return {
        "seller_name": seller_name or None,
        "seller_type": seller_type or None,
        "seller_type_evidence": seller_type_evidence or None,
        "field_sources": field_sources,
        "seller_name_source": field_sources.get("seller_name") or field_sources.get("proprietor_name"),
        "title_number": verified_field("title_number"),
        "company_number": verified_field("company_number") or company_intelligence.get("company_number"),
        "registered_office": verified_field("registered_office") or company_intelligence.get("registered_office"),
        "title_price_paid": verified_field("title_price_paid"),
        "title_price_paid_date": verified_field("title_price_paid_date"),
        "contacts": (legal_summary.get("contacts") or []) if legal_verified else [],
        "company_name_verified": company_intelligence.get("company_name"),
        "company_status": company_intelligence.get("company_status"),
        "company_registered_office": company_intelligence.get("registered_office"),
        "company_url": company_intelligence.get("company_url"),
        "corporate_pressure_score": company_intelligence.get("corporate_pressure_score"),
        "corporate_pressure_label": company_intelligence.get("corporate_pressure_label"),
        "company_identity_verified": company_identity_verified,
    }


def buyer_leverage(lot: dict, deal_analysis: dict | None = None, legal_summary: dict | None = None,
                   planning_items: Iterable[dict] | None = None, company_intelligence: dict | None = None) -> dict:
    """Score negotiating leverage separately from seller motivation."""
    deal_analysis = deal_analysis or {}
    legal_summary = legal_summary or {}
    company_intelligence = company_intelligence or {}
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

    # v1.13.13: only verified failed-auction results and a verified return-to-market
    # transition may add history leverage. Contradictory raw sold statuses do not.
    failures = int(deal_analysis.get("verified_failure_count") if deal_analysis.get("verified_failure_count") is not None else (deal_analysis.get("failure_count") or 0))
    returned_to_market = int(deal_analysis.get("returned_to_market_count") or 0)
    if failures:
        points += min(22, failures * 8)
        reasons.append(f"{failures} concrete failed-auction result(s) observed")
    if returned_to_market:
        points += min(12, returned_to_market * 8)
        reasons.append("Returned to market after an earlier sale-status signal")

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

    profile = seller_profile(legal_summary, lot, company_intelligence)
    if not profile.get("company_identity_verified"):
        company_intelligence = {}
    seller_type = str(profile.get("seller_type") or "").lower()
    if any(term in seller_type for term in DISTRESS_SELLER_TYPES):
        confirmed = "confirmed" in str(profile.get("seller_type_evidence") or "").lower()
        points += 10 if confirmed else 4
        reasons.append(
            f"Confirmed disposal context: {profile.get('seller_type')}" if confirmed
            else f"Disposal signal to verify: {profile.get('seller_type')}"
        )

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

    corporate_pressure = _num(company_intelligence.get("corporate_pressure_score"), 0) or 0
    company_status = str(company_intelligence.get("company_status") or "").strip()
    if corporate_pressure >= 8:
        points += 17
        reasons.append(f"Official corporate-pressure evidence is very high ({company_status or 'Companies House'})")
    elif corporate_pressure >= 6:
        points += 8
        reasons.append(f"Official corporate-pressure evidence is elevated ({company_status or 'Companies House'})")
    elif corporate_pressure >= 3:
        points += 4
        reasons.append("Some official corporate-pressure indicators are present")

    score = round(max(0, min(100, points)) / 10, 1)
    label = "Very High" if score >= 8.5 else "High" if score >= 7 else "Medium" if score >= 5 else "Low" if score >= 3 else "Very Low"
    return {"buyer_leverage_score": score, "buyer_leverage_label": label, "buyer_leverage_reasons": reasons}



def seller_negotiation_plan(row: dict, story: dict | None = None, readiness: dict | None = None) -> dict:
    """Translate seller/auction evidence into a beginner-safe negotiation plan.

    The plan deliberately scores *observable negotiation signals*, not the seller's
    private motivation. It also suppresses any suggestion of a binding bid while
    the acquisition-readiness gate is blocked.
    """
    story = story or {}
    readiness = readiness or {}
    profile = story.get("seller_profile") or {}

    leverage_score = float(story.get("buyer_leverage_score") or 0)
    leverage_label = str(story.get("buyer_leverage_label") or "Low")
    story_confidence = int(story.get("story_confidence") or 0)
    reasons = [str(x) for x in (story.get("buyer_leverage_reasons") or []) if str(x).strip()]

    if leverage_score >= 8:
        position = "Strong"
        headline = "You have a strong negotiating position"
        position_copy = "The auction history gives you reasons to test a lower price before moving upward."
    elif leverage_score >= 6:
        position = "Good"
        headline = "You have a useful negotiating position"
        position_copy = "There are credible signs that the seller may listen to a sensible lower starting point."
    elif leverage_score >= 4:
        position = "Moderate"
        headline = "You have some room to negotiate"
        position_copy = "There are some useful signals, but do not assume the seller is under pressure."
    else:
        position = "Limited"
        headline = "Your negotiating position is limited"
        position_copy = "There is little evidence of price pressure, so focus on information-gathering before pushing on price."

    missing = {str(x).strip().lower() for x in (row.get("legal_missing_components") or [])}
    legal_status = str(row.get("legal_status") or "").lower()
    subject_title_verified = legal_status == "verified" and "title register" not in missing
    seller_name = profile.get("seller_name")
    seller_type = profile.get("seller_type")
    if seller_name and subject_title_verified:
        identity_status = "Confirmed"
        identity_value = str(seller_name)
        identity_copy = "The current legal evidence supports the seller/registered-owner identity shown here."
    else:
        identity_status = "Not yet confirmed"
        identity_value = "Seller identity not yet confirmed"
        identity_copy = "Do not rely on a seller name until the subject title register or equivalent authoritative evidence is verified."

    disposal_copy = None
    seller_type_source = str((profile.get("field_sources") or {}).get("seller_type") or "").strip().lower()
    seller_type_verified = seller_type_source == "verified legal document"
    if seller_type:
        seller_type_low = str(seller_type).lower()
        if seller_type_verified:
            disposal_copy = f"Confirmed disposal context: {seller_type}."
        elif "mortgage" in seller_type_low or "receiver" in seller_type_low:
            disposal_copy = "Possible lender-led disposal. The wording is a negotiation clue, not a confirmed seller fact until authoritative legal evidence verifies it."
        else:
            disposal_copy = f"Possible disposal signal: {seller_type}. Treat this as a clue until authoritative legal evidence confirms it."

    signal_confidence_label = (
        "High confidence in negotiation signals" if story_confidence >= 75
        else "Medium confidence in negotiation signals" if story_confidence >= 50
        else "Low confidence in negotiation signals"
    )

    opening_offer = _num(row.get("opening_offer"))
    guide = _num(row.get("guide_price"))
    max_bid = _num(row.get("max_bid"))
    readiness_status = str(readiness.get("readiness_status") or "")
    blockers = [str(x) for x in (readiness.get("readiness_blockers") or []) if str(x).strip()]
    bid_blocked = readiness_status.upper() == "BID BLOCKED" or bool(blockers)

    lot_ref = _clean(row.get("lot_number"), 40)
    address = _clean(row.get("address") or row.get("title"), 180) or "this property"
    opener_text = f"GBP {opening_offer:,.0f}" if opening_offer else "a cautious opening level"
    guide_text = f"GBP {guide:,.0f}" if guide else "the current guide"
    ceiling_text = f"GBP {max_bid:,.0f}" if max_bid else "not yet established"

    if bid_blocked:
        offer_instruction = f"Use {opener_text} only to test the seller's position. Do not make a binding bid while red STOP items remain."
        ceiling_instruction = "Lotly will not treat the modelled ceiling as permission to bid while a critical evidence blocker remains."
    else:
        offer_instruction = f"Start around {opener_text}. Let the seller respond before increasing, and move in small steps only if the evidence still supports the deal."
        ceiling_instruction = f"Do not exceed the modelled ceiling of {ceiling_text} without re-running the numbers and legal checks."

    ref = f"Lot {lot_ref}, {address}" if lot_ref else address
    call_script = (
        f"I'm interested in {ref}. Before making anything binding, I'd like to understand the seller's position. "
        f"Would the seller consider something around {opener_text}, subject to my legal and financial review? "
        "Can you tell me the seller's current expectation, whether there are competing offers, and whether speed or certainty matters to them?"
    )

    questions = [
        "What price is the seller realistically expecting now?",
        "Are there any other offers on the table, and are any of them proceedable?",
        "Is speed/certainty more important to the seller than achieving the highest price?",
        "Has the seller already rejected an offer, and if so at what level?",
    ]

    return {
        "position": position,
        "headline": headline,
        "position_copy": position_copy,
        "leverage_score": leverage_score,
        "leverage_label": leverage_label,
        "story_confidence": story_confidence,
        "signal_confidence_label": signal_confidence_label,
        "seller_type_verified": seller_type_verified,
        "identity_status": identity_status,
        "identity_value": identity_value,
        "identity_copy": identity_copy,
        "disposal_copy": disposal_copy,
        "opening_offer": opening_offer,
        "guide_price": guide,
        "max_bid": max_bid,
        "bid_blocked": bid_blocked,
        "offer_instruction": offer_instruction,
        "ceiling_instruction": ceiling_instruction,
        "leverage_reasons": reasons[:5],
        "auctioneer_questions": questions,
        "call_script": call_script,
        "guide_context": f"Current guide: {guide_text}",
        "ceiling_context": f"Modelled ceiling: {ceiling_text}",
    }



def auction_beginner_summary(row: dict, history: Iterable[dict] | None = None, readiness: dict | None = None) -> dict:
    """Explain the auction journey in beginner-safe language using normalised evidence."""
    history = list(history or [])
    readiness = readiness or {}
    integrity = auction_history_integrity(row, history)
    reductions = int(row.get("price_reduction_events") or 0)
    reduction_pct = float(row.get("price_reduction_pct") or 0)
    days_since_failure = row.get("days_since_failure")
    guide = _num(row.get("guide_price"))
    opener = _num(row.get("opening_offer"))
    bid_blocked = str(readiness.get("readiness_status") or "").upper() == "BID BLOCKED" or bool(readiness.get("readiness_blockers"))

    if reduction_pct > 0:
        price_move = f"Guide down {reduction_pct:.1f}%"
        price_copy = f"Lotly has observed {reductions or 1} guide-price reduction event(s). This suggests the marketed price has moved, not that the seller must accept below it."
    elif reductions:
        price_move = f"{reductions} guide change(s) observed"
        price_copy = "The guide has moved over time. Ask the auctioneer what changed and what level the seller expects now."
    else:
        price_move = "No guide reduction observed"
        price_copy = "There is no recorded guide-price cut to support extra price pressure yet."

    age_text = "Timing not yet established"
    if days_since_failure is not None:
        try:
            d = int(days_since_failure)
            age_text = "Latest failed/post-auction signal is today" if d == 0 else f"About {d} day{'s' if d != 1 else ''} since the latest failed/post-auction signal"
        except Exception:
            pass

    # If the evidence conflicts, never call the earlier sold observation a failed auction.
    if integrity.get("sale_status_conflict"):
        age_text = "Current availability conflicts with an earlier sold-status signal"

    if bid_blocked:
        if opener:
            action = f"Ask what the seller wants now. If useful, test around GBP {opener:,.0f} as a non-binding price conversation only; do not bid while a red STOP remains."
        else:
            action = "Ask what the seller wants now, but do not make a binding bid while a red STOP remains."
    else:
        if opener:
            action = f"Ask what the seller wants now, then test around GBP {opener:,.0f} and wait for the seller to respond before increasing."
        else:
            action = "Ask the auctioneer for the seller's current expectation before discussing a binding offer."

    guide_text = f"GBP {guide:,.0f}" if guide else "Not captured"
    return {
        "stage": integrity.get("stage"),
        "headline": integrity.get("headline"),
        "stage_copy": integrity.get("stage_copy"),
        "what_happened": integrity.get("what_happened"),
        "current_status": integrity.get("current_status"),
        "price_movement": price_move,
        "price_copy": price_copy,
        "meaning": integrity.get("meaning"),
        "timing": age_text,
        "guide_text": guide_text,
        "action": action,
        "bid_blocked": bid_blocked,
        "confidence_label": integrity.get("confidence_label"),
        "failure_count": int(integrity.get("verified_failure_count") or 0),
        "verified_failure_count": int(integrity.get("verified_failure_count") or 0),
        "returned_to_market_count": int(integrity.get("returned_to_market_count") or 0),
        "sale_status_conflict": bool(integrity.get("sale_status_conflict")),
        "timeline": integrity.get("timeline") or [],
        "reduction_pct": reduction_pct,
    }

def _company_timeline(company: dict | None) -> list[dict]:
    company = company or {}
    out = []
    if company.get("incorporation_date"):
        out.append({
            "date": _date_key(company.get("incorporation_date")),
            "display_date": _clean(company.get("incorporation_date")),
            "type": "company", "label": "Company incorporated",
            "detail": _clean(company.get("company_name") or company.get("company_number"), 180),
            "source_url": company.get("company_url") or "",
        })
    for case in company.get("insolvency_cases") or []:
        dates = case.get("dates") or []
        date = next((d.get("date") for d in dates if d.get("date")), None)
        out.append({
            "date": _date_key(date), "display_date": _clean(date) or "Date not captured",
            "type": "company", "label": f"Insolvency record: {_clean(case.get('type'), 100) or 'case'}",
            "detail": f"Companies House insolvency case {_clean(case.get('number'), 50)}".strip(),
            "source_url": company.get("company_url") or "",
        })
    for filing in (company.get("recent_filings") or [])[:8]:
        desc = _clean(filing.get("description") or filing.get("type"), 150)
        probe = f"{desc} {filing.get('category') or ''}".lower()
        if not any(x in probe for x in ("charge", "receiver", "insolv", "liquid", "administr", "strike", "accounts")):
            continue
        out.append({
            "date": _date_key(filing.get("date")), "display_date": _clean(filing.get("date")) or "Date not captured",
            "type": "company", "label": "Companies House filing", "detail": desc,
            "source_url": company.get("company_url") or "",
        })
    return out


def build_vendor_story(lot: dict, history: Iterable[dict] | None = None, deal_analysis: dict | None = None,
                       legal_summary: dict | None = None, planning_items: Iterable[dict] | None = None,
                       company_intelligence: dict | None = None) -> dict:
    """Build an evidence-led seller story with clearly labelled inferences."""
    deal_analysis = deal_analysis or {}
    legal_summary = legal_summary or {}
    company_intelligence = company_intelligence or {}
    planning_items = list(planning_items or [])
    profile = seller_profile(legal_summary, lot, company_intelligence)
    if not profile.get("company_identity_verified"):
        company_intelligence = {}
    leverage = buyer_leverage(lot, deal_analysis, legal_summary, planning_items, company_intelligence)

    timeline = _auction_timeline(history or []) + _planning_timeline(planning_items) + _company_timeline(company_intelligence)
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
        source = str(profile.get("seller_name_source") or "").lower()
        if source == "legal document":
            facts.append(f"Parsed legal evidence names the proprietor/seller as {profile['seller_name']}")
        else:
            facts.append(f"Auctioneer/listing evidence names or references the seller as {profile['seller_name']} - legal confirmation remains outstanding")
    if profile.get("seller_type"):
        confirmed = "confirmed" in str(profile.get("seller_type_evidence") or "").lower()
        facts.append(
            f"Parsed legal evidence confirms the disposal context as {profile['seller_type']}" if confirmed
            else f"Auctioneer/listing wording signals {profile['seller_type']} - legal confirmation remains outstanding"
        )
    if profile.get("title_price_paid"):
        when = f" on {profile.get('title_price_paid_date')}" if profile.get("title_price_paid_date") else ""
        facts.append(f"Title evidence records a prior price paid of GBP {float(profile['title_price_paid']):,.0f}{when}")
    failures = int(deal_analysis.get("verified_failure_count") if deal_analysis.get("verified_failure_count") is not None else (deal_analysis.get("failure_count") or 0))
    returned_to_market = int(deal_analysis.get("returned_to_market_count") or 0)
    if failures:
        facts.append(f"{failures} distinct failed-auction result(s) are recorded (concrete result signals)")
    if returned_to_market:
        facts.append("The property is currently back/available after an earlier sale-status signal")
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
    if company_intelligence.get("status") == "ok":
        if company_intelligence.get("company_status"):
            facts.append(f"Companies House company status is {company_intelligence.get('company_status')}")
        if company_intelligence.get("outstanding_charge_count"):
            facts.append(f"Companies House records {int(company_intelligence.get('outstanding_charge_count') or 0)} outstanding/unsatisfied charge(s)")
        if company_intelligence.get("insolvency_case_count"):
            facts.append(f"Companies House records {int(company_intelligence.get('insolvency_case_count') or 0)} insolvency case(s)")
        if company_intelligence.get("accounts_overdue"):
            facts.append("Companies House shows accounts as overdue")

    inferences = []
    if failures >= 2:
        inferences.append("Repeated concrete failed-auction results suggest the seller may be increasingly receptive to a credible post-auction offer.")
    elif failures == 1 and str(lot.get("status") or "").lower() == "available post-auction":
        inferences.append("A concrete failed-auction result plus current post-auction availability can create more flexibility than a competitive live sale.")
    elif returned_to_market:
        inferences.append("The property has returned to market after an earlier sale-status signal. That can justify a cautious price test, but the auctioneer should confirm whether the earlier transaction fell through.")
    if reduction >= 10:
        inferences.append("A material guide reduction is consistent with increased price flexibility, although the seller's reserve remains unconfirmed.")
    if subject_refusals:
        inferences.append("A refused planning strategy may have reduced the owner's preferred exit options; confirm whether the seller incurred development/planning costs and whether an alternative scheme remains viable.")
    if (deal_analysis.get("features") or {}).get("vacant"):
        inferences.append("If the asset is genuinely vacant, ongoing finance, rates, insurance, service-charge or security costs may increase pressure to transact; these costs are not confirmed unless evidenced separately.")
    if profile.get("seller_type") and any(term in str(profile["seller_type"]).lower() for term in DISTRESS_SELLER_TYPES):
        if "confirmed" in str(profile.get("seller_type_evidence") or "").lower():
            inferences.append("The confirmed disposal context can favour certainty and speed of execution, but it does not by itself prove that a discounted offer will be accepted.")
        else:
            inferences.append("The disposal wording may indicate a seller who values certainty and speed, but the legal pack should confirm the capacity in which the seller is acting before relying on it in negotiation planning.")
    corporate_pressure = _num(company_intelligence.get("corporate_pressure_score"), 0) or 0
    if corporate_pressure >= 7:
        inferences.append("Official corporate records show material pressure indicators. A buyer offering certainty, speed and clean execution may have stronger negotiating leverage, but seller instructions still need confirming with the auctioneer/solicitor.")
    elif corporate_pressure >= 3:
        inferences.append("Some corporate-record indicators merit checking, but they are not sufficient on their own to infer a distressed sale.")

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
    if legal_summary.get("status") == "verified":
        confidence_points += 10
    if company_intelligence.get("status") == "ok":
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
    legal_pack_changed = bool(row.get("legal_pack_changed"))
    legal_completeness = int(row.get("legal_pack_completeness_pct") or 0)
    legal_complete = legal_status == "verified" and legal_completeness >= 100 and not legal_pack_changed
    legal_partial = legal_status in {"verified", "verified-no-text", "candidates-only", "links-only"}
    if legal_pack_changed:
        legal_detail = "Legal pack changed since the previous snapshot - re-review required"
    elif legal_status == "verified" and legal_completeness < 100:
        missing = row.get("legal_missing_components") or []
        legal_detail = f"Partial verified legal evidence: core pack {legal_completeness}% complete" + (f"; missing {', '.join(missing[:4])}" if missing else "")
    elif legal_complete:
        legal_detail = "Core legal pack verified and complete"
    else:
        legal_detail = "Legal pack not verified: authoritative lot-bound legal documents are still missing or unverified"
    add("Legal pack", 20, "complete" if legal_complete else "partial" if legal_partial else "missing",
        legal_detail, blocker=not legal_complete)
    # Verified legal evidence can still contain a serious issue. For novice buyers,
    # do not let a complete pack create a false sense of safety: a severity-4/5
    # verified legal finding keeps the bid gate closed until a solicitor reviews it.
    critical_legal_flags = [
        f for f in (row.get("legal_risk_flags") or [])
        if int(f.get("severity") or 0) >= 4
    ]
    if critical_legal_flags:
        labels = ", ".join(str(f.get("label") or "Critical legal issue") for f in critical_legal_flags[:3])
        add("Critical legal issue", 0, "missing",
            f"Professional review required before bidding: {labels}", blocker=True)
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
    if row.get("legal_pack_changed"):
        add(1, "Re-review the changed legal pack / addendum", "The auctioneer legal evidence has changed since the previous saved snapshot, so prior legal conclusions may be stale.")
    elif legal_status != "verified":
        add(1, "Obtain and verify the latest legal pack + addendum", "Bid approval is blocked until authoritative lot-bound legal evidence passes the evidence firewall and is reviewed.")
    elif int(row.get("legal_pack_completeness_pct") or 0) < 100:
        missing = row.get("legal_missing_components") or []
        add(1, "Complete the core legal pack", "Verified evidence is only partial. Obtain " + (", ".join(missing[:4]) if missing else "the missing title/special-conditions documents") + " before bid approval.")
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
    missing_components = {str(x).lower() for x in (legal_summary.get("missing_components") or row.get("legal_missing_components") or [])}
    risk_flags = legal_summary.get("risk_flags") or row.get("legal_risk_flags") or []
    if row.get("legal_pack_changed") or legal_summary.get("pack_changed"):
        questions.append("The tracker detected a legal-pack change since the previous snapshot. Please identify exactly what was added, removed or amended and confirm whether any prior advice must change.")
    if status != "verified" or missing_components:
        questions.append("Please confirm we have the latest complete legal pack and every addendum, and identify any missing or unverified documents before exchange/bidding.")
    if "title register" in missing_components:
        questions.append("Please obtain the official Land Registry title register and confirm the registered owner, title number, charges, restrictions and anything that could prevent or delay registration to the buyer.")
    if "special conditions" in missing_components:
        questions.append("Please obtain and review the auction special conditions and confirm every buyer cost, completion obligation, default remedy and unusual term before bidding.")
    lease = _num(extracted.get("lease_years_remaining") or row.get("legal_lease_years") or row.get("listing_lease_years"))
    tenure = str(row.get("tenure") or "").lower()
    if "lease" in missing_components and ("leasehold" in tenure or lease is not None):
        questions.append("Please obtain and review the lease itself. Confirm the exact unexpired term, ground-rent review pattern, service-charge obligations and any restrictions affecting letting, alterations or assignment.")
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
    for flag in risk_flags:
        label = str((flag or {}).get("label") or "")
        low = label.lower()
        if "rentcharge" in low:
            questions.append("A rentcharge/estate-rentcharge issue has been flagged. Please confirm the annual amount, any arrears, enforcement rights, whether the buyer inherits any liability and exactly how any outstanding sum will be discharged or protected on completion.")
        elif "title" in low or "unregistered" in low:
            questions.append("A title-quality issue has been flagged. Please explain the defect, whether good and marketable title can be registered, and any effect on mortgageability or resale.")
        elif "arrears" in low:
            questions.append("Possible arrears have been flagged. Please confirm the exact sum, who is liable, and whether the seller must clear it before or on completion.")
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
        f"- Company number: {profile.get('company_number') or 'Not extracted'}",
        f"- Company status: {profile.get('company_status') or 'Not enriched'}",
        f"- Corporate pressure: {float(profile.get('corporate_pressure_score') or 0):.1f}/10" if profile.get("corporate_pressure_score") is not None else "- Corporate pressure: not enriched",
        "",
        "## Confirmed motivation evidence",
    ]
    for fact in story.get("confirmed_facts") or ["No additional confirmed seller evidence yet."]:
        lines.append(f"- {fact}")
    lines += ["", "## Interpretation (not confirmed fact)"]
    for item in story.get("inferences") or ["Insufficient evidence for a useful seller-pressure inference."]:
        lines.append(f"- {item}")
    if row.get("legal_pack_changed"):
        lines += ["", "## Legal pack change alert", "- Legal evidence changed since the previous saved snapshot. Re-review all changed/addendum documents before bidding."]
    lines += ["", "## Bid blockers / DD gaps"]
    for blocker in readiness.get("readiness_blockers") or ["No automated blocker recorded; normal legal and physical due diligence still required."]:
        lines.append(f"- {blocker}")
    lines += ["", "## Recommended next actions"]
    for idx, action in enumerate(actions or [], start=1):
        lines.append(f"{idx}. {action.get('action')} - {action.get('reason')}")
    lines += ["", "---", "Desktop acquisition triage only. Verify legal, valuation, tax, condition and funding evidence before bidding."]
    return "\n".join(lines)
