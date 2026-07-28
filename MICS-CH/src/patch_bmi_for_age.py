"""
P14 — Carefully process `bmi_for_age_zscore` -> `CP_bmi_for_age_zscore` (CH).

Clean-only (no derivation/backfill). The raw column carries a sentinel 999.99
and biologically-implausible extremes; MICS already flags these in `bmi_flag`
(0 = plausible, 1 = implausible, NULL = not computed). The CP_ copy keeps only
plausible values: `bmi_flag = 0` AND BMI-for-age z within WHO bounds [-5, 5];
everything else -> NULL. The raw `bmi_for_age_zscore` is left unchanged.

(A larger derivation — computing BMI-for-age z from raw weight/height/age/sex via
the WHO 2006 standards to raise coverage ~61% -> ~77% — was scoped out for now.
Note: for under-5, WHO prefers weight-for-height z; BMI-for-age is a 5-19y tool.)

Usage:
    .venv/bin/python MICS-CH/src/patch_bmi_for_age.py            # apply
    .venv/bin/python MICS-CH/src/patch_bmi_for_age.py --verify   # check only
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "bmi_for_age_zscore"
FLAG = "bmi_flag"
CP = "CP_bmi_for_age_zscore"
LO, HI = -5.0, 5.0  # WHO plausible BMI-for-age z bounds


def clean(df: pd.DataFrame) -> pd.Series:
    z = pd.to_numeric(df[BASE], errors="coerce")
    flag = pd.to_numeric(df[FLAG], errors="coerce")
    return z.where((flag == 0) & (z >= LO) & (z <= HI))


def patch_parquet(verify: bool) -> None:
    df = pd.read_parquet(PARQUET)
    if verify:
        ok = CP in df.columns and df[CP].equals(clean(df))
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        print(f"  parquet: {CP} present&correct={ok}; valid={n} across {nds} datasets")
        return
    if not PARQUET.with_suffix(".parquet.bak_p14").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p14"))
    df[CP] = clean(df)
    df.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} across "
          f"{df.loc[df[CP].notna(),'dataset_name'].nunique()} datasets")


def _col_exists(cur, table, col) -> bool:
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(verify: bool) -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_CH_MICS"'
    I = '"ind_que_CH_MICS"'

    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                    f'FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL '
                    f'AND ("{CP}"<{LO} OR "{CP}">{HI})')
        bad = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} datasets; out-of-range={bad}; "
              f"ind_que CP_ rows={cur.fetchone()[0]}")
        conn.close()
        return

    if not _col_exists(cur, "final_CH_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    cur.execute(f'UPDATE {T} SET "{CP}" = CASE '
                f'WHEN {FLAG} = 0 AND {BASE} BETWEEN {LO} AND {HI} THEN {BASE} '
                f'ELSE NULL END WHERE {BASE} IS NOT NULL')
    print("  db: CP_ column populated")

    # mirror ind_que provenance rows (CP_ = copy of base rows), per CP_ convention
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{BASE}' ''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que mirrored {cur.fetchone()[0]} {CP} provenance rows")

    conn.commit()
    conn.close()


def main() -> None:
    verify = "--verify" in sys.argv
    print(f"P14 bmi_for_age_zscore -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); patch_parquet(verify)
    print("== database =="); patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
