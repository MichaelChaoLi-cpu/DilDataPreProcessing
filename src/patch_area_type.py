"""
P24 — `CP_area_type`: harmonized 3-category urban / rural / refugee-camp indicator,
in all four tables (HH source + WM / CH / HL).

The raw `area` (HH6 "Area of residence") is not comparable across surveys:
- codes differ (usually 1=urban / 2=rural, but Zambia 1999 is reversed, and it is
  the LABEL that is authoritative);
- many surveys use >2 categories that must collapse (Mongolia capital/aimag/soum
  centre -> urban; Lao "rural with/without road" -> rural; Suriname coastal/interior
  -> rural; Bangladesh municipality/metro/slum -> urban, tribal -> rural; city-name
  strata -> urban);
- `area` was mis-aligned in ~26 datasets to a region/cluster column, contaminating
  the base with region codes (10-95) that are not HH6 at all.

`CP_area_type` = 1 Urban / 2 Rural / 3 Refugee-camp / NULL. Decisions (per user):
slum (informal urban) -> Urban; peri-urban -> Rural; refugee camp (only the 3 State
of Palestine surveys, HH6=Camp) -> 3; pure-region codings (Egypt sub-national) and
"Other" -> NULL.

Method: build a per-dataset {raw code -> category} map by classifying the HH6 value
labels (read from the HH-module SAV metadata) with multilingual regexes. Apply the
map to each table's own `area` column. Where a dataset's base `area` does not map
(contaminated / mis-aligned), recover HH6 from that module's SAV and backfill
positionally, guarded `hh_number == {HH1.HH2 / WIHHNO / ...}`. Datasets with no HH6
labels but base values in {1,2} default to 1=urban / 2=rural (MICS convention).

Usage:
    .venv/bin/python src/patch_area_type.py               # apply all tables
    .venv/bin/python src/patch_area_type.py --verify
"""
from __future__ import annotations

import io
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
BASE = "area"
CP = "CP_area_type"

# table -> (parquet path, module sav basename, household-id column in that table)
TABLES = {
    "final_HH_MICS": ("MICS-HH/data/HH/processed_data/hh_merged.parquet", "hh", "household_number"),
    "final_WM_MICS": ("MICS-WM/data/WM/processed_data/wm_merged.parquet", "wm", "hh_number"),
    "final_CH_MICS": ("MICS-CH/data/CH/processed_data/ch_merged.parquet", "ch", "household_number"),
    "final_HL_MICS": ("MICS-HL/data/HL/processed_data/hl_merged.parquet", "hl", "household_number"),
}

_CAMP = re.compile(r"camp|refug|مخيم|campo de refug", re.I)
_PERI = re.compile(r"peri.?urb|périurb|peri.?urbain", re.I)
_RURAL = re.compile(r"rural|\bvill\b|village|interior|coast|tribal|zone restante|\bbagh\b|"
                    r"remaining|rural_cob|_cobertura.*rural|nomad|campo\b", re.I)
_URBAN = re.compile(r"urban|urbain|urbano|urbana|\bcity\b|ville|villes|capital|kigali|ouagadou|"
                    r"antananar|antsirabe|metro|municipal|\bkma\b|aimag|soum|center|centre|"
                    r"\btown\b|slum|informal|non.slum|urbano_cob|cobertura.*urb|chef.?lieu|"
                    r"kingston|greater", re.I)
_SENT = re.compile(r"missing|manquant|nsp|\bdk\b|omit|special|no sabe|9999|refus|\bns\b|autre", re.I)
GUARD_KEYS = ["HH2", "hh2", "WM2", "wm2", "WIHHNO", "wihhno", "HI2", "hi2", "hhno", "HHNO"]


def _cat(label) -> int | None:
    l = str(label).strip()
    if _CAMP.search(l):
        return 3
    if _PERI.search(l):
        return 2
    if _RURAL.search(l):
        return 2
    if _URBAN.search(l):
        return 1
    return None


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _hh6_var(meta):
    for v in meta.column_names:
        if v.upper() in ("HH6", "HH6A", "HI6"):
            return v
    for v in meta.column_names:
        lab = meta.column_names_to_labels.get(v) or ""
        if re.search(r"\b(area|milieu|residence|résidence|urban|rural|locality|zona)\b", lab, re.I):
            return v
    return None


def _sav(ds, mod):
    for cand in (RAW / ds / f"{mod}.sav", RAW / ds / f"{mod.upper()}.sav"):
        if cand.exists():
            return cand
    g = [q for q in RAW.glob(f"{ds}/*.sav") if mod in q.name.lower()]
    return g[0] if g else None


def build_maps(datasets):
    """dataset -> ({raw_code: cat}, hh6_varname). Read from the HH-module SAV metadata."""
    import pyreadstat
    maps = {}
    for ds in datasets:
        sav = _sav(ds, "hh")
        if sav is None:
            maps[ds] = ({}, None); continue
        try:
            _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
        except Exception:
            maps[ds] = ({}, None); continue
        var = _hh6_var(meta)
        vl = meta.variable_value_labels.get(var, {}) if var else {}
        m = {}
        for k, v in vl.items():
            try:
                code = float(k)
            except (TypeError, ValueError):
                continue
            c = _cat(v)
            if c is not None:
                m[code] = c
        maps[ds] = (m, var)
    return maps


def _apply_map(area: pd.Series, code_map: dict) -> pd.Series:
    v = pd.to_numeric(area, errors="coerce")
    return v.map(lambda x: code_map.get(x) if pd.notna(x) else None).astype("float64")


def _recover_hh6(ds, mod, hhcol, parquet_ds, code_map, hh6var):
    """Read only HH6 + a guard column from the module SAV, verify positional
    alignment, return mapped-category series. Column-restricted for speed on big SAVs."""
    import pyreadstat
    sav = _sav(ds, mod)
    if sav is None:
        return None, "no SAV"
    _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    var = _hh6_var(meta)
    if var is None:
        return None, "no HH6 in SAV"
    keys = []
    for k in GUARD_KEYS:
        c = _find(meta.column_names, k)
        if c and c not in keys:
            keys.append(c)
    if not keys:
        return None, "no guard key in SAV"
    df, _ = pyreadstat.read_sav(str(sav), usecols=[var] + keys, apply_value_formats=False)
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds[hhcol].reset_index(drop=True), errors="coerce")
    best, key = 0.0, None
    for c in keys:
        m = (a == pd.to_numeric(df[c].reset_index(drop=True), errors="coerce")).mean()
        if m > best:
            best, key = m, c
        if m >= 0.999:
            break
    if best < 0.999:
        return None, f"guard {best:.3%} (best {key})"
    cm = code_map or {float(k): _cat(v) for k, v in meta.variable_value_labels.get(var, {}).items()
                      if str(k).replace(".", "", 1).replace("-", "").isdigit() and _cat(v) is not None}
    hh6 = pd.to_numeric(df[var].reset_index(drop=True), errors="coerce")
    cat = hh6.map(lambda x: cm.get(x) if pd.notna(x) else None).astype("float64")
    return cat, f"HH6={var} n={int(cat.notna().sum())}"


# ---------------------------------------------------------------------------

def _direct_map(df, maps):
    """Vectorized per-dataset direct map of `area` -> category. Returns a float Series."""
    rows = []
    for ds, (cm, _) in maps.items():
        m = dict(cm)
        if not m:
            continue
        for code, cat in m.items():
            rows.append((ds, float(code), cat))
    lut = pd.DataFrame(rows, columns=["dataset_name", "_code", "_cat"])
    d = df[["dataset_name", BASE]].copy()
    d["_code"] = pd.to_numeric(d[BASE], errors="coerce")
    d["_row"] = np.arange(len(d))
    merged = d.merge(lut, on=["dataset_name", "_code"], how="left")
    out = pd.Series(np.nan, index=df.index)
    out.iloc[merged["_row"].values] = merged["_cat"].values
    # fallback: unclassified datasets whose base is a clean {1,2} -> urban/rural
    classified = {ds for ds, (cm, _) in maps.items() if cm}
    for ds in df.loc[out.isna(), "dataset_name"].unique():
        if ds in classified:
            continue
        g = df[df.dataset_name == ds]
        vals = set(pd.to_numeric(g[BASE], errors="coerce").dropna().unique())
        if vals and vals <= {1.0, 2.0}:
            out.loc[g.index] = _apply_map(g[BASE], {1.0: 1, 2.0: 2}).values
    return out


def process_table(table, maps, hh_lut, verify):
    path, mod, hhcol = TABLES[table]
    pq = Path(path)
    df = pd.read_parquet(pq)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([1, 2, 3])].shape[0]) if CP in df.columns else -1
        print(f"  [{table}] parquet {CP} valid={n} across {nds} ds; out-of-range={bad}")
        return set()

    bak = pq.with_suffix(".parquet.bak_p24")
    if not bak.exists():
        shutil.copy2(pq, bak)

    cp = _direct_map(df, maps)
    recovered = set()

    if hh_lut is None:
        # HH (source of truth): recover contaminated/unaligned datasets from the HH SAV
        for ds, g in df.groupby("dataset_name"):
            if cp.loc[g.index].notna().any():
                continue
            code_map, hh6var = maps.get(ds, ({}, None))
            ser, note = _recover_hh6(ds, mod, hhcol, g, code_map, hh6var)
            if ser is not None:
                cp.loc[g.index] = ser.values
                recovered.add(ds)
                print(f"  [{table}] [recover] {ds}: {note}")
            else:
                print(f"  [{table}] [skip]    {ds}: {note}")
    else:
        # member tables: fill still-NULL rows from HH via the household join (fast, no SAV)
        d = df[["dataset_name", "cluster_number", hhcol]].copy()
        d["cl"] = pd.to_numeric(d["cluster_number"], errors="coerce").round()
        d["hn"] = pd.to_numeric(d[hhcol], errors="coerce").round()
        d["_row"] = np.arange(len(d))
        m = d.merge(hh_lut, on=["dataset_name", "cl", "hn"], how="left")
        cat_hh = pd.Series(np.nan, index=df.index)
        cat_hh.iloc[m["_row"].values] = m["cat"].values
        fill = cp.isna() & cat_hh.notna()
        recovered = set(df.loc[fill, "dataset_name"].unique())
        cp[fill] = cat_hh[fill]
        print(f"  [{table}] join-filled {int(fill.sum())} rows / {len(recovered)} datasets from HH")

    df[CP] = cp.values
    df.to_parquet(pq, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    dist = df[CP].value_counts(dropna=True).to_dict()
    print(f"  [{table}] {CP} valid={int(df[CP].notna().sum())} / {nds} datasets; "
          f"dist={{1:{int(dist.get(1.0,0))},2:{int(dist.get(2.0,0))},3:{int(dist.get(3.0,0))}}}; "
          f"recovered={len(recovered)}")
    return recovered


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def sync_db(table, recovered, verify):
    path, mod, hhcol = TABLES[table]
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = f'"{table}"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND "{CP}" NOT IN (1,2,3)')
        bad = cur.fetchone()[0]
        print(f"  [{table}] db {CP} non-null={n} / {nds} ds; out-of-range={bad}")
        conn.close(); return

    df = pd.read_parquet(path, columns=["dataset_name", BASE, CP])
    existed = _col_exists(cur, table, CP)
    if not existed:
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" SMALLINT')
    else:
        cur.execute(f'UPDATE {T} SET "{CP}" = NULL')  # re-run: clear before recompute

    # direct-mapped datasets: CP is a pure function of (dataset_name, numeric area code)
    direct = df[~df.dataset_name.isin(recovered)].dropna(subset=[CP]).copy()
    direct["_raw"] = pd.to_numeric(direct[BASE], errors="coerce")
    direct = direct.dropna(subset=["_raw"])
    lut = direct.drop_duplicates(["dataset_name", "_raw"])[["dataset_name", "_raw", CP]].copy()
    lut[CP] = lut[CP].astype(int)
    cur.execute("CREATE TEMP TABLE _am(dataset text, raw double precision, cat smallint) ON COMMIT DROP")
    buf = io.StringIO()
    lut.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cur.copy_expert("COPY _am(dataset,raw,cat) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", buf)
    cur.execute("CREATE INDEX ON _am(dataset,raw)")
    # area column may be TEXT or DOUBLE PRECISION depending on the table -> cast safely
    cur.execute("""SELECT data_type FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, BASE))
    atype = cur.fetchone()[0]
    if atype in ("double precision", "real", "numeric", "integer", "bigint", "smallint"):
        areanum = f'f.{BASE}'
    else:  # text
        areanum = f"(CASE WHEN f.{BASE} ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN f.{BASE}::double precision END)"
    cur.execute(f'UPDATE {T} f SET "{CP}" = m.cat FROM _am m '
                f'WHERE f.dataset_name = m.dataset AND {areanum} = m.raw')
    print(f"  [{table}] db: direct-mapped {len(lut)} (dataset,area) pairs (area is {atype})")

    # recovered (positional) datasets: DELETE + reinsert whole rows from patched parquet
    if recovered:
        full = pd.read_parquet(path)
        cur.execute(f"""SELECT column_name, data_type FROM information_schema.columns
                        WHERE table_name='{table}'""")
        dbtype = dict(cur.fetchall())
        cols = [c for c in full.columns if c in dbtype]
        for ds in recovered:
            sub = full[full.dataset_name == ds].copy()
            for c in cols:
                if dbtype.get(c) == "bigint":
                    sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
                elif dbtype.get(c) in ("double precision", "smallint", "integer"):
                    sub[c] = pd.to_numeric(sub[c], errors="coerce")
                    if dbtype.get(c) in ("smallint", "integer"):
                        sub[c] = sub[c].astype("Int64")
            cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
            buf = io.StringIO()
            sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
            buf.seek(0)
            collist = ", ".join(f'"{c}"' for c in cols)
            cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        print(f"  [{table}] db: reinserted {len(recovered)} recovered datasets")

    conn.commit()
    conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P24 {CP} — {'VERIFY' if verify else 'APPLY'}")
    if not verify:
        allds = set()
        for path, _, _ in TABLES.values():
            allds |= set(pd.read_parquet(path, columns=["dataset_name"]).dataset_name.unique())
        print(f"building HH6 maps for {len(allds)} datasets...")
        maps = build_maps(sorted(allds))
        print(f"  classified {sum(1 for m,_ in maps.values() if m)} datasets")
    else:
        maps = {}
    if verify:
        for table in TABLES:
            process_table(table, {}, None, True)
            sync_db(table, set(), True)
        print("Done."); return

    # HH first (source of truth), then build a household lookup for the member tables
    rec = process_table("final_HH_MICS", maps, None, False)
    sync_db("final_HH_MICS", rec, False)

    hh = pd.read_parquet(TABLES["final_HH_MICS"][0],
                         columns=["dataset_name", "cluster_number", "household_number", CP])
    hh = hh.dropna(subset=[CP])
    hh["cl"] = pd.to_numeric(hh["cluster_number"], errors="coerce").round()
    hh["hn"] = pd.to_numeric(hh["household_number"], errors="coerce").round()
    hh_lut = (hh.dropna(subset=["cl", "hn"])
                .rename(columns={CP: "cat"})[["dataset_name", "cl", "hn", "cat"]]
                .drop_duplicates(["dataset_name", "cl", "hn"]))

    for table in ("final_WM_MICS", "final_CH_MICS", "final_HL_MICS"):
        rec = process_table(table, maps, hh_lut, False)
        sync_db(table, rec, False)
    print("Done.")


if __name__ == "__main__":
    main()
