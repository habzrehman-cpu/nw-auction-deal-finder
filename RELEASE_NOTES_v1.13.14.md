# Lotly v1.13.14 — Beginner Location Decision Screen

## Location — plain English
- Rebuilds the Deal Room **Location** tab around a first-time investor question: **Is this a sensible place to own this type of property?**
- Adds a simple evidence-led location verdict such as **PROMISING — VERIFY RENTAL DEMAND**, **MIXED — MORE LOCAL EVIDENCE NEEDED** or **CAUTION — REVIEW LOCAL CONSTRAINTS**.
- Separates evidence from assumptions so a familiar postcode is never treated as proof of rent, tenant demand, neighbourhood quality or resale speed.

## Four beginner checks
- **Local sold market** — uses the existing comparable evidence and confidence model.
- **Rent & gross yield** — only displays a rental figure when the user has entered an ERV; Lotly does not invent local rent.
- **Road access** — uses measured motorway/junction evidence where available and labels the distance type.
- **Flood / environment** — summarises the official planning-data screen and flags mapped flood/designation constraints for review.

## Exit and local market evidence
- Adds a plain-English **Who might rent or buy here?** section framed as an audience to test, not assumed demand.
- Adds **Exitability** based on the quality of local sold-price evidence while explicitly stating that sold comparables do not prove sale speed.
- Shows usable sold-comparable count, median sold evidence, observed sold range and valuation spread.
- Shows the five best-matching local sold comparables directly in the Location tab.

## Beginner risk and action layer
- Adds **What could hurt the investment?** using evidence-led warnings such as missing rent evidence, wide comparable spreads, flood/designation constraints and leasehold cost exposure.
- Adds **What Lotly recommends checking next** with practical tasks: rental comps, active competing listings, an on-the-ground area visit and flood/insurance checks where relevant.
- Explicitly discloses evidence Lotly does **not** currently claim to know: crime rate, current competing supply, amenity quality, employment demand and achieved rental demand.

## Advanced location evidence
- Keeps the existing map and motorway enrichment available under **Map & underlying location evidence**.
- Surfaces stored planning/environment constraint records under the advanced evidence section.

## Locked areas
- Discover, Snapshot, Financials, Comparables, Legal & Planning, Seller and Auction remain visually locked. This release changes only the Location experience and its supporting decision logic.

## Quality
- Adds v1.13.14 regression coverage for honest rental-demand wording, user-entered ERV/yield, severe environmental constraints and explicit evidence-gap disclosure.
- Full regression suite: **163 tests passing**.
