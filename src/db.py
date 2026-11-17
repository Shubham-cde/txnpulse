"""Shared DuckDB helpers: connection, CSV loading and running SQL files."""

import re
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "outputs"

CSV_BY_PERIOD = {
    "train": DATA_DIR / "fraudTrain.csv",
    "test": DATA_DIR / "fraudTest.csv",
}

# A query in a SQL file starts with a line like "-- name: fraud_by_hour".
QUERY_NAME_PATTERN = re.compile(r"^-- name: (\w+)\s*$", re.MULTILINE)


def connect(database=":memory:"):
    con = duckdb.connect(database)
    # Timestamps in the data are naive local times; pinning UTC stops DuckDB
    # from shifting epoch conversions into the machine's own time zone.
    con.execute("SET TimeZone = 'UTC'")
    return con


def load_csv(con, csv_path, table_name):
    template = (SQL_DIR / "00_load.sql").read_text(encoding="utf-8")
    # Plain replacement, not str.format: the SQL contains a {...} struct literal.
    sql = template.replace("{csv_path}", Path(csv_path).as_posix()).replace("{table_name}", table_name)
    con.execute(sql)


def load_period(con, period):
    """Create table `txn` for a period.

    train: all training rows, all scored.
    test:  training rows as unscored history plus test rows as scored, so
           per-card window features have history at the start of the test
           period. Metrics must count only rows where is_scored is true.
    """
    if period not in CSV_BY_PERIOD:
        raise ValueError(f"unknown period: {period}")

    load_csv(con, CSV_BY_PERIOD["train"], "raw_train")
    if period == "train":
        con.execute("CREATE OR REPLACE TABLE txn AS SELECT *, TRUE AS is_scored FROM raw_train")
        return

    load_csv(con, CSV_BY_PERIOD["test"], "raw_test")
    con.execute(
        """
        CREATE OR REPLACE TABLE txn AS
        SELECT *, FALSE AS is_scored FROM raw_train
        UNION ALL
        SELECT *, TRUE AS is_scored FROM raw_test
        """
    )


def split_named_queries(sql_text):
    """Return (preamble, [(name, query), ...]) for a SQL file using -- name: markers."""
    parts = QUERY_NAME_PATTERN.split(sql_text)
    preamble = parts[0]
    named = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return preamble, named


def has_statements(sql_text):
    code_lines = [
        line for line in sql_text.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return bool(code_lines)


def run_sql_file(con, sql_path):
    """Run a SQL file of statements with no result sets (e.g. CREATE TABLE)."""
    con.execute(Path(sql_path).read_text(encoding="utf-8"))


def query_to_df(con, query):
    rel = con.sql(query)
    df = rel.df()
    # SUM over integers returns HUGEINT, which pandas turns into float; keep counts as integers.
    for column, column_type in zip(rel.columns, rel.types):
        if str(column_type) == "HUGEINT":
            df[column] = df[column].astype("Int64")
    return df


def run_named_queries(con, sql_path, out_dir):
    """Run the preamble, then each named query, saving each result to out_dir/<name>.csv."""
    preamble, named = split_named_queries(Path(sql_path).read_text(encoding="utf-8"))
    if has_statements(preamble):
        con.execute(preamble)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, query in named:
        df = query_to_df(con, query.rstrip().rstrip(";"))
        df.to_csv(out_dir / f"{name}.csv", index=False)
        results[name] = df
    return results
