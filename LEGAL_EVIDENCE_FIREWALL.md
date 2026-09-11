# Legal Evidence Firewall — v1.10.1

The acquisition engine follows a deny-by-default evidence model.

## Trust rule

**Nothing can become legal evidence merely because it was reachable from an auction website.** A page/document must be tied to the selected lot before it can affect the deal model.

### Verified legal document

A downloaded document is verified only when one of the supported evidence paths succeeds:

- it is a legal-labelled document directly linked from the known lot page and passes the source checks;
- it is a legal-labelled child of a lot-specific pack index that has itself passed the lot identity check;
- its own text/URL contains strong subject identity (postcode/address/lot identifier); or
- the user explicitly uploads it into that property’s Deal Room.

### Unverified candidate

Candidates remain visible for diagnostics/manual access but have no effect on:

- legal risk score or risk register;
- seller/proprietor/company identity;
- Companies House lookup;
- buyer costs, VAT/deposit/completion assumptions;
- legal-pack completeness;
- maximum-bid approval/readiness;
- legal-pack revision/change alarms.

## Lot identity

The verifier uses strong combinations of:

- exact subject postcode;
- auction lot number with lot wording;
- multiple uncommon address tokens;
- matching provider lot-route identifier (for example `/lot-11` on the lot and legal pages).

Same-host alone is deliberately weak and cannot verify a pack page.

## Migration behaviour

Legal rows created before the v1.10.1 evidence policy are retained but quarantined. The dashboard treats them as unverified until **Fetch / refresh legal pack** is run again or a pack is uploaded manually. This prevents stale v1.10.0 generic-site extraction from carrying into current decisions.

## Provider access

The firewall is independent of authentication. If the provider requires a conventional account login, the app can use the user’s own Streamlit-secret credentials where the provider permits automated server access. It does not bypass CAPTCHA, MFA, anti-bot controls or permission restrictions.
