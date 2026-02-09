-- =============================================================================
-- RLC Commodities Database Schema - COMEXSTAT Brazilian Trade Data
-- Version: 1.0.0
-- =============================================================================
--
-- COMEXSTAT (Brazilian Foreign Trade Statistics)
-- Data Source: https://comexstat.mdic.gov.br / https://api-comexstat.mdic.gov.br
--
-- This schema supports the Bronze -> Silver -> Gold medallion architecture
-- for Brazilian agricultural export/import data.
--
-- Key Features:
-- - Monthly trade flows by NCM/HS code
-- - Destination/origin country breakdown
-- - Brazilian state of origin for exports
-- - Historical data from 1997 to present
--
-- =============================================================================

-- =============================================================================
-- DATA SOURCE REGISTRATION
-- =============================================================================

INSERT INTO public.data_source (code, name, description, base_url, auth_type, frequency, is_active)
VALUES (
    'COMEXSTAT',
    'COMEXSTAT - Brazilian Foreign Trade Statistics',
    'Official Brazilian foreign trade statistics from MDIC (Ministry of Development, Industry, Commerce and Services). Monthly export/import data by NCM code, country, and state.',
    'https://api-comexstat.mdic.gov.br',
    'NONE',
    'MONTHLY',
    TRUE
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    is_active = TRUE;

-- =============================================================================
-- BRONZE LAYER - Raw COMEXSTAT Data
-- =============================================================================

-- -----------------------------------------------------------------------------
-- COMEXSTAT Trade Raw: Monthly trade records exactly as received from API
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.comexstat_trade_raw (
    id BIGSERIAL PRIMARY KEY,

    -- Natural key components
    year INT NOT NULL,
    month INT NOT NULL,
    period VARCHAR(7) NOT NULL,              -- 'YYYY-MM' format
    flow VARCHAR(10) NOT NULL,               -- 'export' or 'import'
    ncm_code VARCHAR(10) NOT NULL,           -- 8-digit NCM code
    country_code VARCHAR(10) NOT NULL,       -- Country code (numeric or ISO)
    state_code VARCHAR(5),                   -- Brazilian state (UF) code

    -- Product classification
    commodity VARCHAR(50),                   -- Normalized commodity name
    commodity_description VARCHAR(500),      -- Full product description
    sh6_code VARCHAR(6),                     -- 6-digit HS code
    sh4_code VARCHAR(4),                     -- 4-digit HS code
    chapter VARCHAR(2),                      -- 2-digit HS chapter

    -- Geography
    country_name VARCHAR(200),
    state_name VARCHAR(100),

    -- Values
    value_fob_usd NUMERIC(20, 2),           -- FOB value in USD
    quantity_kg NUMERIC(20, 3),             -- Net weight in kg
    quantity_mt NUMERIC(18, 6),             -- Metric tons (kg / 1000)
    quantity_stat NUMERIC(20, 3),           -- Statistical quantity (product-specific)
    unit VARCHAR(20),                        -- Unit of measure

    -- Derived metrics
    unit_value_usd_mt NUMERIC(12, 2),       -- USD per metric ton

    -- Tracking
    ingest_run_id UUID REFERENCES audit.ingest_run(id),
    collected_at TIMESTAMPTZ DEFAULT NOW(),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Natural key for idempotent upserts
    UNIQUE (year, month, flow, ncm_code, country_code, COALESCE(state_code, 'XX'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_comexstat_period ON bronze.comexstat_trade_raw(year, month);
CREATE INDEX IF NOT EXISTS idx_comexstat_period_str ON bronze.comexstat_trade_raw(period);
CREATE INDEX IF NOT EXISTS idx_comexstat_flow ON bronze.comexstat_trade_raw(flow);
CREATE INDEX IF NOT EXISTS idx_comexstat_commodity ON bronze.comexstat_trade_raw(commodity);
CREATE INDEX IF NOT EXISTS idx_comexstat_ncm ON bronze.comexstat_trade_raw(ncm_code);
CREATE INDEX IF NOT EXISTS idx_comexstat_sh4 ON bronze.comexstat_trade_raw(sh4_code);
CREATE INDEX IF NOT EXISTS idx_comexstat_country ON bronze.comexstat_trade_raw(country_code);
CREATE INDEX IF NOT EXISTS idx_comexstat_country_name ON bronze.comexstat_trade_raw(country_name);
CREATE INDEX IF NOT EXISTS idx_comexstat_state ON bronze.comexstat_trade_raw(state_code);
CREATE INDEX IF NOT EXISTS idx_comexstat_ingest ON bronze.comexstat_trade_raw(ingest_run_id);

COMMENT ON TABLE bronze.comexstat_trade_raw IS 'Raw Brazilian trade data from COMEXSTAT API. One row = one monthly trade flow record.';

-- -----------------------------------------------------------------------------
-- COMEXSTAT Auxiliary Tables: Reference data for code lookups
-- -----------------------------------------------------------------------------

-- NCM Code Reference
CREATE TABLE IF NOT EXISTS bronze.comexstat_ncm_codes (
    ncm_code VARCHAR(10) PRIMARY KEY,
    description_pt VARCHAR(500),             -- Portuguese description
    description_en VARCHAR(500),             -- English description
    unit_code VARCHAR(10),
    unit_description VARCHAR(100),
    sh6_code VARCHAR(6),
    sh4_code VARCHAR(4),
    chapter VARCHAR(2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Country Reference
CREATE TABLE IF NOT EXISTS bronze.comexstat_countries (
    country_code VARCHAR(10) PRIMARY KEY,
    country_name VARCHAR(200),
    country_name_en VARCHAR(200),
    iso_alpha2 VARCHAR(2),
    iso_alpha3 VARCHAR(3),
    continent VARCHAR(50),
    economic_block VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- SILVER LAYER - Standardized Trade Flows
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Brazil Trade Flow: Aggregated, standardized trade data
-- Uses the existing silver.trade_flow table structure
-- -----------------------------------------------------------------------------

-- Add COMEXSTAT as a valid data source for trade_flow
-- (The silver.trade_flow table is defined in 003_silver_layer.sql)

-- Create view for easy querying of Brazil-specific trade data
CREATE OR REPLACE VIEW silver.brazil_trade_flow AS
SELECT
    tf.*,
    c.name AS commodity_full_name,
    l.name AS location_full_name
FROM silver.trade_flow tf
LEFT JOIN public.commodity c ON tf.commodity_code = c.code
LEFT JOIN public.location l ON tf.location_code = l.code
WHERE tf.data_source = 'COMEXSTAT';

COMMENT ON VIEW silver.brazil_trade_flow IS 'Standardized Brazilian trade flows from COMEXSTAT';

-- -----------------------------------------------------------------------------
-- Brazil Trade Monthly: Monthly aggregations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.brazil_trade_monthly (
    id BIGSERIAL PRIMARY KEY,

    -- Dimensions
    year INT NOT NULL,
    month INT NOT NULL,
    period VARCHAR(7) NOT NULL,              -- 'YYYY-MM'
    flow VARCHAR(10) NOT NULL,               -- 'export' or 'import'
    commodity_code VARCHAR(30) NOT NULL,

    -- Aggregated values (all units standardized)
    quantity_mt NUMERIC(18, 3),              -- Total metric tons
    value_usd NUMERIC(20, 2),                -- Total FOB value USD
    avg_price_usd_mt NUMERIC(12, 2),         -- Average unit price

    -- Top destinations/origins
    top_countries JSONB,                     -- Array of {country, mt, usd}

    -- Quality
    record_count INT,                        -- Number of raw records aggregated
    is_complete BOOLEAN DEFAULT TRUE,

    -- Tracking
    ingest_run_id UUID REFERENCES audit.ingest_run(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Natural key
    UNIQUE (year, month, flow, commodity_code)
);

CREATE INDEX IF NOT EXISTS idx_brazil_monthly_period ON silver.brazil_trade_monthly(year, month);
CREATE INDEX IF NOT EXISTS idx_brazil_monthly_commodity ON silver.brazil_trade_monthly(commodity_code);
CREATE INDEX IF NOT EXISTS idx_brazil_monthly_flow ON silver.brazil_trade_monthly(flow);

-- -----------------------------------------------------------------------------
-- Brazil Trade by Country: Country-level aggregations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.brazil_trade_by_country (
    id BIGSERIAL PRIMARY KEY,

    -- Dimensions
    year INT NOT NULL,
    flow VARCHAR(10) NOT NULL,
    commodity_code VARCHAR(30) NOT NULL,
    country_code VARCHAR(10) NOT NULL,
    country_name VARCHAR(200),

    -- Values
    quantity_mt NUMERIC(18, 3),
    value_usd NUMERIC(20, 2),
    avg_price_usd_mt NUMERIC(12, 2),

    -- Market share
    market_share_pct NUMERIC(6, 2),

    -- Tracking
    ingest_run_id UUID REFERENCES audit.ingest_run(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (year, flow, commodity_code, country_code)
);

CREATE INDEX IF NOT EXISTS idx_brazil_country_year ON silver.brazil_trade_by_country(year);
CREATE INDEX IF NOT EXISTS idx_brazil_country_commodity ON silver.brazil_trade_by_country(commodity_code);
CREATE INDEX IF NOT EXISTS idx_brazil_country_country ON silver.brazil_trade_by_country(country_code);

-- -----------------------------------------------------------------------------
-- Brazil Trade by State: State-level aggregations (exports only)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.brazil_trade_by_state (
    id BIGSERIAL PRIMARY KEY,

    -- Dimensions
    year INT NOT NULL,
    flow VARCHAR(10) NOT NULL,
    commodity_code VARCHAR(30) NOT NULL,
    state_code VARCHAR(5) NOT NULL,
    state_name VARCHAR(100),

    -- Values
    quantity_mt NUMERIC(18, 3),
    value_usd NUMERIC(20, 2),
    avg_price_usd_mt NUMERIC(12, 2),

    -- Share of national total
    national_share_pct NUMERIC(6, 2),

    -- Tracking
    ingest_run_id UUID REFERENCES audit.ingest_run(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (year, flow, commodity_code, state_code)
);

CREATE INDEX IF NOT EXISTS idx_brazil_state_year ON silver.brazil_trade_by_state(year);
CREATE INDEX IF NOT EXISTS idx_brazil_state_commodity ON silver.brazil_trade_by_state(commodity_code);
CREATE INDEX IF NOT EXISTS idx_brazil_state_state ON silver.brazil_trade_by_state(state_code);

-- =============================================================================
-- GOLD LAYER - Business-Ready Views & Reports
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Brazil Agricultural Exports Overview: Excel-like summary
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.brazil_ag_exports_summary AS
WITH yearly_totals AS (
    SELECT
        year,
        commodity,
        SUM(quantity_mt) AS total_mt,
        SUM(value_fob_usd) AS total_usd
    FROM bronze.comexstat_trade_raw
    WHERE flow = 'export'
      AND commodity IS NOT NULL
    GROUP BY year, commodity
),
ranked AS (
    SELECT
        year,
        commodity,
        total_mt,
        total_usd,
        ROUND(total_mt / 1000000, 2) AS total_mmt,
        ROUND(total_usd / 1000000000, 2) AS total_billion_usd,
        CASE WHEN total_mt > 0 THEN ROUND(total_usd / total_mt, 2) END AS avg_price_usd_mt,
        ROW_NUMBER() OVER (PARTITION BY year ORDER BY total_usd DESC) AS rank_by_value
    FROM yearly_totals
)
SELECT
    year,
    commodity,
    total_mmt,
    total_billion_usd,
    avg_price_usd_mt,
    rank_by_value
FROM ranked
ORDER BY year DESC, rank_by_value;

COMMENT ON VIEW gold.brazil_ag_exports_summary IS 'Annual summary of Brazilian agricultural exports by commodity';

-- -----------------------------------------------------------------------------
-- Brazil Soybean Complex Exports: Detailed soy exports view
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.brazil_soybean_exports AS
SELECT
    year,
    month,
    period,
    commodity,
    country_name,
    state_name,
    SUM(quantity_mt) AS quantity_mt,
    SUM(quantity_mt) / 1000 AS quantity_tmt,
    SUM(value_fob_usd) AS value_usd,
    SUM(value_fob_usd) / 1000000 AS value_million_usd,
    CASE
        WHEN SUM(quantity_mt) > 0
        THEN ROUND(SUM(value_fob_usd) / SUM(quantity_mt), 2)
    END AS price_usd_mt
FROM bronze.comexstat_trade_raw
WHERE flow = 'export'
  AND commodity IN ('soybeans', 'soybean_meal', 'soybean_oil')
GROUP BY year, month, period, commodity, country_name, state_name
ORDER BY year DESC, month DESC, quantity_mt DESC;

COMMENT ON VIEW gold.brazil_soybean_exports IS 'Brazilian soybean complex exports (beans, meal, oil) by month, country, and state';

-- -----------------------------------------------------------------------------
-- Brazil Trade Top Destinations: Top export destinations by commodity/year
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.brazil_trade_top_destinations AS
WITH country_totals AS (
    SELECT
        year,
        commodity,
        country_name,
        SUM(quantity_mt) AS total_mt,
        SUM(value_fob_usd) AS total_usd,
        ROW_NUMBER() OVER (
            PARTITION BY year, commodity
            ORDER BY SUM(quantity_mt) DESC
        ) AS rank_by_volume
    FROM bronze.comexstat_trade_raw
    WHERE flow = 'export'
      AND commodity IS NOT NULL
      AND country_name IS NOT NULL
    GROUP BY year, commodity, country_name
),
yearly_totals AS (
    SELECT
        year,
        commodity,
        SUM(total_mt) AS year_total_mt
    FROM country_totals
    GROUP BY year, commodity
)
SELECT
    ct.year,
    ct.commodity,
    ct.country_name,
    ct.rank_by_volume,
    ROUND(ct.total_mt / 1000, 1) AS total_tmt,
    ROUND(ct.total_usd / 1000000, 1) AS total_million_usd,
    ROUND(ct.total_mt / yt.year_total_mt * 100, 1) AS market_share_pct,
    CASE
        WHEN ct.total_mt > 0
        THEN ROUND(ct.total_usd / ct.total_mt, 2)
    END AS avg_price_usd_mt
FROM country_totals ct
JOIN yearly_totals yt ON ct.year = yt.year AND ct.commodity = yt.commodity
WHERE ct.rank_by_volume <= 10
ORDER BY ct.year DESC, ct.commodity, ct.rank_by_volume;

COMMENT ON VIEW gold.brazil_trade_top_destinations IS 'Top 10 export destinations by commodity and year';

-- -----------------------------------------------------------------------------
-- Brazil Trade Seasonality: Monthly patterns
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.brazil_trade_seasonality AS
WITH monthly_avg AS (
    SELECT
        month,
        commodity,
        AVG(quantity_mt) AS avg_monthly_mt,
        STDDEV(quantity_mt) AS std_monthly_mt,
        COUNT(DISTINCT year) AS years_of_data
    FROM (
        SELECT
            year,
            month,
            commodity,
            SUM(quantity_mt) AS quantity_mt
        FROM bronze.comexstat_trade_raw
        WHERE flow = 'export'
          AND commodity IS NOT NULL
          AND year >= EXTRACT(YEAR FROM CURRENT_DATE) - 5
        GROUP BY year, month, commodity
    ) monthly
    GROUP BY month, commodity
),
annual_avg AS (
    SELECT
        commodity,
        AVG(avg_monthly_mt) AS annual_avg_mt
    FROM monthly_avg
    GROUP BY commodity
)
SELECT
    m.month,
    m.commodity,
    ROUND(m.avg_monthly_mt / 1000, 1) AS avg_monthly_tmt,
    ROUND(m.avg_monthly_mt / a.annual_avg_mt * 100, 1) AS seasonal_index,
    m.years_of_data
FROM monthly_avg m
JOIN annual_avg a ON m.commodity = a.commodity
ORDER BY m.commodity, m.month;

COMMENT ON VIEW gold.brazil_trade_seasonality IS 'Monthly seasonality patterns for Brazilian agricultural exports';

-- -----------------------------------------------------------------------------
-- Reconciliation View: For verifying data accuracy
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.reconcile_comexstat_totals AS
SELECT
    year,
    month,
    flow,
    commodity,
    COUNT(*) AS record_count,
    COUNT(DISTINCT country_code) AS country_count,
    COUNT(DISTINCT state_code) AS state_count,
    SUM(quantity_mt) AS total_mt,
    SUM(value_fob_usd) AS total_usd,
    MIN(collected_at) AS earliest_collected,
    MAX(collected_at) AS latest_collected
FROM bronze.comexstat_trade_raw
GROUP BY year, month, flow, commodity
ORDER BY year DESC, month DESC, commodity;

COMMENT ON VIEW gold.reconcile_comexstat_totals IS 'Reconciliation view for verifying COMEXSTAT data totals';

-- =============================================================================
-- TRANSFORMATION FUNCTIONS
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Function: Transform bronze to silver monthly aggregates
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION silver.transform_comexstat_monthly(
    p_ingest_run_id UUID
) RETURNS INT AS $$
DECLARE
    v_rows_inserted INT := 0;
BEGIN
    INSERT INTO silver.brazil_trade_monthly (
        year, month, period, flow, commodity_code,
        quantity_mt, value_usd, avg_price_usd_mt,
        top_countries, record_count, ingest_run_id
    )
    SELECT
        year,
        month,
        period,
        flow,
        commodity,
        SUM(quantity_mt),
        SUM(value_fob_usd),
        CASE
            WHEN SUM(quantity_mt) > 0
            THEN ROUND(SUM(value_fob_usd) / SUM(quantity_mt), 2)
        END,
        (
            SELECT jsonb_agg(country_data ORDER BY mt DESC)
            FROM (
                SELECT
                    jsonb_build_object(
                        'country', country_name,
                        'mt', SUM(quantity_mt),
                        'usd', SUM(value_fob_usd)
                    ) AS country_data,
                    SUM(quantity_mt) AS mt
                FROM bronze.comexstat_trade_raw sub
                WHERE sub.year = main.year
                  AND sub.month = main.month
                  AND sub.flow = main.flow
                  AND sub.commodity = main.commodity
                GROUP BY country_name
                ORDER BY SUM(quantity_mt) DESC
                LIMIT 5
            ) top5
        ),
        COUNT(*),
        p_ingest_run_id
    FROM bronze.comexstat_trade_raw main
    WHERE main.ingest_run_id = p_ingest_run_id
      AND main.commodity IS NOT NULL
    GROUP BY year, month, period, flow, commodity
    ON CONFLICT (year, month, flow, commodity_code)
    DO UPDATE SET
        quantity_mt = EXCLUDED.quantity_mt,
        value_usd = EXCLUDED.value_usd,
        avg_price_usd_mt = EXCLUDED.avg_price_usd_mt,
        top_countries = EXCLUDED.top_countries,
        record_count = EXCLUDED.record_count,
        ingest_run_id = EXCLUDED.ingest_run_id,
        updated_at = NOW();

    GET DIAGNOSTICS v_rows_inserted = ROW_COUNT;
    RETURN v_rows_inserted;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- Function: Transform bronze to silver country aggregates
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION silver.transform_comexstat_by_country(
    p_ingest_run_id UUID
) RETURNS INT AS $$
DECLARE
    v_rows_inserted INT := 0;
BEGIN
    WITH country_totals AS (
        SELECT
            year,
            flow,
            commodity,
            country_code,
            country_name,
            SUM(quantity_mt) AS quantity_mt,
            SUM(value_fob_usd) AS value_usd
        FROM bronze.comexstat_trade_raw
        WHERE ingest_run_id = p_ingest_run_id
          AND commodity IS NOT NULL
        GROUP BY year, flow, commodity, country_code, country_name
    ),
    year_totals AS (
        SELECT
            year,
            flow,
            commodity,
            SUM(quantity_mt) AS year_total_mt
        FROM country_totals
        GROUP BY year, flow, commodity
    )
    INSERT INTO silver.brazil_trade_by_country (
        year, flow, commodity_code, country_code, country_name,
        quantity_mt, value_usd, avg_price_usd_mt, market_share_pct,
        ingest_run_id
    )
    SELECT
        ct.year,
        ct.flow,
        ct.commodity,
        ct.country_code,
        ct.country_name,
        ct.quantity_mt,
        ct.value_usd,
        CASE WHEN ct.quantity_mt > 0 THEN ROUND(ct.value_usd / ct.quantity_mt, 2) END,
        CASE WHEN yt.year_total_mt > 0 THEN ROUND(ct.quantity_mt / yt.year_total_mt * 100, 2) END,
        p_ingest_run_id
    FROM country_totals ct
    JOIN year_totals yt ON ct.year = yt.year AND ct.flow = yt.flow AND ct.commodity = yt.commodity
    ON CONFLICT (year, flow, commodity_code, country_code)
    DO UPDATE SET
        country_name = EXCLUDED.country_name,
        quantity_mt = EXCLUDED.quantity_mt,
        value_usd = EXCLUDED.value_usd,
        avg_price_usd_mt = EXCLUDED.avg_price_usd_mt,
        market_share_pct = EXCLUDED.market_share_pct,
        ingest_run_id = EXCLUDED.ingest_run_id,
        updated_at = NOW();

    GET DIAGNOSTICS v_rows_inserted = ROW_COUNT;
    RETURN v_rows_inserted;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- COMMODITY REFERENCE DATA
-- =============================================================================

-- Insert commodity definitions for COMEXSTAT products
INSERT INTO public.commodity (code, name, description, category, unit_code)
VALUES
    ('SOYBEANS', 'Soybeans', 'Soybeans, whether or not broken (NCM 1201)', 'OILSEEDS', 'MT'),
    ('SOYBEAN_MEAL', 'Soybean Meal', 'Soybean oil-cake and meal (NCM 2304)', 'OILSEEDS', 'MT'),
    ('SOYBEAN_OIL', 'Soybean Oil', 'Soybean oil and fractions (NCM 1507)', 'OILSEEDS', 'MT'),
    ('CORN_BR', 'Corn (Brazil)', 'Maize/corn (NCM 1005)', 'GRAINS', 'MT'),
    ('WHEAT_BR', 'Wheat (Brazil)', 'Wheat and meslin (NCM 1001)', 'GRAINS', 'MT'),
    ('COTTON_BR', 'Cotton (Brazil)', 'Cotton, not carded or combed (NCM 5201)', 'FIBER', 'MT'),
    ('SUGAR_RAW', 'Raw Sugar', 'Raw cane sugar (NCM 1701)', 'SUGAR', 'MT'),
    ('SUGAR_REFINED', 'Refined Sugar', 'Refined sugar (NCM 1701)', 'SUGAR', 'MT'),
    ('COFFEE_BR', 'Coffee (Brazil)', 'Coffee, roasted or not (NCM 0901)', 'SOFT_COMMODITIES', 'MT'),
    ('BEEF_FRESH', 'Fresh Beef', 'Fresh or chilled beef (NCM 0201/0202)', 'MEAT', 'MT'),
    ('BEEF_FROZEN', 'Frozen Beef', 'Frozen beef (NCM 0202)', 'MEAT', 'MT'),
    ('CHICKEN_BR', 'Chicken (Brazil)', 'Chicken meat and offal (NCM 0207)', 'MEAT', 'MT'),
    ('PORK_BR', 'Pork (Brazil)', 'Swine meat (NCM 0203)', 'MEAT', 'MT'),
    ('ORANGE_JUICE', 'Orange Juice', 'Orange juice (NCM 2009)', 'BEVERAGES', 'MT'),
    ('ETHANOL_BR', 'Ethanol (Brazil)', 'Ethyl alcohol/ethanol (NCM 2207)', 'BIOFUELS', 'LITERS'),
    ('CELLULOSE_BR', 'Cellulose (Brazil)', 'Chemical wood pulp (NCM 4703)', 'FORESTRY', 'MT')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category;

-- Insert Brazil location
INSERT INTO public.location (code, name, location_type, country_code, continent)
VALUES
    ('BR', 'Brazil', 'COUNTRY', 'BR', 'South America')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name;

-- =============================================================================
-- END OF COMEXSTAT SCHEMA
-- =============================================================================
