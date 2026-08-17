"""
P52 — CP_mother_native_language (CH): the child's mother's native language (decoded
language name), propagated onto each child with a source-priority fallback.

Priority (first available wins), all from the P51 decoded CP_respondent_native_language:
  1. WM  — the mother's own WM (woman 15-49) record, linked via
           (dataset, cluster, household, mother_caretaker_line_number) == WM
           (dataset, cluster, hh_number, woman_line_number | line_number).
  2. CH  — the child questionnaire's own respondent (UF14, usually the mother/caretaker),
           i.e. this child's CP_respondent_native_language.
  3. HH  — the household respondent's language, linked via (dataset, cluster, household).
(HL carries no language variable, so it is not a source.)

Adds CP_mother_native_language (text) and CP_mother_native_language_source ('WM'/'CH'/'HH').

Usage:
    .venv/bin/python MICS-CH/src/patch_child_mother_native_language.py            # apply
    .venv/bin/python MICS-CH/src/patch_child_mother_native_language.py --verify
"""
from __future__ import annotations

import io
import sys
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent.parent
WM_PARQUET = ROOT / "MICS-WM" / "data" / "WM" / "processed_data" / "wm_merged.parquet"
HH_PARQUET = ROOT / "MICS-HH" / "data" / "HH" / "processed_data" / "hh_merged.parquet"
CH_PARQUET = ROOT / "MICS-CH" / "data" / "CH" / "processed_data" / "ch_merged.parquet"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
SRC = "CP_respondent_native_language"
CP = "CP_mother_native_language"
CP_S = "CP_mother_native_language_source"


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def apply(verify):
    ch = pd.read_parquet(CH_PARQUET)
    if verify:
        for col in (CP, CP_S):
            if col not in ch.columns:
                print(f"  parquet {col}: MISSING"); continue
            n = int(ch[col].notna().sum()); nds = ch.loc[ch[col].notna(), "dataset_name"].nunique()
            print(f"  parquet {col}: non-null={n} / {nds} ds")
        if CP_S in ch.columns:
            print("  source breakdown:", ch[CP_S].value_counts(dropna=True).to_dict())
        return
    if not CH_PARQUET.with_suffix(".parquet.bak_p52").exists():
        shutil.copy2(CH_PARQUET, CH_PARQUET.with_suffix(".parquet.bak_p52"))
    ckey = ch[["dataset_name", "cluster_number", "household_number",
               "mother_caretaker_line_number"]].copy()
    for c in ["cluster_number", "household_number", "mother_caretaker_line_number"]:
        ckey[c] = _num(ckey[c])

    # --- source 1: WM mother ---
    wm = pd.read_parquet(WM_PARQUET, columns=["dataset_name", "cluster_number", "hh_number",
                                              "line_number", "woman_line_number", SRC])
    for k in ["cluster_number", "hh_number", "line_number", "woman_line_number"]:
        wm[k] = _num(wm[k])
    wm["_line"] = wm["woman_line_number"].fillna(wm["line_number"])
    wm = wm.dropna(subset=["cluster_number", "hh_number", "_line"])
    wm = wm[wm[SRC].notna()].drop_duplicates(
        subset=["dataset_name", "cluster_number", "hh_number", "_line"])
    mw = ckey.merge(wm[["dataset_name", "cluster_number", "hh_number", "_line", SRC]],
                    how="left",
                    left_on=["dataset_name", "cluster_number", "household_number", "mother_caretaker_line_number"],
                    right_on=["dataset_name", "cluster_number", "hh_number", "_line"])
    wm_lang = mw[SRC].to_numpy(dtype=object)

    # --- source 2: CH own respondent ---
    ch_lang = ch[SRC].to_numpy(dtype=object) if SRC in ch.columns else np.full(len(ch), None, object)

    # --- source 3: HH respondent ---
    hh = pd.read_parquet(HH_PARQUET, columns=["dataset_name", "cluster_number", "household_number", SRC])
    for k in ["cluster_number", "household_number"]:
        hh[k] = _num(hh[k])
    hh = hh.dropna(subset=["cluster_number", "household_number"])
    hh = hh[hh[SRC].notna()].drop_duplicates(subset=["dataset_name", "cluster_number", "household_number"])
    mh = ch[["dataset_name", "cluster_number", "household_number"]].copy()
    for c in ["cluster_number", "household_number"]:
        mh[c] = _num(mh[c])
    mh = mh.merge(hh, how="left", on=["dataset_name", "cluster_number", "household_number"])
    hh_lang = mh[SRC].to_numpy(dtype=object)

    # --- coalesce WM -> CH -> HH ---
    lang = np.full(len(ch), None, dtype=object)
    src = np.full(len(ch), None, dtype=object)
    def _has(a, i):
        v = a[i]; return v is not None and not (isinstance(v, float) and np.isnan(v)) and str(v) != "nan"
    for arr, tag in [(wm_lang, "WM"), (ch_lang, "CH"), (hh_lang, "HH")]:
        take = np.array([lang[i] is None and _has(arr, i) for i in range(len(ch))])
        lang[take] = arr[take]; src[take] = tag
    ch[CP] = lang
    ch[CP_S] = src
    ch.to_parquet(CH_PARQUET, index=False)
    from collections import Counter
    print(f"  parquet: {CP} non-null={int(pd.Series(lang).notna().sum())} / "
          f"{ch.loc[pd.Series(lang, index=ch.index).notna(), 'dataset_name'].nunique()} datasets")
    print("  source breakdown:", dict(Counter(x for x in src if x is not None)))


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        for col in (CP, CP_S):
            cur.execute(f'SELECT COUNT("{col}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{col}" IS NOT NULL) FROM {T}')
            print(f"  db {col}: {cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(CH_PARQUET)
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='final_CH_MICS'")
    dbtype = dict(cur.fetchall())
    for col in (CP, CP_S):
        if col not in dbtype:
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" TEXT'); dbtype[col] = "text"
    cols = [c for c in pdf.columns if c in dbtype]
    assert set(dbtype) - set(pdf.columns) == set(), "DB has columns absent from parquet"
    for c in cols:
        if dbtype.get(c) in ("bigint", "smallint", "integer"):
            pdf[c] = _num(pdf[c]).astype("Int64")
        elif dbtype.get(c) in ("double precision", "real", "numeric"):
            pdf[c] = _num(pdf[c])
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f'TRUNCATE {T}')
    for ds, sub in pdf.groupby("dataset_name", sort=False):
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    for col, txt in [(CP, "Child's mother's native language (language name), WM->CH->HH fallback"),
                     (CP_S, "Source of CP_mother_native_language: WM / CH / HH")]:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (col,))
        cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
            column_label_in_english,source_kind,measure_type,canonical_text)
            SELECT DISTINCT %s, dataset_name, 'WM/CH/HH:CP_respondent_native_language', %s, 'derived',
                   'child_background', %s
            FROM {I} WHERE canonical_varname='mother_education_years' ''', (col, txt, txt))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que added")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P52 CP_mother_native_language — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
