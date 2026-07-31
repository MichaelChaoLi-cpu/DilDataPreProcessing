"""
P21 — Carefully process `child_sample_weight` -> `CP_child_sample_weight` (CH).

Two issues:
1. **Scale inconsistency.** 131/134 datasets store a normalised child weight
   (mean ~ 1 within the survey, the MICS standard). Three store un-normalised
   expansion weights: Thailand 2005-06 (mean 514), Costa Rica MICS6 (98.5),
   Panama MICS5 (60.9). Pooling them un-normalised would weight those surveys'
   cases ~60-500x. Fix: normalise ONLY the outlier datasets (dataset mean > 5)
   to mean 1 by dividing by the dataset mean; leave the already-normalised ones
   unchanged. Weight 0 (excluded case) is kept.
2. **Alignment gap.** 51 datasets never had `child_sample_weight` mapped even
   though their raw SAV has a `chweight`/`CHWEIGHT` ("child sample weight" /
   "pondération enfant" / "ponderador de niños") column. Recovered by guarded
   positional backfill (household_number == HH2/CHHHNO = 100%).

CP_child_sample_weight = child_sample_weight / (dataset mean if that mean > 5
else 1). The raw column is unchanged except the additive recovery backfill.

Usage:
    .venv/bin/python MICS-CH/src/patch_child_sample_weight.py            # apply
    .venv/bin/python MICS-CH/src/patch_child_sample_weight.py --verify   # check
"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "child_sample_weight"
CP = "CP_child_sample_weight"
OUTLIER_MEAN = 5.0  # dataset mean above this = un-normalised -> divide by mean

RECOVER = {
    'Albania MICS2 2000': 'CHWEIGHT', 'Argentina_MICS4_Datasets': 'chweight',
    'Azerbaijan MICS2 2000': 'CHWEIGHT', 'Bolivia 2000 MICS_Datasets': 'CHWEIGHT',
    'Burundi MICS 2005 SPSS Datasets': 'chweight', 'Cameroon 2000 MICS_Datasets': 'CHWEIGHT',
    'Central African Republic 2000 MICS_Datasets': 'CHWEIGHT',
    'Central African Republic MICS 2006 SPSS Datasets': 'chweight',
    'Chad 2000 MICS_Datasets': 'CHWEIGHT',
    'Congo, Democratic Republic of 2001 MICS_Datasets': 'CHWEIGHT',
    "Cote d'Ivoire 2000 MICS_Datasets": 'CHWEIGHT', 'Cuba MICS 2006 SPSS Datasets': 'CHWEIGHT',
    'Cuba MICS6 Datasets': 'chweight', 'Cuba_MICS4_Datasets': 'chweight',
    'Cuba_MICS5_Datasets': 'chweight', 'Djibouti MICS 2006 SPSS Datasets': 'chweight',
    'Dominican Republic 2000 MICS_Datasets': 'CHWEIGHT',
    'Equatorial Guinea 2000 MICS_Datasets': 'CHWEIGHT', 'Gambia 2005-06 MICS_Datasets': 'chweight',
    'Guinea Bissau 2000 MICS_Datasets': 'CHWEIGHT', 'Guyana 2000 MICS_Datasets': 'CHWEIGHT',
    'Guyana MICS 2006-07 SPSS Datasets': 'chweight', 'Indonesia MICS2 2000_Datasets': 'CHWEIGHT',
    'Iraq 2000 MICS_Datasets': 'CHWEIGHT', 'Jamaica 2005 MICS_Datasets': 'chweight',
    'Kenya (Mombasa Informal Settlements)_MICS4_Datasets': 'chweight',
    'Lao PDR MICS2 2000_Datasets': 'CHWEIGHT', 'Madagascar 2000 MICS_Datasets': 'CHWEIGHT',
    'Mali_MICS4_Datasets': 'chweight', 'Moldova MICS2 2000_Datasets': 'CHWEIGHT',
    'Montenegro 2005-06 MICS_Datasets': 'chweight', 'Myanmar 2000 MICS_Datasets': 'CHWEIGHT',
    'Niger 2000 MICS_Datasets': 'CHWEIGHT', 'Nigeria_MICS4_Datasets': 'chweight',
    'Philippines 1999 MICS_Datasets': 'CHWEIGHT', 'Rwanda 2000 MICS_Datasets': 'CHWEIGHT',
    'Sao Tome and Principe_MICS5_Datasets': 'CHWEIGHT',
    'Sao Tome and Principle 2000 MICS_Datasets': 'CHWEIGHT', 'Senegal 2000 MICS_Datasets': 'CHWEIGHT',
    'Sierra Leone 2000 MICS_Datasets': 'CHWEIGHT', 'State of Palestine_MICS4_Datasets': 'chweight',
    'Sudan 2000 MICS (North only)_Datasets': 'CHWEIGHT',
    'Sudan 2000 MICS (South only)_Datasets': 'chweight', 'Suriname 2000 MICS_Datasets': 'CHWEIGHT',
    'Togo 2000 MICS_Datasets': 'CHWEIGHT', 'Togo MICS 2006 SPSS Datasets': 'chweight',
    'Trinidad and Tobago 2000 MICS_Datasets': 'CHWEIGHT',
    'Trinidad and Tobago MICS 2006 SPSS Datasets': 'chweight', 'Venezuela 2000 MICS_Datasets': 'CHWEIGHT',
    'Viet Nam 2000 MICS_Datasets': 'CHWEIGHT', 'Zambia 1999 MICS_Datasets': 'CHWEIGHT',
}


def _find_ch_sav(ds):
    d = RAW / ds
    if (d / "ch.sav").exists():
        return d / "ch.sav"
    cands = [p for p in d.glob("*.sav") if p.stem.lower().startswith("ch")] if d.exists() else []
    return cands[0] if cands else None


def _recover(ds, col, parquet_ds):
    import pyreadstat
    sav = _find_ch_sav(ds)
    if sav is None:
        return None, "no CH SAV"
    df, _ = pyreadstat.read_sav(str(sav))
    low = {c.lower(): c for c in df.columns}
    cc = low.get(col.lower())
    hh = low.get("hh2") or low.get("chhhno")
    if cc is None or hh is None:
        return None, f"col {col}({cc}) or hh-key({hh}) absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[hh].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 1.0:
        return None, f"guard household_number=={hh} {(a==b).mean():.2%}"
    return pd.to_numeric(df[cc].reset_index(drop=True), errors="coerce"), "ok"


def _divisors(df):
    """{dataset: divisor} — dataset mean where > OUTLIER_MEAN, else 1."""
    base = pd.to_numeric(df[BASE], errors="coerce")
    means = base.groupby(df["dataset_name"]).mean()
    return {ds: (m if m > OUTLIER_MEAN else 1.0) for ds, m in means.items()}


def _compute(df):
    base = pd.to_numeric(df[BASE], errors="coerce")
    div = df["dataset_name"].map(_divisors(df)).astype(float)
    return base / div


def patch_parquet(verify):
    if verify:
        df = pd.read_parquet(PARQUET, columns=["dataset_name", BASE, CP])
        cp = _compute(df)
        ok = df[CP].equals(cp)
        n = int(cp.notna().sum()); nds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} datasets "
              f"(mean={cp.mean():.3f})")
        return []
    df = pd.read_parquet(PARQUET)
    applied = []
    for ds, col in RECOVER.items():
        mask = (df["dataset_name"] == ds).values
        if not mask.any():
            continue
        s, note = _recover(ds, col, df.loc[mask])
        if s is None:
            print(f"  [skip] {ds[:40]}: {note}")
            continue
        idx = df.index[mask]
        df.loc[idx, BASE] = pd.Series(s.values, index=idx).where(s.notna().values, df.loc[idx, BASE])
        applied.append(ds)
        print(f"  [ok]   {ds[:40]}: base <- {col} ({int(s.notna().sum())} rows)")
    df[CP] = _compute(df)
    if not PARQUET.with_suffix(".parquet.bak_p21").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p21"))
    df.to_parquet(PARQUET, index=False)
    outliers = {ds: d for ds, d in _divisors(df).items() if d != 1.0}
    print(f"  parquet: {CP} non-null={int(df[CP].notna().sum())} across "
          f"{df.loc[df[CP].notna(),'dataset_name'].nunique()} datasets; recovered {len(applied)}; "
          f"normalised outliers={ {k: round(v,1) for k,v in outliers.items()} }")
    return applied


def patch_yaml(applied):
    if not applied:
        print("  yaml: nothing to add"); return
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    entries = al.setdefault(BASE, [])
    have = {(e["dataset_name"], (e.get("column_in_raw_sav") or "")) for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p21").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p21"))
    added = 0
    for ds in applied:
        if (ds, RECOVER[ds]) in have:
            continue
        entries.append({
            "canonical_text": "Child sample weight", "canonical_varname": BASE,
            "column_in_raw_sav": RECOVER[ds], "column_label_in_english": "Child sample weight",
            "component": None, "confidence": "high", "dataset_name": ds, "derivation": None,
            "entities": [], "entity_operator": None, "event": None, "is_compound": False,
            "measure_type": "survey_design", "needs_review": False, "relation": None,
            "response_type": "numeric", "source_kind": "explicit",
        })
        added += 1
    yaml.safe_dump(al, open(ALIGN, "w", encoding="utf-8"), allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {BASE} mappings")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied, verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor()
    T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL), '
                    f'ROUND(AVG("{CP}")::numeric,3), ROUND(MAX("{CP}")::numeric,1) FROM {T}')
        n, nds, mean, mx = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} datasets (mean={mean}, max={mx}); "
              f"ind_que rows={cur.fetchone()[0]}")
        conn.close(); return

    pdf = pd.read_parquet(PARQUET)
    if not _col_exists(cur, "final_CH_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    # base copy for all; then normalise non-recovered outliers; recovered reinserted
    cur.execute(f'UPDATE {T} SET "{CP}" = {BASE}::float')
    outliers = {ds: d for ds, d in _divisors(pdf).items()
                if d != 1.0 and ds not in applied}
    for ds, d in outliers.items():
        cur.execute(f'UPDATE {T} SET "{CP}" = {BASE}::float / %s WHERE dataset_name=%s', (d, ds))
    print(f"  db: CP_ = base, normalised {len(outliers)} non-recovered outliers")

    if applied:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name='final_CH_MICS'""")
        dbtype = dict(cur.fetchall()); cols = list(pdf.columns)
        assert all(c in dbtype for c in cols)
        cur.execute(f'DELETE FROM {T} WHERE dataset_name = ANY(%s)', (applied,))
        sub = pdf[pdf["dataset_name"].isin(applied)].copy()
        for c in cols:
            if dbtype.get(c) == "bigint":
                sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
            elif dbtype.get(c) == "double precision":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        collist = ", ".join(f'"{c}"' for c in cols)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        print(f"  db: re-inserted {len(applied)} recovered datasets")

    for ds in applied:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{BASE}' AND dataset_name=%s "
                    f"AND column_in_raw_sav=%s", (ds, RECOVER[ds]))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (BASE, ds, RECOVER[ds], "Child sample weight", "explicit",
             "survey_design", "Child sample weight"))
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{BASE}' ''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que {CP} rows={cur.fetchone()[0]}")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P21 child_sample_weight -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(applied)
    print("== database =="); patch_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
