"""
P31 — `CP_fed_milk_yesterday` (CH): re-derived "child drank milk yesterday"
(infant formula OR animal/other milk), fixing a systematic alignment error.

The raw `infant_fed_milk_yesterday` is semantically inconsistent: for ~52 MICS6
datasets it was mapped to `BD8N` = "child ate CHEESE or other food made from milk"
(a solid dairy FOOD, not milk drinking); Cuba MICS4 -> juice, Sao Tome MICS5 ->
fish. And even the correctly-mapped ones mix formula / animal-milk / combined-milk.

`CP_fed_milk_yesterday` = 1 if the child drank **infant formula (BD7D) OR animal/
other milk (BD7E)** yesterday, 0 if neither, NULL if both missing:
- formula component: `infant_fed_formula_yesterday` (cleaned; yes/no or times-count);
- milk component: `infant_fed_milk_yesterday` for datasets where that column is
  genuinely a milk-drink item; for the 54 mis-aligned MICS6 datasets the real animal-
  milk item `BD7E` is recovered from the raw SAV (guarded positional). Cheese/juice/
  fish are excluded. Cuba MICS4 has no animal-milk item -> formula only.

Usage:
    .venv/bin/python MICS-CH/src/patch_fed_milk_yesterday.py            # apply
    .venv/bin/python MICS-CH/src/patch_fed_milk_yesterday.py --verify
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

FORMULA = "infant_fed_formula_yesterday"
MILK = "infant_fed_milk_yesterday"
CP = "CP_fed_milk_yesterday"
SENT = {7.0, 8.0, 9.0, 97.0, 98.0, 99.0, 999.0}
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

# 54 datasets whose `infant_fed_milk_yesterday` is NOT a milk-drink item (BD8N cheese /
# juice / fish) -> recover the real animal-milk item BD7E from the raw SAV instead.
RECOVER_BD7E = {
    'Algeria MICS6 Datasets', 'Azerbaijan MICS6 2023 Datasets', 'Bangladesh MICS6 SPSS Datasets',
    'Belarus MICS6 Datasets', 'Cuba MICS6 Datasets', 'Fiji MICS6 Datasets',
    'Georgia MICS6 SPSS Datasets', 'Ghana MICS6 SPSS Datasets', 'Guyana MICS6 Datasets',
    'Guyana MICS6 Datasets (1)', 'Guyana MICS6 Datasets (2)', 'Iraq MICS6 Datasets',
    'Kiribati MICS6 Datasets', 'Kiribati MICS6 Datasets (1)',
    'Kosovo (UNSCR 1244) (Roma, Ashkali and Egyptian Communities) MICS6 Datasets',
    'Kosovo (UNSCR 1244) MICS6 Datasets', 'Kyrgyz Republic MICS6 Datasets',
    'Kyrgyzstan MICS6 2023 Datasets', 'Lao PDR MICS6 2023 Datasets', 'Lao PDR MICS6 Datasets',
    'Lesotho_MICS6_datasets', 'MICS6 Samoa Datasets', 'MICS6 Samoa Datasets 2', 'Malawi MICS6 SPSS',
    'Mongolia MICS 2018 SPSS Datasets', 'Montenegro (Roma Settlements) MICS6 Datasets',
    'Montenegro MICS6 Datasets', 'Nauru MICS6 2023 Datasets', 'Nauru MICS6 2023 Datasets 2',
    'Nepal MICS6 Datasets', 'Pakistan Azad Jammu and Kashmir MICS6 Datasets',
    'Pakistan Khyber Pakhtunkhwa MICS6 Datasets', 'Pakistan Punjab MICS6 Datasets',
    'Pakistan Sindh MICS6 Datasets', 'Republic of North Macedonia (Roma Settlements) MICS6 Datasets',
    'Republic of North Macedonia MICS6 Datasets', 'Sao Tome and Principe_MICS5_Datasets',
    'Serbia (Roma Settlements) MICS6 Datasets', 'Serbia MICS6 Datasets', 'Sierra Leone MICS6 Datasets',
    'State of Palestine MICS6 Datasets', 'Suriname MICS6 SPSS Datafiles', 'Thailand MICS6 Datasets',
    'The Gambia MICS6 Datasets', 'Tonga MICS6 Datasets', 'Tonga MICS6 Datasets 2',
    'Tunisia MICS6 Datasets', 'Turkmenistan MICS6 SPSS Datasets', 'Turks and Caicos Islands MICS6 Datasets',
    'Tuvalu MICS6 Datasets', 'Tuvalu MICS6 Datasets (1)', 'Vanuatu MICS6 Datasets',
    'Viet Nam MICS6 Datasets', 'Zimbabwe MICS6 SPSS Datasets',
}
# `infant_fed_milk_yesterday` is not a valid milk-drink item for these (excluded above
# plus Cuba MICS4 = juice, which has no animal-milk item at all).
MILK_INVALID = RECOVER_BD7E | {'Cuba_MICS4_Datasets'}


def _fold(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(c)).lower()


_YES = re.compile(r"^(yes|oui|s[ií]|sim|da)\b")
_NO = re.compile(r"^(no|non|n[ãa]o)\b")


def _to_yesno(sub):
    """Per-dataset yes/no from a value column that may be yes/no (1/2) or a times-count."""
    v = pd.to_numeric(sub, errors="coerce")
    clean = v[~v.isin(list(SENT)) & v.notna()]
    out = pd.Series(np.nan, index=sub.index)
    if clean.empty:
        return out
    if clean.max() > 2:                       # times-count: >=1 fed, 0 not
        out[v == 0] = 0.0
        out[(v >= 1) & (~v.isin(list(SENT)))] = 1.0
    else:                                     # yes/no: 1 yes, 2 no
        out[v == 1] = 1.0
        out[v == 2] = 0.0
    return out


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _recover_bd7e(ds, parquet_ds):
    import pyreadstat
    sav = RAW / ds / "ch.sav"
    if not sav.exists():
        for alt in RAW.glob(f"{ds}/*.sav"):
            if "ch" in alt.name.lower():
                sav = alt; break
    if not sav.exists():
        return None, "no SAV"
    df, meta = pyreadstat.read_sav(str(sav), apply_value_formats=False)
    c = _find(df.columns, "BD7E")
    if c is None:
        return None, "BD7E absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    key = next((_find(df.columns, k) for k in GUARD_KEYS if _find(df.columns, k)), None)
    if key is None:
        return None, "no guard key"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 0.999:
        return None, f"guard {(a==b).mean():.3%}"
    return _to_yesno(df[c].reset_index(drop=True)), "BD7E"


def derive(df):
    # formula component (all datasets), per-dataset yes/no-or-count
    formula = df.groupby("dataset_name", group_keys=False)[FORMULA].apply(_to_yesno)
    # milk component: valid `infant_fed_milk_yesterday` datasets only
    milk = pd.Series(np.nan, index=df.index)
    valid_milk = ~df.dataset_name.isin(MILK_INVALID)
    milk[valid_milk] = df[valid_milk].groupby("dataset_name", group_keys=False)[MILK].apply(_to_yesno)
    return formula, milk


def _combine(formula, milk):
    anyyes = (formula == 1) | (milk == 1)
    anyno = (formula == 0) | (milk == 0)
    return pd.Series(np.where(anyyes, 1.0, np.where(anyno, 0.0, np.nan)), index=formula.index)


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={n} / {nds} ds; out-of-range={bad}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p31").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p31"))
    avail = set(df.dataset_name.unique())
    nfc = {unicodedata.normalize("NFC", a): a for a in avail}
    formula, milk = derive(df)
    rec, skip = [], []
    for ds in RECOVER_BD7E:
        actual = ds if ds in avail else nfc.get(unicodedata.normalize("NFC", ds))
        if actual is None:
            skip.append((ds, "not in parquet")); continue
        m = df.dataset_name == actual
        ser, note = _recover_bd7e(ds, df.loc[m])
        if ser is None:
            skip.append((ds, note)); continue
        milk.loc[m] = ser.values
        rec.append(actual)
    for ds, n in skip:
        print(f"  [skip] {ds}: {n}")
    cp = _combine(formula, milk)
    df[CP] = cp.values
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} / {nds} datasets; "
          f"rate={df[CP].mean():.3f}; BD7E-recovered={len(rec)} skipped={len(skip)}")


def _cols(cur):
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_CH_MICS'""")
    return dict(cur.fetchall())


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        print(f"  db {CP}: {cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(PARQUET)
    if CP not in pdf.columns:
        raise SystemExit("run apply first")
    dbtype = _cols(cur)
    if CP not in dbtype:
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" SMALLINT'); dbtype = _cols(cur)
    cols = [c for c in pdf.columns if c in dbtype]
    assert set(dbtype) - set(pdf.columns) == set(), "DB has columns absent from parquet"
    for c in cols:
        if dbtype.get(c) in ("bigint", "smallint", "integer"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("Int64")
        elif dbtype.get(c) in ("double precision", "real", "numeric"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce")
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f'TRUNCATE {T}')
    for ds, sub in pdf.groupby("dataset_name", sort=False):
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (CP,))
    cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
        column_label_in_english,source_kind,measure_type,canonical_text)
        SELECT %s,dataset_name,column_in_raw_sav,column_label_in_english,'derived',measure_type,
               'Child drank milk (formula or animal milk) yesterday'
        FROM {I} WHERE canonical_varname=%s''', (CP, FORMULA))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P31 CP_fed_milk_yesterday — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
