# North West Property Auction Deal Finder


## v1.8.2 - persistent cloud workspace + legal-pack evidence trail

Version 1.8 adds a practical persistent-storage layer for the current single-user Streamlit Community Cloud deployment and deepens legal-pack analysis. The core app remains SQLite-first for speed and portability, but when Supabase is configured it restores the SQLite database from a **private Supabase Storage bucket** after a cold start and uploads a fresh cloud snapshot after live refreshes, comparable/planning/legal updates, shortlist changes, underwriting changes, workspace changes and notes. User-uploaded legal originals can also be retained privately in the same bucket.

This means the auction history, seller story, shortlist, saved underwriting, CRM/workspace notes and extracted legal evidence can survive Streamlit reboots and redeploys. This storage mode is intended for the current single-user/free-testing stage. If the product later becomes a concurrent multi-user platform, move the data model to Postgres rather than sharing a single SQLite snapshot between writers.

### Legal-pack improvements in v1.8.2

The legal screen now accepts **PDF, TXT and ZIP legal packs**. ZIP uploads are safely unpacked and supported PDF/TXT members are analysed individually. PDF extraction inserts page markers so important findings can carry an evidence trail back to the source document and page.

The Deal Room now shows:

- pack completeness percentage plus missing core components
- registered proprietor/seller, seller/disposal type, title number and company number where stated
- registered office where a company address is expressly present in the pack
- title price-paid amount/date where the official-copy wording is extractable
- lease term/start/remaining years, ground rent and service charge
- seller costs charged to buyer, completion period, deposit, VAT/addendum signals and registered-charge references
- EWS1/cladding, fire/building-safety, arrears, restrictive covenant, title-quality and other risk flags
- professional/business contacts actually present in the pack
- an **Evidence trail** with document name, page and short context for extracted findings
- a source/page-aware legal risk register
- private-cloud retention/retrieval of uploaded originals when Supabase is connected

The app deliberately does not search the internet for private personal contact details. It can surface an owner/proprietor name contained in legal evidence and business/professional contacts present in that evidence, while corporate owners can be followed through the Companies House action link.

### Free persistent setup with Supabase

The preferred v1.8.2 connection uses Supabase Storage's **S3-compatible server credentials**, because that is a standard server-to-server storage path for private files.

1. Create a free Supabase project.
2. In **Storage**, create a private bucket named `nw-auction-private`.
3. Open **Storage > Configuration > S3**, enable the S3 protocol and generate an **Access Key ID** and **Secret Access Key**. Copy the endpoint and region shown on the same screen. These S3 credentials are server-only and must stay in Streamlit Secrets.
4. In Streamlit Community Cloud open **Manage app > Settings > Secrets** and add:

```toml
[supabase]
bucket = "nw-auction-private"
database_object = "state/auction_tracker.db"
s3_endpoint = "https://YOUR_PROJECT_REF.storage.supabase.co/storage/v1/s3"
s3_region = "YOUR_PROJECT_REGION"
s3_access_key_id = "YOUR_S3_ACCESS_KEY_ID"
s3_secret_access_key = "YOUR_S3_SECRET_ACCESS_KEY"
```

5. Save Streamlit Secrets and reboot the app. Never commit these credentials to GitHub or place them in `.streamlit/secrets.toml` inside the repository.
6. The sidebar should change from **Local-only storage** to **Private cloud connected**.
7. Run **Refresh live data** once. At the end of the refresh the current SQLite state is uploaded to the private bucket. On a future cold start, v1.8.2 restores that snapshot before opening the database.

A backwards-compatible Supabase REST configuration is also supported for existing deployments using a server key, but the S3 configuration above is the recommended setup for this build.

A `.gitignore` is included to exclude the local SQLite file, Streamlit secrets, Python caches and `.env` files from GitHub.

## v1.7.1 accuracy patch

This patch tightens the acquisition evidence hierarchy after live validation against an Auction House leasehold flat:

- explicit auctioneer **Tenure** wording now outranks loose page text, preventing `freeholder` guidance from being mistaken for Freehold tenure
- guide ranges are preserved as low/high values (for example **GBP 65,000-GBP 85,000**) while the low guide remains the sourcing/filter basis
- short leases are extracted from detail-page wording, including original lease term, start date and stated/unexpired years
- leases below 80 years create a visible short-lease warning, a **BID BLOCKED** readiness state and a provisional (not approved) maximum bid
- post-auction availability is treated as the continuation of the failed sale, not automatically as a second failed auction; repeat failure requires separate concrete auction-result evidence
- fixed administration charges such as **GBP 1,800 inc VAT** are detected and can replace the generic auction-fee allowance
- EPC rating, allocated parking, balcony and auctioneer phone/email are extracted when explicitly published on the lot page
- leasehold flats receive service-charge, ground-rent, major-works and building-safety/EWS1 due-diligence prompts
- Deal Room wording is neutral across residential/commercial lots, and the evidence metric is labelled **Seller-story confidence**

The automated maximum bid remains acquisition triage, not a valuation or legal conclusion. A short lease or unreviewed legal pack prevents bid approval even where the desktop numbers appear attractive.

**Version 1.7.1** builds on the auction-style v1.6 interface and turns the Deal Room into an auction-site-style acquisition platform: browse property cards with images and high-level deal numbers, switch between Residential and Commercial, let the system rank the strongest opportunities first, then open a full Deal Room for underwriting, comparables, auction history, planning, legal-pack and location intelligence.

The public auction sources currently targeted are:

- Allsop
- Savills Property Auctions
- BTG Eddisons Property Auctions
- Auction House North West **and Auction House Manchester** (kept under the Auction House NW source label for database continuity)

It is designed for **on-demand refresh**, not scheduled alerts. Press **Refresh live data** and the backend fetches the current public auction pages, filters to North West England, stores them in SQLite, follows public lot-detail pages when enrichment is due, geocodes the property postcode, measures motorway access, records price/status/date changes, refreshes priority comparable evidence, screens official planning data, discovers public legal-pack material, and recalculates a transparent deal score and underwriting decision.


## Version 1.7 - acquisition intelligence workspace

Version 1.7 is the first build aimed at making the tool a one-stop professional deal-sourcing workspace rather than only an auction search engine.

### Vendor Story & Motivation

Every Deal Room now assembles an evidence-led seller story from auction history, planning records, listing facts and any parsed legal evidence. It shows **Vendor Motivation**, a separate **Buyer Leverage** score and a story-confidence percentage.

The story deliberately separates:

- **Confirmed evidence** - facts actually captured from auction, planning or legal sources.
- **Interpretation** - negotiation hypotheses such as increasing price flexibility or holding-cost pressure. These are clearly labelled as inference rather than fact.
- **Timeline** - auction attempts, guide/status changes and likely subject-property planning events in chronological order.

### Structured legal-pack extraction

When text is available from a public pack or a user-uploaded PDF/TXT file, the legal engine now attempts to extract and display:

- registered proprietor / seller name
- seller/disposal context such as receiver, mortgagee, administrator, liquidator, executor/probate or fund disposal
- title number and company number where stated
- lease start, term and estimated years remaining
- ground-rent and service-charge amounts where clearly stated
- seller costs charged to the buyer
- registered-charge references
- arrears wording
- EWS1/cladding and fire/building-safety wording
- completion period, deposit, VAT and addendum signals
- professional/business contacts appearing in the legal evidence, such as seller solicitor, auctioneer or managing agent

The app does **not** search for private personal contact details outside the supplied/public documents. Owner/proprietor names are surfaced only where the legal evidence contains them; professional contact details are surfaced only when present in that evidence.

The legal screen also generates a tailored **Questions for your solicitor** checklist from the issues detected. Automated extraction remains legal triage, not a substitute for the buyer's solicitor reviewing the latest complete pack and addendum.

### Deal Readiness

The Overview now includes an acquisition-readiness meter and explicit bid blockers. It checks auction status, detail enrichment, history, comparables, valuation, planning, legal pack, works/capex, tenure/lease and location evidence. Missing legal evidence, a short lease, weak valuation evidence or a required-but-zero works budget remains visible as an unresolved blocker.

### Financial scenario compare

The Financials tab compares the current assumptions at the opening offer, 90% of guide, guide price and calculated maximum bid where those values are available. It shows purchase price, all-in cost, profit/equity, ROI, financial score and recommendation side by side.

### Deal Workspace / mini CRM

Each property now has a persistent local workspace with a deal stage, next action, follow-up date and timestamped notes. Current stages include New, Reviewing, Auctioneer Contacted, Viewing, Legal Review, Offer Made, Negotiating, Bid Approved, Won, Lost and Archived.

The workspace also provides an **Action Centre** linking directly to the auction listing, a discovered legal document, planning record and Companies House when a company number has been extracted.

A **Download one-page deal brief** button creates a portable Markdown acquisition brief containing headline economics, seller story, bid blockers and next actions.


## Version 1.6 - professional sourcing workflow

### Browse like an auction website

The primary interface is no longer a database table. It is a property-led browse screen inspired by established auction/search platforms such as EIG, while exposing substantially more acquisition intelligence on each deal.

Use the prominent **Residential / Commercial** switch, then choose:

- **Best deals** - default system ranking, strongest opportunity first
- **Unsold** - available post-auction, no-bid, last-bid and unsold signals
- **New** - newly discovered stock
- **Reductions** - observed guide reductions
- **Relisted** - failed lots returned to market
- **Shortlist** - persistent saved opportunities

Each property card is designed as a fast sourcing snapshot: property image, address, auctioneer, lot/status, guide, key residential or commercial metrics, seller motivation, comparable confidence and a transparent deal-potential score. The old dense table remains available only inside **Analyst table / export view**.

### Deal Room

Click **View deal** to open the full acquisition record. The Deal Room now separates information into:

1. Overview
2. Vendor story
3. Financials
4. Comparables
5. Auction history
6. Planning & legal
7. Location
8. Workspace

The screen highlights both **why the deal may be attractive** and **what still needs checking**. Missing planning/legal evidence is displayed as **UNKNOWN**, never as zero risk.

### Historical auction backfill

Auction House stock is now checked against both the **North West and Manchester past-auction archives**. This is important for lots that move between a regional catalogue and the national unsold page. Historical observations are matched to the subject property and stored as dated events, allowing the engine to reconstruct:

- earlier guide prices
- no-bid / last-bid / unsold results
- repeat auction failures
- relisting
- observed guide reductions
- days since the latest failed-auction signal

A property first discovered today can therefore inherit recent public auction history instead of starting with a false zero-failure record.

### Refurbishment and heritage safeguards

If the listing says **modernisation, refurbishment or upgrading is required** but the saved works budget is GBP 0, the financial-return score is capped, the maximum bid is marked **PROVISIONAL**, and automatic bid approval is blocked until a works allowance is entered.

Grade I/II/listed-building wording and official listed-building planning designations are surfaced as material DD issues. This is particularly important where a seemingly strong residential margin depends on refurbishment or change of use.

### Property-specific auction fees

The detail-page parser now looks for published percentage administration/buyer fees, minimum charges and search fees. Detected charges can feed the underwriting cost stack rather than relying only on the generic auction-fee allowance. The legal pack remains authoritative for all completion/disbursement costs.

### Tighter residential comparables

Residential comparable ranking gives stronger weight to same-street and exact-subtype evidence. Where enough close, exact-type transactions exist, weaker/distant comparables are excluded rather than widening the desktop valuation unnecessarily.

### Motorway resilience

Motorway-junction enrichment now tries multiple public Overpass endpoints and has a fallback junction query. It still labels straight-line fallback mileage honestly if road routing is unavailable.

### Property images

The detail-page enrichment captures the auctioneer's representative social/gallery image URL where publicly exposed. Existing databases will treat missing images as due for detail enrichment, so images will progressively populate after the first upgraded live refresh.

## Windows quick start

1. Install Python 3.11+ from python.org if Python is not already installed.
2. Extract this folder.
3. Double-click `run_windows.bat`.
4. Your browser opens the dashboard, normally at `http://localhost:8501`.
5. Click **Refresh live data**.

The first run installs the Python dependencies. The SQLite database `auction_tracker.db` is created automatically in this folder.


## Updating the Streamlit Community Cloud test app

If an earlier version is already deployed from GitHub:

1. Extract the latest ZIP locally.
2. Upload/replace the project files in the **root** of the existing GitHub repository (keep `app.py`, `requirements.txt` and `tracker/` at repository root).
3. Commit the changes to the `main` branch.
4. Streamlit Community Cloud normally detects the GitHub commit and redeploys automatically.
5. When the app comes back, click **Refresh live data**.
6. Existing rows without images become eligible for detail-page enrichment, Auction House history is backfilled from North West + Manchester archives, and ranking is recalculated.

By default the app can still run from a local SQLite file. In v1.8.2, configure the optional private Supabase persistence layer above before relying on Streamlit Community Cloud for long-term history, shortlist, underwriting, workspace notes or legal evidence.

## What the live enrichment now does

### 1. Opens the individual auction lot page

The catalogue scraper identifies North West lots first. For eligible public detail URLs, the enrichment layer then captures the lot page text and caches it for seven days. This gives the scoring engine a much better chance of finding:

- GIA / floor area in sq ft or sq m
- freehold / leasehold tenure
- parking
- yards and loading access
- vacant possession
- split / multi-let potential
- refurbishment wording
- development / alternative-use wording

The detail page is not repeatedly downloaded on every dashboard refresh. Cached detail text is reused until it is due for renewal.

### 2. Calculates true guide-price GBP/sq ft when floor area is published

If the lot page publishes a usable floor area, the dashboard calculates:

`Guide price / extracted floor area = GBP per sq ft`

The dashboard also shows whether the floor area came from the **Detail page** or the original **Catalogue** text. If no floor area is published, GBP/sq ft remains blank rather than being estimated.

### 3. Geocodes the property postcode

Postcodes are bulk-geocoded through **Postcodes.io** and cached in SQLite. The property record stores latitude/longitude and the geocoding source, so normal refreshes do not repeat completed postcode lookups.

### 4. Finds real North West motorway junctions

The application retrieves motorway ways and `motorway_junction` nodes from **OpenStreetMap via Overpass** for the North West. Junction data is cached locally for 30 days. Target motorways include M6, M53, M55, M56, M57, M58, M60, M61, M62, M65, M66, M67 and M602.

### 5. Measures distance to the nearest junction

For commercial/development lots, the tool identifies the nearest motorway-junction candidates and attempts a road-distance calculation through the public OSRM routing service. The dashboard shows:

- nearest motorway
- nearest junction
- mileage
- distance type: **road** or **straight-line**

If road routing is unavailable, the tool falls back to straight-line distance and labels it explicitly. It never presents straight-line mileage as driving mileage.

## Planning + legal due diligence

The due-diligence layer is available from the Deal Room. Use **Refresh planning + legal** to process a priority batch, or refresh either layer from the selected-property screen.

### Official planning intelligence

The planning module uses the official **Planning Data** API from the Ministry of Housing, Communities and Local Government. For geocoded properties it checks point-based constraints such as:

- conservation areas
- listed buildings / listed-building extents
- flood-risk zones
- green belt
- Article 4 direction areas
- tree-preservation zones
- scheduled monuments
- SSSIs
- ancient woodland
- heritage-at-risk designations

It also searches approximately 350 metres around the property for planning applications from roughly the last 10 years. Where the returned data supports it, the dashboard shows application reference, description, decision, dates, distance, local-authority documentation link and whether the application is likely to relate to the subject property.

The app produces two separate signals:

- **Planning risk** - the DD burden created by statutory designations/constraints.
- **Planning upside** - positive subject/nearby planning evidence such as approved conversion, residential, redevelopment or change-of-use applications.

Planning Data is a beta service and planning-application coverage varies between local planning authorities. A blank result is therefore **not** treated as proof that the property has no planning history or constraints. Always verify material development assumptions on the relevant local planning authority portal.

### Legal-pack intelligence

The legal module follows the public auction lot page and looks for legal-pack, special-condition, addendum, title, lease and EPC links. It does not bypass registration, CAPTCHAs or login walls. Publicly accessible PDFs are parsed locally where possible; inaccessible pack links remain visible for manual opening/download.

The selected-property screen shows:

- legal-pack status: not found / links only / parsed
- number of material legal documents parsed
- detected completion period
- detected deposit percentage
- lease term where stated
- buyer fee where stated
- VAT / option-to-tax warning
- addendum warning
- document-level links and parse status
- legal risk score and individual risk flags

The legal triage looks for wording including title defects, possessory/unregistered title, short leases, overage/clawback, rentcharges, restrictive covenants, buyer-paid seller costs, service-charge arrears, very short completion periods, VAT/TOGC, easements/access rights, mining, contamination, asbestos and occupational/tenancy rights.

If the auctioneer requires registration before the legal pack can be downloaded, use **Upload legal pack PDFs or TXT files** on the deal screen. The app analyses the files locally and stores extracted text in SQLite; it does not retain the original upload as a separate file.

### Acquisition gate

A property may rank highly as a sourcing opportunity before legal documents are available, but the underwriting engine will keep the acquisition decision at **WATCH** until a material legal pack has been parsed. A severe legal-pack issue can independently push the combined risk score to **PASS** even where the financial return and seller motivation look attractive.

This is deliberate: auction legal documents can be incomplete or revised, and the latest pack/addendum must still be checked by a solicitor immediately before bidding.

## Automatic comparable evidence

The tracker now stores a comparable-evidence bundle against each property. Use **Refresh comparable evidence** to update stale evidence without re-scraping every auction catalogue, or use **Refresh this deal's comparables** from the individual underwriting screen. A normal live refresh also processes a priority batch of stale deals, with unsold/no-bid/relisted stock first.

### Residential sold comparables - HM Land Registry

For houses and flats, the app uses the public **HM Land Registry Price Paid Data (PPD)** linked-data endpoint. It:

- finds up to 100 postcodes nearest to the auction lot through Postcodes.io (within the public API's 2 km nearest-postcode radius)
- requests registered **standard residential price-paid transactions** in those postcodes from the last three years
- matches property type, including detached, semi-detached, terraced and flat/maisonette where the auction description supports that distinction
- weights evidence by property-type similarity, distance and recency
- downweights a detected prior sale of the subject property so it does not dominate current local evidence
- removes extreme price outliers when there are enough transactions to do so safely
- stores the comparable low, midpoint, high, count, match score and evidence-confidence percentage

The individual deal screen shows every sale used: address, postcode, sale price, transaction date, type, tenure, distance and match score.

High-confidence residential evidence can automatically seed the desktop **GDV / resale value** when no manual GDV has been saved. The default safety gate requires at least four usable comparables and at least 60% evidence confidence; an automated comparable valuation below 65% confidence cannot trigger a PURSUE recommendation. A manually entered GDV always overrides the automated value.

HM Land Registry PPD has an important limitation: it does **not** provide bedrooms, internal floor area or the condition of each sold property. The automated range is therefore acquisition-screening evidence, not a RICS valuation.

Required attribution used by the app/documentation:

> Contains HM Land Registry data © Crown copyright and database right 2021. This data is licensed under the Open Government Licence v3.0.

HM Land Registry states that Price Paid Data is updated monthly and that the most recent transactions can be incomplete because registration may lag the sale date.

### Commercial sold comparables - tracked auction evidence

Public residential Price Paid Data is not treated as a substitute for commercial valuation evidence. For industrial/commercial/development lots, the app instead builds a growing internal evidence set from **actual sold-result prices captured from Allsop, Savills, BTG Eddisons and Auction House North West**.

Commercial matching uses:

- commercial family/type
- sold-result price
- extracted GIA/floor area where available
- sold GBP/sq ft
- size similarity
- geographic distance
- recency

Where enough size-usable sold auction comparables exist, the app calculates a weighted sold GBP/sq ft benchmark and converts that to a value range for the subject property.

**Commercial automatic valuation is off by default.** Auction results can reflect distress, unusual legal conditions, VAT, leases and other auction-specific circumstances. The evidence is displayed automatically, but you must explicitly tick **Use automatic comparable valuation** before it can seed commercial underwriting. A manual market value, manual market GBP/sq ft or ERV/yield valuation always takes precedence.

### Comparable evidence fields in the dashboard

The main tables now expose:

- comparable low / midpoint / high
- comparable confidence
- comparable count
- guide discount/premium versus comparable midpoint
- whether the current underwriting valuation was seeded automatically

The purpose is to separate **evidence** from **decision**. You can inspect why a desktop valuation exists before relying on the maximum-bid output.

## What the deal engine adds

Each property is ranked from **0 to 10** and also receives a data-confidence score. The dashboard shows the evidence behind the score rather than using a black-box ranking.

### Seller-motivation signals

The score can increase for:

- available post-auction status
- no bids
- last-bid / reserve-gap signals
- relisting after an earlier failed/result state
- repeat failed-auction history
- observed guide-price reductions
- recent post-auction status

### Commercial acquisition profile

Default targets can be changed directly in the dashboard. The initial defaults are:

- target purchase basis: GBP 50/sq ft
- ceiling: GBP 60/sq ft
- preferred size: 9,000+ sq ft
- maximum guide: GBP 1.5m
- preferred motorway distance: within 5 miles
- preference for freehold
- parking and yard/loading signals
- split / multi-let potential
- vacant possession
- development / alternative-use potential

Measured motorway scoring currently gives the strongest weight to properties within about 2 miles, then within your configured preferred distance, with reduced weight out to 10-15 miles.

### Residential flip profile

The default residential acquisition target is GBP 100,000. The engine gives more weight to:

- failed auctions and relists
- guide-price reductions
- sub-target guide price
- vacant possession
- modernisation / refurbishment requirements
- freehold houses
- development / extension potential

### Negotiation opener

For actionable lots, the dashboard can show a heuristic **negotiation opener** derived from guide/result status and repeat failures. This is an acquisition starting point only; it is **not a valuation** or an estimate of market value.

## Dashboard views

- **Best opportunities** - only properties above your chosen hot-score threshold
- **Unsold now** - confirmed post-auction, no-bid and last-bid signals
- **Reductions and relists** - properties where the database has observed price movement or relisting
- **Commercial** - actionable commercial, industrial, development and land lots
- **Residential** - houses, flats and other residential stock
- **All tracked** - full North West database
- **Source health** - latest scraper status for each auction house

The table now includes size source, GBP/sq ft, tenure, nearest motorway, nearest junction, motorway mileage, distance type, negotiation opener and the source link.

The **Deal analysis** section shows the scoring reasons, confidence, exact motorway evidence where available, detail-page enrichment timestamp and complete captured price/status history.

## Strategy and filter controls

Use the scoring-profile selector to choose:

- **Auto by property type**
- **Commercial acquisition**
- **Residential flip**

The acquisition criteria expander lets you change target GBP/sq ft, commercial size, maximum guide, preferred motorway distance, residential target and the hot-score threshold without editing code.

The filter bar also includes **Max motorway miles**. If you set this above zero, properties without measured motorway distance are excluded from that filtered view.

## Data model and caching

The SQLite database stores:

- current property record
- guide/result/status history
- cached detail-page text and enrichment time
- postcode latitude/longitude
- nearest motorway and junction
- straight-line and road mileage where available
- comparable valuation summaries and confidence
- the individual sold comparables used for each deal
- official planning summaries, constraints and nearby planning applications
- legal-pack summaries, risk flags and extracted document text
- persistent underwriting assumptions, including whether auto-comps are allowed for that property
- refresh-source health

If a lot changes through a sequence such as:

`Live -> No Bids -> Relisted -> Guide Reduced -> Available post-auction`

all observed changed states are retained. The deal engine uses that history to strengthen seller-motivation scoring.

## Geography

Primary North West coverage includes Lancashire, Greater Manchester, Merseyside, Cheshire and Cumbria. Filtering uses county/town text plus North West postcode areas. Border postcode areas such as CH/OL/SK use additional town checks to reduce false positives.

Motorway measurements depend on the postcode location rather than the exact building entrance, so even road-routed mileage should be treated as acquisition-screening data rather than a survey-grade measurement.

## Mac / Linux

Run:

```bash
./run_mac_linux.sh
```

## Docker / hosted deployment

```bash
docker build -t nw-auction-tracker .
docker run --rm -p 8501:8501 -v "$(pwd)/data:/data" nw-auction-tracker
```

For a permanently hosted version, deploy the repository to Render, Railway, Azure App Service, AWS, or another Python/Docker host. For durable multi-user history, move the SQLite layer to PostgreSQL/Supabase.

## Tests

From the project folder:

```bash
PYTHONPATH=. pytest -q
```

The v1.6 release currently passes **55 automated tests** covering postcode/money parsing, auction results, North West filtering, floor-area and property-image extraction, detail-page auction dates, postcode geocoding, OpenStreetMap motorway membership/fallbacks, motorway distance logic, residential comparable ranking, commercial auction comparable GBP/sq ft, comparable persistence, exact-property planning matching, legal-link and legal-term/risk extraction, planning/legal database persistence, legal acquisition gating, historical auction backfill, guide reductions, distinct repeat failures, refurbishment safeguards, property-specific auction fees, listed-building flags, shortlist persistence, SDLT calculations, automatic comparable valuation gates, maximum-bid solving, vendor motivation and persistent underwriting assumptions.

## Important operational note

This project uses ordinary public web requests only. It does not log in, register bids, defeat CAPTCHAs or bypass access controls. Auction websites and public mapping services can change their page/API structure or apply rate limits. Each auction source adapter is isolated in `tracker/scrapers.py`; enrichment/geography are isolated in `tracker/enrichment.py` and `tracker/geo.py`; comparable evidence is in `tracker/comparables.py`; and planning/legal due diligence is isolated in `tracker/planning.py`, `tracker/legal.py` and `tracker/diligence.py`.

Auction pages and legal packs remain the authority for tenure, guide price, reserve, condition, title, planning, VAT, buyer fees and sale status. Floor areas are extracted only when published by the auction source. The deal score, legal/planning flags and negotiation opener are triage tools, not property valuations, legal advice or technical due diligence.

HM Land Registry sold-price evidence is registration data, not a condition-adjusted valuation. Commercial tracked-auction evidence is an auction benchmark, not proof of open-market value. Always verify material valuation assumptions before bidding.

## Professional underwriting layer

The dashboard now separates **finding a motivated lot** from **deciding what it is worth paying for**.
Every tracked property receives four distinct acquisition signals:

- **Asset quality score** - size, guide basis, tenure, parking/loading, split potential, motorway access and other property features.
- **Vendor motivation score** - failed auctions, no bids, post-auction availability, repeat failures, guide reductions, relists and disposal/receiver wording.
- **Financial return score** - based only on the valuation and cost assumptions saved against that property.
- **Known listing-risk score** - flags wording such as short leases, title issues, structural/subsidence references, contamination, asbestos, overage, restrictive covenants and VAT/buyer-fee references.

Those feed a transparent **Overall Opportunity Score** and a decision of:

- **PURSUE** - underwriting and motivation justify active engagement, subject to legal/technical checks.
- **WATCH** - promising or incomplete, but more valuation/evidence is required before price commitment.
- **PASS** - sold, materially over the underwritten ceiling, negative spread, or a known risk level that requires specialist review before pursuit.

The engine never manufactures a valuation from the auction guide. A property remains at **WATCH** if it has neither a manual valuation nor sufficiently strong automated comparable evidence. High-confidence residential PPD evidence can seed a desktop GDV; commercial auction evidence requires explicit opt-in before it can seed underwriting.

### Maximum bid calculation

For each selected property, save a working scenario. The app calculates the full cost stack and solves backwards for the maximum purchase price that still meets your configured return hurdle.

Included cost fields are:

- purchase price / working offer
- SDLT
- auction/admin fee
- buyer premium
- legal allowance
- survey / due-diligence allowance
- purchase VAT where the legal pack says VAT is payable
- VAT recoverability
- finance LTV, interest, arrangement fee, exit fee and lender valuation
- refurbishment / fit-out / commercial capex
- works contingency
- monthly holding costs such as empty rates, utilities and insurance allowances
- exit/sale-agent cost
- exit legal cost

For commercial/mixed property, if purchase VAT is entered, SDLT consideration is calculated on the VAT-inclusive consideration. If VAT is marked recoverable, it is excluded from the permanent all-in cost but still affects the SDLT basis.

### Residential flip underwriting

Residential scenarios allow you to enter:

- GDV / resale value
- refurbishment budget
- target profit margin as a percentage of GDV
- working purchase price
- financing and holding assumptions
- sale-agent and exit legal costs
- residential SDLT treatment

The maximum bid is solved backwards so the resulting all-in cost preserves the target profit margin.

The default investor SDLT selection is **Additional dwelling**. The current England/Northern Ireland residential rates from 1 April 2025 are implemented, including the 5 percentage-point higher-rate surcharge for additional dwellings. An explicit corporate 17% mode is available for relevant corporate dwelling transactions above GBP500,000, but the app never selects that special treatment automatically because reliefs/exceptions can apply.

### Commercial acquisition underwriting

Commercial scenarios can use any of these valuation inputs:

- market GBP/sq ft x extracted GIA
- annual ERV capitalised at an exit yield
- a manual market value

If both GBP/sq ft and income-capitalisation values are available, the app uses the **lower** of the two as a conservative working value unless you enter a manual value.

The maximum bid is then solved backwards from your target **equity uplift** after SDLT, fees, VAT treatment, funding, capex, contingency and holding/exit costs.

The dashboard also shows gross yield on all-in cost when ERV is available.

### Persistent property assumptions

Underwriting inputs are stored in SQLite against the property ID. A live-source refresh does not remove them. This lets you add an agent conversation, works estimate, valuation assumption or finance quote once and keep refining the deal while auction status and guide history continue to update.

Use **Clear property underwriting** to remove only the saved scenario; auction/source history remains intact.

## SDLT implementation note

The app implements the current England/Northern Ireland headline purchase rates used for acquisition triage:

**Residential standard:** 0% to GBP125,000; 2% to GBP250,000; 5% to GBP925,000; 10% to GBP1.5m; 12% above. The additional-dwelling mode adds 5 percentage points to each band.

**Non-residential/mixed:** 0% to GBP150,000; 2% on the portion GBP150,001-GBP250,000; 5% above GBP250,000.

Always confirm the actual buyer/entity, VAT position, linked transactions, lease NPV, reliefs and legal-pack consideration with the solicitor/tax adviser before bidding. The dashboard is a deal-screening model, not a tax return calculator.

## v1.8.2 Supabase S3 compatibility

The S3 client now forces SigV4 path-style requests and disables optional flexible-checksum headers unless they are required. This avoids an interoperability problem seen with newer botocore releases and S3-compatible storage providers. The Persistence panel now distinguishes credentials being loaded from a real Supabase connection and from a verified read/write sync.
