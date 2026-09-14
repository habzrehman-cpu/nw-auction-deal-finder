# Lotly v1.13.7

## Legal-pack refresh that explains what happened

The beginner Legal & Planning workflow no longer reports a generic success message when an automatic legal-pack refresh produces no new verified evidence.

### Improvements

- Detects whether refresh actually increased verified documents or core-pack completeness.
- Explains when Lotly found candidate legal-pack links but could not verify them.
- Explains when a provider is permission-gated or likely to require login/registration.
- Makes clear that "no automatic pack found" does **not** mean the property has no legal pack.
- Adds a beginner-friendly fallback directly to the Legal & Planning screen:
  1. open the auction listing;
  2. download the latest legal pack/addendum;
  3. upload PDF/TXT/ZIP files to Lotly;
  4. let Lotly verify property identity and analyse the evidence.
- Uploaded documents continue to pass through the existing Legal Evidence Firewall and Property Identity Lock before they influence bid readiness.
- Discover, Deal Room Snapshot, Financials and Comparables visual layouts remain locked.
