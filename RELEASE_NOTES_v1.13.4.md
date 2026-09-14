# Lotly v1.13.4 - Financial & Comparable Data Integrity

## Financials
- GDV/resale input now displays the live automated comparable midpoint instead of a misleading zero.
- Added explicit GDV source control: Automatic comparable midpoint or Manual override.
- Automatic GDV remains automated when saved; it is no longer silently converted into a manual override.
- Fixed legacy behaviour where a saved residential `use_auto_comps=0` could disable otherwise valid automated comparable evidence.
- Added provenance tracking for valuation and auction-fee assumptions.
- Auction fee inputs now distinguish additional fixed fees from buyer/admin percentage/minimum fees.
- Added effective fee preview at the working purchase price.
- Legacy zero fee overrides no longer mask stronger current listing evidence unless the user explicitly selects Manual override.
- Added assumption provenance summary for valuation, auction fees and legal evidence.

## Comparables
- Replaced the saturating residential match score with a v2 evidence-quality score using property subtype, distance, recency, tenure, locality and price coherence.
- Prior sales of the subject property are down-weighted rather than treated as independent evidence.
- Material price outliers are flagged and down-weighted/removed when sufficient stronger evidence exists.
- Comparable confidence now incorporates average evidence quality and price dispersion, not just comparable count.
- Best-matching evidence now explains why each sale was selected and flags outliers for review.
- Existing legacy comparable sets are identified and prompt the user to refresh before relying on the new match score.

## Locked UI
- Discover remains design-locked.
- Deal Room Snapshot remains visually locked; this release changes Financials and Comparables only.

## Validation
- 132 automated regression/data-integrity tests passing.
- Python compile check passing.
