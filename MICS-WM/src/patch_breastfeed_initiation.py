"""
P28 — Early initiation of breastfeeding (WM).  Three derived indicators from the
"how long after birth was the child first put to the breast?" question
(number + unit): the standard WHO/MICS *early initiation* measure.

  CP_time_to_breastfeed_hours        continuous hours to first breastfeed
  CP_early_initiation_breastfeeding  1 = within 1 hour of birth / 0 later
  CP_breastfed_within_24h            1 = within 24 hours / 0 later

The unit is interpreted by its LABEL, not its code (codes differ across surveys:
0/1/2 Immediately/Hours/Days is usual, some use 1/2/3, one uses Minutes):
  hours = 0 (immediately) | n/60 (minutes) | n (hours) | n*24 (days).
Sentinels (98/99/998/999, unit=Special/DK, implausible n) -> NULL.

Coverage / translation fix: the number+unit pair was aligned for 154 datasets, but
39 more have it UNMAPPED in their raw SAV under a non-English label ("Enfant mis au
sein pour la première fois", "Cuánto tiempo después del nacimiento le dio pecho",
...) — recovered here (guarded positional backfill), excluding look-alikes (MN26 =
time bathed, PN2 = facility stay, PN12 = postnatal check, MN13B = breastfeeding
duration). 154 -> 193 datasets. Only Argentina MICS4 lacks the question.

Usage:
    .venv/bin/python MICS-WM/src/patch_breastfeed_initiation.py            # apply
    .venv/bin/python MICS-WM/src/patch_breastfeed_initiation.py --verify
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
RAWYAML = ROOT / "raw"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

NUM = "time_to_breastfeed_number"
UNIT = "time_to_breastfeed_unit"
CP_H = "CP_time_to_breastfeed_hours"
CP_1 = "CP_early_initiation_breastfeeding"
CP_24 = "CP_breastfed_within_24h"

SENT = {98.0, 99.0, 998.0, 999.0, 9998.0, 9999.0}

# 39 datasets with an unmapped (number, unit) pair in the raw SAV.
RECOVER = {
    'Algeria_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Argentina MICS6 Datasets': ('MN37N', 'MN37U'),
    'Benin_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Cameroon_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Central African Republic MICS6 Datasets': ('MN37N', 'MN37U'),
    'Central African Republic_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Chad_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Costa Rica MICS6 Datasets': ('MN37N', 'MN37U'),
    'Costa Rica_MICS4_Datasets': ('MN25N', 'MN25U'),
    "Côte d'Ivoire_MICS5Datasets": ('MN25N', 'MN25U'),
    'Cuba MICS6 Datasets': ('MN37N', 'MN37U'),
    'Cuba_MICS5_Datasets': ('MN25N', 'MN25U'),
    'DRCongo MICS6 SPSS Datafiles': ('MN37N', 'MN37U'),
    'Dominican Republic MICS6 Datasets': ('MN37N', 'MN37U'),
    'Dominican Republic_MICS5_Datasets': ('MN25N', 'MN25U'),
    'El Salvador_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Guinea_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Honduras MICS6 Datasets': ('MN37N', 'MN37U'),
    'Kyrgyzstan MICS 2005-06 SPSS Datasets': ('mn13n', 'mn13u'),
    'Mali_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Mauritania_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Mauritania_MICS5_Datasets 2': ('MN25N', 'MN25U'),
    'Mexico_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Mongolia (Khuvsgul Aimag)_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Mongolia (Khuvsgul Aimag)_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Mongolia (Nalaikh District)_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Mongolia (Nalaikh District)_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Mongolia MICS 2005 SPSS Datasets': ('MN13N', 'MN13U'),
    'Mongolia_MICS4_Datasets': ('MN25_N', 'MN25_U'),
    'Mozambique MICS 2008 Datasets': ('MN13N', 'MN13U'),
    'Panama_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Paraguay_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Senegal (Dakar)_MICS5_Datasets': ('MN25N', 'MN25U'),
    'Thailand_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Togo MICS6 SPSS Datasets': ('MN37N', 'MN37U'),
    'Togo MICS6 SPSS Datasets (1)': ('MN37N', 'MN37U'),
    'Togo_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Tunisia_MICS4_Datasets': ('MN25N', 'MN25U'),
    'Uruguay_MICS4_Datasets': ('MN25N', 'MN25U'),
}


def _fold(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x)) if not unicodedata.combining(c)).lower()


def _utype(label):
    f = _fold(label)
    if "immediat" in f or "imediat" in f or "inmediat" in f:
        return "imm"
    if "minut" in f:
        return "min"
    if "hour" in f or "heure" in f or "hora" in f:
        return "hr"
    if "day" in f or "jour" in f or "dia" in f:
        return "day"
    return None


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _unit_map(ds, unit_col):
    """{unit code -> type} from the raw-yaml value labels of the dataset's unit column."""
    p = RAWYAML / ds / "wm.yaml"
    if not p.exists() or unit_col is None:
        return {}
    ry = yaml.safe_load(open(p))
    L = ry.get("columns", ry) if isinstance(ry, dict) else ry
    m = {c.get("column_in_raw_sav"): c for c in L}
    col = m.get(unit_col) or m.get(_find(list(m), unit_col) or "")
    vl = (col or {}).get("value_labels") or {}
    out = {}
    for k, v in vl.items():
        try:
            out[float(k)] = _utype(v)
        except (TypeError, ValueError):
            pass
    return out


def _hours(num, ucode, umap):
    """Vectorised hours-to-first-breastfeed from number + unit code + unit-type map."""
    n = pd.to_numeric(num, errors="coerce")
    u = pd.to_numeric(ucode, errors="coerce")
    t = u.map(umap)
    out = pd.Series(np.nan, index=n.index)
    valid_n = n.notna() & ~n.isin(list(SENT)) & (n >= 0) & (n <= 90)
    out[t == "imm"] = 0.0
    out[(t == "min") & valid_n] = n[(t == "min") & valid_n] / 60.0
    out[(t == "hr") & valid_n] = n[(t == "hr") & valid_n]
    out[(t == "day") & valid_n & (n <= 31)] = n[(t == "day") & valid_n & (n <= 31)] * 24.0
    return out


def _unit_src(mapped_unit_align):
    """dataset -> raw unit column, from the alignment (for mapped datasets)."""
    al = yaml.safe_load(open(ALIGN))
    return {e["dataset_name"]: e["column_in_raw_sav"] for e in al.get(UNIT, [])}


def _read_sav(ds):
    import pyreadstat
    sav = RAW / ds / "wm.sav"
    if not sav.exists():
        for alt in RAW.glob(f"{ds}/*.sav"):
            if "wm" in alt.name.lower():
                sav = alt; break
    if not sav.exists():
        return None, "no SAV"
    df, meta = pyreadstat.read_sav(str(sav), apply_value_formats=False)
    return (df, meta), "ok"


def derive(df):
    unit_src = _unit_src(None)
    cph = pd.Series(np.nan, index=df.index)
    mapped = sorted(df.loc[pd.to_numeric(df[UNIT], errors="coerce").notna()
                           | pd.to_numeric(df[NUM], errors="coerce").notna(), "dataset_name"].unique())
    mapped = [d for d in mapped if d not in RECOVER]
    # 1. mapped datasets: from parquet base columns
    for ds in mapped:
        g = df[df.dataset_name == ds]
        umap = _unit_map(ds, unit_src.get(ds) or "MN25U")
        if not umap:
            continue
        cph.loc[g.index] = _hours(g[NUM], g[UNIT], umap).values
    return cph, mapped


def _recover(ds, parquet_ds):
    (out, note) = _read_sav(ds)
    if out is None:
        return None, note
    sdf, meta = out
    numcol, unitcol = RECOVER[ds]
    nc = _find(sdf.columns, numcol); uc = _find(sdf.columns, unitcol)
    if nc is None or uc is None:
        return None, f"cols {numcol}/{unitcol} absent"
    if len(sdf) != len(parquet_ds):
        return None, f"row mismatch {len(sdf)} vs {len(parquet_ds)}"
    hh2 = _find(sdf.columns, "HH2") or _find(sdf.columns, "WM2") or _find(sdf.columns, "WIHHNO")
    if hh2 is None:
        return None, "no guard key"
    a = pd.to_numeric(parquet_ds["hh_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(sdf[hh2].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 0.999:
        return None, f"guard {(a==b).mean():.3%}"
    umap = {}
    for k, v in meta.variable_value_labels.get(uc, {}).items():
        try:
            umap[float(k)] = _utype(v)
        except (TypeError, ValueError):
            pass
    hrs = _hours(sdf[nc].reset_index(drop=True), sdf[uc].reset_index(drop=True), umap)
    return hrs, f"{numcol}/{unitcol} n={int(hrs.notna().sum())}"


# ---------------------------------------------------------------------------

def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        for c in (CP_H, CP_1, CP_24):
            n = int(df[c].notna().sum()) if c in df.columns else 0
            nds = df.loc[df[c].notna(), "dataset_name"].nunique() if c in df.columns else 0
            print(f"  parquet {c}: valid={n} / {nds} ds")
        return []
    if not PARQUET.with_suffix(".parquet.bak_p28").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p28"))
    cph, mapped = derive(df)
    avail = set(df.dataset_name.unique())
    nfc = {unicodedata.normalize("NFC", a): a for a in avail}
    applied, skipped = [], []
    for ds in RECOVER:
        actual = ds if ds in avail else nfc.get(unicodedata.normalize("NFC", ds))
        if actual is None:
            skipped.append((ds, "not in parquet")); continue
        m = df.dataset_name == actual
        hrs, note = _recover(ds, df.loc[m])
        if hrs is None:
            skipped.append((ds, note)); continue
        cph.loc[m] = hrs.values
        applied.append(actual)
        print(f"  [ok]   {ds}: {note}")
    for ds, n in skipped:
        print(f"  [skip] {ds}: {n}")
    df[CP_H] = cph.values
    df[CP_1] = np.where(cph.notna(), (cph <= 1).astype(float), np.nan)
    df[CP_24] = np.where(cph.notna(), (cph <= 24).astype(float), np.nan)
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP_H].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP_H} valid={int(df[CP_H].notna().sum())} / {nds} ds; "
          f"early-init(<=1h)={int((df[CP_1]==1).sum())}; recovered={len(applied)} skipped={len(skipped)}")
    return applied


def _col_exists(cur, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name='final_WM_MICS' AND column_name=%s""", (col,))
    return cur.fetchone() is not None


def sync_db(applied, verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_WM_MICS"'; I = '"ind_que_WM_MICS"'
    if verify:
        for c in (CP_H, CP_1, CP_24):
            cur.execute(f'SELECT COUNT("{c}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{c}" IS NOT NULL) FROM {T}')
            print(f"  db {c}: {cur.fetchone()}")
        conn.close(); return
    pdf = pd.read_parquet(PARQUET)
    for c, t in ((CP_H, "DOUBLE PRECISION"), (CP_1, "SMALLINT"), (CP_24, "SMALLINT")):
        if not _col_exists(cur, c):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{c}" {t}')
    cur.execute(f'UPDATE {T} SET "{CP_H}"=NULL,"{CP_1}"=NULL,"{CP_24}"=NULL')

    # mapped datasets: CP is a function of (dataset, number, unit) -> temp-LUT
    mapped = pdf[~pdf.dataset_name.isin(applied) & pdf[CP_H].notna()].copy()
    mapped["_n"] = pd.to_numeric(mapped[NUM], errors="coerce").round(4)
    mapped["_u"] = pd.to_numeric(mapped[UNIT], errors="coerce")
    lut = mapped.drop_duplicates(["dataset_name", "_n", "_u"])[["dataset_name", "_n", "_u", CP_H, CP_1, CP_24]]
    if len(lut):
        for c in (CP_1, CP_24):
            lut[c] = lut[c].astype("Int64")
        cur.execute("CREATE TEMP TABLE _b(dataset text, n double precision, u double precision, "
                    "h double precision, e1 smallint, w24 smallint) ON COMMIT DROP")
        buf = io.StringIO(); lut.to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert("COPY _b(dataset,n,u,h,e1,w24) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", buf)
        cur.execute("CREATE INDEX ON _b(dataset,n,u)")
        cur.execute(f'UPDATE {T} f SET "{CP_H}"=m.h, "{CP_1}"=m.e1, "{CP_24}"=m.w24 FROM _b m '
                    f'WHERE f.dataset_name=m.dataset '
                    f'AND ROUND({NUM}::numeric,4) IS NOT DISTINCT FROM m.n AND {UNIT} IS NOT DISTINCT FROM m.u')
    print(f"  db: mapped {len(lut)} (dataset,num,unit) combos")

    # recovered datasets: reinsert whole rows from patched parquet
    if applied:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name='final_WM_MICS'""")
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

    for base, cp in [(NUM, CP_H), (NUM, CP_1), (NUM, CP_24)]:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (cp,))
        cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
            column_label_in_english,source_kind,measure_type,canonical_text)
            SELECT %s,dataset_name,column_in_raw_sav,column_label_in_english,source_kind,measure_type,canonical_text
            FROM {I} WHERE canonical_varname=%s''', (cp, base))
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P28 early-initiation breastfeeding — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = apply(verify)
    print("== database =="); sync_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
