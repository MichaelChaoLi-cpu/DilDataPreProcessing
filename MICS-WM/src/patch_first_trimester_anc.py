"""
P23 — Derive `CP_first_trimester_anc` (+ `CP_first_trimester_anc_derived`).

First-trimester ANC = the first antenatal-care visit happened in the first
trimester of pregnancy: **<= 3 completed months** or, when the survey recorded
weeks, **<= 13 weeks**. There is no direct binary in the data; it is derived from
the "how many weeks/months pregnant at first ANC visit" question, which the
alignment split into `anc_first_visit_timing_number` + `anc_first_visit_timing_unit`
(unit 1=weeks / 2=months / 9=missing).

Two parts:

1. DERIVE from the 74 datasets already carrying the timing number+unit
   (`CP_first_trimester_anc_derived = 0`).
2. RECOVER 44 more datasets whose raw SAV holds the first-visit timing question
   but it was never mapped (MICS5 `MN2AN`/`MN2AU`, `MN2AAN`/`MN2AAU`; MICS6
   `MN4AN`/`MN4AU`, `MN4N`/`MN4U`; single month/week columns `MN2AA`/`MN3C`/
   `MN2B1`/`F9`...). Read the raw column(s), take the per-row unit from the paired
   unit column or a fixed unit inferred from the column label, and derive the same
   way (`CP_first_trimester_anc_derived = 1`). Rows are aligned POSITIONALLY to the
   SAV, guarded `hh_number == {HH2/WM2/WIHHNO/HI2/...}` = 100%.

Plausible ranges (else NULL): months 1-9, weeks 1-42. Sentinels 0/98/99 and
unit 9 -> NULL.

Usage:
    .venv/bin/python MICS-WM/src/patch_first_trimester_anc.py             # apply
    .venv/bin/python MICS-WM/src/patch_first_trimester_anc.py --verify    # check
"""
from __future__ import annotations

import io
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

NUM = "anc_first_visit_timing_number"
UNIT = "anc_first_visit_timing_unit"
CP = "CP_first_trimester_anc"
FLAG = "CP_first_trimester_anc_derived"

MONTH_MAX, WEEK_MAX = 9, 42          # plausible gestational age at first ANC
TRI_MONTHS, TRI_WEEKS = 3, 13        # first-trimester cutoff (<=3 months / <=13 weeks)

# 44 datasets with an unmapped first-visit timing question.
# ds -> (number_col, unit_col_or_None, fixed_unit_or_None)  fixed in {'months','weeks'}
RECOVER = {
    "Algeria MICS6 Datasets": ("MN4N", "MN4U", None),
    "Argentina MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Belize_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Benin_MICS5_Datasets": ("MN2AAN", "MN2AAU", None),
    "Cameroon_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Central African Republic MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Chad MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Congo_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Costa Rica MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Côte d'Ivoire_MICS5Datasets": ("MN2AAN", "MN2AAU", None),
    "Cuba_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "DRCongo MICS6 SPSS Datafiles": ("MN4AN", "MN4AU", None),
    "Dominican Republic MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Dominican Republic_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Egypt (Sub-national)_MICS5_Datasets": ("MN3C", None, "months"),
    "El Salvador_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Ghana MICS 2006 SPSS Datasets": ("MN2AA", None, "months"),
    "Guinea Bissau MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Guinea Bissau_MICS5_Datasets": ("MN2AAN", "MN2AAU", None),
    "Guinea_MICS5_Datasets": ("MN2AAN", "MN2AAU", None),
    "Guyana MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Guyana MICS6 Datasets (1)": ("MN4AN", "MN4AU", None),
    "Guyana MICS6 Datasets (2)": ("MN4AN", "MN4AU", None),
    "Honduras MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Iraq 2000 MICS_Datasets": ("MN2B1", None, "months"),
    "Madagascar (South)_ MICS4_Datasets": ("MN2A_CS", None, "months"),
    "Madagascar MICS6 SPSS dataset": ("MN4AN", "MN4AU", None),
    "Mali_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Mauritania_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Mauritania_MICS5_Datasets 2": ("MN2AN", "MN2AU", None),
    "Mexico_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Mongolia (Khuvsgul Aimag)_MICS5_Datasets": ("MN2A", None, "weeks"),
    "Mongolia (Nalaikh District)_MICS5_Datasets": ("MN2A", None, "weeks"),
    "Mongolia_MICS5_Datasets": ("MN2AA", None, "weeks"),
    "Nigeria_MICS4_Datasets": ("MN2AA", None, "months"),
    "Paraguay_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Sao Tome and Principe MICS6 Datasets": ("MN4AN", "MN4AU", None),
    "Sao Tome and Principe MICS6 Datasets (1)": ("MN4AN", "MN4AU", None),
    "Sao Tome and Principe_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Senegal (Dakar)_MICS5_Datasets": ("MN2AN", "MN2AU", None),
    "Somalia 2006 MICS_Datasets": ("MN2AA", None, "months"),
    "Togo MICS6 SPSS Datasets": ("MN4N", "MN4U", None),
    "Togo MICS6 SPSS Datasets (1)": ("MN4N", "MN4U", None),
    "Zimbabwe_Datasets": ("mn2aa", None, "months"),
}

GUARD_KEYS = ["HH2", "hh2", "WM2", "wm2", "WIHHNO", "wihhno", "HI2", "hi2", "hhno", "HHNO"]

# NFC-normalized view so lookups work whether the dataset name is NFC or NFD.
_RECOVER_NFC = {unicodedata.normalize("NFC", k): v for k, v in RECOVER.items()}


def _rec(ds):
    return _RECOVER_NFC[unicodedata.normalize("NFC", ds)]


def _ft(num: pd.Series, unit: pd.Series) -> pd.Series:
    """First-trimester (1/0/NaN) from a numeric timing value + a unit series
    (1=weeks, 2=months; anything else -> missing)."""
    n = pd.to_numeric(num, errors="coerce").astype(float)
    u = pd.to_numeric(unit, errors="coerce").astype(float)
    out = np.full(len(n), np.nan)
    mo = (u == 2) & (n >= 1) & (n <= MONTH_MAX)
    wk = (u == 1) & (n >= 1) & (n <= WEEK_MAX)
    out[mo] = (n[mo] <= TRI_MONTHS).astype(float)
    out[wk] = (n[wk] <= TRI_WEEKS).astype(float)
    return pd.Series(out, index=num.index)


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _resolve(ds, available):
    """Map a RECOVER key to the actual dataset_name in parquet, tolerant of
    Unicode NFC/NFD differences (parquet stores some names decomposed, e.g.
    'Côte d'Ivoire')."""
    if ds in available:
        return ds
    n = unicodedata.normalize("NFC", ds)
    for a in available:
        if unicodedata.normalize("NFC", a) == n:
            return a
    return None


def _read_sav(ds):
    import pyreadstat
    sav = RAW / ds / "wm.sav"
    if not sav.exists():
        for alt in RAW.glob(f"{ds}/*.sav"):
            if "wm" in alt.name.lower():
                sav = alt; break
    if not sav.exists():
        return None, "no SAV"
    df, _ = pyreadstat.read_sav(str(sav), apply_value_formats=False)
    return df, "ok"


def _recover_one(ds, parquet_ds):
    """Return (ft_series, note) positionally aligned to parquet_ds, or (None, note)."""
    numcol, unitcol, fixed = RECOVER[ds]
    df, note = _read_sav(ds)
    if df is None:
        return None, note
    if len(df) != len(parquet_ds):
        return None, f"row mismatch SAV {len(df)} vs pq {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["hh_number"].reset_index(drop=True), errors="coerce")
    key, best = None, 0.0
    for cand in GUARD_KEYS:
        c = _find(df.columns, cand)
        if c is None:
            continue
        m = (a == pd.to_numeric(df[c].reset_index(drop=True), errors="coerce")).mean()
        if m > best:
            key, best = c, m
        if m >= 0.999:
            break
    if best < 0.999:
        return None, f"guard hh_number==key {best:.3%} (best {key})"
    df = df.reset_index(drop=True)
    nc = _find(df.columns, numcol)
    if nc is None:
        return None, f"number col {numcol} absent"
    num = df[nc]
    if unitcol is not None:
        uc = _find(df.columns, unitcol)
        if uc is None:
            return None, f"unit col {unitcol} absent"
        unit = df[uc]
    else:
        unit = pd.Series(2 if fixed == "months" else 1, index=df.index)
    ft = _ft(num, unit)
    return ft, f"{numcol}/{unitcol or fixed} n={int(ft.notna().sum())} ft={np.nanmean(ft.values):.2f}"


# ---------------------------------------------------------------------------

def _mapped_set(df):
    """Datasets carrying the mapped timing number (derive directly), minus any we
    re-read from raw (none overlap, but keep it explicit)."""
    return sorted(d for d in df.loc[df[NUM].notna(), "dataset_name"].unique()
                  if d not in RECOVER)


def patch_parquet(verify: bool):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        rec = df.loc[df[FLAG] == 1, "dataset_name"].nunique() if FLAG in df.columns else 0
        print(f"  parquet: {CP} present={CP in df.columns}; valid(0/1)={n} across {nds} ds; "
              f"out-of-range={bad}; recovered datasets={rec}")
        return []

    if not PARQUET.with_suffix(".parquet.bak_p23").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p23"))

    cp = pd.Series(np.nan, index=df.index)
    flag = pd.Series(np.nan, index=df.index)

    # 1. derive from the mapped timing number+unit
    mapped = _mapped_set(df)
    mmask = df.dataset_name.isin(mapped)
    cp[mmask] = _ft(df.loc[mmask, NUM], df.loc[mmask, UNIT]).values
    flag[mmask] = np.where(cp[mmask].notna(), 0.0, np.nan)

    # 2. recover 44 from raw SAV, guarded positional
    avail = set(df.dataset_name.unique())
    applied, skipped = [], []
    for ds in RECOVER:
        actual = _resolve(ds, avail)
        if actual is None:
            skipped.append((ds, "not in parquet")); continue
        mask = df.dataset_name == actual
        ft, note = _recover_one(ds, df.loc[mask])
        if ft is None:
            skipped.append((ds, note)); continue
        cp.loc[mask] = ft.values
        flag.loc[mask] = np.where(ft.notna().values, 1.0, np.nan)
        applied.append(actual)
        print(f"  [ok]   {ds}: {note}")
    for ds, note in skipped:
        print(f"  [skip] {ds}: {note}")

    df[CP] = cp.values
    df[FLAG] = flag.values
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} across {nds} datasets; "
          f"derived(mapped)={len(mapped)} recovered={len(applied)} skipped={len(skipped)}")
    return applied


def patch_yaml(applied):
    if not applied:
        print("  yaml: nothing to add"); return
    with open(ALIGN, encoding="utf-8") as f:
        al = yaml.safe_load(f) or {}
    entries = al.get(NUM, [])
    have = {e.get("dataset_name") for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p23").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p23"))
    added = 0
    for ds in applied:
        if ds in have:
            continue
        numcol, unitcol, fixed = _rec(ds)
        entries.append({
            "canonical_text": "Weeks or months pregnant at first ANC visit",
            "canonical_varname": NUM, "column_in_raw_sav": numcol,
            "column_label_in_english": "Timing of first antenatal visit (recovered P23)",
            "component": None, "confidence": "high", "dataset_name": ds,
            "derivation": None, "entities": [], "entity_operator": None, "event": None,
            "is_compound": False, "measure_type": "antenatal_care",
            "needs_review": False, "relation": None, "response_type": "numeric",
            "source_kind": "explicit",
        })
        added += 1
    al[NUM] = entries
    with open(ALIGN, "w", encoding="utf-8") as f:
        yaml.safe_dump(al, f, allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {NUM} mappings")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied, verify):
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'
    I = '"ind_que_WM_MICS"'

    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                    f'FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND "{CP}" NOT IN (0,1)')
        bad = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(DISTINCT dataset_name) FROM {T} WHERE "{FLAG}"=1')
        rec = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        ind = cur.fetchone()[0]
        print(f"  db: {CP} non-null={n} across {nds} datasets; out-of-range={bad}; "
              f"recovered datasets={rec}; ind_que CP_ rows={ind}")
        conn.close()
        return

    pdf = pd.read_parquet(PARQUET)
    mapped = _mapped_set(pdf)

    for col in (CP, FLAG):
        if not _col_exists(cur, "final_WM_MICS", col):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" DOUBLE PRECISION')

    # 1. derive mapped datasets in place from the existing timing columns
    cur.execute(
        f'UPDATE {T} SET "{CP}" = CASE '
        f'  WHEN {NUM} IS NULL OR {NUM} < 1 OR {NUM} > {WEEK_MAX} THEN NULL '
        f'  WHEN {UNIT}=2 AND {NUM} <= {MONTH_MAX} THEN (CASE WHEN {NUM} <= {TRI_MONTHS} THEN 1 ELSE 0 END) '
        f'  WHEN {UNIT}=1 THEN (CASE WHEN {NUM} <= {TRI_WEEKS} THEN 1 ELSE 0 END) '
        f'  ELSE NULL END, '
        f'"{FLAG}" = NULL '
        f'WHERE dataset_name = ANY(%s)', (mapped,))
    cur.execute(f'UPDATE {T} SET "{FLAG}" = 0 WHERE "{CP}" IS NOT NULL AND dataset_name = ANY(%s)',
                (mapped,))
    print(f"  db: derived {len(mapped)} mapped datasets")

    # 2. re-insert recovered datasets from patched parquet
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_WM_MICS'""")
    dbtype = dict(cur.fetchall())
    cols = list(pdf.columns)
    assert all(c in dbtype for c in cols), "DB missing a parquet column"
    for ds in applied:
        sub = pdf[pdf["dataset_name"] == ds].copy()
        for c in cols:
            if dbtype.get(c) == "bigint":
                sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
            elif dbtype.get(c) == "double precision":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
        buf = io.StringIO()
        sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
        buf.seek(0)
        collist = ", ".join(f'"{c}"' for c in cols)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    print(f"  db: re-inserted {len(applied)} recovered datasets")

    # ind_que: provenance for CP_ (mirror the timing-number rows + recovered rows)
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    for ds in applied:
        numcol = _rec(ds)[0]
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{NUM}' AND dataset_name=%s", (ds,))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (NUM, ds, numcol, "Timing of first antenatal visit (recovered P23)",
             "explicit", "antenatal_care", "Weeks or months pregnant at first ANC visit"))
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{NUM}' ''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que mirrored {cur.fetchone()[0]} {CP} provenance rows")

    conn.commit()
    conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P23 first_trimester_anc -> {CP} — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(applied)
    print("== database =="); patch_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
