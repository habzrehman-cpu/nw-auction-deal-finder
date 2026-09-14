# Lotly v1.13.5

## Comparable refresh persistence fix

- Keeps the currently open Deal Room selected while refreshing comparable evidence.
- Stores both the local property id and stable auction source key before the refresh.
- Adds a source-key identity fallback so a database restore/rebuild cannot silently detach the open Deal Room from the same auction listing.
- Comparable refresh failures now leave the property open and surface a clear error instead of losing context.
- Successful refreshes return the user to the same Deal Room with a confirmation message.
- Discover and Deal Room Snapshot visual designs remain locked.
