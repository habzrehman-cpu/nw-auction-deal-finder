# Lotly v1.13.6

## Beginner-first Legal & Planning

This release redesigns the Deal Room Legal & Planning tab for buyers with capital but little or no property-investment experience.

### What changed
- Default Legal & Planning view now translates due diligence into three plain-English states: **STOP**, **CHECK**, and **CLEAR**.
- Added an overall bid gate explaining whether the user should stop, obtain confirmation, or continue to solicitor review.
- Added eight simple decision cards covering:
  - legal pack
  - ownership and title
  - tenure / lease
  - costs and major works
  - occupation / tenancy
  - building safety
  - planning
  - auction completion / deposit terms
- Every card explains **why it matters** and the **next action**.
- Added a core-document checklist for title register, title plan, special conditions, lease where relevant, and latest addendum.
- Added obvious **Refresh legal pack** and **Refresh planning check** controls.
- Added copy/download-ready **Questions to send your solicitor**.
- Moved technical planning tables, evidence trails, document identity checks and raw legal detail into a collapsed **Advanced evidence & source records** section.
- A severity 4/5 finding from verified legal evidence now keeps the bid gate blocked until professional review, even where the core pack itself is complete.

### Design lock
- Discover remains design-locked.
- Deal Room Snapshot, Financials and Comparables layouts remain unchanged.

### Quality
- Python compile check passes.
- 138 automated tests pass.
