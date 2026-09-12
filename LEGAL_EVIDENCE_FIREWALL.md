# Legal Evidence Firewall + Property Identity Lock + Revalidation — v1.10.3

v1.10.3 adds **historic evidence revalidation and purge**. On legal refresh the app re-checks every stored automatic document against the current document-class gate and subject property identity. Previously trusted documents that fail are quarantined; all derived rent, seller/company, contact, risk and buyer-cost evidence is rebuilt from the surviving verified set. Stale Companies House enrichment is removed when the verified corporate identity disappears.

The legal acquisition pipeline is deny-by-default. A discovered file is not legal evidence until it passes **both** the legal document-class gate and the selected property's identity gate.

## Automatic evidence gate

1. Discover candidate legal link/document.
2. Classify document type. Generic marketing/advisory/provider pages are excluded.
3. Score lot identity from postcode, address tokens, lot number and lot-route identifiers.
4. Hard reject explicit cross-property identity conflicts.
5. Only a recognised legal/DD document above the verification threshold may enter the legal parser.
6. Candidate and rejected files stay visible for audit but cannot influence the deal.

### Identity scoring

- exact subject postcode: dominant evidence;
- subject address tokens: corroborating evidence;
- lot number / provider lot route: corroborating evidence;
- explicit different property postcode: automatic cross-property rejection;
- same auction-provider host alone: weak evidence only.

### Source tiers

- `verified-legal-document` — may influence legal risk, ownership, rent, buyer costs, pack completeness and bid readiness;
- `verified-legal-pack-index` — verified lot-specific navigation/index, but not itself a legal document;
- `candidate-unverified` — visible for manual follow-up, excluded from conclusions;
- `rejected-cross-property` — identified mismatch or disallowed evidence class, retained only for audit;
- auctioneer property evidence and external/contextual enrichment remain separate.

## Core-pack bid gate

A few verified documents are not the same as a complete legal pack. The app keeps bid readiness blocked until the required core components are verified. Missing core documents are shown prominently in the Deal Room.

## User uploads

Files deliberately uploaded into a selected Deal Room are treated as user-attested evidence and remain clearly marked as such. The buyer/solicitor must still confirm they are the latest complete pack/addendum.

## Migration

Pre-v1.10.2 legal summaries remain stored for audit but are quarantined from live deal scoring until refreshed through the Property Identity Lock.

## Provider access

Authentication and evidence verification are separate. The app never bypasses CAPTCHA, MFA, anti-bot controls, paywalls or provider permission restrictions.