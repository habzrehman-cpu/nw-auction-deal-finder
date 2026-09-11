# Companies House ownership intelligence setup (v1.9)

The Companies House integration is optional and read-only. It uses the official Companies House Public Data API to enrich corporate sellers after a company number is extracted from the legal pack (or where an exact company-name match can be resolved safely).

## 1. Create a free Companies House API key

1. Open the Companies House Developer Hub: https://developer.company-information.service.gov.uk/
2. Sign in or create an account.
3. Create an application (live/public-data use is fine for this read-only integration).
4. Create an **API key** client for the application.
5. Copy the API key and keep it private.

The Public Data API uses HTTP Basic authentication with the API key as the username and a blank password. The key must never be committed to GitHub.

## 2. Add the key to Streamlit Secrets

Open **Streamlit > Manage app > Settings > Secrets** and add this separate block underneath your existing Supabase section:

```toml
[companies_house]
api_key = "YOUR_COMPANIES_HOUSE_API_KEY"
```

Save the Secrets and reboot the app.

The sidebar should then show **Companies House API configured**.

## 3. What the app retrieves

For a verified corporate seller the app can retrieve and persist:

- company name, number, status and registered office;
- incorporation date and SIC codes;
- active directors (name, role and appointment date only);
- persons with significant control (public corporate-control information only);
- outstanding and satisfied registered charges and charge holders;
- insolvency cases;
- accounts/confirmation-statement overdue flags;
- recent relevant Companies House filings;
- a separate **Corporate pressure** score used only as acquisition triage.

The app deliberately does not surface dates of birth or personal residential addresses from Companies House data.

## 4. How it appears in the Deal Room

Open **Vendor story** for a property. If a company seller is identified, the page shows **Ownership / company intelligence** and a button to refresh the official Companies House record. Corporate facts are added to the Vendor Story timeline and are kept separate from interpretation.

A company being financed, having charges or filing late is not proof of seller distress. The tracker treats those as evidence to investigate, not as a statement of motive.
