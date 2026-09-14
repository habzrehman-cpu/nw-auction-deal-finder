# Lotly v1.12.7

## Stable hero rendering and deployment identification

This release addresses the live Streamlit screenshots where the v1.12.6 layout changes were visible but the approved houses hero still failed to render.

- Replaces the brittle DOM `:has()` hero targeting with a stable keyed Streamlit container (`st-key-lotly_hero`).
- Applies the approved terraced-house hero asset directly to that keyed container as an embedded data URI, so Community Cloud does not depend on a public/static asset URL.
- Removes the hero border in code (`border=False`) rather than relying on CSS to remove it.
- Pulls the account strip upward to remove the excess blank band at the top of the main workspace.
- Keeps the white-to-mint gradient, diagonal house artwork, Update data popover and last-updated indicator in the hero.
- Slightly tightens filter controls to bring the opportunity cards higher on the first screen.
- Adds a subtle `Lotly v1.12.7` label at the bottom of the sidebar so the deployed version can be confirmed instantly.
- Raises the minimum Streamlit version to 1.44 because keyed containers expose a stable CSS class from that version onward.
- Preserves all sourcing, scoring, underwriting, shortlist, comparison, pipeline, legal, planning, Companies House and refresh logic.
- Regression suite: 120 tests passing.
