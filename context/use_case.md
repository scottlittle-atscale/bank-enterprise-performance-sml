# Bank Enterprise Performance — Use Case

**Slug:** `bank_enterprise_performance`
**Vertical:** US retail + commercial banking (regional-bank profile)
**Target platform:** Google BigQuery — `atscale-sales-demo.BANK_ENTERPRISE_PERFORMANCE`
**Currency:** USD (single currency, no FX)
**Window:** 2023-07-01 → 2026-06-30 (36 months); monthly snapshots through 2026-06-01
**Data strategy:** Tier 3 — bespoke synthetic, fully fictional and brand-neutral (reusable across accounts)

> This is a **generic, reusable** banking dataset — no customer or prospect name appears
> in the slug, dataset, schema, table/column names, or any data value. It is currently
> being used for a regional-bank demo but is intended to be reused for any bank engagement.

## Scenario

A single **unified enterprise-performance model** for a US regional + commercial bank —
a constellation (galaxy) schema in which four lines of business share one set of
conformed dimensions, so an executive or line-of-business leader can ask questions of
any one area *and* roll the whole bank up along the same axes (region, product, line of
business, customer). This is the semantic-layer story: four historically siloed subject
areas, one governed model, one set of definitions.

The four lines of business (four fact tables):

- **Retail Deposits** (Consumer Bank) — branch-level deposit balances, product mix,
  account growth, and attrition, as a monthly snapshot.
- **Consumer Lending** (Consumer Bank) — mortgage, home-equity (HELOC + loan),
  indirect auto and marine originations with as-of delinquency by vintage.
- **Commercial Payments** (Commercial Bank) — treasury-management fee revenue,
  volume, and product adoption by commercial client and industry vertical.
- **CRE + Middle Market Lending** (Commercial Bank) — commercial-real-estate and
  C&I facility commitments, outstandings, credit-quality (risk rating), and NIM,
  as a monthly snapshot.

The conformed dimensions — `dim_date`, `dim_line_of_business`, `dim_market`,
`dim_branch`, `dim_product`, `dim_customer`, `dim_risk_rating` — are what make the
cross-LOB questions answerable from one model.

## What the data is shaped to answer (the brief NLQs + engineered stories)

### Retail Deposits
- *"Show total deposit balances by region and product for the last 12 months."*
  → `fact_deposit_snapshot`; `eom_balance` is **semi-additive** (read as-of a snapshot).
- *"Which branches grew deposits fastest quarter-over-quarter?"*
  → **Story A3:** a set of **breakout branches** in the Denver CO and Boise ID markets
  grow deposits ~3.4× the region rate (≈191% over the window).
- *"What is our deposit mix by customer segment?"*
  → `customer_segment` degenerate dimension (Mass Market / Mass Affluent / Private-HNW /
  Small Business); Private-HNW carries outsized per-account balances.
- *"Where is deposit attrition highest?"*
  → **Story A2:** a deliberate **attrition spike** — Pacific region, Mass Market segment —
  from March 2026, with elevated `accounts_closed` and balance runoff.
- **Story A1** underpins all of the above: **Rocky Mountains grows deposits fastest**
  (~99% over the window vs. 7–15% elsewhere).

### Consumer Lending
- *"What were HELOC originations by state, this quarter vs last?"*
  → **Story B1:** a **HELOC origination surge in OH, NY, PA** over the final two quarters.
- *"Show 30/60/90-day delinquency rates by loan vintage."*
  → **Story B2:** the **2024-H1 vintage runs ~2.6× the delinquency** of other vintages
  (~15% vs ~6% any-DPD).
- *"Compare average loan size and rate across mortgage vs HELOC."*
  → 30-yr mortgage ≈ $316K @ 6.4%, HELOC ≈ $88K @ 8.6%, home-equity loan ≈ $52K @ 7.9%.
- *"Which markets have the highest indirect auto loan volume?"*
  → **Story B4:** auto concentrates in **Cleveland OH, Detroit MI, Columbus OH, Buffalo NY**;
  **Story B3:** indirect auto also carries the **highest delinquency** of any product (~11%).

### Commercial Payments
- *"Show commercial payments fee revenue by product and industry vertical, YTD."*
  → **Story C1:** **Healthcare and Technology verticals over-index** on fee revenue.
- *"Which treasury / payment products are growing fastest year-over-year?"*
  → **Story C2:** **Real-Time Payments (~2×) and Commercial Card (~1.7×)** grow fastest.
- *"What is payments revenue growth year-over-year?"*
  → **Story C3:** ~15% blended fee growth first-12mo → last-12mo (a double-digit
  commercial-payments growth narrative).
- *"Who are our top fee-income commercial clients this quarter?"*
  → **Story C4:** a dozen **marquee clients** drive outsized fee income.

### CRE + Middle Market
- *"Show loan commitments and outstandings by sector and region."*
  → `fact_loan_facility_snapshot`; `commitment_amount` / `outstanding_balance` are
  **semi-additive**.
- *"What is the credit-quality (risk-rating) mix of the portfolio?"*
  → **Story D2:** ~84% Pass / ~10% Criticized / ~6% Classified of current outstandings.
- *"Which sectors have rising non-performing balances?"*
  → **Story D1:** **Real Estate CRE non-performing balances rise sharply** over the final
  six months (migration into Substandard), reaching ~21% of the Real-Estate CRE book.
- *"Show net interest margin (NIM) by loan type over the last 8 quarters."*
  → `nim_bps` is a **ratio** (average, never sum); CRE Bridge highest, CRE Term lowest.

### Cross-line-of-business (the unified-model payoff)
- *"Show total balances across Consumer and Commercial by region."*
  → union of consumer deposits + commercial outstandings via conformed `region`.
- *"Which regions over-index on commercial vs consumer?"*
  → Rocky Mountains skews consumer (~27% commercial share) on the back of its deposit
  surge; Pacific / Great Lakes / Northeast run ~40% commercial.

## Grain & semantics

| Table | Grain | Notes |
|---|---|---|
| `dim_date` | one row per calendar day | `is_month_end` flags snapshot dates; `quarter_name` = "Qn YYYY" |
| `dim_line_of_business` | line of business | segment: Consumer Bank / Commercial Bank |
| `dim_market` | metro market | region → state → market (15-state footprint) |
| `dim_branch` | branch | ~1,000 branches; branch_type; belongs to a market |
| `dim_product` | product | product_category + line_of_business across all four LOBs |
| `dim_risk_rating` | regulatory rating | Pass / Criticized / Classified; `is_nonperforming` |
| `dim_customer` | account / client | customer_type Consumer vs Commercial; segment, industry_vertical, region |
| `fact_deposit_snapshot` | branch × deposit-category × segment × month | **semi-additive** balances; additive open/close/interest flows |
| `fact_loan_origination` | one row per consumer loan booked | as-of delinquency + current balance; `vintage` |
| `fact_payment_transaction` | commercial client × payments product × month | additive txn/volume/fee flows |
| `fact_loan_facility_snapshot` | CRE/C&I facility × month | **semi-additive** commitment/outstanding; additive interest flow; `nim_bps` ratio |

## Aggregate shape (seed 42)

- **Deposits:** ~$117.5B current balance across ~15.2M accounts (409,788 snapshot rows)
- **Consumer lending:** 200,000 originations, ~$27.0B originated, ~$25.8B current balance
- **Commercial payments:** ~$1.87B fee revenue, ~$5.69T volume, 5,963 active clients (538,223 rows)
- **CRE + Middle Market:** ~$91.4B commitments, ~$69.4B outstanding, 8,000 facilities (244,072 rows)
- 58,000 customers (50,000 consumer + 8,000 commercial); 1,000 branches; 30 markets; 24 products

## Known limitations

- Single currency (USD); no FX, no tax.
- Deposits and CRE/MM are **monthly snapshots**, not continuous ledgers; balances are
  semi-additive (tagged in `data_profile.yaml`) — the model must mark them so they are
  read as-of a snapshot date and never summed across snapshots.
- Consumer-loan `delinquency_status` and `current_balance` are a single as-of-current-month
  state per loan, not a monthly delinquency roll-forward.
- Commercial payments are aggregated monthly at client × product (no individual transactions).
- Figures are illustrative demo scale, internally consistent but brand-neutral and not tied
  to any specific bank's reported balances.
- `PRIMARY KEY`s are declared `NOT ENFORCED`; foreign keys are kept as comments
  (BigQuery rejects project-qualified FK references) — joins live in the AtScale semantic model.
