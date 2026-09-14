# Lotly v1.13.13 — Auction History Integrity

## Auction evidence integrity
- Groups duplicate auction observations into a single beginner-facing event while preserving the raw history underneath.
- Treats `Sold`, `Sold Prior` and `Sold After` as **auctioneer status signals**, not proof of legal completion or Land Registry transfer.
- If the current listing is available again after an earlier sold-status signal, Lotly now says **Available post-auction — a previous sale status needs clarification** rather than calling it a failed auction.
- Adds a returned-to-market signal without converting contradictory sold observations into failed-auction attempts.
- Normalises the beginner timeline to show the sequence clearly: status reported -> returned/available now.
- Seller negotiation leverage now only receives auction-history points from concrete failed-auction results or a verified return-to-market transition; contradictory sold statuses do not inflate leverage.

## Legal evidence summary
- The Deal Room evidence strip no longer displays an incomplete core legal pack simply as `Verified`.
- A partially verified pack now shows its actual completeness, for example **75% verified — incomplete**.
- The green legal evidence state is reserved for a complete current-policy core pack.

## Locked areas
- Discover and the established Deal Room visual layouts remain unchanged. This release is an evidence-integrity update, not a redesign.
