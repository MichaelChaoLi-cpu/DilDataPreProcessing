"""
P19 — Derive `CP_age_at_first_birth` (WM): woman's age (completed years) at her
first live birth. There is no clean surveyed variable for this (only ~5 datasets
asked it directly); it is a derived quantity.

Two sources, in order of accuracy:
  A. CMC difference (PRIMARY): floor((first_child_birth_date_cmc -
     woman_birth_date_cmc) / 12). A difference of two century-month codes is
     calendar-agnostic (any Buddhist/Bikram-Sambat offset cancels) and
     month-precise. Covers 134 datasets.
  B. Year method (FALLBACK, extends coverage): CP_first_birth_year -
     (interview_year_CE - woman_age), where interview_year_CE = 1900 +
     floor((interview_date_cmc-1)/12). Year-level, so ±1 vs method A (validated:
     A vs B = 100% within 1 year). Uses the already-cleaned CP_first_birth_year
     (P18) so its calendar fixes carry through. Adds ~33 datasets -> 167 total.

CP_age_at_first_birth = A if in [10, 49]; else B if in [10, 49]; else NULL.
CP_age_at_first_birth_estimated = 0 if from A (CMC-exact), 1 if from B
(year-level approximation), NULL if CP is NULL.

Pure per-row function of existing columns — no SAV / alignment_v2.yaml changes,
no re-insertion.

Usage:
    .venv/bin/python MICS-WM/src/patch_age_at_first_birth.py            # apply
    .venv/bin/python MICS-WM/src/patch_age_at_first_birth.py --verify   # check
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

CP = "CP_age_at_first_birth"
EST = "CP_age_at_first_birth_estimated"
LO, HI = 10, 49
COLS = ["dataset_name", "woman_birth_date_cmc", "first_child_birth_date_cmc",
        "interview_date_cmc", "woman_age", "CP_first_birth_year"]


def _compute(df: pd.DataFrame):
    n = lambda c: pd.to_numeric(df[c], errors="coerce")
    wcmc, ccmc = n("woman_birth_date_cmc"), n("first_child_birth_date_cmc")
    icmc, wage, fby = n("interview_date_cmc"), n("woman_age"), n("CP_first_birth_year")
    valid_cmc = wcmc.between(1, 1600) & ccmc.between(1, 1600)
    A = np.floor((ccmc - wcmc) / 12).where(valid_cmc)
    iyr = (1900 + np.floor((icmc - 1) / 12)).where(icmc.between(1, 1600))
    B = (fby - (iyr - wage)).where(fby.notna() & iyr.notna() & wage.between(10, 60))
    A_ok = A.where(A.between(LO, HI))
    B_ok = B.where(B.between(LO, HI))
    cp = A_ok.fillna(B_ok)
    est = pd.Series(np.nan, index=df.index)
    est[A_ok.notna()] = 0.0
    est[A_ok.isna() & B_ok.notna()] = 1.0
    return cp, est


def patch_parquet(verify: bool):
    if verify:
        df = pd.read_parquet(PARQUET, columns=COLS + [CP, EST])
        cp, est = _compute(df)
        ok = df[CP].equals(cp) and df[EST].equals(est)
        n = int(cp.notna().sum()); nds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} datasets "
              f"(min={cp.min():.0f}, median={cp.median():.0f}, max={cp.max():.0f}; "
              f"exact={int((est==0).sum())}, estimated={int((est==1).sum())})")
        return
    full = pd.read_parquet(PARQUET)
    cp, est = _compute(full)
    if not PARQUET.with_suffix(".parquet.bak_p19").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p19"))
    full[CP] = cp; full[EST] = est
    full.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} non-null={int(cp.notna().sum())} across "
          f"{full.loc[cp.notna(),'dataset_name'].nunique()} datasets "
          f"(exact={int((est==0).sum())}, estimated={int((est==1).sum())})")


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
                    f'COUNT(*) FILTER (WHERE "{CP}" IS NOT NULL AND ("{CP}"<{LO} OR "{CP}">{HI})), '
                    f'COUNT(*) FILTER (WHERE "{EST}"=0), COUNT(*) FILTER (WHERE "{EST}"=1) FROM {T}')
        n, nds, mn, mx, bad, ex, es = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} datasets (min={mn},max={mx}); "
              f"out-of-range={bad}; exact={ex} estimated={es}; ind_que rows={cur.fetchone()[0]}")
        conn.close(); return

    for col in (CP, EST):
        if not _col_exists(cur, "final_WM_MICS", col):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" DOUBLE PRECISION')
    A = "floor((first_child_birth_date_cmc::float - woman_birth_date_cmc::float)/12.0)"
    Aok = (f"CASE WHEN woman_birth_date_cmc::float BETWEEN 1 AND 1600 "
           f"AND first_child_birth_date_cmc::float BETWEEN 1 AND 1600 "
           f"AND {A} BETWEEN {LO} AND {HI} THEN {A} END")
    iyr = "(1900 + floor((interview_date_cmc::float - 1)/12.0))"
    B = f'("CP_first_birth_year"::float - ({iyr} - woman_age::float))'
    Bok = (f"CASE WHEN \"CP_first_birth_year\" IS NOT NULL "
           f"AND interview_date_cmc::float BETWEEN 1 AND 1600 "
           f"AND woman_age::float BETWEEN 10 AND 60 AND {B} BETWEEN {LO} AND {HI} THEN {B} END")
    cur.execute(f'UPDATE {T} SET "{CP}" = COALESCE(({Aok}),({Bok})), '
                f'"{EST}" = CASE WHEN ({Aok}) IS NOT NULL THEN 0 '
                f'WHEN ({Bok}) IS NOT NULL THEN 1 END')
    print("  db: CP_ + estimated computed (CMC-diff primary, year-method fallback)")

    cur.execute(f"DELETE FROM {I} WHERE canonical_varname IN ('{CP}','{EST}')")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT DISTINCT '{CP}', dataset_name,
               'first_child_birth_date_cmc - woman_birth_date_cmc / CP_first_birth_year',
               'Age at first birth (derived)', 'derived', 'fertility',
               'Age at first birth'
        FROM {T} WHERE "{CP}" IS NOT NULL''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que {CP} rows={cur.fetchone()[0]}")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P19 derive {CP} — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); patch_parquet(verify)
    print("== database =="); patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
