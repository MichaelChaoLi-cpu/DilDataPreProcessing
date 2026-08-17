"""
P51 — CP_respondent_native_language (WM / HH / CH): the respondent's native language /
mother tongue, DECODED to the language NAME (text) from the SAV value labels.

The raw respondent_native_language is a country-specific numeric code (WM14 / HH16 / UF14,
codes renumber per dataset), so it is not comparable as-is. This patch, per dataset, finds
the respondent's native-language column BY LABEL (mother tongue / native language / langue
maternelle / lengua materna …), reads it, and decodes each code to its value-label text
(the language name). Sentinels (DK / missing / no response / inconsistent) -> NULL.

Excluded by label: the household HEAD's language (HC1B "mother tongue of head" — a separate
canonical), the language OF INTERVIEW / QUESTIONNAIRE, and the French "école maternelle"
(nursery school) false friend of "langue maternelle".

Applied to every dataset that has a respondent-language question (both already-mapped and
unmapped), so the whole CP column is uniform decoded text. Guarded positional backfill:
SAV row count == parquet AND household id matches at >= 99.9%.

Usage:
    .venv/bin/python MICS-WM/src/patch_respondent_native_language.py wm|hh|ch
    .venv/bin/python MICS-WM/src/patch_respondent_native_language.py wm --verify
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

ROOT = Path(__file__).parent.parent.parent
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
CP = "CP_respondent_native_language"

MOD = {
    "wm": dict(parquet=ROOT / "MICS-WM/data/WM/processed_data/wm_merged.parquet",
               table="final_WM_MICS", ind="ind_que_WM_MICS", sav="wm", hhcol="hh_number"),
    "hh": dict(parquet=ROOT / "MICS-HH/data/HH/processed_data/hh_merged.parquet",
               table="final_HH_MICS", ind="ind_que_HH_MICS", sav="hh", hhcol="household_number"),
    "ch": dict(parquet=ROOT / "MICS-CH/data/CH/processed_data/ch_merged.parquet",
               table="final_CH_MICS", ind="ind_que_CH_MICS", sav="ch", hhcol="household_number"),
}
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]

_NL = re.compile(r"(mother tongue|native language|native tongue|first language|langue maternelle|"
                 r"lengua materna|idioma materno|lingua materna|langue du repondant|"
                 r"langue de la repondante|langue de la femme|langue parlee)")
_EXCL = re.compile(r"(head|chef de menage|\bjefe\b|chefe|"
                   r"ecole|school|frequent|escuela|escola|nursery|kindergarten|prescolaire|"
                   r"interview|questionnaire|entrevista|entretien|conducted in|langue de l.entretien)")
_MISS = re.compile(r"(^dk$|don.?t know|no sabe|ne sait|nsp|missing|manquant|em falta|sem resposta|"
                   r"no response|no responde|refus|inconsist|incoher|not stated|^ns$|^99$|omit)")


def _fold(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(c)).lower()


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _clean_lang(v):
    s = str(v).strip()
    if not s or _MISS.search(_fold(s)):
        return None
    return re.sub(r"\s+", " ", s)


def _sav_dir(ds):
    for cand in (ds, unicodedata.normalize("NFC", ds), unicodedata.normalize("NFD", ds)):
        if (RAW / cand).is_dir():
            return RAW / cand
    tgt = unicodedata.normalize("NFC", ds)
    for d in RAW.iterdir():
        if d.is_dir() and unicodedata.normalize("NFC", d.name) == tgt:
            return d
    return None


def _from_raw(ds, parquet_ds, sav_tag, hhcol):
    import pyreadstat
    d = _sav_dir(ds)
    if d is None:
        return None, "no dir"
    sav = next((p for p in d.glob("*.sav") if sav_tag in p.name.lower()), None)
    if sav is None:
        return None, "no SAV"
    try:
        _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    except Exception as e:
        return None, f"meta err {e!s:.30}"
    col = None
    for cc in meta.column_names:
        f = _fold(meta.column_names_to_labels.get(cc) or "")
        if _NL.search(f) and not _EXCL.search(f):
            col = cc; break
    if col is None:
        return None, "no native-language column"
    vl = meta.variable_value_labels.get(col, {})
    if not vl:
        return None, "no value labels (codes only)"
    key = next((_find(meta.column_names, k) for k in GUARD_KEYS if _find(meta.column_names, k)), None)
    need = [col] + ([key] if key else [])
    try:
        df, _ = pyreadstat.read_sav(str(sav), usecols=need, apply_value_formats=False)
    except Exception as e:
        return None, f"read err {e!s:.30}"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    if key is None:
        return None, "no guard key"
    a = pd.to_numeric(parquet_ds[hhcol].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
    g = (a == b).mean()
    if g < 0.999:
        return None, f"guard {g:.3%} ({key})"
    cmap = {float(k): _clean_lang(v) for k, v in vl.items()}
    raw = pd.to_numeric(df[col].reset_index(drop=True), errors="coerce")
    out = raw.map(lambda x: cmap.get(x) if pd.notna(x) else None)
    return out, f"{col} n={int(out.notna().sum())} langs={raw.dropna().nunique()} g={g:.1%}"


def apply(mode, verify):
    cfg = MOD[mode]
    df = pd.read_parquet(cfg["parquet"])
    if verify:
        if CP not in df.columns:
            print(f"  parquet {CP}: MISSING"); return
        n = int(df[CP].notna().sum()); nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
        print(f"  parquet {CP}: non-null={n} / {nds} ds; distinct langs={df[CP].dropna().nunique()}")
        return
    bak = cfg["parquet"].with_suffix(f".parquet.bak_p51")
    if not bak.exists():
        shutil.copy2(cfg["parquet"], bak)
    out = np.full(len(df), None, dtype=object)
    ok, skip = [], []
    for ds in df.dataset_name.unique():
        m = (df.dataset_name == ds).values
        ser, note = _from_raw(ds, df.loc[m], cfg["sav"], cfg["hhcol"])
        if ser is None:
            skip.append((ds, note)); continue
        out[m] = np.asarray(ser.values, dtype=object)
        ok.append((ds, note))
    for ds, note in ok:
        print(f"  [ok]   {ds[:40]:40s} {note}")
    for ds, note in sorted(skip):
        if note not in ("no dir", "no SAV", "no native-language column"):
            print(f"  [skip] {ds[:40]:40s} {note}")
    df[CP] = out
    df.to_parquet(cfg["parquet"], index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} non-null={int(df[CP].notna().sum())} / {nds} datasets; "
          f"sourced={len(ok)} skipped={len(skip)}")


def sync_db(mode, verify):
    cfg = MOD[mode]
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = f'"{cfg["table"]}"'; I = f'"{cfg["ind"]}"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        print(f"  db {CP}: {cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(cfg["parquet"])
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=%s", (cfg["table"],))
    dbtype = dict(cur.fetchall())
    if CP not in dbtype:
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" TEXT'); dbtype[CP] = "text"
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
        SELECT DISTINCT %s, dataset_name, 'respondent native language (by label)',
               'Respondent native language, decoded to language name', 'derived',
               measure_type, 'Respondent native language (language name)'
        FROM {I} WHERE canonical_varname='respondent_native_language' ''', (CP,))
    print(f"  db: rebuilt {cfg['table']} ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    mode = next((a for a in sys.argv[1:] if a in MOD), None)
    if not mode:
        print("specify module: wm | hh | ch"); sys.exit(1)
    verify = "--verify" in sys.argv
    print(f"P51 CP_respondent_native_language [{mode}] — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(mode, verify)
    print("== database =="); sync_db(mode, verify)
    print("Done.")


if __name__ == "__main__":
    main()
