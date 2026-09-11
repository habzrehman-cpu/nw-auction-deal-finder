# Legal-pack automation setup (v1.10.1)

Version 1.10.1 can automatically acquire and analyse legal documents when the provider permits server-side access, with a strict **Legal Evidence Firewall**. It does not bypass CAPTCHAs, anti-bot controls, MFA, registration restrictions or provider terms.

## What happens automatically

- **Public direct PDFs/ZIPs:** the app can follow lot-specific legal-document links, download supported files, parse them and store verified originals privately in Supabase.
- **Lot-specific pack pages:** an HTML page must pass the subject-lot identity check before the app follows its child documents.
- **Login-required documents:** where the provider permits it, the app can use your own account credentials (or a valid session cookie) stored only in Streamlit Secrets. It stops at CAPTCHA/MFA/unsupported interactive authentication.
- **Pack revisions:** verified legal documents are fingerprinted. Changed/added/removed verified documents can re-block the deal until reviewed.
- **Manual fallback:** PDF, TXT or ZIP upload remains available in the Deal Room whenever automatic acquisition cannot establish a trustworthy lot-bound pack.

## Evidence Firewall

A discovered link is only a **candidate** until the app can prove it belongs to the selected lot. Generic provider pages such as lease-advisory, property-search, business-sales, education, investor-relations, consultancy, news/contact and general services pages are rejected and are never allowed to feed legal conclusions.

The Deal Room therefore separates:

- **Unverified candidates**
- **Verified legal docs**
- **Verified docs parsed**

Only verified legal docs can drive ownership/company identity, legal risk, pack completeness, buyer fees/terms, Companies House enrichment or bid approval. Existing pre-v1.10.1 legal extractions are quarantined until refreshed.

See `LEGAL_EVIDENCE_FIREWALL.md` for the trust model.

## Provider guardrails

- **BTG Eddisons:** public lot-bound files are attempted automatically. Some Eddisons legal-pack routes may require an account. You can configure your own account credentials if the provider permits the server-side login route; otherwise use manual upload.
- **Savills:** can use your own configured account and stops at any CAPTCHA/MFA/unsupported challenge.
- **Auction House / Auction Passport:** automated page access remains permission-gated by default. Only set `permission_confirmed = true` if you have provider permission for this use.
- **Allsop:** automated legal-document acquisition remains permission-gated by default. Only enable after the required provider permission is obtained.

## Streamlit Secrets

Open **Streamlit > Manage app > Settings > Secrets** and add the relevant sections alongside your existing Supabase and Companies House configuration.

```toml
[legal_sources]
auto_enabled = true

[legal_sources.eddisons]
enabled = true
# Optional if a specific Eddisons legal route requires your account:
# email = "YOUR_EDDISONS_ACCOUNT_EMAIL"
# password = "YOUR_EDDISONS_ACCOUNT_PASSWORD"
# cookie = "session_name=session_value"
# login_url = "https://..."

[legal_sources.savills]
enabled = true
email = "YOUR_SAVILLS_ACCOUNT_EMAIL"
password = "YOUR_SAVILLS_ACCOUNT_PASSWORD"
# Optional alternative if you deliberately manage a valid session cookie:
# cookie = "session_name=session_value"
# Optional if Savills changes its login route:
# login_url = "https://auctions.savills.co.uk/component/user/login"

[legal_sources.auction_house]
enabled = true
permission_confirmed = false
# Only after provider permission is obtained:
# permission_confirmed = true
# email = "YOUR_ACCOUNT_EMAIL"
# password = "YOUR_ACCOUNT_PASSWORD"
# or cookie = "session_name=session_value"

[legal_sources.allsop]
enabled = true
permission_confirmed = false
# Only after the required provider permission is obtained:
# permission_confirmed = true
```

Save Secrets and reboot Streamlit. The sidebar **Legal pack automation > Source access status** shows whether each provider is ready, login-required or permission-blocked.

## After upgrading from v1.10.0

The app deliberately does **not** trust legal analysis created under the old policy. For a deal previously analysed in v1.10.0:

1. open the Deal Room;
2. go to **Planning & legal**;
3. click **Fetch / refresh legal pack**; or upload the actual pack;
4. confirm the screen reports verified legal documents before relying on the risk register or seller identity;
5. sync the cloud snapshot after validation.

This is intentional. It prevents unrelated provider-site text stored by v1.10.0 from remaining in current acquisition decisions.

## Security rules

- Never put provider passwords/cookies, Supabase secret keys or Companies House keys in GitHub.
- Never paste those credentials into chat.
- Use Streamlit Secrets for the deployed app.
- If an account requires MFA/CAPTCHA/interactive challenge, complete/download the pack manually and upload it to the Deal Room instead.
- Rotate credentials immediately if you believe they have been exposed.

## Legal caveat

Automated analysis is acquisition triage, not legal advice. Even a verified pack may be incomplete or superseded. The latest complete pack/addendum and legal acceptability must be confirmed by the buyer’s solicitor before bidding or exchange.
