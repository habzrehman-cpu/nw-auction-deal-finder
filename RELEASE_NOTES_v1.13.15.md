# Lotly v1.13.15 — Location integrity + beginner Workspace

## Location
- Deal Room sidebar now shows the Residential Buy Box when the selected deal is residential instead of leaking commercial criteria into a flat/house analysis.
- Flood/environment wording now distinguishes evidence at/very near the property from evidence elsewhere in the search radius and explicitly avoids claiming that a mapped item proves the property itself will flood.
- Added a rental-comparable workflow inside Location. Users can add current rental evidence, and Lotly only treats rent as supported after at least three comparables.
- With three or more rental comparables Lotly shows an evidence-backed rent range, median rent and gross yield at the current guide.
- A supported median rent can be copied into Financials as the working ERV without retyping it.

## Workspace
- Rebuilt Workspace as a beginner-friendly deal action centre.
- Adds one clear deal status and one clear next action at the top.
- Automatically generates an acquisition checklist from live Legal, Planning, Valuation, Rental, Finance, Viewing/condition and Auction evidence.
- A completed Workspace task records user progress only; it never overrides a red evidence gate elsewhere in Lotly.
- Adds simple stages: Reviewing → Due diligence → Ready to offer → Offer made → Negotiating → Acquired / Passed.
- Adds important auctioneer/legal evidence contacts and shortcuts.
- Adds persistent price-test / offer history.
- Retains persistent deal notes and one-page deal brief download.
- Adds custom tasks for user-specific actions.

## Data persistence
- Added persistent rental comparables, deal tasks and offer-history tables to the local/cloud-snapshot database.

## Quality
- Discover, Snapshot, Financials, Comparables, Seller, Auction and Legal & Planning approved layouts remain unchanged.
- 168 regression tests pass.
