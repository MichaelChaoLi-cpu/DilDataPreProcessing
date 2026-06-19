"""Database access layer for the MICS dashboard.

All aggregations happen inside PostgreSQL — Python only receives
the ~100-row summary result, never the raw millions-row table.
"""
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st

from utils import is_safe_identifier

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

TABLE_CONFIG: dict[str, dict[str, str]] = {
    "WM — Women": {
        "data": "final_WM_MICS2MICS6",
        "index": "ind_que_WM_MICSMICS",
    },
    "CH — Children under 5": {
        "data": "final_CH_MICS2MICS6",
        "index": "ind_que_CH_MICSMICS",
    },
    "HH — Household": {
        "data": "final_MICS2MICS6",
        "index": "ind_que_MICSMICS",
    },
    "HL — Household Listing": {
        "data": "final_HL_MICS2MICS6",
        "index": "ind_que_HL_MICSMICS",
    },
}

# Columns that carry no analytic meaning (admin / identifiers)
_ADMIN_COLS = frozenset({
    "dataset_name", "cluster_number", "hh_number", "line_number",
    "child_line_number", "woman_line_number",
    "data_entry_clerk", "interviewer_number", "supervisor_number",
    "hh_interviewer_number", "field_editor", "editor",
    "psu", "stratum", "interview_day", "interview_month",
    "interview_year", "interview_date_cmc", "interview_start_hour",
    "interview_start_minute", "interview_end_hour", "interview_end_minute",
    "interview_result", "child_interview_result", "hh_interview_result",
    "consent",
})

# SQL expression that maps dataset_name → MICS round label
ROUND_CASE = """
CASE
  WHEN dataset_name LIKE '%MICS6%'              THEN 'MICS6'
  WHEN dataset_name LIKE '%MICS5%'              THEN 'MICS5'
  WHEN dataset_name LIKE '%MICS4%'              THEN 'MICS4'
  WHEN dataset_name LIKE '%MICS3%'              THEN 'MICS3'
  WHEN dataset_name LIKE '%MICS2%'              THEN 'MICS2'
  WHEN dataset_name ~ '200[5-7]'                THEN 'MICS3'
  WHEN dataset_name ~ '199[5-9]|200[0-2]'       THEN 'MICS2'
  ELSE 'Unknown'
END
"""


# ── low-level helpers ─────────────────────────────────────────────────────────

def _connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(**DB_PARAMS)


def run_query(sql: str) -> pd.DataFrame:
    """Execute SQL and return a DataFrame without triggering SQLAlchemy warnings."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if cur.description else []
        return pd.DataFrame([dict(r) for r in rows], columns=cols)
    finally:
        conn.close()


def _round_filter_clause(rounds: list[str]) -> str:
    """Return a WHERE sub-clause for MICS round filtering (empty = all rounds)."""
    if not rounds or len(rounds) == 5:
        return ""
    quoted = ", ".join(f"'{r}'" for r in rounds)
    return f"AND ({ROUND_CASE}) IN ({quoted})"


# ── cached queries ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner="Loading variable list…")
def get_variable_list(data_table: str, index_table: str) -> pd.DataFrame:
    """Return DataFrame[column_name, data_type, measure_type, label, display].

    One row per column in the data table, enriched with labels from the
    alignment index. Admin/identifier columns are excluded.
    """
    # Best label per canonical variable (longest non-empty English label wins)
    labels_sql = f"""
    SELECT DISTINCT ON (canonical_varname)
        canonical_varname,
        measure_type,
        column_label_in_english AS label
    FROM "{index_table}"
    WHERE column_label_in_english IS NOT NULL
      AND column_label_in_english <> ''
    ORDER BY canonical_varname,
             LENGTH(column_label_in_english) DESC
    """

    cols_sql = f"""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = '{data_table}'
    ORDER BY ordinal_position
    """

    labels_df = run_query(labels_sql)
    cols_df = run_query(cols_sql)

    merged = cols_df.merge(
        labels_df,
        left_on="column_name",
        right_on="canonical_varname",
        how="left",
    ).drop(columns=["canonical_varname"], errors="ignore")

    merged = merged[~merged["column_name"].isin(_ADMIN_COLS)].copy()
    merged["label"] = merged["label"].fillna("(no label)")
    merged["measure_type"] = merged["measure_type"].fillna("other")

    # Display string used in the selectbox: searchable by category, name, label
    merged["display"] = (
        "[" + merged["measure_type"] + "]  "
        + merged["column_name"] + "  —  "
        + merged["label"]
    )
    return merged.reset_index(drop=True)


_NUM_REGEX = r"'^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$'"

@st.cache_data(ttl=3600, show_spinner="Detecting variable type…")
def detect_var_kind(data_table: str, varname: str) -> str:
    """Return 'binary', 'numeric', or 'categorical'.

    - binary      : ≥90% of valid values are exactly 1 or 2 (yes/no coding).
                    Map shows proportion of "1".
    - numeric     : castable-to-float, more than 3 meaningful distinct values.
                    Map shows mean.
    - categorical : column contains non-numeric strings (e.g. 'A', 'B').
                    Map is not available; histogram shows value frequencies.

    For TEXT columns that contain a mix of numeric strings and letter codes,
    the numeric rows (≥30% of non-null) are used for binary/numeric
    classification — the SQL queries already filter out non-castable rows.
    """
    if not is_safe_identifier(varname):
        return "categorical"

    # Sample distinct values to detect the column's character
    sql_distinct = f"""
    SELECT DISTINCT "{varname}"::TEXT AS val
    FROM "{data_table}"
    WHERE "{varname}" IS NOT NULL
    LIMIT 60
    """
    raw_vals = run_query(sql_distinct)["val"].dropna().tolist()

    # Check whether all sampled values are float-castable
    all_numeric = True
    has_non_integer_float = False
    for v in raw_vals:
        try:
            fv = float(v)
            if "." in str(v) and fv != int(fv):
                has_non_integer_float = True
        except (ValueError, TypeError):
            all_numeric = False

    if not all_numeric:
        # Mixed column: measure the numeric fraction in the actual table
        sql_frac = f"""
        SELECT
            COUNT(*) FILTER (
                WHERE "{varname}"::TEXT ~ {_NUM_REGEX}
            )::FLOAT / NULLIF(COUNT(*), 0) AS numeric_frac
        FROM "{data_table}"
        TABLESAMPLE BERNOULLI(2)
        WHERE "{varname}" IS NOT NULL
        """
        row = run_query(sql_frac).iloc[0]
        numeric_frac = float(row["numeric_frac"] or 0)

        if numeric_frac < 0.30:
            return "categorical"   # too few numeric rows to be useful on a map
        # Otherwise: enough numeric content → fall through to binary/numeric check
        # (SQL queries will filter non-castable rows automatically)
        has_non_integer_float = False   # reset; recalculate below from numeric rows

    # Any true fractional float → continuous numeric (e.g. z-scores)
    if has_non_integer_float:
        return "numeric"

    # Pre-filter to numeric-castable rows in a CTE, then classify.
    # This avoids cast errors when the column contains letter codes ('A', '?', etc.).
    sql_count = f"""
    WITH numeric_rows AS (
        SELECT "{varname}"::TEXT::DOUBLE PRECISION AS val
        FROM "{data_table}" TABLESAMPLE BERNOULLI(2)
        WHERE "{varname}" IS NOT NULL
          AND "{varname}"::TEXT ~ {_NUM_REGEX}
    )
    SELECT
        COUNT(DISTINCT ROUND(val)) FILTER (
            WHERE val NOT IN (7, 8, 9, 97, 98, 99)
        ) AS n_distinct,
        COUNT(*) FILTER (
            WHERE val IN (1, 2)
        ) AS n_binary,
        COUNT(*) FILTER (
            WHERE val NOT IN (7, 8, 9, 97, 98, 99)
        ) AS n_valid
    FROM numeric_rows
    """
    cnt = run_query(sql_count).iloc[0]
    n_distinct = int(cnt["n_distinct"] or 0)
    n_binary   = int(cnt["n_binary"]   or 0)
    n_valid    = int(cnt["n_valid"]    or 1)

    if n_distinct <= 3 and n_valid > 0 and n_binary / n_valid >= 0.90:
        return "binary"
    return "numeric"


@st.cache_data(ttl=3600, show_spinner="Loading value frequencies…")
def get_freq_data(
    data_table: str,
    varname: str,
    rounds: list[str],
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top-N value counts for categorical (non-numeric) variables."""
    if not is_safe_identifier(varname):
        return pd.DataFrame()

    round_clause = _round_filter_clause(rounds)
    sql = f"""
    SELECT
        "{varname}"::TEXT AS val,
        COUNT(*) AS freq
    FROM "{data_table}"
    WHERE "{varname}" IS NOT NULL
      AND "{varname}"::TEXT NOT IN ('', '?', '.', 'NA', 'N/A')
      {round_clause}
    GROUP BY val
    ORDER BY freq DESC
    LIMIT {top_n}
    """
    return run_query(sql)


@st.cache_data(ttl=3600, show_spinner="Aggregating by country…")
def get_map_data(
    data_table: str,
    varname: str,
    rounds: list[str],
    var_kind: str,
) -> pd.DataFrame:
    """Return DataFrame[dataset_name, n_valid, metric] — one row per survey.

    metric is:
      - proportion of value==1  (binary)
      - arithmetic mean         (numeric)
    """
    if not is_safe_identifier(varname) or var_kind == "text":
        return pd.DataFrame()

    round_clause = _round_filter_clause(rounds)

    if var_kind == "binary":
        # Valid rows: value is 1 or 2 (exact integer match, handles '1.0' too)
        value_where = f"""
        "{varname}"::TEXT ~ '^[12](\\.0+)?$'
        """
        agg_expr = f"""
        AVG(CASE WHEN ROUND("{varname}"::TEXT::DOUBLE PRECISION) = 1
                 THEN 1.0 ELSE 0.0 END)
        """
    else:
        # Valid rows: castable to float and not a standard missing code
        value_where = f"""
        "{varname}"::TEXT ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$'
        AND NOT (
              "{varname}"::TEXT::DOUBLE PRECISION
              = FLOOR("{varname}"::TEXT::DOUBLE PRECISION)
              AND "{varname}"::TEXT::DOUBLE PRECISION IN (7, 8, 9, 97, 98, 99)
        )
        """
        agg_expr = f'AVG("{varname}"::TEXT::DOUBLE PRECISION)'

    sql = f"""
    SELECT
        dataset_name,
        COUNT(*)           AS n_valid,
        {agg_expr}         AS metric
    FROM "{data_table}"
    WHERE "{varname}" IS NOT NULL
      AND {value_where}
      {round_clause}
    GROUP BY dataset_name
    ORDER BY dataset_name
    """
    return run_query(sql)


@st.cache_data(ttl=3600, show_spinner="Loading distribution…")
def get_sample_data(
    data_table: str,
    varname: str,
    rounds: list[str],
    var_kind: str,
) -> pd.DataFrame:
    """Return a sample of individual values for the histogram.

    Uses TABLESAMPLE BERNOULLI to avoid a full scan on large tables.
    Binary variables return full counts (cheap GROUP BY).
    """
    if not is_safe_identifier(varname) or var_kind == "text":
        return pd.DataFrame()

    round_clause = _round_filter_clause(rounds)

    if var_kind == "binary":
        sql = f"""
        SELECT
            ROUND("{varname}"::TEXT::DOUBLE PRECISION)::INT AS val,
            COUNT(*) AS freq
        FROM "{data_table}"
        WHERE "{varname}"::TEXT ~ '^[12](\\.0+)?$'
          {round_clause}
        GROUP BY val
        ORDER BY val
        """
    else:
        # 3 % random sample – fast even on 10M-row tables, representative enough
        sql = f"""
        SELECT "{varname}"::TEXT::DOUBLE PRECISION AS val
        FROM "{data_table}" TABLESAMPLE BERNOULLI(3)
        WHERE "{varname}" IS NOT NULL
          AND "{varname}"::TEXT ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$'
          AND NOT (
                "{varname}"::TEXT::DOUBLE PRECISION
                = FLOOR("{varname}"::TEXT::DOUBLE PRECISION)
                AND "{varname}"::TEXT::DOUBLE PRECISION IN (7, 8, 9, 97, 98, 99)
          )
          {round_clause}
        LIMIT 200000
        """
    return run_query(sql)


@st.cache_data(ttl=3600, show_spinner="Loading dataset summary…")
def get_dataset_summary(data_table: str, index_table: str) -> tuple[pd.DataFrame, int]:
    """Return (summary_df, total_rows) for the Card 1 overview table.

    Uses pg_stats system catalog for near-instant approximate counts
    (null_frac × reltuples).  Falls back to a 5 % TABLESAMPLE if the
    catalog has not been populated (no ANALYZE run yet).

    summary_df columns:
        Variable, Category, Description, Valid N, Coverage %, Type
    """
    # ── pg_stats estimates (instant) ────────────────────────────────────────
    stats_sql = f"""
    SELECT
        s.attname                          AS column_name,
        s.null_frac,
        c.reltuples::BIGINT                AS total_est
    FROM pg_stats s
    JOIN pg_class c ON c.relname = s.tablename
    WHERE s.tablename = '{data_table}'
      AND s.schemaname = 'public'
    """
    stats_df = run_query(stats_sql)

    has_stats = (
        not stats_df.empty
        and stats_df["total_est"].iloc[0] > 0
        and stats_df["null_frac"].notna().any()
    )

    if has_stats:
        total = int(stats_df["total_est"].iloc[0])
        stats_df["n_valid"] = (
            (total * (1.0 - stats_df["null_frac"].fillna(0)))
            .clip(lower=0)
            .round()
            .astype(int)
        )
        stats_df["pct_valid"] = (
            (1.0 - stats_df["null_frac"].fillna(0)) * 100
        ).round(1).clip(0, 100)
        counts = stats_df[["column_name", "n_valid", "pct_valid"]]
        approx = True
    else:
        # ── Fallback: 5 % sample scan ────────────────────────────────────────
        cols_list = run_query(f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = '{data_table}'
            ORDER BY ordinal_position
        """)["column_name"].tolist()
        analytic = [c for c in cols_list
                    if c not in _ADMIN_COLS and is_safe_identifier(c)]
        exprs = ",\n".join(f'COUNT("{c}") AS "{c}"' for c in analytic)
        sample_df = run_query(f"""
            SELECT COUNT(*) AS __total__, {exprs}
            FROM "{data_table}" TABLESAMPLE BERNOULLI(5)
        """)
        sample_total = int(sample_df["__total__"].iloc[0])
        total = sample_total * 20          # scale up to 100 %
        records = []
        for col in analytic:
            n_s = int(sample_df[col].iloc[0])
            n_est = n_s * 20
            records.append({
                "column_name": col,
                "n_valid": n_est,
                "pct_valid": round(100 * n_s / sample_total, 1) if sample_total else 0,
            })
        counts = pd.DataFrame(records)
        approx = True                      # still estimates from sample

    # ── Labels from alignment index ──────────────────────────────────────────
    labels_df = run_query(f"""
        SELECT DISTINCT ON (canonical_varname)
            canonical_varname,
            measure_type,
            column_label_in_english AS label
        FROM "{index_table}"
        WHERE column_label_in_english IS NOT NULL
          AND column_label_in_english <> ''
        ORDER BY canonical_varname, LENGTH(column_label_in_english) DESC
    """)

    # ── Data types ───────────────────────────────────────────────────────────
    dtypes_df = run_query(f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = '{data_table}'
    """)

    # ── Merge ────────────────────────────────────────────────────────────────
    df = (
        counts
        .merge(dtypes_df, on="column_name", how="left")
        .merge(
            labels_df,
            left_on="column_name", right_on="canonical_varname",
            how="left",
        )
        .drop(columns=["canonical_varname"], errors="ignore")
    )
    df = df[~df["column_name"].isin(_ADMIN_COLS)].copy()
    df["label"] = df["label"].fillna("—")
    df["measure_type"] = df["measure_type"].fillna("other")

    _TYPE_MAP = {
        "double precision": "float",
        "real": "float",
        "bigint": "integer",
        "integer": "integer",
        "smallint": "integer",
        "text": "text",
    }
    df["type"] = df["data_type"].map(_TYPE_MAP).fillna("other")

    result = df[[
        "column_name", "measure_type", "label",
        "n_valid", "pct_valid", "type",
    ]].rename(columns={
        "column_name":  "Variable",
        "measure_type": "Category",
        "label":        "Description",
        "n_valid":      "Valid N",
        "pct_valid":    "Coverage %",
        "type":         "Type",
    })

    return result, total, approx


@st.cache_data(ttl=3600, show_spinner="Counting rows…")
def get_row_counts(
    data_table: str,
    varname: str,
    rounds: list[str],
    var_kind: str,
) -> dict:
    """Return total rows in the filtered table and valid rows for the variable."""
    if not is_safe_identifier(varname):
        return {"total": 0, "valid": 0}

    round_clause = _round_filter_clause(rounds)

    if var_kind == "binary":
        valid_where = f'"{varname}"::TEXT ~ \'^[12](\\\\.0+)?$\''
    elif var_kind == "numeric":
        valid_where = f"""
        "{varname}"::TEXT ~ '^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$'
        AND NOT (
              "{varname}"::TEXT::DOUBLE PRECISION
              = FLOOR("{varname}"::TEXT::DOUBLE PRECISION)
              AND "{varname}"::TEXT::DOUBLE PRECISION IN (7, 8, 9, 97, 98, 99)
        )
        """
    else:
        valid_where = "FALSE"

    sql = f"""
    SELECT
        COUNT(*)                                          AS total,
        COUNT(*) FILTER (WHERE {valid_where})             AS valid
    FROM "{data_table}"
    WHERE TRUE {round_clause}
    """
    df = run_query(sql)
    return {
        "total": int(df["total"].iloc[0]),
        "valid": int(df["valid"].iloc[0]),
    }
