"""
P32 — `CP_breastfeeding_status` (CH): 3-category current breastfeeding status.

Pure derivation from two existing CP_ columns (no SAV read):
    CP_ever_breastfed (P29) + CP_still_breastfeeding (P30)

    2 = currently breastfeeding   (still=1; implies ever, so it wins over a
        stray ever=0 — a child breastfeeding now was obviously ever breastfed)
    0 = never breastfed           (ever=0 and not currently)
    1 = ever breastfed but stopped / weaned   (ever=1 and still=0)
    NULL = indeterminate          (ever unknown & not-currently, or ever=1 with
        still unknown — can't place on the never/stopped/current axis)

Coverage = union of ever & still = 241 datasets (~1.22M rows). This is the
MICS "current breastfeeding status": ever gives the lifetime axis, still gives
the current axis; together they place each child in never / weaned / current.

DB: pure function of two existing DB columns, so the update is a single SQL
CASE mirroring the pandas logic exactly — no reupload. ind_que rows are the
union of the ever/still provenance, relabelled source_kind='derived'.

Usage:
    .venv/bin/python MICS-CH/src/patch_breastfeeding_status.py            # apply
    .venv/bin/python MICS-CH/src/patch_breastfeeding_status.py --verify
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

CP = "CP_breastfeeding_status"
EVER = "CP_ever_breastfed"
STILL = "CP_still_breastfeeding"

# SQL CASE — MUST stay identical to _derive() below.
CASE_SQL = f'''CASE
    WHEN "{STILL}" = 1 THEN 2
    WHEN "{EVER}" = 0 THEN 0
    WHEN "{EVER}" = 1 AND "{STILL}" = 0 THEN 1
    ELSE NULL END'''


def _derive(ever, still):
    """3-category status as a float Series (NaN where indeterminate)."""
    ever = pd.to_numeric(ever, errors="coerce")
    still = pd.to_numeric(still, errors="coerce")
    st = pd.Series(np.nan, index=ever.index)
    st[(ever == 1) & (still == 0)] = 1        # ever, stopped
    st[ever == 0] = 0                          # never (still 0 or null)
    st[still == 1] = 2                         # currently (applied last: wins)
    return st


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        if CP not in df.columns:
            print(f"  parquet {CP}: MISSING"); return
        v = df[CP]
        nds = df.loc[v.notna(), "dataset_name"].nunique()
        bad = int(df.loc[v.notna() & ~v.isin([0, 1, 2])].shape[0])
        vc = v.value_counts(dropna=True).sort_index().to_dict()
        print(f"  parquet {CP}: valid={int(v.notna().sum())} / {nds} ds; "
              f"out-of-range={bad}; dist={vc}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p32").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p32"))
    df[CP] = _derive(df[EVER], df[STILL]).values
    df.to_parquet(PARQUET, index=False)
    v = df[CP]
    nds = df.loc[v.notna(), "dataset_name"].nunique()
    vc = v.value_counts(dropna=True).sort_index().to_dict()
    print(f"  parquet: {CP} valid={int(v.notna().sum())} / {nds} datasets; dist={vc}")


def _col_exists(cur, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name='final_CH_MICS' AND column_name=%s""", (col,))
    return cur.fetchone() is not None


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND "{CP}" NOT IN (0,1,2)')
        oor = cur.fetchone()[0]
        cur.execute(f'SELECT "{CP}", COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL GROUP BY 1 ORDER BY 1')
        dist = {int(k): v for k, v in cur.fetchall()}
        print(f"  db {CP}: non-null={n} / {nds} ds; out-of-range={oor}; dist={dist}")
        conn.close(); return
    if not _col_exists(cur, CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" SMALLINT')
    cur.execute(f'UPDATE {T} SET "{CP}" = {CASE_SQL}')
    # ind_que: derived from ever+still — carry both parents' raw provenance.
    cur.execute(f'DELETE FROM {I} WHERE canonical_varname=%s', (CP,))
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT DISTINCT %s, dataset_name, column_in_raw_sav, column_label_in_english,
               'derived', 'breastfeeding',
               'Breastfeeding status (0=never, 1=weaned, 2=currently)'
        FROM {I} WHERE canonical_varname IN (%s, %s)''', (CP, EVER, STILL))
    print("  db: updated + ind_que mirrored (derived from ever+still)")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P32 CP_breastfeeding_status — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
