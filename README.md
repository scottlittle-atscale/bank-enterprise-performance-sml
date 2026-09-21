# Bank Enterprise Performance — AtScale SML Model

Unified enterprise-performance semantic model for a US retail + commercial bank:
four lines of business over seven conformed dimensions (constellation / galaxy schema).

## Inputs

| Input | File | Description |
|---|---|---|
| Use case | `context/use_case.md` | Personas, NLQs, engineered stories, grain & semantics table |
| NLQs | (embedded in `use_case.md`) | Per-LOB and cross-LOB questions; not supplied separately |
| DDL | `context/02_ddl.sql` | 11 `CREATE OR REPLACE TABLE` statements, BigQuery Standard SQL |
| ERD | `context/erd.mmd` | Mermaid `erDiagram`; confirms all fact->dim FKs and the two snowflake chains |
| Data profile | `context/data_profile.yaml` | Row counts + per-column `distinct`/`nulls`/sample values; drives `is_unique_key` |
| Curated catalog context | `context/openmetadata_context.json` | **Read live from OpenMetadata** at `http://localhost:8585` — table/column descriptions, 25 glossary terms, governance + additivity tags |
| Original bundle | `context/bank_enterprise_performance_context.zip` | Verbatim archive as handed in |
| Target warehouse | BigQuery | `atscale-sales-demo.BANK_ENTERPRISE_PERFORMANCE` |
| `build.yaml` | (not provided) | Defaults applied; see Assumptions |

## Build parameters

| Parameter | Value | Source |
|---|---|---|
| `unrelated_dimension_handling` | `repeat` | default (Rule 3) — applied to all 21 base metrics |
| `warehouse` | BigQuery | prompt + use case |
| `model_unique_name` | `bank_enterprise_performance` | derived from use-case slug |
| `catalog_unique_name` | `bank_enterprise_performance_catalog` | `<model>_catalog` (Rule 8c) |
| `currency` | USD | `use_case.md` / `data_profile.yaml` |
| `time_window` | 2023-07-01 to 2026-06-30 (36 months) | `use_case.md` |
| `use_cases_covered` | Retail Deposits, Consumer Lending, Commercial Payments, CRE + Middle Market, cross-LOB | all four facts modelled |
| `use_cases_excluded` | (none) | — |
| `semi_additive_default` | `position: last` on true snapshot measures | OpenMetadata `semi-additive` tag |

## Assumptions and decisions

- **Additivity comes from the catalog, not inference.** Every metric's `calculation_method` is
  set from its OpenMetadata `BankGovernance.*` tag — see the mapping table under Generation summary.
- **the DDL's PROJECT / DATASET placeholders resolved to concrete values** (Rule 17). The DDL parameterizes both;
  emitted as `database: atscale-sales-demo`, `schema: BANK_ENTERPRISE_PERFORMANCE` per the use case.
- **`current_balance` is tagged `semi-additive` but emitted WITHOUT a `semi_additive` block.**
  `fact_loan_origination` is a transaction grain (one row per loan booked) whose only date is
  `origination_date`; there is no snapshot date to take a last-non-empty position over. Applying
  `position: last` would collapse the measure to the most recent origination date. Emitted as
  `sum`. **This is the one place the catalog tag was not applied literally** — flagged rather than
  silently resolved.
- **Ratios use `average`, per the glossary.** `Interest Rate` ("average across loans, never sum"),
  `Loan-to-Value` ("Average, never sum") and `Net Interest Margin bps` ("aggregate with average,
  never sum") carry no `semi_additive` block, so `average` is legal under Rule 19.
- **Redundant fact FKs not joined.** `fact_deposit_snapshot.market_id` and
  `fact_loan_origination.market_id` are reachable through `branch_id` via the Geography snowflake;
  `fact_loan_facility_snapshot.lob_id` is reachable through `product_id` via the Product snowflake.
  Joining them again would duplicate the path.
- **Two snowflake chains kept in one dimension each** (Rule 5): `dim_market`+`dim_branch` ->
  Geography Dimension; `dim_line_of_business`+`dim_product` -> Product Dimension.
- **Region is not a single conformed dimension.** `region` exists on `dim_market`, `dim_branch` and
  `dim_customer`. No shared `dim_region` table exists and no fact carries a region key, so a truly
  conformed Region dimension is not expressible without denormalizing region onto each fact. Region
  is exposed on the Geography hierarchy (consumer facts) and as a `Customer Region` secondary
  attribute (commercial facts). Cross-LOB "by region" questions must slice each side by its own
  region attribute.
- **Four degenerate dimensions** (`customer_segment`, `vintage`, `delinquency_status`, `fico_band`)
  declared `is_degenerate: true` with no `type:`, and listed in the model's `dimensions:` block (Rule 12).
- **Calculated columns added:** `prior_year_num` on `dim_date` (required for `ParallelPeriod`, Rule 13);
  `is_delinquent` and `loan_count` on `fact_loan_origination`; `nonperforming_outstanding` on
  `fact_loan_facility_snapshot`.
- **Customer name / key are tagged PII** in the catalog; they remain modelled (`customer_name` as the
  `name_column`) but are flagged here so row-level security or column masking can be applied.

## Generation summary

**Objects:** 11 datasets · 9 dimensions (5 standard/time + 4 degenerate) · 21 base metrics ·
9 calculated metrics · 14 model relationships.

**Role-play prefixes:** `Snapshot {0}` (deposits + facilities), `Origination {0}` (consumer
lending), `Activity {0}` (commercial payments) — all three over the one time dimension.

**Snowflake bridges:** `dim_branch.market_id` -> Market; `dim_product.lob_id` -> Line of Business.

**Additivity mapping applied from the OpenMetadata catalog:**

| Metric | Dataset | Catalog tag | `calculation_method` | `semi_additive` |
|---|---|---|---|---|
| End-of-Month Balance | `fact_deposit_snapshot` | semi-additive | `sum` | yes |
| Average Daily Balance | `fact_deposit_snapshot` | semi-additive | `sum` | yes |
| Account Count | `fact_deposit_snapshot` | semi-additive | `sum` | yes |
| Accounts Opened | `fact_deposit_snapshot` | additive-flow | `sum` | no |
| Accounts Closed | `fact_deposit_snapshot` | additive-flow | `sum` | no |
| Interest Expense | `fact_deposit_snapshot` | additive-flow | `sum` | no |
| Commitment Amount | `fact_loan_facility_snapshot` | semi-additive | `sum` | yes |
| Outstanding Balance | `fact_loan_facility_snapshot` | semi-additive | `sum` | yes |
| Undrawn Amount | `fact_loan_facility_snapshot` | semi-additive | `sum` | yes |
| Interest Income | `fact_loan_facility_snapshot` | additive-flow | `sum` | no |
| Net Interest Margin bps | `fact_loan_facility_snapshot` | ratio | `average` | no |
| Loan Amount Originated | `fact_loan_origination` | additive | `sum` | no |
| Current Loan Balance | `fact_loan_origination` | semi-additive | `sum` | no |
| Interest Rate | `fact_loan_origination` | ratio | `average` | no |
| Loan-to-Value | `fact_loan_origination` | ratio | `average` | no |
| Transaction Count | `fact_payment_transaction` | additive | `sum` | no |
| Payment Volume | `fact_payment_transaction` | additive | `sum` | no |
| Payment Fee Revenue | `fact_payment_transaction` | additive | `sum` | no |
| Loan Count | `fact_loan_origination` | — | `sum` | no |
| Delinquent Loan Count | `fact_loan_origination` | — | `sum` | no |
| Nonperforming Outstanding | `fact_loan_facility_snapshot` | — | `sum` | yes |

**Caveats:** see `current_balance` and Region under Assumptions.

## Reproducing this build

`context/` holds verbatim copies of every input consumed — the original
`bank_enterprise_performance_context.zip`, its extracted files, and
`openmetadata_context.json` (the curated catalog content as read live from OpenMetadata at
build time). Re-running the skill with the same inputs and the build parameters above should
produce an equivalent model. Note that `openmetadata_context.json` is a point-in-time capture:
if the catalog's descriptions, glossary terms or additivity tags change, re-read it before
regenerating, since it drives every `calculation_method`.
