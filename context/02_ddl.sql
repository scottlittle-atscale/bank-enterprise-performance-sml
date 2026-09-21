-- 02_ddl.sql — bank_enterprise_performance schema (BigQuery Standard SQL)
-- 7 conformed dimensions + 4 fact tables (constellation / galaxy schema).
--
-- BigQuery notes vs Snowflake:
--   * Types: NUMBER->INT64, VARCHAR->STRING, NUMBER(p,2) money->NUMERIC,
--     ratios/rates/bps->FLOAT64, BOOLEAN->BOOL, DATE->DATE.
--   * PRIMARY KEY is declared NOT ENFORCED (documentation only).
--   * FOREIGN KEYs are intentionally NOT declared: BigQuery rejects any project
--     qualifier in a FK REFERENCES target ("cannot reference a table in a
--     different project"), and AtScale defines joins in the semantic model rather
--     than reading BigQuery FK metadata. The intended FKs are kept as comments
--     below each fact and are fully captured in erd.mmd / use_case.md.
--   * Facts are partitioned on their date column and clustered on hot join keys.
--   * CREATE OR REPLACE makes this idempotent.
-- ${PROJECT} / ${DATASET} are substituted by load.sh.

-- ============================================================
-- Conformed dimensions
-- ============================================================
CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_date` (
  date_id       DATE   NOT NULL,
  day_of_week   INT64,
  day_name      STRING,
  day_of_month  INT64,
  month_num     INT64,
  month_name    STRING,
  year_month    STRING,
  quarter_num   INT64,
  quarter_name  STRING,
  year_num      INT64,
  is_weekend    BOOL,
  is_month_end  BOOL,
  PRIMARY KEY (date_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_line_of_business` (
  lob_id   INT64  NOT NULL,
  lob_name STRING,               -- Retail Deposits, Consumer Lending, Commercial Payments, ...
  segment  STRING,               -- Consumer Bank | Commercial Bank
  PRIMARY KEY (lob_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_market` (
  market_id   INT64  NOT NULL,
  market_name STRING,            -- metro
  state       STRING,            -- 15-state footprint
  region      STRING,            -- Great Lakes | Northeast | Pacific | Rocky Mountains
  PRIMARY KEY (market_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_branch` (
  branch_id   INT64  NOT NULL,
  branch_name STRING,
  branch_type STRING,            -- Financial Center | In-Store | Private Bank Office
  market_id   INT64,
  state       STRING,
  region      STRING,
  PRIMARY KEY (branch_id) NOT ENFORCED
  -- FK (intended): market_id -> dim_market(market_id)
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_product` (
  product_id       INT64  NOT NULL,
  product_name     STRING,
  product_category STRING,       -- Checking, Mortgage, Home Equity, Card, CRE, C&I, ...
  line_of_business STRING,
  lob_id           INT64,
  PRIMARY KEY (product_id) NOT ENFORCED
  -- FK (intended): lob_id -> dim_line_of_business(lob_id)
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_risk_rating` (
  risk_rating_id   INT64  NOT NULL,
  rating_grade     STRING,       -- 1-3 Strong ... 9 Doubtful
  regulatory_class STRING,       -- Pass | Criticized | Classified
  is_nonperforming BOOL,
  PRIMARY KEY (risk_rating_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.dim_customer` (
  customer_id       INT64  NOT NULL,
  customer_key      STRING,
  customer_name     STRING,
  customer_type     STRING,      -- Consumer | Commercial
  segment           STRING,      -- Mass Market/Mass Affluent/Private-HNW/Small Business | Middle Market/Corporate/Institutional
  industry_vertical STRING,      -- Healthcare, Technology, Real Estate, ... (commercial); 'N/A' for consumer
  revenue_band      STRING,      -- commercial revenue band; 'N/A' for consumer
  region            STRING,
  state             STRING,
  acquisition_date  DATE,
  PRIMARY KEY (customer_id) NOT ENFORCED
);

-- ============================================================
-- Fact tables
-- ============================================================

-- Retail Deposits — MONTHLY SNAPSHOT. eom_balance / avg_daily_balance /
-- account_count are SEMI-ADDITIVE (read as-of a snapshot, not summed over months);
-- accounts_opened/closed and interest_expense_mtd are additive period flows.
CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.fact_deposit_snapshot` (
  deposit_snapshot_id  INT64  NOT NULL,
  snapshot_date        DATE,
  branch_id            INT64,
  market_id            INT64,
  product_id           INT64,
  customer_segment     STRING,   -- degenerate: Mass Market | Mass Affluent | Private / HNW | Small Business
  eom_balance          NUMERIC,  -- semi-additive
  avg_daily_balance    NUMERIC,  -- semi-additive
  account_count        INT64,    -- semi-additive
  accounts_opened      INT64,    -- additive flow
  accounts_closed      INT64,    -- additive flow (attrition)
  interest_expense_mtd NUMERIC,  -- additive flow
  PRIMARY KEY (deposit_snapshot_id) NOT ENFORCED
  -- FK (intended): branch_id -> dim_branch, market_id -> dim_market, product_id -> dim_product
)
PARTITION BY snapshot_date
CLUSTER BY branch_id, product_id;

-- Consumer Lending — TRANSACTION grain, one row per loan booked. delinquency_status
-- and current_balance are as-of the current month (2026-06).
CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.fact_loan_origination` (
  loan_id            INT64  NOT NULL,
  origination_date   DATE,
  customer_id        INT64,
  branch_id          INT64,
  market_id          INT64,
  product_id         INT64,
  loan_amount        NUMERIC,   -- additive (originated principal)
  current_balance    NUMERIC,   -- as-of-now outstanding
  interest_rate_pct  FLOAT64,
  term_months        INT64,
  fico_band          STRING,
  ltv                FLOAT64,
  vintage            STRING,    -- YYYY-MM of origination
  delinquency_status STRING,    -- Current | 30 DPD | 60 DPD | 90+ DPD
  days_past_due      INT64,
  PRIMARY KEY (loan_id) NOT ENFORCED
  -- FK (intended): customer_id -> dim_customer, branch_id -> dim_branch,
  --                market_id -> dim_market, product_id -> dim_product
)
PARTITION BY origination_date
CLUSTER BY product_id, customer_id;

-- Commercial Payments — MONTHLY aggregate at client x product. All measures are
-- additive period flows.
CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.fact_payment_transaction` (
  payment_id         INT64  NOT NULL,
  activity_month     DATE,           -- 1st of the activity month
  customer_id        INT64,
  product_id         INT64,
  transaction_count  INT64,          -- additive
  payment_volume_usd NUMERIC,        -- additive
  fee_revenue_usd    NUMERIC,        -- additive
  PRIMARY KEY (payment_id) NOT ENFORCED
  -- FK (intended): customer_id -> dim_customer, product_id -> dim_product
)
PARTITION BY activity_month
CLUSTER BY customer_id, product_id;

-- CRE + Middle Market — MONTHLY SNAPSHOT per facility. commitment/outstanding/undrawn
-- are SEMI-ADDITIVE balances; interest_income_mtd is an additive flow; nim_bps is a
-- FLOAT64 ratio (do not sum). Facilities persist to the window end.
CREATE OR REPLACE TABLE `${PROJECT}.${DATASET}.fact_loan_facility_snapshot` (
  facility_snapshot_id INT64  NOT NULL,
  snapshot_date        DATE,
  facility_id          INT64,          -- degenerate facility key
  customer_id          INT64,
  product_id           INT64,
  lob_id               INT64,          -- Commercial Real Estate | Middle Market Lending
  risk_rating_id       INT64,
  commitment_amount    NUMERIC,        -- semi-additive
  outstanding_balance  NUMERIC,        -- semi-additive
  undrawn_amount       NUMERIC,        -- semi-additive
  interest_income_mtd  NUMERIC,        -- additive flow
  nim_bps              FLOAT64,        -- ratio (bps) — do not sum
  is_nonperforming     BOOL,
  PRIMARY KEY (facility_snapshot_id) NOT ENFORCED
  -- FK (intended): customer_id -> dim_customer, product_id -> dim_product,
  --                lob_id -> dim_line_of_business, risk_rating_id -> dim_risk_rating
)
PARTITION BY snapshot_date
CLUSTER BY customer_id, product_id;
