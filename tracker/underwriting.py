from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
from typing import Any


COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}
SOLD_STATUSES = {"sold", "sold prior", "sold after"}


@dataclass
class UnderwritingDefaults:
    auction_admin_fee: float = 1500.0
    buyer_premium_pct: float = 0.0
    buyer_premium_minimum: float = 0.0
    search_fee: float = 0.0
    legal_cost: float = 2000.0
    survey_cost: float = 1000.0
    finance_mode: str = "Cash"
    ltv_pct: float = 70.0
    annual_interest_pct: float = 10.0
    term_months: int = 6
    arrangement_fee_pct: float = 2.0
    exit_fee_pct: float = 0.0
    valuation_fee: float = 1000.0
    target_residential_profit_margin_pct: float = 20.0
    target_commercial_equity_margin_pct: float = 20.0
    residential_sale_cost_pct: float = 1.5
    residential_exit_legal_cost: float = 1500.0
    residential_sdlt_mode: str = "Additional dwelling"


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        n = float(value)
        return n if isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sdlt_nonresidential(price: float) -> float:
    """England/Northern Ireland non-residential SDLT purchase/premium rates."""
    price = max(0.0, float(price or 0))
    return (
        max(0.0, min(price, 250_000) - 150_000) * 0.02
        + max(0.0, price - 250_000) * 0.05
    )


def _progressive_tax(price: float, bands: list[tuple[float | None, float]]) -> float:
    price = max(0.0, float(price or 0))
    tax = 0.0
    lower = 0.0
    for upper, rate in bands:
        if price <= lower:
            break
        taxable_upper = price if upper is None else min(price, upper)
        tax += max(0.0, taxable_upper - lower) * rate
        if upper is None or price <= upper:
            break
        lower = upper
    return tax


def sdlt_residential(price: float, mode: str = "Additional dwelling") -> float:
    """Current England/NI residential SDLT bands from 1 April 2025 onward.

    Corporate 17% is provided as an explicit mode because reliefs/exceptions can apply;
    the tool never selects it automatically.
    """
    price = max(0.0, float(price or 0))
    mode_key = (mode or "").strip().lower()
    if mode_key.startswith("corporate 17") and price > 500_000:
        return round(price * 0.17, 2)
    surcharge = 0.05 if ("additional" in mode_key or mode_key.startswith("corporate 17")) else 0.0
    bands = [
        (125_000, 0.00 + surcharge),
        (250_000, 0.02 + surcharge),
        (925_000, 0.05 + surcharge),
        (1_500_000, 0.10 + surcharge),
        (None, 0.12 + surcharge),
    ]
    return _progressive_tax(price, bands)


def infer_underwriting_strategy(lot: dict, requested: str = "auto") -> str:
    if requested and requested != "auto":
        return requested.lower()
    typ = (lot.get("property_type") or "").lower()
    return "commercial" if typ in COMMERCIAL_TYPES else "residential"




def extract_listing_fees(lot: dict) -> dict:
    """Extract common auction buyer charges from public listing/detail text.

    The result is advisory and only fills missing property-specific assumptions.
    """
    text = " ".join(str(lot.get(k) or "") for k in ("title", "raw_text", "detail_text"))
    out = {"buyer_premium_pct": None, "buyer_premium_minimum": None, "search_fee": None, "fee_evidence": []}
    pct_patterns = [
        r"(?:administration|admin|buyers?|buyer'?s)\s*(?:fee|premium)[^%]{0,100}?(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%[^.]{0,80}(?:administration|admin|buyers?|buyer'?s)\s*(?:fee|premium)",
    ]
    for pattern in pct_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            out["buyer_premium_pct"] = float(m.group(1))
            out["fee_evidence"].append(f"Buyer/admin fee {m.group(1)}% detected in listing")
            break
    m = re.search(r"\b(?:minimum|min)\b[^GBP0-9]{0,30}(?:GBP|pounds?)?\s*([0-9][0-9,]*(?:\.\d+)?)", text.replace("£", "GBP"), re.I)
    if m:
        out["buyer_premium_minimum"] = float(m.group(1).replace(",", ""))
        out["fee_evidence"].append(f"Minimum buyer/admin fee GBP {out['buyer_premium_minimum']:,.0f} detected")
    m = re.search(r"search\s*fees?[^GBP0-9]{0,30}(?:GBP|pounds?)?\s*([0-9][0-9,]*(?:\.\d+)?)", text.replace("£", "GBP"), re.I)
    if m:
        out["search_fee"] = float(m.group(1).replace(",", ""))
        out["fee_evidence"].append(f"Search fee GBP {out['search_fee']:,.0f} detected")
    return out

def known_risk_flags(lot: dict) -> list[dict]:
    text = " ".join(
        str(lot.get(k) or "") for k in ("title", "address", "raw_text", "detail_text")
    ).lower()
    patterns = [
        (r"short lease|lease.{0,30}(?:under|less than)\s*(?:80|70|60)\s*years", 4, "Possible short-lease issue"),
        (r"structural|subsidence|unstable|unsafe structure", 4, "Structural / subsidence wording"),
        (r"contaminat|radioactive", 5, "Contamination wording"),
        (r"asbestos", 3, "Asbestos wording"),
        (r"japanese knotweed|knotweed", 4, "Japanese knotweed wording"),
        (r"possessory title|unregistered title|adverse possession", 4, "Title-quality wording"),
        (r"overage|clawback", 3, "Overage / clawback wording"),
        (r"restrictive covenant", 2, "Restrictive-covenant wording"),
        (r"easement|right of way", 1, "Easement / right-of-way wording"),
        (r"tenant|tenanted|occupied|part let|lease in place", 1, "Occupancy / lease obligations require review"),
        (r"vat.{0,20}(?:payable|applicable|elected|opted)", 2, "VAT wording requires tax review"),
        (r"buyer.{0,20}(?:premium|fee)|administration fee", 1, "Auction buyer fee / premium wording"),
        (r"grade\s*(?:i|ii|ii\*)\s*listed|listed building|listed property", 3, "Listed-building / heritage consent risk"),
    ]
    flags = []
    seen = set()
    for pattern, severity, label in patterns:
        if re.search(pattern, text, re.I) and label not in seen:
            flags.append({"severity": severity, "label": label})
            seen.add(label)
    return flags


def risk_score(lot: dict, deal_analysis: dict | None = None) -> dict:
    deal_analysis = deal_analysis or {}
    flags = known_risk_flags(lot)
    base_raw = sum(f["severity"] for f in flags)
    base_score = min(10.0, base_raw / 2.0)
    legal_score = _num(deal_analysis.get("legal_risk_score"), 0) or 0
    planning_score = _num(deal_analysis.get("planning_risk_score"), 0) or 0
    for item in deal_analysis.get("legal_risk_flags") or []:
        label = str(item.get("label") or "Legal-pack issue")
        severity = int(item.get("severity") or 1)
        if not any(f.get("label") == f"Legal: {label}" for f in flags):
            flags.append({"severity": severity, "label": f"Legal: {label}"})
    if planning_score >= 2:
        flags.append({
            "severity": max(1, min(5, int(round(planning_score / 2)))),
            "label": f"Planning/designation DD burden ({planning_score:.1f}/10)",
        })
    combined = base_score + legal_score * 0.65 + planning_score * 0.35
    # A severe legal-pack issue must not be diluted by otherwise clean listing/planning data.
    if legal_score >= 8:
        combined = max(combined, legal_score)
    if planning_score >= 9:
        combined = max(combined, planning_score * 0.9)
    score = round(_clamp(combined, 0, 10), 1)
    return {
        "risk_score": score, "risk_flags": flags,
        "listing_risk_score": round(base_score, 1),
        "legal_risk_score": round(legal_score, 1),
        "planning_risk_score": round(planning_score, 1),
    }


def vendor_motivation(lot: dict, deal_analysis: dict | None = None) -> dict:
    deal_analysis = deal_analysis or {}
    status = (lot.get("status") or "").strip().lower()
    points = {
        "available post-auction": 55,
        "no bids": 50,
        "last bid": 46,
        "relisted": 35,
        "withdrawn": 20,
        "postponed": 15,
        "live": 8,
    }.get(status, 5)
    reasons = []
    if status:
        reasons.append(f"Current auction status: {lot.get('status')}")

    failures = int(deal_analysis.get("failure_count") or 0)
    if failures >= 1:
        add = min(20, failures * 7)
        points += add
        reasons.append(f"{failures} failed-auction signal(s) observed")

    reduction = _num(deal_analysis.get("price_reduction_pct"), 0) or 0
    if reduction >= 20:
        points += 18
        reasons.append(f"Guide reduced {reduction:.1f}% from first observed guide")
    elif reduction >= 10:
        points += 12
        reasons.append(f"Guide reduced {reduction:.1f}%")
    elif reduction >= 5:
        points += 7
        reasons.append(f"Guide reduced {reduction:.1f}%")

    days = deal_analysis.get("days_since_failure")
    if days is not None:
        if days <= 14:
            points += 8
            reasons.append("Very recent failed/post-auction window")
        elif days <= 45:
            points += 10
            reasons.append("Seller has had time to consider post-auction offers")
        elif days <= 90:
            points += 7
            reasons.append("Extended time since failed/post-auction event")
        else:
            points += 3
            reasons.append("Older unresolved auction history")

    text = " ".join(str(lot.get(k) or "") for k in ("title", "raw_text", "detail_text")).lower()
    motivated_terms = [
        "by order of the mortgagees", "mortgagee", "receiver", "lpa receiver", "administrator",
        "liquidator", "company disposal", "executor", "probate", "must be sold", "vacant possession",
        "fund disposal", "by order of a fund",
    ]
    hits = [term for term in motivated_terms if term in text]
    if hits:
        points += min(15, 5 + 3 * (len(hits) - 1))
        reasons.append("Motivated/disposal wording: " + ", ".join(hits[:3]))

    score = round(_clamp(points, 0, 100) / 10, 1)
    if score >= 8.5:
        label = "Very High"
    elif score >= 7.0:
        label = "High"
    elif score >= 5.0:
        label = "Medium"
    elif score >= 3.0:
        label = "Low"
    else:
        label = "Very Low"
    return {"motivation_score": score, "motivation_label": label, "motivation_reasons": reasons}


def _finance_costs(price: float, assumptions: dict, defaults: UnderwritingDefaults) -> dict:
    mode = str(assumptions.get("finance_mode") or defaults.finance_mode)
    if mode.lower() == "cash":
        return {
            "finance_mode": "Cash", "loan_amount": 0.0, "deposit": price,
            "interest_cost": 0.0, "arrangement_fee": 0.0, "exit_fee": 0.0,
            "valuation_fee": 0.0, "finance_cost": 0.0,
        }
    ltv = _clamp(_num(assumptions.get("ltv_pct"), defaults.ltv_pct) or 0, 0, 100) / 100
    annual = max(0.0, _num(assumptions.get("annual_interest_pct"), defaults.annual_interest_pct) or 0) / 100
    months = int(max(0, _num(assumptions.get("term_months"), defaults.term_months) or 0))
    arrangement_pct = max(0.0, _num(assumptions.get("arrangement_fee_pct"), defaults.arrangement_fee_pct) or 0) / 100
    exit_pct = max(0.0, _num(assumptions.get("exit_fee_pct"), defaults.exit_fee_pct) or 0) / 100
    valuation_fee = max(0.0, _num(assumptions.get("valuation_fee"), defaults.valuation_fee) or 0)
    loan = price * ltv
    interest = loan * annual * (months / 12)
    arrangement = loan * arrangement_pct
    exit_fee = loan * exit_pct
    total = interest + arrangement + exit_fee + valuation_fee
    return {
        "finance_mode": mode, "loan_amount": loan, "deposit": price - loan,
        "interest_cost": interest, "arrangement_fee": arrangement, "exit_fee": exit_fee,
        "valuation_fee": valuation_fee, "finance_cost": total,
    }


def acquisition_costs(price: float, strategy: str, assumptions: dict | None = None,
                      defaults: UnderwritingDefaults | None = None) -> dict:
    assumptions = assumptions or {}
    defaults = defaults or UnderwritingDefaults()
    price = max(0.0, float(price or 0))
    auction_admin = max(0.0, _num(assumptions.get("auction_admin_fee"), defaults.auction_admin_fee) or 0)
    buyer_pct = max(0.0, _num(assumptions.get("buyer_premium_pct"), defaults.buyer_premium_pct) or 0) / 100
    buyer_minimum = max(0.0, _num(assumptions.get("buyer_premium_minimum"), defaults.buyer_premium_minimum) or 0)
    search_fee = max(0.0, _num(assumptions.get("search_fee"), defaults.search_fee) or 0)
    buyer_premium = max(price * buyer_pct, buyer_minimum) if (buyer_pct or buyer_minimum) else 0.0
    legal = max(0.0, _num(assumptions.get("legal_cost"), defaults.legal_cost) or 0)
    survey = max(0.0, _num(assumptions.get("survey_cost"), defaults.survey_cost) or 0)
    purchase_vat_pct = max(0.0, _num(assumptions.get("purchase_vat_pct"), 0.0) or 0) / 100
    purchase_vat = price * purchase_vat_pct
    vat_recoverable = bool(assumptions.get("vat_recoverable", False))
    vat_cash_cost = 0.0 if vat_recoverable else purchase_vat
    sdlt_consideration = price + purchase_vat

    if strategy == "commercial":
        sdlt = sdlt_nonresidential(sdlt_consideration)
        sdlt_basis = "Non-residential / mixed"
    else:
        sdlt_mode = str(assumptions.get("residential_sdlt_mode") or defaults.residential_sdlt_mode)
        sdlt = sdlt_residential(sdlt_consideration, sdlt_mode)
        sdlt_basis = sdlt_mode

    finance = _finance_costs(price, assumptions, defaults)
    acquisition_only = price + sdlt + auction_admin + buyer_premium + search_fee + legal + survey + vat_cash_cost + finance["finance_cost"]
    return {
        "purchase_price": price,
        "sdlt": sdlt,
        "sdlt_basis": sdlt_basis,
        "auction_admin_fee": auction_admin,
        "buyer_premium": buyer_premium,
        "buyer_premium_minimum": buyer_minimum,
        "search_fee": search_fee,
        "legal_cost": legal,
        "survey_cost": survey,
        "purchase_vat": purchase_vat,
        "vat_recoverable": vat_recoverable,
        "vat_cash_cost": vat_cash_cost,
        "sdlt_consideration": sdlt_consideration,
        "acquisition_cost_before_works": acquisition_only,
        **finance,
    }


def _works_cost(assumptions: dict, strategy: str) -> dict:
    direct = _num(assumptions.get("refurb_cost"), 0.0) or 0.0
    if strategy == "commercial":
        direct += _num(assumptions.get("capex_cost"), 0.0) or 0.0
    contingency_pct = max(0.0, _num(assumptions.get("contingency_pct"), 10.0) or 0) / 100
    contingency = direct * contingency_pct
    return {"works_cost": direct, "works_contingency": contingency, "works_total": direct + contingency}


def _value_inputs(lot: dict, deal_analysis: dict, strategy: str, assumptions: dict) -> dict:
    comp_mid = _num(deal_analysis.get("comparable_valuation_mid"))
    comp_low = _num(deal_analysis.get("comparable_valuation_low"))
    comp_high = _num(deal_analysis.get("comparable_valuation_high"))
    comp_psf = _num(deal_analysis.get("comparable_unit_psf_mid"))
    comp_conf = int(_num(deal_analysis.get("comparable_confidence"), 0) or 0)
    comp_count = int(_num(deal_analysis.get("comparable_count"), 0) or 0)
    comp_provider = str(deal_analysis.get("comparable_provider") or "")
    saved_auto_flag = assumptions.get("use_auto_comps")
    if saved_auto_flag is None:
        auto_enabled = strategy == "residential"
    else:
        auto_enabled = bool(saved_auto_flag)

    if strategy == "commercial":
        size = _num(deal_analysis.get("size_sqft"))
        market_psf = _num(assumptions.get("market_psf"))
        psf_value = size * market_psf if size and market_psf else None
        erv = _num(assumptions.get("erv_annual"))
        exit_yield = _num(assumptions.get("exit_yield_pct"))
        income_value = (erv / (exit_yield / 100)) if erv and exit_yield and exit_yield > 0 else None
        manual = _num(assumptions.get("manual_market_value"))
        auto_value = comp_mid if auto_enabled and comp_conf >= 60 and comp_count >= 3 and comp_mid else None
        if not auto_value and auto_enabled and comp_psf and size and comp_conf >= 60 and comp_count >= 3:
            auto_value = comp_psf * size
        if manual:
            selected = manual
            basis = "Manual market value"
            auto_used = False
        elif psf_value and income_value:
            selected = min(psf_value, income_value)
            basis = "Conservative lower of GBP/sq ft and capitalised ERV"
            auto_used = False
        elif psf_value:
            selected = psf_value
            basis = "Market GBP/sq ft assumption"
            auto_used = False
        elif income_value:
            selected = income_value
            basis = "ERV capitalised at exit yield"
            auto_used = False
        elif auto_value:
            selected = auto_value
            basis = f"Automatic auction sold-comparable benchmark ({comp_count} comps)"
            auto_used = True
        else:
            selected = None
            basis = "Market value required"
            auto_used = False
        return {
            "market_value": selected, "market_value_basis": basis,
            "psf_market_value": psf_value, "income_market_value": income_value,
            "market_psf": market_psf, "erv_annual": erv, "exit_yield_pct": exit_yield,
            "gdv": None, "auto_comparable_used": auto_used,
            "comparable_valuation_low": comp_low, "comparable_valuation_mid": comp_mid,
            "comparable_valuation_high": comp_high, "comparable_unit_psf_mid": comp_psf,
            "comparable_confidence": comp_conf, "comparable_count": comp_count,
            "comparable_provider": comp_provider,
        }
    gdv = _num(assumptions.get("gdv")) or _num(assumptions.get("manual_market_value"))
    auto_value = comp_mid if auto_enabled and comp_conf >= 60 and comp_count >= 4 and comp_mid else None
    selected = gdv or auto_value
    if gdv:
        basis = "GDV / resale value"
        auto_used = False
    elif auto_value:
        basis = f"Automatic HM Land Registry sold-comparable midpoint ({comp_count} comps)"
        auto_used = True
    else:
        basis = "GDV required"
        auto_used = False
    return {
        "market_value": selected, "market_value_basis": basis,
        "gdv": selected if strategy == "residential" else gdv,
        "psf_market_value": None, "income_market_value": None,
        "market_psf": None, "erv_annual": None, "exit_yield_pct": None,
        "auto_comparable_used": auto_used,
        "comparable_valuation_low": comp_low, "comparable_valuation_mid": comp_mid,
        "comparable_valuation_high": comp_high, "comparable_unit_psf_mid": comp_psf,
        "comparable_confidence": comp_conf, "comparable_count": comp_count,
        "comparable_provider": comp_provider,
    }


def _all_in_at(price: float, strategy: str, assumptions: dict, defaults: UnderwritingDefaults, market_value: float | None = None) -> dict:
    costs = acquisition_costs(price, strategy, assumptions, defaults)
    works = _works_cost(assumptions, strategy)
    months = int(max(0, _num(assumptions.get("term_months"), defaults.term_months) or 0))
    holding_monthly = max(0.0, _num(assumptions.get("holding_cost_monthly"), 0.0) or 0)
    holding_cost = holding_monthly * months
    if strategy == "residential":
        default_sale_pct = defaults.residential_sale_cost_pct
        default_exit_legal = defaults.residential_exit_legal_cost
    else:
        default_sale_pct = 0.0
        default_exit_legal = 0.0
    sale_pct = max(0.0, _num(assumptions.get("sale_cost_pct"), default_sale_pct) or 0) / 100
    exit_legal = max(0.0, _num(assumptions.get("exit_legal_cost"), default_exit_legal) or 0)
    sale_cost = (market_value or 0.0) * sale_pct if market_value else 0.0
    exit_cost = sale_cost + exit_legal if market_value else 0.0
    total = costs["acquisition_cost_before_works"] + works["works_total"] + holding_cost + exit_cost
    return {**costs, **works, "holding_cost": holding_cost, "sale_cost": sale_cost, "exit_legal_cost": exit_legal if market_value else 0.0, "exit_cost": exit_cost, "all_in_cost": total}


def _solve_max_price(strategy: str, assumptions: dict, defaults: UnderwritingDefaults,
                     market_value: float | None) -> int | None:
    if not market_value or market_value <= 0:
        return None
    if strategy == "residential":
        target_margin = _clamp(
            _num(assumptions.get("target_profit_margin_pct"), defaults.target_residential_profit_margin_pct) or 0,
            0, 90,
        ) / 100
        target_total_cost = market_value * (1 - target_margin)
    else:
        target_equity = _clamp(
            _num(assumptions.get("target_equity_margin_pct"), defaults.target_commercial_equity_margin_pct) or 0,
            0, 90,
        ) / 100
        # Target uplift is defined as (MV - all-in) / all-in. Rearranging gives the
        # maximum all-in cost that still preserves the requested equity margin.
        target_total_cost = market_value / (1 + target_equity)

    if target_total_cost <= 0:
        return None
    low, high = 0.0, market_value * 1.5
    for _ in range(70):
        mid = (low + high) / 2
        total = _all_in_at(mid, strategy, assumptions, defaults, market_value)["all_in_cost"]
        if total <= target_total_cost:
            low = mid
        else:
            high = mid
    step = 1000 if low < 500_000 else 5000
    return int(low // step * step)


def _financial_score(strategy: str, market_value: float | None, all_in: float,
                     erv: float | None = None) -> tuple[float, dict]:
    if not market_value or all_in <= 0:
        return 0.0, {}
    profit = market_value - all_in
    roi = profit / all_in * 100
    if strategy == "residential":
        margin = profit / market_value * 100
        thresholds = [(25, 10), (20, 9), (15, 8), (10, 6), (5, 4), (0, 2)]
        score = next((s for t, s in thresholds if margin >= t), 0)
        return float(score), {"profit": profit, "roi_pct": roi, "profit_margin_pct": margin}
    equity_uplift = roi
    thresholds = [(35, 10), (25, 9), (20, 8), (15, 7), (10, 6), (5, 5), (0, 3)]
    score = next((s for t, s in thresholds if equity_uplift >= t), 0)
    gross_yield = (erv / all_in * 100) if erv and all_in else None
    return float(score), {"equity_uplift_pct": equity_uplift, "profit": profit, "roi_pct": roi, "gross_yield_pct": gross_yield}


def _asset_quality_score(lot: dict, deal_analysis: dict, strategy: str) -> float:
    points = 0.0
    if strategy == "commercial":
        size = _num(deal_analysis.get("size_sqft")) or 0
        psf = _num(deal_analysis.get("price_per_sqft"))
        features = deal_analysis.get("features") or {}
        if size >= 9000: points += 2.0
        elif size >= 6000: points += 1.2
        elif size >= 3000: points += 0.6
        if psf is not None:
            if psf <= 50: points += 2.0
            elif psf <= 60: points += 1.5
            elif psf <= 75: points += 0.7
        if deal_analysis.get("tenure") == "Freehold": points += 1.0
        if features.get("parking"): points += 0.7
        if features.get("loading"): points += 0.8
        if features.get("split_potential"): points += 1.2
        miles = _num(deal_analysis.get("motorway_distance_miles"))
        if miles is not None:
            if miles <= 2: points += 1.3
            elif miles <= 5: points += 1.0
            elif miles <= 10: points += 0.5
    else:
        features = deal_analysis.get("features") or {}
        price = _num(lot.get("guide_price"))
        if price and price <= 100_000: points += 2.0
        elif price and price <= 125_000: points += 1.0
        if (lot.get("property_type") or "").lower() == "house": points += 1.2
        if features.get("vacant"): points += 1.8
        if features.get("refurbishment"): points += 2.0
        if deal_analysis.get("tenure") == "Freehold": points += 1.2
        if features.get("development"): points += 1.3
    planning_upside = _num(deal_analysis.get("planning_opportunity_score"), 0) or 0
    if planning_upside > 0:
        points += min(1.5, planning_upside * 0.15)
    return round(_clamp(points, 0, 10), 1)


def underwrite_property(lot: dict, deal_analysis: dict, assumptions: dict | None = None,
                        defaults: UnderwritingDefaults | None = None,
                        strategy: str = "auto") -> dict:
    assumptions = dict(assumptions or {})
    defaults = defaults or UnderwritingDefaults()
    detected_fees = extract_listing_fees(lot)
    if detected_fees.get("buyer_premium_pct") is not None and assumptions.get("buyer_premium_pct") is None:
        assumptions["buyer_premium_pct"] = detected_fees["buyer_premium_pct"]
        # A published percentage administration fee replaces the generic flat auction allowance unless the user saved one.
        if "auction_admin_fee" not in assumptions:
            assumptions["auction_admin_fee"] = 0.0
    if detected_fees.get("buyer_premium_minimum") is not None and assumptions.get("buyer_premium_minimum") is None:
        assumptions["buyer_premium_minimum"] = detected_fees["buyer_premium_minimum"]
    if detected_fees.get("search_fee") is not None and assumptions.get("search_fee") is None:
        assumptions["search_fee"] = detected_fees["search_fee"]
    selected = infer_underwriting_strategy(lot, strategy if strategy != "auto" else str(assumptions.get("strategy") or "auto"))
    guide = _num(lot.get("guide_price")) or 0.0
    current_price = _num(assumptions.get("purchase_price")) or _num(deal_analysis.get("opening_offer")) or guide

    values = _value_inputs(lot, deal_analysis, selected, assumptions)
    current_costs = _all_in_at(current_price, selected, assumptions, defaults, values.get("market_value"))
    financial_score, financial_metrics = _financial_score(
        selected, values.get("market_value"), current_costs["all_in_cost"], values.get("erv_annual")
    )
    max_bid = _solve_max_price(selected, assumptions, defaults, values.get("market_value"))
    max_bid_costs = _all_in_at(max_bid, selected, assumptions, defaults, values.get("market_value")) if max_bid else None

    motivation = vendor_motivation(lot, deal_analysis)
    risk = risk_score(lot, deal_analysis)
    asset_score = _asset_quality_score(lot, deal_analysis, selected)

    valuation_ready = bool(values.get("market_value"))
    works_entered = (_num(assumptions.get("refurb_cost"), 0) or 0) > 0 or (
        selected == "commercial" and (_num(assumptions.get("capex_cost"), 0) or 0) > 0
    )
    features = deal_analysis.get("features") or {}
    works_required_signal = bool(features.get("refurbishment"))
    listed_signal = bool(features.get("listed_building") or deal_analysis.get("planning_listed_flag"))
    works_missing = works_required_signal and not works_entered
    if works_missing:
        financial_score = min(financial_score, 4.0)
    confidence = 35
    if valuation_ready:
        if values.get("auto_comparable_used"):
            confidence += min(20, int((values.get("comparable_confidence") or 0) * 0.25))
        else:
            confidence += 25
    if selected == "commercial" and deal_analysis.get("size_sqft"): confidence += 10
    if deal_analysis.get("detail_enriched"): confidence += 8
    if int(deal_analysis.get("failure_count") or 0) > 0: confidence += 8
    if works_entered: confidence += 8
    if works_missing: confidence -= 15
    if listed_signal and works_required_signal: confidence -= 5
    if assumptions.get("underwriting_notes"): confidence += 4
    if deal_analysis.get("planning_status") == "ok": confidence += 4
    if deal_analysis.get("legal_status") == "parsed": confidence += 10
    confidence = int(_clamp(confidence, 0, 100))

    overall = 0.30 * asset_score + 0.30 * motivation["motivation_score"] + 0.40 * financial_score
    overall -= min(2.5, risk["risk_score"] * 0.18)
    overall = round(_clamp(overall, 0, 10), 1)

    status = (lot.get("status") or "").lower()
    reasons = []
    warnings = []
    if values.get("auto_comparable_used"):
        warnings.append(
            "The valuation is seeded from automated comparable evidence. Treat the maximum bid as desktop acquisition triage until condition, legal pack and local market evidence are verified."
        )
    if deal_analysis.get("planning_status") in {"error", "unavailable", None, ""}:
        warnings.append("Official planning-data screening is incomplete or unavailable; planning risk is UNKNOWN until checked against the relevant authority/source.")
    if works_missing:
        warnings.append("The listing indicates modernisation/refurbishment but the works budget is GBP 0. Financial return and maximum bid are provisional until a works estimate is entered.")
    if listed_signal:
        warnings.append("Listed-building / heritage wording or designation detected. Refurbishment and change-of-use assumptions require heritage/planning review.")
    for fee_note in detected_fees.get("fee_evidence") or []:
        warnings.append(fee_note)
    if status in SOLD_STATUSES:
        recommendation = "PASS"
        action = "Already sold / sold prior. Retain only as market evidence."
        reasons.append("Lot is no longer actionable")
    elif risk["risk_score"] >= 8:
        recommendation = "PASS"
        action = "Known listing/legal/planning risk is too high for automatic pursuit; specialist review required."
        reasons.append("High combined due-diligence risk score")
    elif not valuation_ready:
        recommendation = "WATCH"
        action = "Complete valuation inputs before setting a maximum bid."
        warnings.append("No market value/GDV has been entered yet; a professional maximum bid cannot be calculated safely.")
    elif works_missing:
        recommendation = "WATCH"
        action = "Works estimate required before the bid ceiling can be approved. The displayed maximum bid is provisional only."
        reasons.append("Refurbishment/modernisation is indicated but no works budget has been entered")
    elif values.get("auto_comparable_used") and (values.get("comparable_confidence") or 0) < 65:
        recommendation = "WATCH"
        action = "Automatic comparable evidence is not yet strong enough for a PURSUE decision; verify valuation evidence or enter a manual GDV/market value."
        reasons.append("Comparable valuation confidence is below the 65% pursue threshold")
    elif str(deal_analysis.get("legal_status") or "").lower() not in {"parsed", "reviewed"}:
        recommendation = "WATCH"
        action = "Commercially attractive, but do not progress to bid approval until the latest legal pack and addendum are parsed/reviewed."
        reasons.append("Legal pack has not yet passed the acquisition gate")
        warnings.append("Auction legal packs can be revised up to the sale. Confirm the latest complete pack with your solicitor immediately before bidding.")
    else:
        guide_vs_max = ((guide - max_bid) / max_bid * 100) if max_bid and guide else None
        current_profit = financial_metrics.get("profit")
        if current_profit is not None and current_profit < 0:
            recommendation = "PASS"
            action = "Current underwritten price produces a negative value spread."
            reasons.append("Negative underwritten return at the working purchase price")
        elif financial_score >= 7 and motivation["motivation_score"] >= 6 and overall >= 7:
            recommendation = "PURSUE"
            if max_bid and current_price > max_bid:
                action = f"Pursue only at GBP {max_bid:,} or below; the current working offer is above the underwritten ceiling."
                reasons.append("Strong opportunity, but price discipline is required")
            else:
                action = f"Approach at or near GBP {int(current_price):,}; do not exceed GBP {max_bid:,}." if max_bid else "Pursue subject to legal and valuation checks."
                reasons.append("Return, asset quality and seller motivation combine positively")
        elif max_bid and guide and guide <= max_bid and financial_score >= 6:
            recommendation = "PURSUE"
            action = f"Guide is within the underwritten ceiling; do not exceed GBP {max_bid:,}."
            reasons.append("Guide sits within the calculated maximum bid")
        elif max_bid and guide_vs_max is not None and guide_vs_max > 15 and motivation["motivation_score"] < 7:
            recommendation = "PASS"
            action = f"Guide is materially above the calculated ceiling of GBP {max_bid:,}; only revisit after a major price/status change."
            reasons.append(f"Guide is {guide_vs_max:.1f}% above maximum bid")
        else:
            recommendation = "WATCH"
            action = f"Engage selectively; target GBP {max_bid:,} or below." if max_bid else "Continue monitoring until underwriting is complete."
            reasons.append("Opportunity is not yet strong enough for an automatic PURSUE decision")

    if max_bid and guide:
        discount_to_guide = (guide - max_bid) / guide * 100
    else:
        discount_to_guide = None

    return {
        "underwriting_strategy": selected.title(),
        "working_purchase_price": current_price,
        **values,
        **current_costs,
        **financial_metrics,
        "financial_score": financial_score,
        "asset_quality_score": asset_score,
        **motivation,
        **risk,
        "underwriting_confidence": confidence,
        "overall_opportunity_score": overall,
        "max_bid": max_bid,
        "max_bid_provisional": bool(max_bid and works_missing),
        "bid_ceiling_approved": bool(max_bid and not works_missing and str(deal_analysis.get("legal_status") or "").lower() in {"parsed", "reviewed"}),
        "works_required_signal": works_required_signal,
        "works_missing": works_missing,
        "listed_building_signal": listed_signal,
        "detected_fee_evidence": detected_fees.get("fee_evidence") or [],
        "detected_buyer_premium_pct": detected_fees.get("buyer_premium_pct"),
        "detected_buyer_premium_minimum": detected_fees.get("buyer_premium_minimum"),
        "detected_search_fee": detected_fees.get("search_fee"),
        "max_bid_all_in": max_bid_costs["all_in_cost"] if max_bid_costs else None,
        "discount_to_guide_pct": discount_to_guide,
        "recommendation": recommendation,
        "recommended_action": action,
        "underwriting_reasons": reasons,
        "underwriting_warnings": warnings,
    }
