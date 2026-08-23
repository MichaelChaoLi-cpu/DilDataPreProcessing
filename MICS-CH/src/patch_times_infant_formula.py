"""
P54 — `CP_times_infant_formula_yesterday` (CH): number of times the child was fed infant
formula yesterday (a COUNT, not yes/no).

Source by LABEL: the "times child drank infant formula" column — BD7D1 (MICS6), BF5 (MICS4/5),
BD7EN, BF3D1, DD2B. Raw times_infant_formula_yesterday was mapped for only 7 datasets; the
column is present in ~142.

Sentinel handling is per-dataset via the value labels (the coding differs by round):
  - MICS6 BD7D1: 7 = "7 OR MORE", 8 = DK, 9 = NO RESPONSE  -> 8/9 are sentinels;
  - MICS4 BF5:   1-12 are real counts, only 99 = Missing   -> 8-12 kept as counts.
A code is NULLed if its value label says DK/missing/NR/NSP/inconsistent, or if code >= 90;
otherwise the numeric count (1..~30) is kept (7 means "7 or more" where the survey caps there).

Guard: SAV row count == parquet AND household id matches >= 99.9%.

Usage:
    .venv/bin/python MICS-CH/src/patch_times_infant_formula.py            # apply
    .venv/bin/python MICS-CH/src/patch_times_infant_formula.py --verify
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

CP = "CP_times_infant_formula_yesterday"
BASE = "times_infant_formula_yesterday"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

# "times child drank infant formula" — a count column. TIMES word + FORMULA word.
_TIMES = re.compile(r"(times|nombre de fois|nombre.*fois|number of times|\bfois\b|veces|vezes|"
                    r"quantas vezes|cuantas veces|cantidad de veces)")
_FORM = re.compile(r"(formula|formule|maternise|infantil|lactea infantil|leite.*infantil|"
                   r"nan\b|lactogen)")
_EXCL = re.compile(r"(breast|maternel|materno|amamant|animal|tinned|cow|de vache|yogurt|yaourt|"
                   r"water|juice|jugo|diarrh|solid|porridge)")


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


def _select_col(meta):
    """The 'times child drank infant formula' count column (first label match)."""
    for col, lbl in meta.column_names_to_labels.items():
        f = _fold(lbl)
        if _TIMES.search(f) and _FORM.search(f) and not _EXCL.search(f):
            return col
    return None


def _sentinel_codes(vl):
    """Codes whose value label marks them DK/missing/etc -> to be NULLed."""
    out = set()
    for k, v in (vl or {}).items():
        try:
            code = float(k)
        except (TypeError, ValueError):
            continue
        if _MISS.search(_fold_ascii(v)):
            out.add(code)
    return out


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _sav_dir(ds):
    for cand in (ds, unicodedata.normalize("NFC", ds), unicodedata.normalize("NFD", ds)):
        if (RAW / cand).is_dir():
            return RAW / cand
    tgt = unicodedata.normalize("NFC", ds)
    for d in RAW.iterdir():
        if d.is_dir() and unicodedata.normalize("NFC", d.name) == tgt:
            return d
    return None


def _from_raw(ds, parquet_ds):
    import pyreadstat
    d = _sav_dir(ds)
    if d is None:
        return None, "no dir"
    sav = d / "ch.sav"
    if not sav.exists():
        sav = next((p for p in d.glob("*.sav") if "ch" in p.name.lower()), None)
    if sav is None or not sav.exists():
        return None, "no SAV"
    try:
        _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    except Exception as e:
        return None, f"meta err {e!s:.30}"
    col = _select_col(meta)
    if col is None:
        return None, "no times-formula column"
    key = next((_find(meta.column_names, k) for k in GUARD_KEYS if _find(meta.column_names, k)), None)
    if key is None:
        return None, "no guard key"
    try:
        df, _ = pyreadstat.read_sav(str(sav), usecols=list(dict.fromkeys([col, key])),
                                    apply_value_formats=False)
    except Exception as e:
        return None, f"read err {e!s:.30}"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
    g = (a == b).mean()
    if g < 0.999:
        return None, f"guard {g:.3%} ({key})"
    sent = _sentinel_codes(meta.variable_value_labels.get(col, {}))
    v = pd.to_numeric(df[col].reset_index(drop=True), errors="coerce")
    out = v.where(v.between(1, 89) & ~v.isin(sent))   # keep count 1..89, drop labeled sentinels
    out = out.astype("float64")
    return out, f"{col} n={int(out.notna().sum())} max={out.max()} g={g:.1%}"


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        rng = (float(df[CP].min()), float(df[CP].max())) if (CP in df.columns and df[CP].notna().any()) else None
        print(f"  parquet {CP}: valid={n} / {nds} ds; range={rng}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p54").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p54"))
    cp = np.full(len(df), np.nan)
    ok, skip = [], []
    for ds in df.dataset_name.unique():
        m = (df.dataset_name == ds).values
        ser, note = _from_raw(ds, df.loc[m])
        if ser is None:
            skip.append((ds, note)); continue
        cp[m] = ser.values
        ok.append((ds, note))
    for ds, note in ok:
        print(f"  [ok]   {ds[:40]:40s} {note}")
    for ds, note in sorted(skip):
        if note not in ("no yogurt column", "no dir", "no SAV") and "row mismatch" not in note:
            print(f"  [skip] {ds[:40]:40s} {note}")
    df[CP] = cp
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} / {nds} datasets; "
          f"sourced={len(ok)} skipped={len(skip)}")


def _cols(cur):
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_CH_MICS'""")
    return dict(cur.fetchall())


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT MIN("{CP}"), MAX("{CP}") FROM {T} WHERE "{CP}" IS NOT NULL')
        print(f"  db {CP}: non-null={n} / {nds} ds; range={cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(PARQUET)
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
        SELECT %s, dataset_name, 'BD7D1/BF5/BD7EN (times formula)',
               'Number of times child drank infant formula yesterday',
               'derived', measure_type, 'Number of times child fed infant formula yesterday'
        FROM {I} WHERE canonical_varname=%s''', (CP, BASE))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P54 CP_times_infant_formula_yesterday — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
