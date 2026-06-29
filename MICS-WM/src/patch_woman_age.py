"""
P01 — Split woman_age into actual age and age group.
See DATA_PATCH_LOG.md § P01 for full context.

Two independent steps — run separately as needed:

  python patch_woman_age.py parquet   # patch wm_merged.parquet only
  python patch_woman_age.py db        # re-upload final_WM_MICS + fix ind_que
  python patch_woman_age.py all       # both (parquet first, then db)

DB status:   DONE (2026-06-29)
Parquet status: PARTIAL — WAGE-source datasets still NULL pending pipeline fix
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

PARQUET_FILE = DATA_DIR / "WM" / "processed_data" / "wm_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")


# ---------------------------------------------------------------------------
# parquet step
# ---------------------------------------------------------------------------

def patch_parquet() -> None:
    """
    Add woman_age_group; clean woman_age (set 1-7 to NaN).
    Safe to re-run — idempotent on the value ranges.
    Note: WAGE-source datasets remain NULL until pipeline is re-run.
    """
    print(f"Reading {PARQUET_FILE} ...")
    df = pd.read_parquet(PARQUET_FILE)

    wa = df["woman_age"]
    is_group  = wa.between(1, 7)    # WAGE-source
    is_actual = wa.between(15, 49)  # WB2-source

    age_group = pd.Series(np.nan, index=df.index, dtype="float64")
    age_group[is_group]  = wa[is_group]
    age_group[is_actual] = np.minimum(7, np.floor((wa[is_actual] - 15) / 5) + 1)

    df["woman_age_group"] = age_group
    df.loc[is_group, "woman_age"] = np.nan

    print(f"  woman_age_group non-null: {age_group.notna().sum():,}")
    print(f"  woman_age non-null:       {df['woman_age'].notna().sum():,}")
    df.to_parquet(PARQUET_FILE, index=False)
    print("  Parquet saved.")


# ---------------------------------------------------------------------------
# DB step
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    return conn


def _pg_type(dtype) -> str:
    if dtype.kind in ("i", "u"):
        return "BIGINT"
    if dtype.kind == "f":
        return "DOUBLE PRECISION"
    return "TEXT"


def _drop_and_create(cur, table: str, df: pd.DataFrame) -> None:
    cur.execute(f'DROP TABLE IF EXISTS "{table}"')
    cols_ddl = ",\n  ".join(f'"{c}" {_pg_type(df[c].dtype)}' for c in df.columns)
    cur.execute(f'CREATE TABLE "{table}" (\n  {cols_ddl}\n)')


def _copy_upload(conn, cur, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    col_list = ", ".join(f'"{c}"' for c in df.columns)
    cur.copy_expert(
        f"COPY \"{table}\" ({col_list}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
        buf,
    )
    conn.commit()


def patch_db() -> None:
    """
    Re-upload final_WM_MICS from patched parquet, then fix ind_que_WM_MICS.
    Requires patch_parquet() to have been run first.
    """
    print(f"Reading patched parquet ...")
    df = pd.read_parquet(PARQUET_FILE)

    conn = _connect()
    try:
        # -- final_WM_MICS
        print(f"Re-uploading final_WM_MICS ({len(df):,} rows) ...")
        with conn.cursor() as cur:
            _drop_and_create(cur, "final_WM_MICS", df)
            conn.commit()
            _copy_upload(conn, cur, "final_WM_MICS", df)
        print("  final_WM_MICS done.")

        # -- ind_que_WM_MICS
        print("Updating ind_que_WM_MICS ...")
        with conn.cursor() as cur:
            # WAGE-source → woman_age_group
            cur.execute("""
                UPDATE "ind_que_WM_MICS"
                SET canonical_varname = 'woman_age_group',
                    canonical_text    = 'Age group of woman (1=15-19, 2=20-24, 3=25-29, 4=30-34, 5=35-39, 6=40-44, 7=45-49)'
                WHERE canonical_varname = 'woman_age'
                  AND dataset_name IN (
                      SELECT DISTINCT dataset_name FROM "ind_que_WM_MICS"
                      WHERE canonical_varname = 'woman_age'
                        AND column_in_raw_sav IN ('WAGE','wage','agegrp','AGEGRP')
                  )
            """)
            print(f"  Renamed {cur.rowcount} rows to woman_age_group")

            # WB2-source → add derived woman_age_group entry
            cur.execute("""
                INSERT INTO "ind_que_WM_MICS"
                    (canonical_varname, dataset_name, column_in_raw_sav,
                     column_label_in_english, source_kind, measure_type, canonical_text)
                SELECT 'woman_age_group', dataset_name, column_in_raw_sav,
                       column_label_in_english, 'derived', measure_type,
                       'Age group of woman (1=15-19 … 7=45-49), derived from actual age'
                FROM "ind_que_WM_MICS"
                WHERE canonical_varname = 'woman_age'
                  AND dataset_name NOT IN (
                      SELECT DISTINCT dataset_name FROM "ind_que_WM_MICS"
                      WHERE canonical_varname = 'woman_age_group'
                  )
            """)
            print(f"  Inserted {cur.rowcount} derived woman_age_group rows")
            conn.commit()
        print("  ind_que_WM_MICS done.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("parquet", "all"):
        patch_parquet()
    if mode in ("db", "all"):
        patch_db()
    print("Done.")


if __name__ == "__main__":
    main()
