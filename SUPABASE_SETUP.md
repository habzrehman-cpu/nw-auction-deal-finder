# Supabase private persistence setup (v1.9)

The verified setup for the current single-user Streamlit deployment is a private Supabase Storage bucket accessed server-side through the Supabase Storage REST API.

## 1. Private bucket

Create a private Storage bucket named:

`nw-auction-private`

## 2. Server secret

Create a Supabase **Secret API key** for the Streamlit backend. Keep it only in Streamlit Secrets; never commit it to GitHub or expose it in browser/client code.

## 3. Streamlit Secrets

```toml
[supabase]
bucket = "nw-auction-private"
database_object = "state/auction_tracker.db"
url = "https://YOUR_PROJECT_REF.supabase.co"
secret_key = "YOUR_SUPABASE_SECRET_KEY"
```

Save the secrets and reboot the app. The sidebar should show **Private cloud read/write verified** after a successful sync.

The app saves the SQLite snapshot at `state/auction_tracker.db` and stores uploaded legal originals under `legal-packs/<property-id>/...`.

### Optional S3 mode

Supabase S3-compatible credentials are still supported, but are not required for this deployment. If both S3 and REST credentials are supplied, the current code may prefer the configured S3 path. Use one persistence mode at a time to keep troubleshooting simple.

## Security

The Supabase secret key is a backend credential with elevated access. Store it only in Streamlit Secrets or another secure server-side secret store. Never send it in chat, email, URLs or source code.

## Architecture

The current free-test build cloud-synchronises one SQLite database snapshot. This is appropriate for the present single-user workflow. Before multi-user/concurrent production use, migrate the transactional data model to Postgres rather than allowing multiple writers to overwrite one SQLite snapshot.
