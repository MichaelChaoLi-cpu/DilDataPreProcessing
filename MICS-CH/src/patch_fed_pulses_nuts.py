"""
P37 — `CP_fed_pulses_nuts_seeds_yesterday` (CH): child ate beans, peas, lentils, nuts
or seeds yesterday, 1/0.

Source: **BD8M** — "Child ate beans, peas, lentils or nuts, or any food made from these,
yesterday" (the MICS5/6 24-hour legumes-and-nuts food-group item). Rebuilt FRESH from the
raw SAV rather than harmonizing the existing `dd_legumes_nuts`, because that column is
silently contaminated: for several multi-source datasets the merge took the WRONG raw
column (e.g. Algeria MICS6 dd_legumes_nuts == BD8G "figues, pommes, poires" vitamin-A
fruit, not BD8M; others carried BD7D infant formula or IM8/IM12 immunization columns).

Guard, per dataset: (a) BD8M must be present AND its variable label must actually be
legumes/nuts (excludes e.g. Pakistan-KP MICS5 whose BD8M is "other solid food" — its
food-group letters are shifted), (b) SAV row count == parquet row count, (c)
household_number matches the SAV HH id ≥ 99.9% (positional alignment). Value classified
from BD8M's own multilingual labels: 1=Yes -> 1, 2=No -> 0, sentinels (7/8/9) -> NULL.

Two datasets carry the legumes item under a shifted letter (verified genuine legumes) and
are read from that column instead: Pakistan-KP MICS5 `BD8K`, Madagascar-South MICS4 `BF15LX`.

Usage:
    .venv/bin/python MICS-CH/src/patch_fed_pulses_nuts.py            # apply
    .venv/bin/python MICS-CH/src/patch_fed_pulses_nuts.py --verify
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

CP = "CP_fed_pulses_nuts_seeds_yesterday"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]
# datasets whose legumes item sits under a shifted letter (verified legumes label)
SPECIAL = {
    "Pakistan_(Khyber_Pakhtunkhwa)_MICS5_Datasets": "BD8K",
    "Madagascar (South)_ MICS4_Datasets": "BF15LX",
}

_LEG = re.compile(r"(bean|pea\b|peas|lentil|nut|haricot|pois|noix|frijol|feij|legum|lenteja|"
                  r"porot|chicharo|guisante|nozes|habichuela|guandul|garbanzo|soya|mani\b|"
                  r"arachid|ervilha|amande|cacahu|mung|chickpea)")


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


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _harmonize(base):
    v = pd.to_numeric(base, errors="coerce")
    return pd.Series(np.where(v == 1, 1.0, np.where(v == 2, 0.0, np.nan)), index=base.index)


def _single_bd8m_datasets():
    """Datasets whose dd_legumes_nuts was mapped ONLY from BD8M — the merged column
    value there is trustworthy BD8M and can be kept when the raw re-read guard fails
    (id-recoded datasets: Kosovo/Montenegro MICS6). Multi-source ones are excluded
    because the merge may have taken the wrong column (e.g. Algeria's BD8G fruit)."""
    conn = psycopg2.connect(**DB_PARAMS); cur = conn.cursor()
    cur.execute("""SELECT dataset_name FROM "ind_que_CH_MICS"
                   WHERE canonical_varname='dd_legumes_nuts'
                   GROUP BY dataset_name
                   HAVING array_agg(DISTINCT column_in_raw_sav) = ARRAY['BD8M']""")
    out = {r[0] for r in cur.fetchall()}
    conn.close()
    return out


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
    """(series aligned to parquet_ds, note) or (None, why). Reads raw BD8M (or the
    dataset's SPECIAL column), requiring a legumes label + household alignment."""
    import pyreadstat
    d = _sav_dir(ds)
    if d is None:
        return None, "no dir"
    sav = d / "ch.sav"
    if not sav.exists():
        sav = next((p for p in d.glob("*.sav") if "ch" in p.name.lower()), None)
    if sav is None or not sav.exists():
        return None, "no SAV"
    want = SPECIAL.get(ds, "BD8M")
    try:
        _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    except Exception as e:
        return None, f"meta err {e!s:.30}"
    col = _find(meta.column_names, want)
    if col is None:
        return None, f"{want} absent"
    lbl = meta.column_names_to_labels.get(col) or ""
    if not _LEG.search(_fold(lbl)):
        return None, f"{want} not legumes: '{lbl[:40]}'"
    key = next((_find(meta.column_names, k) for k in GUARD_KEYS if _find(meta.column_names, k)), None)
    need = [col] + ([key] if key else [])
    try:
        df, _ = pyreadstat.read_sav(str(sav), usecols=list(dict.fromkeys(need)), apply_value_formats=False)
    except Exception as e:
        return None, f"read err {e!s:.30}"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    if key is None:
        return None, "no guard key"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
    g = (a == b).mean()
    if g < 0.999:
        return None, f"guard {g:.3%} ({key})"
    cmap = _classify(meta.variable_value_labels.get(col, {}))
    v = pd.to_numeric(df[col].reset_index(drop=True), errors="coerce")
    out = v.map(lambda x: cmap.get(x) if pd.notna(x) else None).astype("float64")
    return out, f"{col} n={int(out.notna().sum())} g={g:.1%}"


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={n} / {nds} ds; out-of-range={bad}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p37").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p37"))
    single_bd8m = _single_bd8m_datasets()
    cp = np.full(len(df), np.nan)
    ok, skip, kept = [], [], []
    for ds in df.dataset_name.unique():
        m = (df.dataset_name == ds).values
        ser, note = _from_raw(ds, df.loc[m])
        if ser is None:
            # trusted fallback: single-BD8M-source merged value (guard-failing id-recoded ds)
            if ds in single_bd8m:
                base = _harmonize(df.loc[m, "dd_legumes_nuts"])
                if base.notna().any():
                    cp[m] = base.values
                    kept.append((ds, f"kept dd (single-BD8M) n={int(base.notna().sum())}; raw:{note}"))
                    continue
            skip.append((ds, note)); continue
        cp[m] = ser.values
        ok.append((ds, note))
    for ds, note in ok:
        print(f"  [ok]   {ds[:44]:44s} {note}")
    for ds, note in kept:
        print(f"  [keep] {ds[:44]:44s} {note}")
    for ds, note in sorted(skip):
        # only report skips that had a real column present (noise filter)
        if "absent" not in note and "no SAV" not in note and "no dir" not in note:
            print(f"  [skip] {ds[:44]:44s} {note}")
    df[CP] = cp
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} / {nds} datasets; "
          f"raw={len(ok)} kept={len(kept)} skipped={len(skip)}")


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
        SELECT %s, dataset_name, 'BD8M',
               'Child ate beans, peas, lentils, nuts or seeds yesterday',
               'derived', measure_type, 'Child ate pulses, nuts or seeds yesterday'
        FROM {I} WHERE canonical_varname=%s''', (CP, "dd_legumes_nuts"))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P37 CP_fed_pulses_nuts_seeds_yesterday — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
