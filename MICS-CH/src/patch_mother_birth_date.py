"""
P50 — mother's birth date on each child (CH):
    CP_mother_birth_year, CP_mother_birth_year_estimated, CP_mother_birth_month

Each child is linked to its mother's WM (woman 15-49) record and given her birth
year/month. Link key: (dataset_name, cluster_number, household_number,
mother_caretaker_line_number) == WM (dataset_name, cluster_number, hh_number,
woman_line_number | line_number) — the same link P09 used for mother_education.

Sources, in priority order:
  1. mother's WM (woman 15-49) record — year = CP_woman_birth_year (P26, real age via
     HL, Gregorian) + its _estimated flag; month = woman_birth_month cleaned to 1-12
     (else derived from woman_birth_date_cmc).
  2. HL household-listing FALLBACK when the mother is not in the WM 15-49 file (e.g.
     older than 49): link the mother's HL member row (same line number) — year from
     HL year_of_birth, else survey_year - HL age (flagged estimated); month from HL
     month_of_birth. This recovers children whose mother is >49 or otherwise not a WM
     respondent.

Usage:
    .venv/bin/python MICS-CH/src/patch_mother_birth_date.py            # apply
    .venv/bin/python MICS-CH/src/patch_mother_birth_date.py --verify
"""
from __future__ import annotations

import io
import sys
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent.parent
WM_PARQUET = ROOT / "MICS-WM" / "data" / "WM" / "processed_data" / "wm_merged.parquet"
HL_PARQUET = ROOT / "MICS-HL" / "data" / "HL" / "processed_data" / "hl_merged.parquet"
CH_PARQUET = ROOT / "MICS-CH" / "data" / "CH" / "processed_data" / "ch_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

CP_Y = "CP_mother_birth_year"
CP_YE = "CP_mother_birth_year_estimated"
CP_M = "CP_mother_birth_month"
NEW_COLS = [CP_Y, CP_YE, CP_M]


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _mother_lookup():
    wm = pd.read_parquet(WM_PARQUET, columns=[
        "dataset_name", "cluster_number", "hh_number", "line_number", "woman_line_number",
        "CP_woman_birth_year", "CP_woman_birth_year_estimated",
        "woman_birth_month", "woman_birth_date_cmc"])
    for k in ["cluster_number", "hh_number", "line_number", "woman_line_number"]:
        wm[k] = _num(wm[k])
    wm["_line"] = wm["woman_line_number"].fillna(wm["line_number"])
    # clean birth month: valid 1-12, else derive from CMC
    m = _num(wm["woman_birth_month"])
    m = m.where(m.between(1, 12))
    cmc = _num(wm["woman_birth_date_cmc"])
    m_cmc = ((cmc - 1) % 12 + 1).where(cmc.between(1, 1500))
    wm["_bmonth"] = m.fillna(m_cmc)
    wm["_byear"] = _num(wm["CP_woman_birth_year"])
    wm["_byear_est"] = _num(wm["CP_woman_birth_year_estimated"])
    wm = wm.dropna(subset=["cluster_number", "hh_number", "_line"])
    wm = wm[wm["_byear"].notna() | wm["_bmonth"].notna()]
    # one row per mother key (drop dup line ids within a household)
    wm = wm.drop_duplicates(subset=["dataset_name", "cluster_number", "hh_number", "_line"])
    return wm[["dataset_name", "cluster_number", "hh_number", "_line",
               "_byear", "_byear_est", "_bmonth"]]


def _hl_mother_lookup():
    """Household-listing fallback: the mother is a household member in HL (covers
    mothers >49 not in the WM 15-49 file). Birth year from HL year_of_birth, else
    survey_year - HL age (estimated); month from HL month_of_birth."""
    hl = pd.read_parquet(HL_PARQUET, columns=[
        "dataset_name", "cluster_number", "household_number", "line_number",
        "age", "year_of_birth", "month_of_birth"])
    for k in ["cluster_number", "household_number", "line_number"]:
        hl[k] = _num(hl[k])
    yob = _num(hl["year_of_birth"]).where(lambda s: s.between(1900, 2015))
    age = _num(hl["age"]).where(lambda s: s.between(10, 95))
    mth = _num(hl["month_of_birth"]).where(lambda s: s.between(1, 12))
    hl["_yob"] = yob
    hl["_age"] = age
    hl["_hmonth"] = mth
    hl = hl.dropna(subset=["cluster_number", "household_number", "line_number"])
    hl = hl[hl["_yob"].notna() | hl["_age"].notna() | hl["_hmonth"].notna()]
    hl = hl.drop_duplicates(subset=["dataset_name", "cluster_number", "household_number", "line_number"])
    return hl[["dataset_name", "cluster_number", "household_number", "line_number",
               "_yob", "_age", "_hmonth"]]


def apply(verify):
    ch = pd.read_parquet(CH_PARQUET)
    if verify:
        for col in NEW_COLS:
            if col not in ch.columns:
                print(f"  parquet {col}: MISSING"); continue
            n = int(ch[col].notna().sum())
            nds = ch.loc[ch[col].notna(), "dataset_name"].nunique()
            print(f"  parquet {col}: non-null={n} / {nds} ds")
        return
    if not CH_PARQUET.with_suffix(".parquet.bak_p50").exists():
        shutil.copy2(CH_PARQUET, CH_PARQUET.with_suffix(".parquet.bak_p50"))
    keys = ["dataset_name", "cluster_number", "household_number", "mother_caretaker_line_number"]
    k = ch[keys].copy()
    for c in ["cluster_number", "household_number", "mother_caretaker_line_number"]:
        k[c] = _num(k[c])
    # --- primary: WM (woman 15-49) link ---
    moms = _mother_lookup()
    merged = k.merge(moms, how="left",
                     left_on=["dataset_name", "cluster_number", "household_number",
                              "mother_caretaker_line_number"],
                     right_on=["dataset_name", "cluster_number", "hh_number", "_line"])
    year = merged["_byear"].to_numpy(dtype="float64", na_value=np.nan).copy()
    yest = merged["_byear_est"].to_numpy(dtype="float64", na_value=np.nan).copy()
    month = merged["_bmonth"].to_numpy(dtype="float64", na_value=np.nan).copy()
    n_wm = int(np.isfinite(year).sum())

    # --- fallback: HL household-listing link (mothers not in WM, e.g. >49) ---
    hl = _hl_mother_lookup()
    mh = k.merge(hl, how="left",
                 left_on=["dataset_name", "cluster_number", "household_number",
                          "mother_caretaker_line_number"],
                 right_on=["dataset_name", "cluster_number", "household_number", "line_number"])
    sy = _num(ch["CP_survey_year"]).to_numpy(dtype="float64", na_value=np.nan)
    hl_yob = mh["_yob"].to_numpy(dtype="float64", na_value=np.nan)
    hl_age = mh["_age"].to_numpy(dtype="float64", na_value=np.nan)
    hl_month = mh["_hmonth"].to_numpy(dtype="float64", na_value=np.nan)
    hl_from_age = np.where(np.isfinite(hl_age) & np.isfinite(sy), sy - hl_age, np.nan)
    hl_year = np.where(np.isfinite(hl_yob), hl_yob, hl_from_age)
    hl_year = np.where((hl_year >= 1900) & (hl_year <= 2015), hl_year, np.nan)
    hl_year_est = np.where(np.isfinite(hl_yob), 0.0, 1.0)  # age-derived → estimated

    take_y = ~np.isfinite(year) & np.isfinite(hl_year)
    year[take_y] = hl_year[take_y]; yest[take_y] = hl_year_est[take_y]
    take_m = ~np.isfinite(month) & np.isfinite(hl_month)
    month[take_m] = hl_month[take_m]
    n_hl = int(take_y.sum())

    ch[CP_Y] = year; ch[CP_YE] = yest; ch[CP_M] = month
    ch.to_parquet(CH_PARQUET, index=False)
    print(f"  linked: WM={n_wm} +HL-fallback={n_hl}")
    for col in NEW_COLS:
        n = int(ch[col].notna().sum()); nds = ch.loc[ch[col].notna(), "dataset_name"].nunique()
        print(f"  parquet: {col} non-null={n} / {nds} datasets")


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        for col in NEW_COLS:
            cur.execute(f'SELECT COUNT("{col}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{col}" IS NOT NULL) FROM {T}')
            print(f"  db {col}: {cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(CH_PARQUET)
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='final_CH_MICS'")
    dbtype = dict(cur.fetchall())
    for col, typ in [(CP_Y, "SMALLINT"), (CP_YE, "SMALLINT"), (CP_M, "SMALLINT")]:
        if col not in dbtype:
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" {typ}')
    dbtype = dict([*dbtype.items(), (CP_Y, "smallint"), (CP_YE, "smallint"), (CP_M, "smallint")])
    cols = [c for c in pdf.columns if c in dbtype]
    assert set(dbtype) - set(pdf.columns) == set(), "DB has columns absent from parquet"
    for c in cols:
        if dbtype.get(c) in ("bigint", "smallint", "integer"):
            pdf[c] = _num(pdf[c]).astype("Int64")
        elif dbtype.get(c) in ("double precision", "real", "numeric"):
            pdf[c] = _num(pdf[c])
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f'TRUNCATE {T}')
    for ds, sub in pdf.groupby("dataset_name", sort=False):
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    for col, txt in [(CP_Y, "Mother's birth year (from linked WM CP_woman_birth_year)"),
                     (CP_YE, "Mother's birth year is estimated"),
                     (CP_M, "Mother's birth month 1-12 (from linked WM woman_birth_month / CMC)")]:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (col,))
        cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
            column_label_in_english,source_kind,measure_type,canonical_text)
            SELECT DISTINCT %s, dataset_name, 'WM:CP_woman_birth_year|HL:age', %s, 'derived',
                   'child_background', %s
            FROM {I} WHERE canonical_varname='mother_education_years' ''', (col, txt, txt))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que added")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P50 mother birth date — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
