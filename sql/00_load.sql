-- Loads one raw Kaggle card-transactions CSV into a cleaned table.
-- Placeholders filled by src/db.py: {csv_path}, {table_name}
--
-- Every raw column is declared so types never depend on sniffing.
-- cc_num and zip are read as text: they are identifiers, not quantities.
--
-- Data minimisation: the index column, first, last, street, gender, dob and job
-- are read from the file but never selected. They are not needed by any rule or
-- model and must not end up in features, reports or charts.
--
-- unix_time is kept only so the DQ checks can show it disagrees with
-- trans_date_trans_time. ts is the source of truth; do not use unix_time.

CREATE OR REPLACE TABLE {table_name} AS
SELECT
    trans_num,
    trans_date_trans_time AS ts,
    cc_num                AS card_id,
    merchant,
    category,
    amt,
    city,
    state,
    zip,
    lat,
    long,
    city_pop,
    merch_lat,
    merch_long,
    unix_time,
    CAST(is_fraud AS INTEGER) AS is_fraud
FROM read_csv(
    '{csv_path}',
    header = true,
    columns = {
        'row_index': 'BIGINT',
        'trans_date_trans_time': 'TIMESTAMP',
        'cc_num': 'VARCHAR',
        'merchant': 'VARCHAR',
        'category': 'VARCHAR',
        'amt': 'DOUBLE',
        'first': 'VARCHAR',
        'last': 'VARCHAR',
        'gender': 'VARCHAR',
        'street': 'VARCHAR',
        'city': 'VARCHAR',
        'state': 'VARCHAR',
        'zip': 'VARCHAR',
        'lat': 'DOUBLE',
        'long': 'DOUBLE',
        'city_pop': 'BIGINT',
        'job': 'VARCHAR',
        'dob': 'VARCHAR',
        'trans_num': 'VARCHAR',
        'unix_time': 'BIGINT',
        'merch_lat': 'DOUBLE',
        'merch_long': 'DOUBLE',
        'is_fraud': 'INTEGER'
    }
);
