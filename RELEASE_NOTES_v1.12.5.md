# Lotly v1.12.5

## Approved Discover UI alignment patch

This release fixes the remaining differences between the deployed Streamlit screen and the approved Lotly Discover design.

- Removes the unused Streamlit sidebar header space so the Lotly brand starts at the top of the sidebar.
- Forces the sidebar to the approved 252 px width so the main content aligns with the reference design.
- Renders the terraced-house hero artwork as an explicit in-app image layer instead of relying on a CSS background data URI, making the approved hero reliable on GitHub/Streamlit deployments.
- Makes the hero borderless and more compact so the KPI and filter rows sit higher on the first screen.
- Keeps the white account strip, mint/teal hero treatment, KPI cards, filter surface and two-column opportunity cards.
- Replaces the KPI glyphs with consistent outline SVG icons for a closer match to the approved design.
- Tightens filter spacing to reduce unnecessary vertical scrolling.
- Preserves all sourcing, scoring, underwriting, shortlist, comparison, pipeline, legal, planning and refresh logic.
- Regression suite: 120 tests passing.
