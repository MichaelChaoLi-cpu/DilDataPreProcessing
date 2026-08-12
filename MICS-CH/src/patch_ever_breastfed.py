"""
P29 — `CP_ever_breastfed` (CH): harmonized "was the child ever breastfed?" 1/0.

Value alignment: 1=Yes -> 1, 2=No -> 0, sentinels (7/8/9 DK/missing, stray 3) -> NULL
(the coding is uniform 1=Yes/2=No across all mapped datasets, multilingual labels).

Translation-gap recovery: the question was aligned for 205 datasets, but 31 more have
it UNMAPPED in their raw SAV under a non-English label — mostly French "L'enfant a été
allaité", Spanish "El niño fue amamantado", Portuguese "Alimentado com leite materno"
(BF1 in MICS2-5, BD2 in MICS6). Recovered here by guarded positional backfill, with the
value classified from that column's own SAV labels. Look-alikes (diarrhoea CA1, "still
breastfeeding", "...yesterday", drank-water) are excluded by construction. 205 -> 236.

Usage:
    .venv/bin/python MICS-CH/src/patch_ever_breastfed.py            # apply
    .venv/bin/python MICS-CH/src/patch_ever_breastfed.py --verify
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

BASE = "ever_breastfed"
CP = "CP_ever_breastfed"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

# 31 datasets with an unmapped ever-breastfed column (raw SAV col).
RECOVER = {
    'Algeria MICS6 Datasets': 'BD2', 'Algeria_MICS4_Datasets': 'BF1',
    'Benin_MICS5_Datasets': 'BD2', 'Cameroon_MICS5_Datasets': 'BD2',
    'Central African Republic MICS6 Datasets': 'BD2', 'Central African Republic_MICS4_Datasets': 'BF1',
    'Chad MICS6 Datasets': 'BD2', 'Chad_MICS4_Datasets': 'BF1', 'Congo_MICS5_Datasets': 'BD2',
    "Côte d'Ivoire_MICS5Datasets": 'BD2', 'Cuba MICS 2006 SPSS Datasets': 'BF1',
    'DRCongo MICS6 SPSS Datafiles': 'BD2', 'Guinea Bissau 2000 MICS_Datasets': 'BF1',
    'Guinea_MICS5_Datasets': 'BD2', 'Madagascar (South)_ MICS4_Datasets': 'BF1',
    'Madagascar 2000 MICS_Datasets': 'BF1', 'Madagascar MICS6 SPSS dataset': 'BD2',
    'Mali_MICS4_Datasets': 'BF1', 'Mali_MICS5_Datasets': 'BD2', 'Mauritania_MICS4_Datasets': 'BF1',
    'Mauritania_MICS5_Datasets': 'BD2', 'Mauritania_MICS5_Datasets 2': 'BD2',
    'Niger 2000 MICS_Datasets': 'BF1', 'Panama_MICS5_Datasets': 'BF1',
    'Rwanda 2000 MICS_Datasets': 'BF1', 'Senegal (Dakar)_MICS5_Datasets': 'BD2',
    'Togo 2000 MICS_Datasets': 'BF1', 'Togo MICS6 SPSS Datasets': 'BD2',
    'Togo MICS6 SPSS Datasets (1)': 'BD2', 'Togo_MICS4_Datasets': 'BF1',
    'Tunisia_MICS4_Datasets': 'BF1',
}


def _fold(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(c)).lower()


_YES = re.compile(r"^(yes|oui|s[ií]|sim|da)\b")
_NO = re.compile(r"^(no|non|n[ãa]o)\b")
_MISS = re.compile(r"(dk|nsp|no sabe|missing|manquant|omit|special|ns\b|don.?t|no response|no responde|em falta)")


def _classify(vl):
    """{code -> 1(yes)/0(no)/None} from a column's value labels."""
    out = {}
    for k, v in (vl or {}).items():
        try:
            code = float(k)
        except (TypeError, ValueError):
            continue
        f = _fold(v)
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


def _recover(ds, col, parquet_ds):
    import pyreadstat
    sav = RAW / ds / "ch.sav"
    if not sav.exists():
        for alt in RAW.glob(f"{ds}/*.sav"):
            if "ch" in alt.name.lower():
                sav = alt; break
    if not sav.exists():
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
    return out, f"{col} n={int(out.notna().sum())}"


# ---------------------------------------------------------------------------

def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={n} / {nds} ds; out-of-range={bad}")
        return []
    if not PARQUET.with_suffix(".parquet.bak_p29").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p29"))
    avail = set(df.dataset_name.unique())
    nfc = {unicodedata.normalize("NFC", a): a for a in avail}
    cp = _harmonize(df[BASE])                       # 205 mapped datasets
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
            (BASE, ds, RECOVER.get(unicodedata.normalize("NFC", ds), RECOVER.get(ds, "BF1")),
             "Ever breastfed (recovered P29)", "explicit", "breastfeeding", "Child ever breastfed"))
    cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
        column_label_in_english,source_kind,measure_type,canonical_text)
        SELECT %s,dataset_name,column_in_raw_sav,column_label_in_english,source_kind,measure_type,canonical_text
        FROM {I} WHERE canonical_varname=%s''', (CP, BASE))
    print("  db: ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P29 CP_ever_breastfed — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = apply(verify)
    print("== database =="); sync_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
