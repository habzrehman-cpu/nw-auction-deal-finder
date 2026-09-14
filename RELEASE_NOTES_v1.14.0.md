# Lotly v1.14.0 — Guided Deal Room Release Candidate

This release turns the Deal Room into a beginner-first property investment decision journey while keeping the approved Discover/Home page unchanged.

## Guided Deal Room

- Replaces the old Snapshot front door with **Guided View**.
- Leads with the question: **Should I buy this property, and if so, what is the right price?**
- Adds a persistent decision journey:
  - Price
  - Numbers
  - Value
  - Legal
  - Location
  - Funding
  - Decision
- Uses beginner-safe outcomes:
  - **DO NOT PROCEED**
  - **KEEP INVESTIGATING**
  - **READY TO NEGOTIATE**
  - **READY TO BID / OFFER**
- Every major section explains the evidence, why it matters and the next action.
- Detailed Seller, Financials, Comparables, Auction, Legal & Planning, Location and Workspace tabs remain available as the evidence layer.

## Flip / Buy & Keep strategy

- Adds a persistent per-property strategy selector.
- **Flip** focuses on purchase, refurbishment, total investment, modelled resale value, potential profit, ROI and price ceiling.
- **Buy & Keep** focuses on purchase, total investment, evidence-backed rent, gross yield and modelled equity.
- Lotly does not invent rent. Yield remains pending until rental evidence or a user-supplied ERV is available.
- Gross yield is kept separate from net cash flow; finance and ongoing costs still need to be confirmed.

## England-only property checks

The Guided View now combines the property due-diligence picture into simple **CLEAR / CHECK / STOP / NOT VERIFIED** cards for:

- Legal pack
- Planning
- Building Regulations / Building Control evidence
- Flood risk
- Coal / mining
- Previous property history

A missing record is never treated as proof that a property is clear. Planning permission and Building Regulations are treated as separate checks. Building Regulations completion/final-certificate evidence and coal/mining searches are recognised from verified uploaded legal/search documents.

## Legal pack upload as a first-class workflow

- Adds a prominent **Upload the legal pack** route inside Guided View.
- Supports the existing PDF/TXT/ZIP legal-pack workflow when auctioneer access is behind login.
- Keeps the property-identity firewall in force before uploaded evidence can affect the decision.
- Missing title/legal evidence continues to block bidding rather than being inferred from weaker sources.

## Evidence and decision integrity

- Automatically attempts to migrate legacy residential comparable evidence to the current matching model before it is used by Guided View.
- Legacy/unrefreshed comparable evidence keeps valuation-derived figures **PROVISIONAL**.
- Separates **Returns score** from **Evidence confidence** in Financials.
- Reuses the Seller tab's canonical negotiation-leverage score everywhere.
- Reuses the normalized Auction state everywhere; an unconfirmed result is not described as a failed auction.
- Max buy is labelled provisional unless the evidence basis is supported.
- Road-access wording suppresses unhelpful stored place names unless the reference is a meaningful strategic road/junction.

## Design lock

- The approved **Discover/Home page remains unchanged**.
- The v1.14 Guided View is now the locked beginner-first Deal Room front door.
- Future work should improve evidence coverage and correctness without redesigning the approved layout unless explicitly requested.

## Validation

- **188 automated tests pass.**
- Python compile checks pass.
- The core Discover property-card/feed rendering functions were compared with v1.13.17 and remain unchanged.
