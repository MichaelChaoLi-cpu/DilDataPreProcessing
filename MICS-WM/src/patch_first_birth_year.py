"""
P18 — Carefully process `first_birth_year` -> `CP_first_birth_year` (WM):
a clean, calendar-harmonised Gregorian (CE) year of the woman's first birth.

The raw `first_birth_year` is a mess for cross-country use:
  * only 116/251 datasets populated;
  * sentinels 9997/9998/9999 (~42.7k rows);
  * NON-Gregorian calendars — Thailand stores the Buddhist Era year (2513-2559 =
    1970-2016; BE = CE + 543) and Nepal MICS5 the Bikram Sambat year
    (2035-2071 = 1978-2014; BS ~ CE + 57);
  * one dataset (Palestinians in Lebanon 2006) uses a 2-digit year.

`first_child_birth_date_cmc` (a Gregorian century-month code) is present in 138
datasets and, converted via `1900 + floor((cmc-1)/12)`, reproduces the Gregorian
year field EXACTLY (100% on 487,969 rows where both exist) — and it is calendar-
agnostic (Thailand's CMC already gives CE). So:

CP_first_birth_year (Gregorian CE, valid 1950-2024) is, per row:
  1. the CMC-derived year, if it lands in [1950, 2024]; else
  2. the year field converted to CE per the dataset's calendar
     (Thailand -543, Nepal -57, Palestinians 2-digit pivot, else as-is), if in
     range; else NULL.

This both cleans the calendars/sentinels AND lifts coverage 116 -> ~191 datasets
(the 75 datasets that have CMC but no year field). The raw `first_birth_year` is
left unchanged. CP_ is a pure per-row function of existing columns, so no SAV /
alignment_v2.yaml changes and no row re-insertion are needed.

Usage:
    .venv/bin/python MICS-WM/src/patch_first_birth_year.py            # apply
    .venv/bin/python MICS-WM/src/patch_first_birth_year.py --verify   # check
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "first_birth_year"
CMC = "first_child_birth_date_cmc"
CP = "CP_first_birth_year"
LO, HI = 1950, 2024  # plausible Gregorian first-birth year range

# Non-Gregorian year-field calendars (only used when CMC is unavailable/invalid).
THAI = [  # Buddhist Era: CE = BE - 543
    "Thailand 2005-06 MICS_Datasets", "Thailand_MICS4_Datasets",
    "Thailand_MICS5_Datasets", "Thailand_14_Provinces_MICS5_Datasets",
]
NEPAL = ["Nepal_MICS5_Datasets"]           # Bikram Sambat: CE ~ BS - 57
PALEST = ["Palestinians in Lebanon MICS 2006 SPSS Datasets"]  # 2-digit year


def _year_from_field(df: pd.DataFrame) -> pd.Series:
    """Year field converted to Gregorian CE per the dataset's calendar."""
    y = pd.to_numeric(df[BASE], errors="coerce")
    ds = df["dataset_name"]
    out = y.copy()
    out[ds.isin(THAI)] = y[ds.isin(THAI)] - 543
    out[ds.isin(NEPAL)] = y[ds.isin(NEPAL)] - 57
    p = ds.isin(PALEST) & (y < 100)
    out[p] = np.where(y[p] <= 24, 2000 + y[p], 1900 + y[p])
    return out


def _compute(df: pd.DataFrame) -> pd.Series:
    cmc = pd.to_numeric(df[CMC], errors="coerce")
    ycmc = 1900 + np.floor((cmc - 1) / 12)
    cp = ycmc.where(ycmc.between(LO, HI))
    yfield = _year_from_field(df)
    return cp.fillna(yfield.where(yfield.between(LO, HI)))


def patch_parquet(verify: bool):
    if verify:
        df = pd.read_parquet(PARQUET, columns=["dataset_name", BASE, CMC, CP])
        cp = _compute(df)
        ok = df[CP].equals(cp)
        n = int(cp.notna().sum()); nds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} datasets "
              f"(min={cp.min():.0f}, max={cp.max():.0f})")
        return
    full = pd.read_parquet(PARQUET)
    cp = _compute(full)
    if not PARQUET.with_suffix(".parquet.bak_p18").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p18"))
    full[CP] = cp
    full.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} non-null={int(cp.notna().sum())} across "
          f"{full.loc[cp.notna(),'dataset_name'].nunique()} datasets "
          f"(range {cp.min():.0f}-{cp.max():.0f})")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(verify: bool):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'; I = '"ind_que_WM_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL), '
                    f'MIN("{CP}"), MAX("{CP}"), '
                    f'COUNT(*) FILTER (WHERE "{CP}" IS NOT NULL AND ("{CP}"<{LO} OR "{CP}">{HI})) FROM {T}')
        n, nds, mn, mx, bad = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} datasets (min={mn}, max={mx}); "
              f"out-of-range={bad}; ind_que CP_ rows={cur.fetchone()[0]}")
        conn.close(); return

    if not _col_exists(cur, "final_WM_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')

    def _inlist(names):  # quoted SQL literal list of (constant) dataset names
        return "(" + ",".join("'" + n.replace("'", "''") + "'" for n in names) + ")"
    ycmc = f"(1900 + floor(({CMC}::float - 1)/12.0))"
    fby = f"{BASE}::float"
    yconv = (f"CASE WHEN dataset_name IN {_inlist(THAI)} THEN {fby} - 543 "
             f"WHEN dataset_name IN {_inlist(NEPAL)} THEN {fby} - 57 "
             f"WHEN dataset_name IN {_inlist(PALEST)} AND {fby} < 100 "
             f"THEN CASE WHEN {fby} <= 24 THEN 2000 + {fby} ELSE 1900 + {fby} END "
             f"ELSE {fby} END")
    cur.execute(
        f'UPDATE {T} SET "{CP}" = COALESCE('
        f'  CASE WHEN {ycmc} BETWEEN {LO} AND {HI} THEN {ycmc} END,'
        f'  CASE WHEN ({yconv}) BETWEEN {LO} AND {HI} THEN ({yconv}) END)')
    print("  db: CP_ computed (CMC-derived, else calendar-converted year field)")

    # ind_que: mirror base rows to CP_, plus a derived row for datasets that
    # gained coverage from CMC only (have CP_ but no first_birth_year mapping).
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{BASE}' ''')
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT DISTINCT '{CP}', f.dataset_name, '{CMC}',
               'Year of first birth (derived from CMC)', 'derived', 'fertility',
               'Year of first birth'
        FROM {T} f
        WHERE f."{CP}" IS NOT NULL
          AND f.dataset_name NOT IN (SELECT dataset_name FROM {I} WHERE canonical_varname='{BASE}')''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que {CP} rows={cur.fetchone()[0]}")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P18 first_birth_year -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); patch_parquet(verify)
    print("== database =="); patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
