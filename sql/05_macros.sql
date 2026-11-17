-- Shared SQL macros. src/db.py runs this file on every new connection, so the
-- pipeline, the EDA and the tests all use one definition.

-- Great-circle distance in km between two (lat, long) points; Earth radius 6,371 km.
CREATE OR REPLACE MACRO haversine_km(lat1, lon1, lat2, lon2) AS
    2 * 6371.0 * ASIN(SQRT(
        POWER(SIN(RADIANS(lat2 - lat1) / 2), 2)
        + COS(RADIANS(lat1)) * COS(RADIANS(lat2)) * POWER(SIN(RADIANS(lon2 - lon1) / 2), 2)
    ));

-- Bands are closed on the left: [lower, upper).
CREATE OR REPLACE MACRO amount_band(a) AS
    CASE
        WHEN a < 10   THEN '01: <10'
        WHEN a < 50   THEN '02: 10-50'
        WHEN a < 100  THEN '03: 50-100'
        WHEN a < 200  THEN '04: 100-200'
        WHEN a < 300  THEN '05: 200-300'
        WHEN a < 500  THEN '06: 300-500'
        WHEN a < 750  THEN '07: 500-750'
        WHEN a < 1000 THEN '08: 750-1000'
        WHEN a < 1500 THEN '09: 1000-1500'
        ELSE               '10: 1500+'
    END;
