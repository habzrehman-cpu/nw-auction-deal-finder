# Lotly v1.12.6

## Hero rendering and Discover layout correction

This release fixes the remaining rendering differences seen on the live Streamlit deployment after v1.12.5.

- Applies the approved terraced-house hero artwork as a CSS background on the exact Streamlit hero container, avoiding collapsed absolute-image wrappers.
- Restricts hero styling to the hero container only, preventing the pale mint background from leaking into filters and property-card rows.
- Uses the approved white-to-mint hero gradient with the terraced-house artwork anchored to the right at preserved proportions.
- Removes residual top spacing from the Streamlit main block and closes the default element gap between the account bar and hero.
- Keeps the approved white sidebar, top account strip, KPI row, filters, Cards / Map / Table controls and two-column opportunity cards.
- Slightly tightens opportunity-card image height so the first result row is closer to the approved desktop composition.
- Preserves live sourcing, scoring, underwriting, shortlist, comparison, pipeline, legal, planning, company-intelligence and refresh logic.
- Regression suite: 120 tests passing.
