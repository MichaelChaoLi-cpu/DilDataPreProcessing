"""
MJ01b: Pull and merge CH + HH data for WASH causal-effect analysis.

Research design: Saturation / phase-in identification
  Treatment: WASH coverage (improved drinking water, improved sanitation, handwashing)
  Outcome:   Child stunting (HAZ < -2), wasting (WHZ < -2)
  Mediator:  Diarrhea in last 2 weeks
  Unit:      Child-level; coverage aggregated to cluster / country-year level

Output: data/mj01b_analysis.parquet

Tables used (PostgreSQL localhost:5432, db: mda):
  final_CH_MICS
  final_HH_MICS

Variable notes
--------------
diarrhea_last_2_weeks:
  Most datasets: 1=Yes, 2=No; sentinels: 7,8,9,100
  MICS2 era (5 datasets): 0=No, 1=Yes → handled below

main_source_of_drinking_water (JMP codes):
  Improved  : 11-14, 21, 31, 32, 51, 61
  Unimproved: 22, 23, 41, 42, 71-73, 81, 91-94
  MICS2 old codes (1-10) mapped separately (see OLD_WATER_IMPROVED below)
  Sentinels : 96, 97, 98, 99

type_of_toilet_facility (JMP codes):
  Improved  : 11, 12, 13, 14, 15, 21
  Unimproved: 22, 23, 24, 31, 41, 51, 95
  MICS2 old codes (1-8) mapped separately (see OLD_TOILET_IMPROVED below)
  Sentinels : 96, 97, 98, 99

height_for_age_zscore / weight_for_height_zscore:
  Valid range -6 to 6 (WHO flag threshold); values ≥ 99 are sentinels
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# JMP improved water / sanitation lookup sets
# ---------------------------------------------------------------------------

# Standard JMP codes (two-digit), post-MICS3
IMPROVED_WATER_JMP = {11, 12, 13, 14, 21, 31, 32, 51, 61}
# 15 = piped (neighbor, some versions), 17 = packaged water (limited)
# 61 = bottled water — included as it meets JMP basic threshold for drinking

IMPROVED_SANITATION_JMP = {11, 12, 13, 14, 15, 21}
# 21 = composting toilet (improved); 16/18 = flush variants

# Old MICS2 single-digit water codes (1-9)
# Source: UNICEF MICS2 questionnaire (2000) codebook
OLD_WATER_IMPROVED = {
    1: True,   # Piped water
    2: True,   # Borehole / tube well
    3: True,   # Protected dug well
    4: False,  # Unprotected dug well
    5: True,   # Protected spring
    6: False,  # Unprotected spring
    7: True,   # Rainwater
    8: False,  # River / lake / dam (surface water)
    9: False,  # Tanker truck / vendor
    10: False, # Other
}

# Old MICS2 single-digit toilet codes (1-8)
OLD_TOILET_IMPROVED = {
    1: True,   # Flush toilet
    2: True,   # Ventilated improved pit latrine (VIP)
    3: True,   # Pit latrine with slab
    4: False,  # Pit latrine without slab / open pit
    5: False,  # No facility / bush / field
    6: False,  # Other
    7: False,  # Hanging toilet / bucket
    8: False,  # Don't know
}

WATER_SENTINEL  = {96, 97, 98, 99}
TOILET_SENTINEL = {96, 97, 98, 99}

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

SQL_CH = """
SELECT
    c.dataset_name,
    c.cluster_number,
    c.household_number,
    c.child_line_number,
    -- outcomes
    c.height_for_age_zscore         AS haz,
    c.weight_for_height_zscore      AS whz,
    c.height_for_age_flag,
    c.weight_for_height_flag,
    -- mediator
    c.diarrhea_last_2_weeks,
    c.fever_last_2_weeks,
    -- child controls (use harmonized age from P07)
    c.child_age_years,
    c.child_age_months,
    c.sex_of_child,
    -- household / contextual controls
    c.area,
    c.region,
    c.wealth_index_quintile,
    c.mother_education_harmonized,
    -- survey
    c.child_sample_weight,
    c.interview_year
FROM "final_CH_MICS" c
"""

SQL_HH = """
SELECT
    dataset_name,
    cluster_number,
    household_number,
    -- WASH
    main_source_of_drinking_water,
    type_of_toilet_facility,
    toilet_facility_shared,
    toilet_shared_with_other_households_or_public,
    soap_or_other_material_available_for_handwashing,
    handwashing_material_bar_soap,
    water_available_at_handwashing_place,
    time_to_get_water_minutes,
    treat_water_to_make_safer
FROM "final_HH_MICS"
"""

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    return conn


def _extract_survey_year(dataset_name: str) -> int | None:
    """Parse survey year from dataset_name string."""
    # Explicit 4-digit year in name (e.g. 'Nigeria MICS 2007 SPSS Datasets')
    m = re.search(r'\b(19|20)\d{2}\b', dataset_name)
    if m:
        return int(m.group())
    # MICS round → approximate midpoint year
    round_years = {"MICS6": 2019, "MICS5": 2014, "MICS4": 2010,
                   "MICS3": 2006, "MICS2": 2001, "LSIS": 2014}
    for tag, yr in round_years.items():
        if tag in dataset_name:
            return yr
    return None


def _extract_country(dataset_name: str) -> str:
    """Best-effort country name from dataset_name prefix."""
    # Strip trailing round/format info
    name = re.sub(
        r'\s*(MICS\d?|SPSS|Datasets?|[0-9]{4}|LSIS|_?\d+).*$',
        '', dataset_name, flags=re.IGNORECASE
    ).strip().rstrip('_- ')
    return name


def _recode_improved_water(val) -> float:
    """Return 1.0 (improved), 0.0 (unimproved), or NaN."""
    if pd.isna(val):
        return np.nan
    code = int(float(val))
    if code in WATER_SENTINEL:
        return np.nan
    if 1 <= code <= 10:  # old MICS2 codes
        return float(OLD_WATER_IMPROVED.get(code, np.nan))
    if code in IMPROVED_WATER_JMP:
        return 1.0
    if code in {22, 23, 41, 42, 71, 72, 73, 81, 91, 92, 93, 94}:
        return 0.0
    return np.nan  # unknown code


def _recode_improved_sanitation(toilet_val, shared_val, shared2_val) -> float:
    """
    Return 1.0 (improved, not shared), 0.0 (unimproved or shared), NaN.
    JMP definition: improved facility NOT shared with other households.
    """
    if pd.isna(toilet_val):
        return np.nan
    try:
        code = int(float(toilet_val))
    except (ValueError, TypeError):
        return np.nan
    if code in TOILET_SENTINEL:
        return np.nan

    if 1 <= code <= 8:
        improved = OLD_TOILET_IMPROVED.get(code, None)
        if improved is None:
            return np.nan
    elif code in IMPROVED_SANITATION_JMP:
        improved = True
    elif code in {22, 23, 24, 25, 26, 31, 41, 51, 52, 61, 71, 88, 95}:
        improved = False
    else:
        return np.nan

    if not improved:
        return 0.0

    # Check if shared — any value > 1 or 'yes' indicator means shared
    # toilet_facility_shared: 1=only with HH members, 2=shared w/ others, 3=public
    # toilet_shared_with_other_households_or_public: 1=yes, 2=no
    def _is_shared(v) -> bool | None:
        if pd.isna(v):
            return None
        try:
            iv = int(float(v))
        except (ValueError, TypeError):
            return None
        return iv in {2, 3}  # shared or public

    s1 = _is_shared(shared_val)
    s2 = _is_shared(shared2_val)
    shared = s1 or s2  # True if either confirms shared
    if shared:
        return 0.0
    return 1.0


def _recode_diarrhea(val, dataset_name: str, mics2_datasets: set[str]) -> float:
    """Return 1.0=Yes, 0.0=No, NaN=sentinel/unknown."""
    if pd.isna(val):
        return np.nan
    code = int(val)
    try:
        code = int(float(val))
    except (ValueError, TypeError):
        return np.nan
    if code in {7, 8, 9, 100}:  # sentinels
        return np.nan
    if dataset_name in mics2_datasets:
        # MICS2 era uses 0=No, 1=Yes
        if code == 0:
            return 0.0
        if code == 1:
            return 1.0
        return np.nan
    # Standard: 1=Yes, 2=No
    if code == 1:
        return 1.0
    if code == 2:
        return 0.0
    return np.nan


def _recode_handwashing(soap_val, water_val) -> float:
    """1 = soap + water available at handwashing place, 0 = not, NaN = missing."""
    # soap_or_other_material_available_for_handwashing: 1=Yes, 2=No
    # water_available_at_handwashing_place: 1=Yes, 2=No
    def _yes(v) -> bool | None:
        if pd.isna(v): return None
        try:
            return int(float(v)) == 1
        except (ValueError, TypeError):
            return None
    s = _yes(soap_val)
    w = _yes(water_val)
    if s is None and w is None:
        return np.nan
    # require both; treat missing as False
    return float((s is True) and (w is not False))


# ---------------------------------------------------------------------------
# Main pull + merge
# ---------------------------------------------------------------------------

def pull() -> pd.DataFrame:
    conn = _connect()
    print("Pulling CH data ...")
    ch = pd.read_sql(SQL_CH, conn)
    print(f"  CH rows: {len(ch):,}")

    print("Pulling HH data ...")
    hh = pd.read_sql(SQL_HH, conn)
    print(f"  HH rows: {len(hh):,}")
    conn.close()

    # --- survey year + country ---
    ch["survey_year"] = ch["dataset_name"].map(_extract_survey_year)
    ch["country"]     = ch["dataset_name"].map(_extract_country)

    # Use interview_year if available (overrides regex estimate)
    if "interview_year" in ch.columns:
        mask = ch["interview_year"].notna() & (ch["interview_year"].between(1995, 2030))
        ch.loc[mask, "survey_year"] = ch.loc[mask, "interview_year"].astype(int)

    print(f"  Survey year range: {int(ch['survey_year'].min())} – {int(ch['survey_year'].max())}")

    # --- MICS2 dataset set (diarrhea 0=No coding) ---
    mics2_datasets = set(ch.loc[ch["dataset_name"].str.contains("MICS2|2000 MICS|MICS 2000", na=False), "dataset_name"].unique())
    print(f"  MICS2-era datasets identified: {len(mics2_datasets)}")

    # --- Diarrhea binary ---
    print("Recoding diarrhea ...")
    ch["diarrhea"] = [
        _recode_diarrhea(v, ds, mics2_datasets)
        for v, ds in zip(ch["diarrhea_last_2_weeks"], ch["dataset_name"])
    ]

    # --- Z-score filtering ---
    print("Filtering z-scores ...")
    # Use flag if available (flag != 0 → invalid); fall back to ±6 range
    haz = pd.to_numeric(ch["haz"], errors="coerce")
    whz = pd.to_numeric(ch["whz"], errors="coerce")

    if "height_for_age_flag" in ch.columns:
        haz_flag = pd.to_numeric(ch["height_for_age_flag"], errors="coerce")
        haz = haz.where(haz_flag == 0)          # NULL if flagged
    haz = haz.where(haz.between(-6, 6))         # ±6 safety net

    if "weight_for_height_flag" in ch.columns:
        whz_flag = pd.to_numeric(ch["weight_for_height_flag"], errors="coerce")
        whz = whz.where(whz_flag == 0)
    whz = whz.where(whz.between(-6, 6))

    ch["haz_clean"] = haz
    ch["whz_clean"] = whz
    ch["stunting"]  = (haz < -2).astype("Float64")   # NA-preserving
    ch["wasting"]   = (whz < -2).astype("Float64")

    print(f"  Valid HAZ: {haz.notna().sum():,}  Stunting rate: {(haz < -2).mean():.1%}")
    print(f"  Valid WHZ: {whz.notna().sum():,}  Wasting rate:  {(whz < -2).mean():.1%}")
    print(f"  Diarrhea (Yes): {(ch['diarrhea'] == 1).sum():,} / {ch['diarrhea'].notna().sum():,}")

    # --- HH WASH recoding ---
    print("Recoding WASH variables ...")
    hh["improved_water"] = hh["main_source_of_drinking_water"].map(_recode_improved_water)

    hh["improved_sanitation"] = [
        _recode_improved_sanitation(t, s1, s2)
        for t, s1, s2 in zip(
            hh["type_of_toilet_facility"],
            hh["toilet_facility_shared"],
            hh["toilet_shared_with_other_households_or_public"],
        )
    ]

    hh["handwashing_soap_water"] = [
        _recode_handwashing(s, w)
        for s, w in zip(
            hh["soap_or_other_material_available_for_handwashing"],
            hh["water_available_at_handwashing_place"],
        )
    ]

    # Water collection time: basic service = ≤ 30 min (round-trip)
    hh["water_time_min"] = pd.to_numeric(hh["time_to_get_water_minutes"], errors="coerce")
    hh["water_on_premises"] = (hh["water_time_min"] == 0).astype("Float64")
    hh["basic_water_access"] = (
        hh["improved_water"].fillna(0).astype(bool) &
        (hh["water_time_min"].fillna(999) <= 30)
    ).astype("Float64")
    # Where time_to_get_water is missing, fall back to just improved_water
    missing_time = hh["water_time_min"].isna()
    hh.loc[missing_time, "basic_water_access"] = hh.loc[missing_time, "improved_water"]

    print(f"  Improved water:      {hh['improved_water'].mean():.1%} of HH")
    print(f"  Improved sanitation: {hh['improved_sanitation'].mean():.1%} of HH")
    print(f"  Handwashing (soap+water): {hh['handwashing_soap_water'].mean():.1%} of HH")

    # --- Merge CH + HH on (dataset_name, cluster_number, household_number) ---
    print("Merging CH + HH ...")
    join_keys = ["dataset_name", "cluster_number", "household_number"]
    for col in join_keys:
        ch[col] = ch[col].astype(str)
        hh[col] = hh[col].astype(str)

    hh_wash = hh[[
        "dataset_name", "cluster_number", "household_number",
        "improved_water", "improved_sanitation", "handwashing_soap_water",
        "basic_water_access", "water_on_premises", "water_time_min",
        "treat_water_to_make_safer",
    ]].drop_duplicates(subset=join_keys)  # one HH row per household

    df = ch.merge(hh_wash, on=join_keys, how="left")
    n_wash = df["improved_water"].notna().sum()
    print(f"  Merged rows: {len(df):,}  |  matched to HH WASH: {n_wash:,} ({n_wash/len(df):.1%})")

    # --- Cluster-level WASH coverage (saturation variable) ---
    print("Computing cluster-level WASH coverage ...")
    cluster_keys = ["dataset_name", "cluster_number"]
    clust_cov = hh.groupby(cluster_keys)[["improved_water", "improved_sanitation"]].mean().reset_index()
    clust_cov.columns = cluster_keys + ["cluster_water_coverage", "cluster_sanit_coverage"]
    for col in cluster_keys:
        clust_cov[col] = clust_cov[col].astype(str)
    df = df.merge(clust_cov, on=cluster_keys, how="left")

    # Country-year level coverage
    cy_cov = hh.merge(
        ch[["dataset_name", "survey_year"]].drop_duplicates(),
        on="dataset_name", how="left"
    ).groupby(["country" if "country" in hh.columns else "dataset_name", "survey_year"])[
        ["improved_water", "improved_sanitation"]
    ].mean().reset_index()

    # --- Final column selection ---
    keep_cols = [
        # identifiers
        "dataset_name", "country", "survey_year",
        "cluster_number", "household_number", "child_line_number",
        # outcomes
        "haz_clean", "whz_clean", "stunting", "wasting",
        # mediator
        "diarrhea", "fever_last_2_weeks",
        # child controls
        "child_age_years", "child_age_months", "sex_of_child",
        # household / contextual
        "area", "region", "wealth_index_quintile", "mother_education_harmonized",
        # WASH (household-level)
        "improved_water", "improved_sanitation", "handwashing_soap_water",
        "basic_water_access", "water_on_premises", "water_time_min",
        "treat_water_to_make_safer",
        # WASH (cluster-level coverage — saturation design IV)
        "cluster_water_coverage", "cluster_sanit_coverage",
        # survey
        "child_sample_weight",
    ]
    # keep only cols that actually exist
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols]

    return df, cy_cov


def main() -> None:
    df, cy_cov = pull()

    out_path = OUT_DIR / "mj01b_analysis.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}  ({len(df):,} rows × {len(df.columns)} cols)")

    print("\n=== Column summary ===")
    print(df.dtypes.to_string())

    print("\n=== WASH coverage by survey year (country-year means) ===")
    if "survey_year" in cy_cov.columns and "improved_water" in cy_cov.columns:
        yr_agg = cy_cov.groupby("survey_year")[["improved_water","improved_sanitation"]].mean()
        print(yr_agg.round(3).to_string())

    print("\n=== Key variable non-null counts ===")
    for col in ["stunting", "wasting", "diarrhea",
                "improved_water", "improved_sanitation", "handwashing_soap_water",
                "cluster_water_coverage", "child_age_years"]:
        if col in df.columns:
            n = df[col].notna().sum()
            print(f"  {col:<35} {n:>10,}  ({n/len(df):.1%})")

    print("\n=== Stunting / wasting by WASH access ===")
    for wash_var in ["improved_water", "improved_sanitation"]:
        if wash_var not in df.columns or "stunting" not in df.columns:
            continue
        tbl = df.groupby(wash_var)["stunting"].mean().round(3)
        print(f"\n  {wash_var}:\n{tbl.to_string()}")


if __name__ == "__main__":
    main()
