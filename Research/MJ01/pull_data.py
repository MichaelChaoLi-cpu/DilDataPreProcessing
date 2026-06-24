"""
MJ01: Pull and merge CH + WM data for child stunting analysis.

Output: data/mj01_analysis.parquet

Tables used:
  final_CH_MICS2MICS6  (PostgreSQL, localhost:5432, db: mda)
  final_WM_MICS2MICS6
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

SQL_CH = """
SELECT
    dataset_name,
    cluster_number,
    household_number,
    child_line_number,
    mother_caretaker_line_number,
    -- outcome
    height_for_age_zscore,
    weight_for_age_zscore,
    weight_for_height_zscore,
    -- child controls
    sex_of_child,
    child_age_months,
    area,
    region,
    wealth_index_quintile,
    mother_education,
    ever_breastfed          AS ch_ever_breastfed,
    still_breastfeeding,
    -- survey metadata
    child_sample_weight,
    interview_year
FROM "final_CH_MICS2MICS6"
WHERE height_for_age_zscore IS NOT NULL
  AND height_for_age_zscore BETWEEN -6 AND 6
"""

SQL_WM = """
SELECT
    dataset_name,
    cluster_number,
    hh_number,
    woman_line_number,
    -- maternal characteristics
    education_level         AS wm_education_level,
    woman_age,
    literacy,
    currently_married_or_cohabiting,
    received_anc,
    anc_visits,
    ever_breastfed          AS wm_ever_breastfed,
    media_tv_frequency,
    wealth_quintile         AS wm_wealth_quintile,
    -- survey metadata
    women_sample_weight,
    interview_year          AS wm_interview_year
FROM "final_WM_MICS2MICS6"
"""


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    return conn


def pull() -> pd.DataFrame:
    conn = _connect()
    print("Pulling CH data ...")
    ch = pd.read_sql(SQL_CH, conn)
    print(f"  CH rows: {len(ch):,}")

    print("Pulling WM data ...")
    wm = pd.read_sql(SQL_WM, conn)
    print(f"  WM rows: {len(wm):,}")
    conn.close()

    print("Merging ...")
    join_keys_ch = ["dataset_name", "cluster_number", "household_number", "mother_caretaker_line_number"]
    join_keys_wm = ["dataset_name", "cluster_number", "hh_number", "woman_line_number"]
    for col in join_keys_ch:
        ch[col] = ch[col].astype(str)
    for col in join_keys_wm:
        wm[col] = wm[col].astype(str)

    merged = ch.merge(
        wm,
        left_on=join_keys_ch,
        right_on=join_keys_wm,
        how="left",
        suffixes=("", "_wm"),
    )
    merged.drop(columns=["hh_number", "woman_line_number"], inplace=True)

    # drop the rare duplicated rows from WM multi-match
    before = len(merged)
    merged.drop_duplicates(
        subset=["dataset_name", "cluster_number", "household_number", "child_line_number"],
        inplace=True,
    )
    if len(merged) < before:
        print(f"  Dropped {before - len(merged)} duplicate rows from WM multi-match")

    n_matched = merged["wm_education_level"].notna().sum()
    print(f"  Merged rows: {len(merged):,}  |  matched to WM: {n_matched:,} ({n_matched/len(merged):.1%})")

    return merged


def main() -> None:
    df = pull()

    out_path = OUT_DIR / "mj01_analysis.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved: {out_path}  ({len(df):,} rows x {len(df.columns)} cols)")

    print("\nColumn summary:")
    print(df.dtypes.to_string())

    print("\nHAZ descriptive stats:")
    print(df["height_for_age_zscore"].describe().round(3).to_string())

    stunting_rate = (df["height_for_age_zscore"] < -2).mean()
    print(f"\nOverall stunting prevalence (HAZ < -2): {stunting_rate:.1%}")


if __name__ == "__main__":
    main()
