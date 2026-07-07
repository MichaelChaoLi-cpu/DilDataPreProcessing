"""
P07 — Split child_age_months into child_age_months (true months) + child_age_years (all datasets).

Problem:
  209 datasets recorded child age in YEARS (0-4) but merged into child_age_months.
  This makes the variable incomparable across datasets.

Fix:
  - Add child_age_years (0-4, available for ALL datasets):
      * year-coded datasets (max <= 4): use current child_age_months value directly
      * month-coded datasets (max >  4): FLOOR(child_age_months / 12)
  - child_age_months: keep 0-59 values for month-coded datasets; NULL for year-coded.
  - Both: set to NULL for rows with value < 0 or > 59 (data errors, 4,050 rows).

Detection rule: datasets where MAX(child_age_months) <= 4 are year-coded (209 datasets).

Usage:
  python patch_child_age.py db
  python patch_child_age.py parquet
  python patch_child_age.py all
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

PARQUET_FILE = DATA_DIR / "CH" / "processed_data" / "ch_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Identify year-coded datasets
# ---------------------------------------------------------------------------

def get_year_coded_datasets(cur) -> set[str]:
    cur.execute("""
        SELECT dataset_name
        FROM "final_CH_MICS"
        WHERE child_age_months IS NOT NULL
        GROUP BY dataset_name
        HAVING MAX(child_age_months) <= 4
    """)
    return {r[0] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# DB step
# ---------------------------------------------------------------------------

def patch_db() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            year_coded = get_year_coded_datasets(cur)
            print(f"Year-coded datasets: {len(year_coded)}")

            # 1. Add child_age_years if absent
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'final_CH_MICS'
                  AND column_name = 'child_age_years'
            """)
            if cur.fetchone() is None:
                print("Adding column child_age_years ...")
                cur.execute(
                    'ALTER TABLE "final_CH_MICS" '
                    'ADD COLUMN child_age_years DOUBLE PRECISION'
                )
                conn.commit()
            else:
                print("Column child_age_years already exists, will overwrite.")

            # 2. Populate child_age_years for YEAR-CODED datasets
            #    child_age_years = child_age_months (the year value 0-4)
            print("Populating child_age_years for year-coded datasets ...")
            cur.execute("""
                UPDATE "final_CH_MICS"
                SET child_age_years = child_age_months
                WHERE dataset_name = ANY(%s)
                  AND child_age_months IS NOT NULL
                  AND child_age_months BETWEEN 0 AND 4
            """, (list(year_coded),))
            n_year = cur.rowcount
            conn.commit()
            print(f"  Year-coded rows set: {n_year:,}")

            # 3. Populate child_age_years for MONTH-CODED datasets
            #    child_age_years = FLOOR(child_age_months / 12), only for valid months 0-59
            print("Populating child_age_years for month-coded datasets ...")
            cur.execute("""
                UPDATE "final_CH_MICS"
                SET child_age_years = FLOOR(child_age_months / 12)
                WHERE dataset_name != ALL(%s)
                  AND child_age_months IS NOT NULL
                  AND child_age_months BETWEEN 0 AND 59
            """, (list(year_coded),))
            n_month = cur.rowcount
            conn.commit()
            print(f"  Month-coded rows set: {n_month:,}")

            # 4. NULL out child_age_months for year-coded datasets
            print("Nulling child_age_months for year-coded datasets ...")
            cur.execute("""
                UPDATE "final_CH_MICS"
                SET child_age_months = NULL
                WHERE dataset_name = ANY(%s)
                  AND child_age_months IS NOT NULL
            """, (list(year_coded),))
            n_nulled = cur.rowcount
            conn.commit()
            print(f"  Rows nulled: {n_nulled:,}")

            # 5. NULL out remaining out-of-range child_age_months (errors in month-coded)
            print("Nulling out-of-range child_age_months (< 0 or > 59) ...")
            cur.execute("""
                UPDATE "final_CH_MICS"
                SET child_age_months = NULL
                WHERE child_age_months IS NOT NULL
                  AND (child_age_months < 0 OR child_age_months > 59)
            """)
            n_oob = cur.rowcount
            conn.commit()
            print(f"  Out-of-range rows nulled: {n_oob:,}")

            # 6. Verify
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE child_age_years IS NOT NULL)  AS years_nonnull,
                    COUNT(*) FILTER (WHERE child_age_months IS NOT NULL) AS months_nonnull,
                    MIN(child_age_years)  AS min_years,
                    MAX(child_age_years)  AS max_years,
                    MIN(child_age_months) AS min_months,
                    MAX(child_age_months) AS max_months
                FROM "final_CH_MICS"
            """)
            r = cur.fetchone()
            print(f"\n  child_age_years  non-null: {r[0]:,}  range: {r[2]} – {r[3]}")
            print(f"  child_age_months non-null: {r[1]:,}  range: {r[4]} – {r[5]}")

            cur.execute("""
                SELECT child_age_years, COUNT(*) AS n
                FROM "final_CH_MICS"
                WHERE child_age_years IS NOT NULL
                GROUP BY child_age_years
                ORDER BY child_age_years
            """)
            print("\n  child_age_years distribution:")
            for val, n in cur.fetchall():
                print(f"    {int(val)}: {n:,}")

        # 7. Update ind_que
        print("\nUpdating ind_que_CH_MICS ...")
        _update_ind_que(conn)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nDB patch done.")


def _update_ind_que(conn) -> None:
    with conn.cursor() as cur:
        # Remove any existing derived rows for child_age_years
        cur.execute("""
            DELETE FROM "ind_que_CH_MICS"
            WHERE canonical_varname = 'child_age_years'
        """)

        # Insert derived rows: one per dataset that has child_age_months records
        cur.execute("""
            INSERT INTO "ind_que_CH_MICS"
                (canonical_varname, dataset_name, column_in_raw_sav,
                 column_label_in_english, source_kind, measure_type, canonical_text)
            SELECT DISTINCT
                'child_age_years',
                dataset_name,
                'child_age_months',
                'Derived: child age in completed years (0-4) from child_age_months',
                'derived',
                'child_background',
                'Child age in completed years (0-4). For year-coded datasets: original value. For month-coded: FLOOR(months/12).'
            FROM "ind_que_CH_MICS"
            WHERE canonical_varname = 'child_age_months'
        """)
        conn.commit()
        print(f"  ind_que: inserted {cur.rowcount} derived rows.")


# ---------------------------------------------------------------------------
# Parquet step
# ---------------------------------------------------------------------------

def patch_parquet() -> None:
    print(f"Reading {PARQUET_FILE} ...")
    df = pd.read_parquet(PARQUET_FILE)

    age = pd.to_numeric(df["child_age_months"], errors="coerce")

    # Identify year-coded datasets
    dataset_max = (
        df.assign(_age=age)
        .groupby("dataset_name")["_age"]
        .max()
    )
    year_coded = set(dataset_max[dataset_max <= 4].index)
    print(f"  Year-coded datasets: {len(year_coded)}")

    is_year = df["dataset_name"].isin(year_coded)

    # child_age_years
    child_age_years = pd.array([np.nan] * len(df), dtype="Float64")

    # year-coded: use current value (0-4), only where value is 0-4
    mask_yr = is_year & age.between(0, 4)
    child_age_years[mask_yr.values] = age[mask_yr].values

    # month-coded: FLOOR(months/12), only where 0-59
    mask_mo = (~is_year) & age.between(0, 59)
    child_age_years[mask_mo.values] = np.floor(age[mask_mo].values / 12)

    df["child_age_years"] = child_age_years

    # Fix child_age_months: NULL for year-coded, NULL for out-of-range
    age_fixed = age.copy()
    age_fixed[is_year] = np.nan                          # NULL year-coded
    age_fixed[~age.between(0, 59)] = np.nan              # NULL out-of-range
    df["child_age_months"] = pd.array(age_fixed, dtype="Float64")

    print(f"  child_age_years  non-null: {df['child_age_years'].notna().sum():,}")
    print(f"  child_age_months non-null: {df['child_age_months'].notna().sum():,}")
    print(f"  child_age_years dist: {dict(df['child_age_years'].value_counts(dropna=True).sort_index())}")

    df.to_parquet(PARQUET_FILE, index=False)
    print("  Parquet saved.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("db", "all"):
        patch_db()
    if mode in ("parquet", "all"):
        patch_parquet()
    print("\nAll done.")


if __name__ == "__main__":
    main()
