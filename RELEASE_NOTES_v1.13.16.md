# Lotly v1.13.16 — Workspace guardrails and guided actions

This release completes the beginner-first Workspace refinement without changing the locked Discover or approved Deal Room analysis layouts.

## Workspace checklist hierarchy

- Splits evidence-driven tasks into three clear groups:
  - **Must resolve before bidding**
  - **Check before making an offer**
  - **Negotiation actions**
- Keeps hard legal/timing blockers visually separate from ordinary due-diligence and non-binding negotiation work.

## Action done vs issue resolved

- A task now records two separate states:
  - whether the buyer has completed the action; and
  - whether Lotly can see that the underlying evidence issue is resolved.
- Completing a call/email/task never clears a red evidence gate by itself.
- Resolved auto-generated evidence items are retained in a collapsed history instead of being deleted.

## Guided navigation

- Deal Room tabs are now stateful.
- Workspace task buttons can take the user directly to the relevant Deal Room area (Legal & Planning, Financials, Comparables, Location, Auction or Seller).
- Opening a new property from Discover still starts on Snapshot.
- Streamlit minimum version is now 1.55 to support stateful tab navigation.

## Stage and offer safety

- While a red STOP remains, Lotly blocks progression to **Ready to offer**, **Offer made** and **Acquired**.
- Non-binding negotiation remains available.
- Binding offer-history statuses are also blocked while the deal is evidence-blocked.

## Buyer solicitor contact

- Adds a persistent buyer-solicitor contact to Workspace.
- Legal-pack solicitor/contact details are kept separate and clearly labelled as potentially representing the seller.
- This prevents a novice user from mistaking the seller's legal representative for their own solicitor.

## Validation

- 173 automated tests pass.
- Python compile checks pass.
