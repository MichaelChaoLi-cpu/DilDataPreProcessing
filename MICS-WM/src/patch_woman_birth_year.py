"""
P26 — Fix `CP_woman_age` (recover real age) + derive `CP_woman_birth_year`
(+ `CP_woman_birth_year_estimated`).  WM module.

Two problems:
1. `woman_age` (and its P11 copy `CP_woman_age`) is contaminated: 153 datasets
   store the 5-year AGE-GROUP code (1–7), not the real age — identical to
   `woman_age_group`. Only 86 datasets hold the real age (15–49).
2. No harmonized woman birth year existed.

The real age lives in the household listing (HL) — every woman is a household
member with her actual age recorded. HL age is calendar-independent (years lived),
so joining WM↔HL on (dataset, cluster, household, line) recovers the real age
(HL coverage ≥95% for 150/153 group-code datasets; 100% for Thailand & Nepal).

Fix:
- `CP_woman_age` = real age: `woman_age` where it is already real (10–64), else the
  HL-recovered age; NULL where neither is available (3 broken-key group datasets).
- `CP_woman_birth_year` (Gregorian, 1940–2010), hybrid by precision:
  * exact (est=0): `woman_birth_date_cmc` → year (primary) or raw `woman_birth_year`
    (fill), for non-Nepal/Thailand datasets (their cmc/year field is Gregorian);
  * age-based (est=1): `CP_survey_year − CP_woman_age`, used for Nepal, Thailand
    (Bikram-Sambat / Buddhist-Era birth fields; also age is group-coded there) and
    any dataset lacking a Gregorian birth-date source. Gregorian by construction,
    ±1 year (age is integer). `CP_woman_birth_year_estimated` flags 0=exact / 1=age.

Usage:
    .venv/bin/python MICS-WM/src/patch_woman_birth_year.py            # apply
    .venv/bin/python MICS-WM/src/patch_woman_birth_year.py --verify
"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

WM_PQ = Path("MICS-WM/data/WM/processed_data/wm_merged.parquet")
HL_PQ = Path("MICS-HL/data/HL/processed_data/hl_merged.parquet")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

CP_AGE = "CP_woman_age"
CP_BY = "CP_woman_birth_year"
CP_EST = "CP_woman_birth_year_estimated"
AGE_LO, AGE_HI = 10, 64
YEAR_LO, YEAR_HI = 1940, 2010


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _hl_age_lookup(wm):
    """Real age per WM row via HL join on (dataset, cluster, household, line)."""
    hl = pd.read_parquet(HL_PQ, columns=["dataset_name", "cluster_number",
                                         "household_number", "line_number", "age"])
    hl["cl"] = _num(hl["cluster_number"]).round()
    hl["hn"] = _num(hl["household_number"]).round()
    hl["ln"] = _num(hl["line_number"]).round()
    hl["ha"] = _num(hl["age"])
    lut = (hl.dropna(subset=["cl", "hn", "ln", "ha"])
             .drop_duplicates(["dataset_name", "cl", "hn", "ln"])
             [["dataset_name", "cl", "hn", "ln", "ha"]])
    w = pd.DataFrame({
        "dataset_name": wm["dataset_name"],
        "cl": _num(wm["cluster_number"]).round(),
        "hn": _num(wm["hh_number"]).round(),
        "ln": _num(wm["line_number"]).round(),
        "_row": np.arange(len(wm)),
    })
    m = w.merge(lut, on=["dataset_name", "cl", "hn", "ln"], how="left")
    out = pd.Series(np.nan, index=wm.index)
    out.iloc[m["_row"].values] = m["ha"].values
    return out


def derive(wm):
    ds = wm["dataset_name"].astype(str)
    nepal = ds.str.contains("nepal", case=False)
    thai = ds.str.contains("thailand", case=False)
    wa = _num(wm["woman_age"])
    hl_age = _hl_age_lookup(wm)

    # CP_woman_age: real age (raw where real, else HL), cleaned
    real_raw = wa.where((wa >= AGE_LO) & (wa <= AGE_HI))
    hl_ok = hl_age.where((hl_age >= AGE_LO) & (hl_age <= AGE_HI))
    cp_age = real_raw.where(real_raw.notna(), hl_ok)

    # CP_woman_birth_year
    sy = _num(wm["CP_survey_year"])
    cmc = _num(wm["woman_birth_date_cmc"])
    cmc_yr = 1900 + np.floor((cmc - 1) / 12)
    by_raw = _num(wm["woman_birth_year"])
    greg = ~nepal & ~thai

    exact = pd.Series(np.nan, index=wm.index)
    use_cmc = greg & cmc_yr.between(YEAR_LO, YEAR_HI)
    exact[use_cmc] = cmc_yr[use_cmc]
    use_by = greg & exact.isna() & by_raw.between(YEAR_LO, YEAR_HI)
    exact[use_by] = by_raw[use_by]

    agebased = (sy - cp_age).where(lambda s: s.between(YEAR_LO, YEAR_HI))

    cp_by = exact.where(exact.notna(), agebased)
    est = pd.Series(np.nan, index=wm.index)
    est[cp_by.notna()] = 1.0
    est[exact.notna()] = 0.0

    # plausibility guard: the birth year must imply a plausible woman age
    # (drops mis-aligned/contaminated birth-year fields, e.g. Algeria MICS6 → 2008).
    implied = sy - cp_by
    bad = cp_by.notna() & sy.notna() & ~implied.between(12, 60)
    cp_by[bad] = np.nan
    est[bad] = np.nan

    return cp_age, cp_by, est


# ---------------------------------------------------------------------------

def apply(verify):
    df = pd.read_parquet(WM_PQ)
    if verify:
        for c, lo, hi in [(CP_AGE, AGE_LO, AGE_HI), (CP_BY, YEAR_LO, YEAR_HI)]:
            n = int(df[c].notna().sum()) if c in df.columns else 0
            nds = df.loc[df[c].notna(), "dataset_name"].nunique() if c in df.columns else 0
            bad = int(df.loc[df[c].notna() & ~df[c].between(lo, hi)].shape[0]) if c in df.columns else -1
            print(f"  parquet {c}: valid={n} / {nds} ds; out-of-range={bad}")
        if CP_EST in df.columns:
            print(f"  parquet {CP_EST}: exact(0)={int((df[CP_EST]==0).sum())} "
                  f"age(1)={int((df[CP_EST]==1).sum())}")
        return

    if not WM_PQ.with_suffix(".parquet.bak_p26").exists():
        shutil.copy2(WM_PQ, WM_PQ.with_suffix(".parquet.bak_p26"))
    cp_age, cp_by, est = derive(df)
    df[CP_AGE] = cp_age.values
    df[CP_BY] = cp_by.values
    df[CP_EST] = est.values
    df.to_parquet(WM_PQ, index=False)
    print(f"  parquet: {CP_AGE} valid={int(cp_age.notna().sum())} / "
          f"{df.loc[cp_age.notna(),'dataset_name'].nunique()} ds; "
          f"{CP_BY} valid={int(cp_by.notna().sum())} / {df.loc[cp_by.notna(),'dataset_name'].nunique()} ds; "
          f"est: exact={int((est==0).sum())} age={int((est==1).sum())}")


def _col_exists(cur, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name='final_WM_MICS' AND column_name=%s""", (col,))
    return cur.fetchone() is not None


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'
    I = '"ind_que_WM_MICS"'
    if verify:
        for c in (CP_AGE, CP_BY, CP_EST):
            cur.execute(f'SELECT COUNT("{c}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{c}" IS NOT NULL) FROM {T}')
            print(f"  db {c}: non-null={cur.fetchone()}")
        conn.close(); return

    pdf = pd.read_parquet(WM_PQ)
    for c in (CP_BY, CP_EST):
        if not _col_exists(cur, c):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{c}" DOUBLE PRECISION')

    # row-level values (HL-recovered age, hybrid birth year) + 11% duplicate row keys
    # => reinsert every dataset from the patched parquet (parquet is source of truth).
    # Coerce dtypes ONCE on the full frame, then stream by dataset via a single groupby
    # (avoids O(n^2) per-dataset filtering of the 2.96M-row frame).
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_WM_MICS'""")
    dbtype = dict(cur.fetchall())
    cols = [c for c in pdf.columns if c in dbtype]
    assert set(pdf.columns) - set(dbtype) == set(), "parquet has columns absent from DB"
    for c in cols:
        if dbtype.get(c) in ("bigint", "smallint", "integer"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("Int64")
        elif dbtype.get(c) in ("double precision", "real", "numeric"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce")
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f'TRUNCATE {T}')
    n = 0
    for ds, sub in pdf.groupby("dataset_name", sort=False):
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        n += 1
    print(f"  db: reinserted {n} datasets (via TRUNCATE + grouped COPY)")

    # ind_que: mirror woman_age -> CP_woman_age (refresh) and woman_birth_year -> CP_woman_birth_year
    for base, cp in [("woman_age", CP_AGE), ("woman_birth_year", CP_BY), ("woman_birth_year", CP_EST)]:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (cp,))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            SELECT %s, dataset_name, column_in_raw_sav, column_label_in_english,
                   source_kind, measure_type, canonical_text
            FROM {I} WHERE canonical_varname=%s''', (cp, base))
    print("  db: ind_que mirrored CP_woman_age / CP_woman_birth_year rows")

    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P26 CP_woman_age + CP_woman_birth_year — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
