# North West Property Auction Deal Finder

A live-pull auction dashboard, acquisition triage engine and due-diligence workspace for public property-auction listings from:

- Allsop
- Savills Property Auctions
- BTG Eddisons Property Auctions
- Auction House North West

It is designed for **on-demand refresh**, not scheduled alerts. Press **Refresh live data** and the backend fetches the current public auction pages, filters to North West England, stores them in SQLite, follows public lot-detail pages when enrichment is due, geocodes the property postcode, measures motorway access, records price/status/date changes, refreshes priority comparable evidence, screens official planning data, discovers public legal-pack material, and recalculates a transparent deal score and underwriting decision.

## Windows quick start

1. Install Python 3.11+ from python.org if Python is not already installed.
2. Extract this folder.
3. Double-click `run_windows.bat`.
4. Your browser opens the dashboard, normally at `http://localhost:8501`.
5. Click **Refresh live data**.

The first run installs the Python dependencies. The SQLite database `auction_tracker.db` is created automatically in this folder.

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

Version 1.5 adds a dedicated due-diligence layer. Use **Refresh planning + legal** to process a priority batch, or refresh either layer from the selected-property screen.

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

The automated tests cover postcode/money parsing, auction results, North West filtering, floor-area extraction, detail-page text extraction, postcode geocoding parsing, OpenStreetMap motorway membership, motorway distance logic, residential comparable parsing/ranking, commercial auction comparable GBP/sq ft, comparable persistence, planning constraint/application analysis, legal-link discovery, legal-term/risk extraction, planning/legal database persistence, legal acquisition gating, price reductions, repeat failures, deal scoring, SDLT calculations, automatic comparable valuation gates, maximum-bid solving, vendor motivation and persistent underwriting assumptions.

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
