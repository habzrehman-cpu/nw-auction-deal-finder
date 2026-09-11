# Legal-pack automation setup (v1.10)

Version 1.10 can automatically acquire and analyse legal documents when the provider allows server-side access. It does not bypass CAPTCHAs, anti-bot controls, registration restrictions or provider terms.

## What happens automatically

- **Public direct PDFs/ZIPs:** the app follows legal-document links, downloads supported files, parses them and stores the original privately in Supabase when cloud persistence is configured.
- **Savills login-required documents:** the app can use your own Savills account credentials (or a session cookie) stored only in Streamlit Secrets. It submits a conventional login form and stops if a CAPTCHA or unsupported authentication step is encountered.
- **Eddisons/public documents:** direct public legal files are acquired automatically where exposed by the lot/legal page.
- **Pack revisions:** every parsed document is fingerprinted. Changed/added/removed legal documents can re-block the deal until the latest evidence is reviewed.
- **Manual fallback:** PDF, TXT or ZIP upload remains available in the Deal Room if a provider does not permit server-side automated retrieval or the login flow cannot be completed safely.

## Provider guardrails

Two sources are deliberately permission-gated in the app:

- **Auction House / Auction Passport:** automated page access is disabled by default because published Auction House terms restrict automated software use without consent. Only set `permission_confirmed = true` if you have obtained the provider's permission for this use.
- **Allsop:** automated legal-document acquisition is disabled by default because Allsop's published website terms restrict robots/data-extraction tools without prior written permission. Only enable it after permission is obtained.

This is a compliance guardrail, not a technical limitation. The app never attempts to defeat a CAPTCHA, bot check or access control.

## Streamlit Secrets

Open **Streamlit > Manage app > Settings > Secrets** and add the following alongside your existing Supabase and Companies House sections.

```toml
[legal_sources]
auto_enabled = true

[legal_sources.eddisons]
enabled = true

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
# Only after prior written permission is obtained:
# permission_confirmed = true
```

Save the Secrets and reboot the Streamlit app. The sidebar **Legal pack automation > Source access status** section shows which providers are ready, login-required or permission-blocked.

## Security rules

- Never put account passwords, cookies, Supabase secret keys or Companies House keys in GitHub.
- Never paste those credentials into chat.
- Use Streamlit Secrets only for the deployed app.
- If a provider account supports MFA/CAPTCHA and an interactive challenge is required, complete/download the pack manually and upload it to the Deal Room instead.
- Remove or rotate credentials immediately if you think they have been exposed.

## Evidence integrity

Automatic retrieval does not make an extracted statement authoritative by itself. Version 1.10 records whether a fact came from a parsed legal document or from auctioneer/listing text. Key fields can carry document/page evidence, and legal documents outrank listing heuristics. The buyer's solicitor must still review the latest complete pack and addendum before bidding or exchange.
