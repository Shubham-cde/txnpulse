-- Shared SQL macros. src/db.py runs this file on every new connection, so the
-- pipeline, the EDA and the tests all use one definition.

-- Great-circle distance in km between two (lat, long) points; Earth radius 6,371 km.
CREATE OR REPLACE MACRO haversine_km(lat1, lon1, lat2, lon2) AS
    2 * 6371.0 * ASIN(SQRT(
        POWER(SIN(RADIANS(lat2 - lat1) / 2), 2)
        + COS(RADIANS(lat1)) * COS(RADIANS(lat2)) * POWER(SIN(RADIANS(lon2 - lon1) / 2), 2)
    ));
