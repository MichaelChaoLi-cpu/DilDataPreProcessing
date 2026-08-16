"""
P38 — `CP_fed_yogurt_yesterday` (CH): child drank or ate yogurt yesterday, 1/0.

Rebuilt FRESH from raw, label-driven, because `infant_fed_yogurt_yesterday` (148
datasets) is contaminated: it mixed the yes/no item with its TIMES-count companion
(values 3/4/7 appear — BD8A1/BD8AN "Times drank or ate yogurt", BF14 "Nombre fois")
and, for some datasets, cheese / mixed-dairy / diarrhoea-liquid columns.

Per dataset, select EVERY column whose label is yogurt AND is a yes/no item, then
OR-combine them (a child counts as yes if any yogurt item is yes):
  - BD8A  "Child drank or ate yogurt yesterday" (MICS5/6, already covers drink+eat)
  - BD7F / BD7F2  "Child drank (sweet) yogurt / ayran / kefir yogurt drinks" (MICS6-2023
    split the liquid form out; also Algeria "yaourt liquide")
  - BF13  "L'enfant a bu ou mangé des yaourts hier" (MICS4)
  - BF3I  "Child received yogurt" (a few MICS4), ca2e "Yoghurt drink" (Iraq 2006)

Excluded by construction:
  - TIMES-count companions (label has times/nombre/fois/number) — not yes/no;
  - cheese / mixed dairy ("cheese, yogurt or other milk products"; "fromage ou yaourt";
    Mexico "otros alimentos… excepto yogurt");
  - diarrhoea catch-all liquids ("Other (yogurt, sour milk, tea, sugar…)"; "autre liquide").

Value: 1=Yes -> 1, 2=No -> 0; sentinels (7/8/9) -> NULL. Guard: SAV row count ==
parquet AND household_number == SAV HH id >= 99.9%.

Usage:
    .venv/bin/python MICS-CH/src/patch_fed_yogurt.py            # apply
    .venv/bin/python MICS-CH/src/patch_fed_yogurt.py --verify
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

CP = "CP_fed_yogurt_yesterday"
BASE = "infant_fed_yogurt_yesterday"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

_YOG = re.compile(r"(yogurt|yoghurt|yaourt|yogur|iogurt|joghurt|yougourt|\bayran\b|\bkefir\b)")
_COUNT = re.compile(r"(times|nombre|fois|number|veces|vezes|cuantas|quantas|numero|no\. of|how many)")
# cheese / mixed-dairy / negation / diarrhoea catch-all liquids
_EXCL = re.compile(r"(cheese|fromage|queso|queijo|kase|except|excepto|exceto|sauf|salvo|"
                   r"sour milk|lait caille|\btea\b|\bthe\b|sugar|salt|solution|"
                   r"other liquid|autre liquide|otros alimentos|other milk product|"
                   r"produit a base de lait)")


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


def _is_yesno(vl):
    ks = {int(float(k)) for k in (vl or {}) if str(k).replace(".", "").replace("-", "").isdigit()}
    return 1 in ks and 2 in ks


def _select_cols(meta):
    """Names of every yogurt yes/no column (excluding counts / cheese / catch-alls)."""
    out = []
    for col, lbl in meta.column_names_to_labels.items():
        f = _fold(lbl)
        if _YOG.search(f) and not _COUNT.search(f) and not _EXCL.search(f):
            if _is_yesno(meta.variable_value_labels.get(col, {})):
                out.append(col)
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
    ycols = _select_cols(meta)
    if not ycols:
        return None, "no yogurt column"
    key = next((_find(meta.column_names, k) for k in GUARD_KEYS if _find(meta.column_names, k)), None)
    if key is None:
        return None, "no guard key"
    try:
        df, _ = pyreadstat.read_sav(str(sav), usecols=list(dict.fromkeys(ycols + [key])),
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
    df = df.reset_index(drop=True)
    anyyes = pd.Series(False, index=df.index)
    anyno = pd.Series(False, index=df.index)
    for col in ycols:
        cmap = _classify(meta.variable_value_labels.get(col, {}))
        v = pd.to_numeric(df[col], errors="coerce").map(lambda x: cmap.get(x) if pd.notna(x) else None)
        anyyes |= (v == 1).fillna(False)
        anyno |= (v == 0).fillna(False)
    out = pd.Series(np.where(anyyes, 1.0, np.where(anyno, 0.0, np.nan)), index=df.index)
    return out, f"[{'+'.join(ycols)}] n={int(out.notna().sum())} g={g:.1%}"


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={n} / {nds} ds; out-of-range={bad}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p38").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p38"))
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
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND "{CP}" NOT IN (0,1)')
        print(f"  db {CP}: non-null={n} / {nds} ds; out-of-range={cur.fetchone()[0]}")
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
        SELECT %s, dataset_name, 'BD8A/BD7F',
               'Child drank or ate yogurt yesterday',
               'derived', measure_type, 'Child drank or ate yogurt yesterday'
        FROM {I} WHERE canonical_varname=%s''', (CP, BASE))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P38 CP_fed_yogurt_yesterday — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
