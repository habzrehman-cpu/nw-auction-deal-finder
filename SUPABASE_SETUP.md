# Supabase private persistence setup (v1.8.1)

This is the recommended free-test setup for keeping auction history, shortlist, underwriting, CRM notes and uploaded legal originals across Streamlit reboots.

## 1. Create the bucket

1. Open your Supabase project.
2. Go to **Storage**.
3. Create a new **private** bucket called `nw-auction-private`.

## 2. Create S3 server credentials

1. In Supabase go to **Storage > Configuration > S3**.
2. Enable the S3 protocol if required.
3. Generate an **Access Key ID** and **Secret Access Key**.
4. Copy the **Endpoint** and **Region** shown by Supabase.
5. Keep these values private. Do not paste them into GitHub or any public code/file.

## 3. Add them to Streamlit Secrets

Open the deployed Streamlit app, then **Manage app > Settings > Secrets** and paste:

```toml
[supabase]
bucket = "nw-auction-private"
database_object = "state/auction_tracker.db"
s3_endpoint = "https://YOUR_PROJECT_REF.storage.supabase.co/storage/v1/s3"
s3_region = "YOUR_PROJECT_REGION"
s3_access_key_id = "YOUR_S3_ACCESS_KEY_ID"
s3_secret_access_key = "YOUR_S3_SECRET_ACCESS_KEY"
```

Replace the four placeholder values with the exact values shown by Supabase.

## 4. Save and reboot

1. Save the Streamlit Secrets.
2. Reboot the app.
3. In the app sidebar, **Persistence** should show **Private cloud connected**.
4. Click **Refresh live data** once.
5. When the refresh completes, the database is snapshotted to the private bucket.

On a future cold start, if the local Streamlit database is absent, the app restores `state/auction_tracker.db` from Supabase before opening the dashboard.

## Legal packs

In a Deal Room, open **Planning & legal** and upload PDF/TXT documents or a ZIP legal pack. When cloud persistence is connected:

- supported documents are parsed individually;
- the original files are stored under `legal-packs/<property-id>/...` in the private bucket;
- extracted text, findings and source/page evidence are stored in the deal database;
- stored originals can be retrieved from the Deal Room.

## Security

Supabase S3 access keys are server credentials with broad Storage access. Store them only in Streamlit Secrets (or secure environment variables for another server). Never commit them to GitHub, paste them into source code, or expose them in a browser-facing component.

## Current architecture note

v1.8.1 uses a cloud-synchronised SQLite snapshot because the current deployment is single-user and on a free test stack. If this becomes a concurrent multi-user product, migrate the tables to Postgres so multiple users cannot overwrite the same SQLite snapshot.


## v1.8.2 connection status

`Private cloud connected - write not yet verified` means the app successfully listed the configured private bucket. After the first successful `Sync cloud snapshot`, the status changes to `Private cloud read/write verified`. If an S3 request fails, v1.8.2 surfaces the HTTP/S3 error detail rather than a generic upload message.
