# Deal Room Design Lock — v1.14.0

The beginner-first Guided Deal Room was approved for the v1.14.0 release candidate and is now design-locked.

## Product purpose

Lotly is a guided property-investment decision system, not a data dashboard. A beginner should be able to understand whether a property makes sense without already knowing auction, valuation, conveyancing or property-investment terminology.

The core question is:

> **Should I buy this property, and if so, what is the right price?**

## Locked beginner journey

The default property screen is **Guided View** and follows this order:

1. Investment strategy — Flip or Buy & Keep
2. Price
3. Numbers / return
4. Value and comparable evidence
5. Legal and property checks
6. Location
7. Seller / auction story and negotiation
8. Funding
9. Final decision and next action

The visible decision journey must continue to use simple evidence states and plain-English explanations.

## Locked evidence language

- **CLEAR** — supported evidence does not currently show a blocker.
- **CHECK** — evidence exists but needs review or confirmation.
- **STOP** — a live issue or critical missing evidence prevents a safe bid/offer.
- **NOT VERIFIED** — Lotly does not currently hold enough evidence to make the check.

Missing evidence must never be represented as CLEAR.

Every beginner-facing section should answer:

1. What does this mean?
2. Why does it matter?
3. What should I do next?

## England-only v1 scope

The Guided View may surface only checks Lotly can genuinely retrieve, calculate or assess from official/public evidence, existing product data or user-uploaded documents. The core property-check cards are:

- Legal pack
- Planning
- Building Regulations / Building Control
- Flood risk
- Coal / mining
- Previous property history

Council/public coverage can vary. An unavailable council record must remain NOT VERIFIED or CHECK rather than being treated as clean.

## Legal pack workflow

Because auction packs are often behind registration/login, **Upload Legal Pack** is a permanent first-class action. Uploaded evidence remains subject to the property-identity/evidence firewall before it can change a decision.

## Evidence layer

The detailed tabs remain available for users who want to inspect the evidence:

- Seller
- Financials
- Comparables
- Auction
- Legal & Planning
- Location
- Workspace

The Guided View summarizes these sources; it must not create a conflicting second version of auction status, negotiation leverage, valuation confidence or legal readiness.

## Areas that may change without redesign approval

- Evidence accuracy and source coverage
- Calculations and scoring integrity
- Bug fixes
- Accessibility/responsive defects
- Data-source integrations
- Additional evidence detail behind the guided view

## Areas that require explicit redesign approval

- Reordering the core beginner journey
- Replacing the Flip / Buy & Keep strategy selector
- Removing the decision journey
- Replacing the CLEAR / CHECK / STOP / NOT VERIFIED evidence model
- Major restyling, re-spacing or restructuring of the Guided View

The separate `DISCOVER_DESIGN_LOCK.md` continues to protect the Discover/Home page.
