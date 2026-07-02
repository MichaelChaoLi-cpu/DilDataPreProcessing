"""
Generic patch for media-frequency harmonized variables.

Adds <varname>_harmonized to final_WM_MICS and wm_merged.parquet.

Usage:
  python patch_media_frequency_harmonized.py media_radio_frequency db
  python patch_media_frequency_harmonized.py media_radio_frequency parquet
  python patch_media_frequency_harmonized.py media_radio_frequency all
  python patch_media_frequency_harmonized.py media_newspaper_frequency all
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

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
PARQUET_FILE = DATA_DIR / "WM" / "processed_data" / "wm_merged.parquet"


def _load_map(varname: str) -> pd.DataFrame:
    map_csv = DATA_DIR / "WM" / f"{varname}_harmonize_map.csv"
    df = pd.read_csv(map_csv)
    df.loc[df["harmonized"] == -1, "harmonized"] = np.nan
    return df[["dataset_name", "raw_value", "harmonized"]]


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    return conn


def _norm_int(x):
    try:
        return int(float(x))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# DB step
# ---------------------------------------------------------------------------

def patch_db(varname: str) -> None:
    new_col = f"{varname}_harmonized"
    map_df = _load_map(varname)
    valid = map_df[map_df["harmonized"].notna()].copy()
    valid["harmonized"] = valid["harmonized"].astype(float)
    valid["tv_val_num"] = valid["raw_value"].map(_norm_int).astype(float, errors="ignore")
    valid = valid[valid["tv_val_num"].notna()]

    print(f"[{varname}]")
    print(f"  Mapping rows (valid 0-3): {len(valid):,}")
    print(f"  Mapping rows (→ NULL):    {map_df['harmonized'].isna().sum():,}")

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'final_WM_MICS' AND column_name = '{new_col}'
            """)
            if cur.fetchone() is None:
                print(f"  Adding column {new_col} ...")
                cur.execute(f'ALTER TABLE "final_WM_MICS" ADD COLUMN "{new_col}" DOUBLE PRECISION')
                conn.commit()
            else:
                print(f"  Column {new_col} exists, will overwrite.")

            cur.execute("""
                CREATE TEMP TABLE _freq_map (
                    dataset_name TEXT,
                    freq_val     DOUBLE PRECISION,
                    harmonized   DOUBLE PRECISION
                )
            """)
            buf = io.StringIO()
            valid[["dataset_name", "tv_val_num", "harmonized"]].to_csv(
                buf, index=False, header=False, na_rep="\\N"
            )
            buf.seek(0)
            cur.copy_expert(
                "COPY _freq_map (dataset_name, freq_val, harmonized) "
                "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
            conn.commit()
            print(f"  Temp map loaded ({len(valid):,} rows).")

            print(f"  Updating {new_col} ...")
            cur.execute(f"""
                UPDATE "final_WM_MICS" w
                SET "{new_col}" = m.harmonized
                FROM _freq_map m
                WHERE w.dataset_name = m.dataset_name
                  AND w."{varname}" = m.freq_val
            """)
            updated = cur.rowcount
            conn.commit()
            print(f"  Rows updated: {updated:,}")

            cur.execute(f"""
                SELECT "{new_col}", COUNT(*) AS n
                FROM "final_WM_MICS"
                GROUP BY "{new_col}"
                ORDER BY "{new_col}"
            """)
            print("  Distribution:")
            labels = {0: "0=Never", 1: "1=<weekly", 2: "2=≥weekly", 3: "3=~daily", None: "NULL"}
            for val, n in cur.fetchall():
                lbl = labels.get(int(val) if val is not None else None, str(val))
                print(f"    {lbl:<12} {n:>12,}")

        _update_ind_que(conn, varname, new_col)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("  DB patch done.")


def _update_ind_que(conn, varname: str, new_col: str) -> None:
    canonical_text = (
        f"Harmonized {varname.replace('_', ' ')} (4-level): "
        "0=Never, 1=<once/week, 2=>=once/week, 3=Almost every day"
    )
    with conn.cursor() as cur:
        cur.execute(f"""
            DELETE FROM "ind_que_WM_MICS" WHERE canonical_varname = '{new_col}'
        """)
        cur.execute(f"""
            INSERT INTO "ind_que_WM_MICS"
                (canonical_varname, dataset_name, column_in_raw_sav,
                 column_label_in_english, source_kind, measure_type, canonical_text)
            SELECT DISTINCT
                '{new_col}',
                dataset_name,
                '{varname}',
                'Derived: harmonized frequency (4-level) from {varname}',
                'derived',
                'media_exposure',
                %s
            FROM "ind_que_WM_MICS"
            WHERE canonical_varname = '{varname}'
        """, (canonical_text,))
        conn.commit()
        print(f"  ind_que: inserted {cur.rowcount} derived rows.")


# ---------------------------------------------------------------------------
# Parquet step
# ---------------------------------------------------------------------------

def patch_parquet(varname: str) -> None:
    new_col = f"{varname}_harmonized"
    map_df = _load_map(varname)
    map_df["tv_val_num"] = map_df["raw_value"].map(_norm_int)
    lookup = (
        map_df[map_df["tv_val_num"].notna()]
        .set_index(["dataset_name", "tv_val_num"])["harmonized"]
    )

    print(f"[{varname}] Reading parquet ...")
    df = pd.read_parquet(PARQUET_FILE)

    tv = pd.to_numeric(df[varname], errors="coerce")
    tv_int = tv.map(lambda x: int(x) if pd.notna(x) else None)
    keys = list(zip(df["dataset_name"], tv_int))
    harmonized = pd.array([lookup.get(k, np.nan) for k in keys], dtype="Float64")
    df[new_col] = harmonized

    n_valid = pd.notna(harmonized).sum()
    print(f"  {new_col} non-null: {n_valid:,} / {len(df):,}")
    print("  Value counts:")
    for v, n in pd.Series(harmonized).value_counts(dropna=False).sort_index().items():
        print(f"    {v}: {n:,}")

    df.to_parquet(PARQUET_FILE, index=False)
    print("  Parquet saved.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python patch_media_frequency_harmonized.py <varname> [db|parquet|all]")
        sys.exit(1)

    varname = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"

    map_csv = DATA_DIR / "WM" / f"{varname}_harmonize_map.csv"
    if not map_csv.exists():
        print(f"ERROR: {map_csv} not found. Run scan_media_frequency_labels.py first.")
        sys.exit(1)

    if mode in ("db", "all"):
        patch_db(varname)
    if mode in ("parquet", "all"):
        patch_parquet(varname)
    print("\nAll done.")


if __name__ == "__main__":
    main()
