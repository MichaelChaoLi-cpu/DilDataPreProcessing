"""
P12 — Carefully process `age_at_first_union` -> `CP_age_at_first_union`, and
recover the one fully-missing dataset that actually has the data.

Two parts:

1. Backfill Mozambique MICS 2008 (the only one of 41 fully-missing datasets
   whose raw WM SAV holds an unmapped age-at-first-union column). Its parquet
   keys are broken (cluster_number / line_number all NULL — see P10), so rows
   are aligned POSITIONALLY to the SAV. Alignment is guarded: the patch aborts
   unless hh_number == HH2 for every one of the 15,060 rows. Source column is
   `AGEM` ("Idade na 1a uniao/casamento"), which covers more women than MA8.
   The mapping is also written into alignment_v2.yaml so a full rebuild
   reproduces it.

2. Create `CP_age_at_first_union`: a carefully-processed copy of
   age_at_first_union keeping only plausible ages 8-49; sentinels (97/98/99),
   zero, negatives, implausibly low (<8) and >49 are set to NULL. Values 8-9 are
   kept — they concentrate in known child-marriage countries and are genuine.

The original `age_at_first_union` is left as-is except for the Mozambique
backfill (a pure addition — it was 100% NULL there), so prior work is
unaffected. Cleaning lives only in the CP_ copy.

Usage:
    .venv/bin/python MICS-WM/src/patch_age_first_union.py            # apply
    .venv/bin/python MICS-WM/src/patch_age_first_union.py --verify   # check only
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
SAV = Path("/Volumes/MikesDataBackup/MICS/raw/Mozambique MICS 2008 Datasets/wm.sav")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

DS = "Mozambique MICS 2008 Datasets"
BASE = "age_at_first_union"
CP = "CP_age_at_first_union"
RAW_COL = "AGEM"
LO, HI = 8, 49  # plausible age-at-first-union range (inclusive)


def clean(s: pd.Series) -> pd.Series:
    """Keep ages in [LO,HI]; everything else (sentinels, <8, >49, 0, neg) -> NaN."""
    v = pd.to_numeric(s, errors="coerce")
    return v.where((v >= LO) & (v <= HI))


# ---------------------------------------------------------------------------
# Mozambique source (positional, guarded)
# ---------------------------------------------------------------------------

def _mozambique_agem(parquet_moz: pd.DataFrame) -> pd.Series:
    """Read AGEM from the SAV, verify 1:1 positional alignment, return aligned series."""
    import pyreadstat
    df, _ = pyreadstat.read_sav(str(SAV), usecols=["HH2", RAW_COL])
    if len(df) != len(parquet_moz):
        raise RuntimeError(f"row count mismatch: SAV {len(df)} vs parquet {len(parquet_moz)}")
    a = pd.to_numeric(parquet_moz["hh_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df["HH2"].reset_index(drop=True), errors="coerce")
    match = (a == b).mean()
    if match < 1.0:
        raise RuntimeError(f"positional guard failed: hh_number==HH2 only {match:.4%}")
    return pd.to_numeric(df[RAW_COL].reset_index(drop=True), errors="coerce")


# ---------------------------------------------------------------------------
# alignment_v2.yaml
# ---------------------------------------------------------------------------

def patch_yaml(verify: bool) -> None:
    with open(ALIGN, encoding="utf-8") as f:
        al = yaml.safe_load(f) or {}
    entries = al.get(BASE, [])
    has = any(e.get("dataset_name") == DS for e in entries)
    if verify:
        print(f"  yaml: Mozambique->{RAW_COL} mapping present: {has}")
        return
    if has:
        print("  yaml: already has Mozambique entry, skip")
        return
    if not ALIGN.with_suffix(".yaml.bak_p12").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p12"))
    template = next((e for e in entries), {})
    entries.append({
        "canonical_text": "Age at first marriage/union",
        "canonical_varname": BASE,
        "column_in_raw_sav": RAW_COL,
        "column_label_in_english": "Age at first union/marriage",
        "component": None, "confidence": "high", "dataset_name": DS,
        "derivation": None, "entities": [], "entity_operator": None,
        "event": None, "is_compound": False,
        "measure_type": template.get("measure_type", "marriage"),
        "needs_review": False, "relation": None, "response_type": "numeric",
        "source_kind": "explicit",
    })
    al[BASE] = entries
    with open(ALIGN, "w", encoding="utf-8") as f:
        yaml.safe_dump(al, f, allow_unicode=True, sort_keys=True)
    print(f"  yaml: added Mozambique {BASE}->{RAW_COL}")


# ---------------------------------------------------------------------------
# parquet
# ---------------------------------------------------------------------------

def patch_parquet(verify: bool) -> None:
    df = pd.read_parquet(PARQUET)
    moz = df["dataset_name"] == DS

    if verify:
        n_moz = df.loc[moz, BASE].notna().sum()
        cp_ok = CP in df.columns and df[CP].equals(clean(df[BASE]))
        valid = df[CP].between(LO, HI).sum() if CP in df.columns else 0
        print(f"  parquet: Mozambique {BASE} non-null={n_moz}; "
              f"{CP} present&correct={cp_ok}; CP valid total={valid}")
        return

    if not PARQUET.with_suffix(".parquet.bak_p12").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p12"))

    # 1. Mozambique backfill (positional, guarded)
    agem = _mozambique_agem(df.loc[moz])
    df.loc[moz, BASE] = agem.values
    print(f"  parquet: Mozambique {BASE} filled {agem.notna().sum()} raw values")

    # 2. CP_ = cleaned copy of base (whole table)
    df[CP] = clean(df[BASE])
    df.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} valid(8-49)={int(df[CP].notna().sum())} "
          f"across {df.loc[df[CP].notna(),'dataset_name'].nunique()} datasets")


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

def _col_exists(cur, table, col) -> bool:
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(verify: bool) -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'
    I = '"ind_que_WM_MICS"'

    if verify:
        cur.execute(f'SELECT COUNT({BASE}) FROM {T} WHERE dataset_name=%s', (DS,))
        print(f"  db: Mozambique {BASE} non-null={cur.fetchone()[0]}")
        if _col_exists(cur, "final_WM_MICS", CP):
            cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                        f'FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
            n, nds = cur.fetchone()
            cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL '
                        f'AND ("{CP}"<{LO} OR "{CP}">{HI})')
            bad = cur.fetchone()[0]
            print(f"  db: {CP} non-null={n} across {nds} datasets; out-of-range={bad}")
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} ind_que rows={cur.fetchone()[0]}")
        conn.close()
        return

    # patched Mozambique subset from parquet (has base AGEM + CP_ + all cols)
    pdf = pd.read_parquet(PARQUET)
    moz = pdf[pdf["dataset_name"] == DS].copy()

    # 1. add CP_ column
    if not _col_exists(cur, "final_WM_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')

    # 2. clean base into CP_ (only non-null base rows; null base -> CP_ stays NULL).
    #    Mozambique rows are replaced below anyway.
    cur.execute(f'UPDATE {T} SET "{CP}" = CASE WHEN {BASE} BETWEEN {LO} AND {HI} '
                f'THEN {BASE} ELSE NULL END WHERE {BASE} IS NOT NULL')

    # 3. Mozambique: broken keys -> delete + re-insert from patched parquet
    cols = list(pdf.columns)
    assert all(_col_exists(cur, "final_WM_MICS", c) for c in cols), "DB missing a parquet column"
    # coerce subset to the DB's declared column types so COPY never fails on
    # "36.0" -> BIGINT etc.
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_WM_MICS'""")
    dbtype = dict(cur.fetchall())
    for c in cols:
        if dbtype.get(c) == "bigint":
            moz[c] = pd.to_numeric(moz[c], errors="coerce").astype("Int64")
        elif dbtype.get(c) == "double precision":
            moz[c] = pd.to_numeric(moz[c], errors="coerce")
    cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (DS,))
    buf = io.StringIO()
    moz[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    print(f"  db: re-inserted {len(moz)} Mozambique rows")

    # 4. ind_que: add Mozambique base row, then mirror all base rows to CP_
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname IN ('{CP}') "
                f"OR (canonical_varname='{BASE}' AND dataset_name=%s)", (DS,))
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (BASE, DS, RAW_COL, "Age at first union/marriage",
         "explicit", "marriage", "Age at first marriage/union"))
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
    print(f"P12 age_at_first_union -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== yaml =="); patch_yaml(verify)
    print("== parquet =="); patch_parquet(verify)
    print("== database =="); patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
