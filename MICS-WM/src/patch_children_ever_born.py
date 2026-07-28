"""
P13 — Carefully process `children_ever_born` -> `CP_children_ever_born`, and
recover fully-missing datasets whose raw WM SAV holds an unmapped CEB column.

Two parts:

1. Backfill 10 of the 39 fully-missing datasets from a validated raw CEB column
   (scan_children_ever_born.py located them; values are real, mean 1.8-4.4).
   Cross-module backfill is impossible (CEB is women-only) and component
   derivation (sum of sons/daughters) proved unreliable (~16% exact), so the
   raw column is the only trustworthy source. Rows are aligned POSITIONALLY to
   the SAV, guarded: a dataset is backfilled ONLY if hh_number == HH2 for every
   row; otherwise it is skipped and reported. Mappings are written to
   alignment_v2.yaml so a full rebuild reproduces them.

2. Create `CP_children_ever_born`: carefully-processed copy of
   children_ever_born keeping only plausible counts 0-20; sentinel 99 and
   implausibly high values (>20) are set to NULL. The variable is already very
   clean (only ~8 such rows pre-backfill). The raw `children_ever_born` is left
   unchanged except for the additive backfill. Cross-variable inconsistencies
   (CEB < children_dead etc.) are intentionally NOT altered here.

Usage:
    .venv/bin/python MICS-WM/src/patch_children_ever_born.py            # apply
    .venv/bin/python MICS-WM/src/patch_children_ever_born.py --verify   # check
"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "children_ever_born"
CP = "CP_children_ever_born"
LO, HI = 0, 20  # plausible children-ever-born range (inclusive)

# dataset_name -> raw SAV column holding CEB (validated by scan+distribution).
BACKFILL = {
    "Benin_MICS5_Datasets": "CEB",
    "Mauritania_MICS4_Datasets": "CEB",
    "Mauritania_MICS5_Datasets": "CEB",
    "Mauritania_MICS5_Datasets 2": "CEB",
    "Mauritania MICS 2007 SPSS Datasets": "ceb",
    "Mexico_MICS5_Datasets": "CEB",
    "Cameroon_MICS5_Datasets": "CEB",
    "Senegal (Dakar)_MICS5_Datasets": "CEB",
    "Kyrgyzstan MICS 2005-06 SPSS Datasets": "ceb",
    "Burundi MICS 2005 SPSS Datasets": "CM9",
}


def clean(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors="coerce")
    return v.where((v >= LO) & (v <= HI))


def _find(cols, name):
    """Case-insensitive column lookup."""
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _sav_ceb(ds: str, col: str, parquet_ds: pd.DataFrame):
    """Read the CEB column from the SAV, verify positional 1:1 alignment via
    hh_number==HH2. Return (series, note). series is None if the guard fails."""
    import pyreadstat
    sav = RAW / ds / "wm.sav"
    if not sav.exists():
        return None, "no SAV"
    df, _ = pyreadstat.read_sav(str(sav))
    ccol = _find(df.columns, col)
    hh2 = _find(df.columns, "HH2")
    if ccol is None:
        return None, f"col {col} absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch SAV {len(df)} vs pq {len(parquet_ds)}"
    if hh2 is not None:
        a = pd.to_numeric(parquet_ds["hh_number"].reset_index(drop=True), errors="coerce")
        b = pd.to_numeric(df[hh2].reset_index(drop=True), errors="coerce")
        if (a == b).mean() < 1.0:
            return None, f"guard hh_number==HH2 {(a==b).mean():.3%}"
    else:
        return None, "no HH2 to guard"
    return pd.to_numeric(df[ccol].reset_index(drop=True), errors="coerce"), "ok"


# ---------------------------------------------------------------------------

def patch_parquet(verify: bool) -> list[str]:
    df = pd.read_parquet(PARQUET)
    if verify:
        valid = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        cp_ok = CP in df.columns and df[CP].equals(clean(df[BASE]))
        filled = [d for d in BACKFILL if df.loc[df.dataset_name == d, BASE].notna().any()]
        print(f"  parquet: {CP} present&correct={cp_ok}; valid={valid} across {nds} ds; "
              f"backfilled datasets={len(filled)}")
        return filled

    if not PARQUET.with_suffix(".parquet.bak_p13").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p13"))

    applied = []
    for ds, col in BACKFILL.items():
        mask = df["dataset_name"] == ds
        if not mask.any():
            print(f"  [skip] {ds}: not in parquet"); continue
        series, note = _sav_ceb(ds, col, df.loc[mask])
        if series is None:
            print(f"  [skip] {ds}: {note}"); continue
        df.loc[mask, BASE] = series.values
        applied.append(ds)
        print(f"  [ok]   {ds}: {col} filled {int(series.notna().sum())} raw values")

    df[CP] = clean(df[BASE])
    df.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} valid(0-20)={int(df[CP].notna().sum())} across "
          f"{df.loc[df[CP].notna(),'dataset_name'].nunique()} datasets; "
          f"{len(applied)}/{len(BACKFILL)} datasets backfilled")
    return applied


def patch_yaml(applied: list[str]) -> None:
    if not applied:
        print("  yaml: nothing to add"); return
    with open(ALIGN, encoding="utf-8") as f:
        al = yaml.safe_load(f) or {}
    entries = al.get(BASE, [])
    have = {e.get("dataset_name") for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p13").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p13"))
    added = 0
    for ds in applied:
        if ds in have:
            continue
        entries.append({
            "canonical_text": "Children ever born", "canonical_varname": BASE,
            "column_in_raw_sav": BACKFILL[ds],
            "column_label_in_english": "Children ever born",
            "component": None, "confidence": "high", "dataset_name": ds,
            "derivation": None, "entities": [], "entity_operator": None,
            "event": None, "is_compound": False, "measure_type": "fertility",
            "needs_review": False, "relation": None, "response_type": "numeric",
            "source_kind": "explicit",
        })
        added += 1
    al[BASE] = entries
    with open(ALIGN, "w", encoding="utf-8") as f:
        yaml.safe_dump(al, f, allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {BASE} mappings")


def _col_exists(cur, table, col) -> bool:
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied: list[str], verify: bool) -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'
    I = '"ind_que_WM_MICS"'

    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                    f'FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL '
                    f'AND ("{CP}"<{LO} OR "{CP}">{HI})')
        bad = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        ind = cur.fetchone()[0]
        print(f"  db: {CP} non-null={n} across {nds} datasets; out-of-range={bad}; "
              f"ind_que CP_ rows={ind}")
        conn.close()
        return

    pdf = pd.read_parquet(PARQUET)

    if not _col_exists(cur, "final_WM_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    cur.execute(f'UPDATE {T} SET "{CP}" = CASE WHEN {BASE} BETWEEN {LO} AND {HI} '
                f'THEN {BASE} ELSE NULL END WHERE {BASE} IS NOT NULL')

    # re-insert each backfilled dataset from patched parquet (uniform, robust to
    # broken keys); coerce dtypes to DB column types so COPY never fails.
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
    print(f"  db: re-inserted {len(applied)} backfilled datasets")

    # ind_que: add base rows for backfilled datasets, then mirror all base -> CP_
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    for ds in applied:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{BASE}' AND dataset_name=%s", (ds,))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (BASE, ds, BACKFILL[ds], "Children ever born", "explicit",
             "fertility", "Children ever born"))
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
    print(f"P13 children_ever_born -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(applied)
    print("== database =="); patch_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
