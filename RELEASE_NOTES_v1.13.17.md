# Lotly v1.13.17 — Funding confirmation and contact-aware Workspace

This release makes the final Workspace blocker explicit for beginner investors without changing the locked Discover or Deal Room analysis layouts.

## Funding readiness

- Adds a persistent buyer funding position:
  - **Cash available**
  - **Mortgage/bridge approved**
  - **Agreement in principle only**
  - **Funding not confirmed**
- Adds an explicit contractual-timing confirmation: **Yes — confirmed / No / Not sure**.
- A fast-completion funding blocker only clears when the buyer confirms **Yes — confirmed** and the funding position is cash available or a fully approved mortgage/bridge facility.
- An agreement in principle is deliberately not treated as completion-ready funding.
- Stores an optional broker/lender contact and evidence/reference note.
- Funding confirmation is a buyer workflow assertion only; it does not replace proof of funds, lender approval, legal advice or contractual checks.

## Workspace task integrity

- The 14-day funding task is now a genuine evidence-driven blocker rather than a task that can remain open forever after the buyer ticks **Action done**.
- Saving a valid funding confirmation removes the live funding blocker and moves it to resolved history.
- Reverting funding to unconfirmed reopens the blocker.
- A fast-completion funding task is always treated as **Must resolve before bidding**.

## Contact-aware actions

- Solicitor-review tasks now show the buyer's saved solicitor name/phone/email directly beside the action.
- Funding-deadline tasks show the saved broker/lender contact beside the action.

## Validation

- 178 automated tests pass.
- Python compile checks pass.
