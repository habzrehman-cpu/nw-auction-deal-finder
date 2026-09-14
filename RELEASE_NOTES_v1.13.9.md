# Lotly v1.13.9

Legal-pack document recognition and lot-term accuracy release.

- Recognises compressed auction filenames such as `OfficialCopyLease...` and `TITLEPLAN...` without relying on spaces in the filename.
- Reclassifies previously saved generic user-uploaded legal documents at analysis time, so older uploads benefit without mandatory re-upload.
- Distinguishes the subject title from superior freehold/headlease titles. A freehold or headlease register can no longer satisfy the subject property's Title Register requirement.
- Uses subject-title matching for the core legal checklist (Title Register, Title Plan and Lease).
- Gives lot-specific Special Conditions precedence over generic auction-information wording for completion days, deposit and fee extraction.
- Prevents generic Auction Information / enquiry sheets from being mistaken for the Special Conditions document merely because they mention it.
- Tightens seller/owner extraction so superior-title proprietors are not presented as the subject-property owner.
- Adds regression coverage based on the failure mode found in the Lot 11 Salford legal pack.

Expected Lot 11 result after refresh:
- Subject Lease: found
- Subject Title Plan: found
- Special Conditions: found
- Subject Title Register (MAN115545): still missing from the uploaded archive
- Core-pack completeness: 75%
- Contract completion deadline: 14 days, 10% deposit

Discover, Deal Room Snapshot, Financials/Comparables and the Legal & Planning visual layout remain locked.
