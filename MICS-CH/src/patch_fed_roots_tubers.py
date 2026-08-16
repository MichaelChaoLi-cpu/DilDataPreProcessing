"""
P36 — `CP_fed_roots_tubers_plantains_yesterday` (CH): child ate white roots, tubers or
plantains yesterday, 1/0.

Source: **BD8E** — "Child ate white potatoes, white yams, manioc, cassava or any other
foods made from roots yesterday" (the MICS5/6 24-hour white-roots-and-tubers food-group
item; some datasets also list plantains, e.g. Cuba "plátano verde"). Verified: all 115
datasets carrying BD8E label it unambiguously as white roots/tubers across EN/FR/ES/PT
(potatoes/yams/manioc/cassava/"pommes de terre, igname, manioc"/"batata, inhame,
mandioca"/"papa, yuca, ñame"); value labels all yes/no.

Base = the existing `dd_white_roots_tubers` (94 datasets: 93 from BD8E + 1 Madagascar-
South BF15DX "aliments à base de racines", verified roots). Recovers 22 more datasets
whose BD8E was unmapped. BD8E-only scope keeps the construct identical; the MICS4 roots
items under other codes (Ghana DD1H, CAR BF19C, Mali BF16C) are left out of this scope.

Value alignment: 1=Yes -> 1, 2=No -> 0; sentinels (7 incoherent, 8/9 DK/missing) -> NULL.

Usage:
    .venv/bin/python MICS-CH/src/patch_fed_roots_tubers.py            # apply
    .venv/bin/python MICS-CH/src/patch_fed_roots_tubers.py --verify
"""
from __future__ import annotations

import io
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "dd_white_roots_tubers"
CP = "CP_fed_roots_tubers_plantains_yesterday"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

# 22 datasets carrying BD8E in the raw SAV but with it unmapped.
_RECOVER_DATASETS = [
    "Central African Republic MICS6 Datasets", "Congo_MICS5_Datasets", "Costa Rica MICS6 Datasets",
    "Cuba_MICS5_Datasets", "Dominican Republic MICS6 Datasets", "Dominican Republic_MICS5_Datasets",
    "DRCongo MICS6 SPSS Datafiles", "Guinea Bissau MICS6 Datasets", "Guinea Bissau_MICS5_Datasets",
    "Guinea_MICS5_Datasets", "Honduras MICS6 Datasets", "Mexico_MICS5_Datasets",
    "Mongolia (Khuvsgul Aimag)_MICS5_Datasets", "Mongolia (Nalaikh District)_MICS5_Datasets",
    "Montenegro (Roma Settlements)_MICS5_Datasets", "Montenegro_MICS5_Datasets",
    "Paraguay_MICS5_Datasets", "Sao Tome and Principe MICS6 Datasets",
    "Sao Tome and Principe MICS6 Datasets (1)", "Sao Tome and Principe_MICS5_Datasets",
    "Turkmenistan_MICS5_Datasets", "Turkmenistan_MICS5_Datasets 2",
]
RECOVER = {ds: "BD8E" for ds in _RECOVER_DATASETS}


def _fold(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(c)).lower()


def _fold_ascii(x):
    """Fold AND drop non-letter chars so mojibake labels still match (e.g. Portuguese
    'Não' stored as 'NÃ£o' -> 'nao')."""
    return re.sub(r"[^a-z ]", "", _fold(x))


_YES = re.compile(r"^(yes|oui|s[ií]|sim|da)\b")
_NO = re.compile(r"^(no|non|n[ãa]o)\b")
_MISS = re.compile(r"(dk|nsp|no sabe|missing|manquant|omit|special|ns\b|don.?t|no response|"
                   r"no responde|em falta|incoheren|incoheren|\bsabe\b|ne sait|nsp)")


def _classify(vl):
    """{code -> 1(yes)/0(no)/None} from a column's value labels."""
    out = {}
    for k, v in (vl or {}).items():
        try:
            code = float(k)
        except (TypeError, ValueError):
            continue
        f = _fold_ascii(v)
        if _MISS.search(f):
            out[code] = None
        elif _YES.match(f):
            out[code] = 1
        elif _NO.match(f):
            out[code] = 0
        else:
            out[code] = None
    return out


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _harmonize(base):
    v = pd.to_numeric(base, errors="coerce")
    return pd.Series(np.where(v == 1, 1.0, np.where(v == 2, 0.0, np.nan)), index=base.index)


def _sav_dir(ds):
    """Resolve the raw dir even when the on-disk name uses a different unicode
    normalization (Côte d'Ivoire NFC vs NFD)."""
    for cand in (ds, unicodedata.normalize("NFC", ds), unicodedata.normalize("NFD", ds)):
        if (RAW / cand).is_dir():
            return RAW / cand
    tgt = unicodedata.normalize("NFC", ds)
    for d in RAW.iterdir():
        if d.is_dir() and unicodedata.normalize("NFC", d.name) == tgt:
            return d
    return None


def _recover(ds, col, parquet_ds):
    import pyreadstat
    d = _sav_dir(ds)
    if d is None:
        return None, "no dir"
    sav = d / "ch.sav"
    if not sav.exists():
        sav = next((p for p in d.glob("*.sav") if "ch" in p.name.lower()), None)
    if sav is None or not sav.exists():
        return None, "no SAV"
    df, meta = pyreadstat.read_sav(str(sav), apply_value_formats=False)
    c = _find(df.columns, col)
    if c is None:
        return None, f"col {col} absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    key = next((_find(df.columns, k) for k in GUARD_KEYS if _find(df.columns, k)), None)
    if key is None:
        return None, "no guard key"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 0.999:
        return None, f"guard {(a==b).mean():.3%} ({key})"
    cmap = _classify(meta.variable_value_labels.get(c, {}))
    v = pd.to_numeric(df[c].reset_index(drop=True), errors="coerce")
    out = v.map(lambda x: cmap.get(x) if pd.notna(x) else None).astype("float64")
    return out, f"{c} n={int(out.notna().sum())}"


# ---------------------------------------------------------------------------

def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={n} / {nds} ds; out-of-range={bad}")
        return []
    if not PARQUET.with_suffix(".parquet.bak_p36").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p36"))
    avail = set(df.dataset_name.unique())
    nfc = {unicodedata.normalize("NFC", a): a for a in avail}
    cp = _harmonize(df[BASE])                       # 94 mapped datasets
    applied, skipped = [], []
    for ds, col in RECOVER.items():
        actual = ds if ds in avail else nfc.get(unicodedata.normalize("NFC", ds))
        if actual is None:
            skipped.append((ds, "not in parquet")); continue
        m = df.dataset_name == actual
        ser, note = _recover(ds, col, df.loc[m])
        if ser is None:
            skipped.append((ds, note)); continue
        cp.loc[m] = ser.values
        applied.append(actual)
        print(f"  [ok]   {ds}: {note}")
    for ds, n in skipped:
        print(f"  [skip] {ds}: {n}")
    df[CP] = cp.values
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} / {nds} datasets; "
          f"recovered={len(applied)} skipped={len(skipped)}")
    return applied


def _col_exists(cur, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name='final_CH_MICS' AND column_name=%s""", (col,))
    return cur.fetchone() is not None


def sync_db(applied, verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND "{CP}" NOT IN (0,1)')
        print(f"  db {CP}: non-null={n} / {nds} ds; out-of-range={cur.fetchone()[0]}")
        conn.close(); return
    pdf = pd.read_parquet(PARQUET)
    if not _col_exists(cur, CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" SMALLINT')
    # mapped datasets: in-place 1->1 / 2->0
    cur.execute(f'UPDATE {T} SET "{CP}" = CASE WHEN {BASE}=1 THEN 1 WHEN {BASE}=2 THEN 0 ELSE NULL END '
                f'WHERE {BASE} IS NOT NULL')
    # recovered datasets: reinsert from patched parquet
    if applied:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name='final_CH_MICS'""")
        dbtype = dict(cur.fetchall()); cols = [c for c in pdf.columns if c in dbtype]
        for ds in applied:
            sub = pdf[pdf.dataset_name == ds].copy()
            for c in cols:
                if dbtype.get(c) in ("bigint", "smallint", "integer"):
                    sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
                elif dbtype.get(c) in ("double precision", "real", "numeric"):
                    sub[c] = pd.to_numeric(sub[c], errors="coerce")
            cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
            buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
            cl = ", ".join(f'"{c}"' for c in cols)
            cur.copy_expert(f'COPY {T} ({cl}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        print(f"  db: reinserted {len(applied)} recovered datasets")
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (CP,))
    for ds in applied:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s AND dataset_name=%s", (BASE, ds))
        cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
            column_label_in_english,source_kind,measure_type,canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (BASE, ds, RECOVER.get(unicodedata.normalize("NFC", ds), RECOVER.get(ds, "BD8E")),
             "Child ate white roots/tubers yesterday (recovered P36)", "explicit",
             "infant_feeding", "Child ate white roots, tubers or plantains yesterday"))
    cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
        column_label_in_english,source_kind,measure_type,canonical_text)
        SELECT %s,dataset_name,column_in_raw_sav,column_label_in_english,source_kind,measure_type,canonical_text
        FROM {I} WHERE canonical_varname=%s''', (CP, BASE))
    print("  db: ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P36 CP_fed_roots_tubers_plantains_yesterday — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = apply(verify)
    print("== database =="); sync_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
