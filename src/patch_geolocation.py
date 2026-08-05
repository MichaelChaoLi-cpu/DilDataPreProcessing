"""
P27 — Standardised geography: `CP_country` / `CP_country_code` (level 0) and
`CP_subnational` / `CP_subnational_matched` (level 1), in all four tables.

Reference (data/geolocation/, gitignored): country.json = ISO3 + canonical country
name; state.json = canonical admin-1 names per country_id.

- **CP_country / CP_country_code**: the dataset's country, matched from dataset_name
  to country.json (accent-folded + an alias table for MICS spellings — DRCongo,
  Lao PDR→Laos, Viet Nam→Vietnam, Swaziland, North Macedonia, São Tomé, …; sub-
  national surveys map to the mother country — Pakistan (Punjab)→Pakistan, Kenya
  (…County)→Kenya, Egypt (Sub-national)→Egypt; Palestinians-in-Lebanon→Lebanon).
  255/255 datasets matched.
- **CP_subnational**: the household's admin-1 unit *name*. The raw `region` column
  holds a numeric code; the code→name labels live in the HH-module SAV. Each code's
  label is canonicalised to the state.json name for that country (exact → accent-
  /case-fold → strip region/province words → safe fuzzy, Levenshtein ≤2, no
  substring guessing). If it matches, `CP_subnational_matched=1` and the value is the
  state.json spelling; otherwise the cleaned raw label is kept (`=0`). ~52 % of codes
  match the reference; the rest keep their real raw name (macro-regions / trans-
  literation / re-districting differ from admin-1). Datasets with no region labels in
  the SAV (or no `region` code in the merged data) are left NULL.

No per-row SAV reads: only SAV *metadata* (value labels) is swept once to build the
`(dataset, region_code) → name` map; application maps the existing `region` column.

Usage:
    .venv/bin/python src/patch_geolocation.py --build     # build/refresh geo-map cache
    .venv/bin/python src/patch_geolocation.py             # apply all tables
    .venv/bin/python src/patch_geolocation.py --verify
"""
from __future__ import annotations

import io
import json
import glob
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
GEO = Path("data/geolocation")
CACHE = GEO / "_geo_maps_cache.json"
RAW = Path([ln.split("=", 1)[1].strip().strip("'\"")
            for ln in open(".env") if ln.startswith("DATA_RAW_DIR")][0])

TABLES = {
    "final_HH_MICS": "MICS-HH/data/HH/processed_data/hh_merged.parquet",
    "final_WM_MICS": "MICS-WM/data/WM/processed_data/wm_merged.parquet",
    "final_CH_MICS": "MICS-CH/data/CH/processed_data/ch_merged.parquet",
    "final_HL_MICS": "MICS-HL/data/HL/processed_data/hl_merged.parquet",
}
CP_C, CP_CC = "CP_country", "CP_country_code"
CP_S, CP_SM = "CP_subnational", "CP_subnational_matched"
CP_D, CP_DM = "CP_district", "CP_district_matched"

ALIAS = {
    "cote d'ivoire": "Côte d'Ivoire", "drcongo": "Democratic Republic of the Congo",
    "congo, democratic republic of": "Democratic Republic of the Congo",
    "congo": "Republic of the Congo", "lao pdr": "Laos",
    "lao people's democratic republic": "Laos", "viet nam": "Vietnam", "vietnam": "Vietnam",
    "kyrgyz republic": "Kyrgyzstan", "guinea bissau": "Guinea-Bissau",
    "sao tome and principe": "São Tomé and Príncipe", "sao tome and principle": "São Tomé and Príncipe",
    "the gambia": "Gambia", "st.lucia": "Saint Lucia", "st lucia": "Saint Lucia",
    "macedonia": "North Macedonia", "macedonia, the former yugoslav republic of": "North Macedonia",
    "republic of north macedonia": "North Macedonia", "state of palestine": "Palestine",
    "palestinians in lebanon": "Lebanon", "lebanon (palestinians)": "Lebanon", "kosovo": "Kosovo",
}
FILLER = re.compile(r"\b(datasets?|spss|datafiles?|data)\b", re.I)
STRIP = re.compile(r"\b(region|province|governorate|state|division|district|zone|oblast|county|prov|gov|no)\b")


def fold(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _lev(a, b):
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def build_maps():
    country = json.load(open(GEO / "country.json"))
    state = json.load(open(GEO / "state.json"))
    canon = {fold(c["country_name"]): (c["country_name"], c["country_code"]) for c in country}
    alias_f = {fold(k): v for k, v in ALIAS.items()}
    name2code = {c["country_name"]: c["country_code"] for c in country}

    def clean(n):
        n = re.split(r"\s*[_ ]?MICS\d?|_LSIS|\bLSIS\b|\b(19|20)\d\d\b", n)[0]
        n = n.replace("_", " ")
        n = FILLER.sub(" ", n)
        n = re.sub(r"\s+\d+\s*$", "", n)
        return re.sub(r"\s+", " ", n).strip(" -_")

    def country_of(ds):
        raw = ds.replace("_", " ")
        cands = [clean(ds)]
        m = re.search(r"MICS\d?\s+([A-Za-z].*)", raw)
        if m:
            cands.append(clean(m.group(1)))
        cands += [re.sub(r"\s*\(.*?\)\s*", " ", c).strip() for c in cands]
        for c in cands:
            if not c:
                continue
            f = fold(c)
            if f in alias_f:
                return alias_f[f]
            if f in canon:
                return canon[f][0]
        toks = fold(clean(ds)).split()
        for j in range(len(toks), 0, -1):
            f = " ".join(toks[:j])
            if f in alias_f:
                return alias_f[f]
            if f in canon:
                return canon[f][0]
        return None

    by_c = {}
    for s in state:
        by_c.setdefault(s["country_id"], {})[fold(s["name"])] = s["name"]

    def canon_region(nm, code):
        cand = by_c.get(code, {})
        if not cand:
            return None
        f = fold(nm)
        if f in cand:
            return cand[f]
        f2 = re.sub(r"\s+", " ", STRIP.sub(" ", f)).strip()
        if f2 and f2 in cand:
            return cand[f2]
        if len(f2) >= 4:
            best, bd = None, 3
            for k, v in cand.items():
                d = _lev(f2, k)
                if d < bd:
                    bd, best = d, v
                elif d == bd:
                    best = None
            if best and bd <= 2:
                return best
        return None

    def sav(ds):
        for p in (RAW / ds / "hh.sav", RAW / ds / "HH.sav"):
            if p.exists():
                return p
        g = [q for q in glob.glob(str(RAW / ds / "*.sav")) if "hh" in os.path.basename(q).lower()]
        return Path(g[0]) if g else None

    # admin-1 raw source columns per dataset for `region` and `province`, from the HH
    # alignment (both are admin-1 — some surveys' HH7 landed in `province`, not `region`).
    import yaml
    al = yaml.safe_load(open("MICS-HH/data/HH/alignment_v2.yaml"))
    reg_src = {e["dataset_name"]: e["column_in_raw_sav"] for e in al.get("region", [])}
    prov_src = {e["dataset_name"]: e["column_in_raw_sav"] for e in al.get("province", [])}
    dist_src = {e["dataset_name"]: e["column_in_raw_sav"] for e in al.get("district", [])}

    def label_map(m, var, code):
        vl = m.variable_value_labels.get(var, {}) if var else {}
        out = {}
        for c, nm in vl.items():
            try:
                key = str(float(c))
            except (TypeError, ValueError):
                continue
            cr = canon_region(nm, code) if code else None
            out[key] = [cr, 1] if cr else [re.sub(r"\s+", " ", str(nm)).strip().title(), 0]
        return out

    def pick(m, prefer):
        low = {v.upper(): v for v in m.column_names}
        for cand in prefer:
            if cand and cand.upper() in low:
                return low[cand.upper()]
        return None

    import pyreadstat
    allds = set()
    for p in TABLES.values():
        allds |= set(pd.read_parquet(p, columns=["dataset_name"]).dataset_name.unique())
    cmap, regions, provinces, districts = {}, {}, {}, {}
    for ds in sorted(allds):
        cn = country_of(ds)
        cmap[ds] = [cn, name2code.get(cn)]
        code = name2code.get(cn)
        s = sav(ds)
        if not s:
            continue
        try:
            _, m = pyreadstat.read_sav(str(s), metadataonly=True)
        except Exception:
            continue
        rvar = pick(m, [reg_src.get(ds), "HH7", "HI7", "REGION"])
        pvar = pick(m, [prov_src.get(ds), "PROVINCE", "PROV", "HHA", "HI7A", "HH1A"])
        dvar = pick(m, [dist_src.get(ds), "HH7A", "HH7B", "DISTRICT"])
        rmm = label_map(m, rvar, code)
        pmm = label_map(m, pvar, code)
        dmm = label_map(m, dvar, code)
        if rmm:
            regions[ds] = rmm
        if pmm:
            provinces[ds] = pmm
        if dmm:
            districts[ds] = dmm
    obj = {"country": cmap, "regions": regions, "provinces": provinces, "districts": districts}
    json.dump(obj, open(CACHE, "w"), ensure_ascii=False)
    print(f"  built maps: country {sum(1 for v in cmap.values() if v[0])}/{len(cmap)}; "
          f"region {len(regions)}; province {len(provinces)}; district {len(districts)}")
    return obj


def _maps():
    if not CACHE.exists():
        return build_maps()
    return json.load(open(CACHE))


def _apply_cols(df, maps):
    cmap = maps["country"]; regions = maps["regions"]; provinces = maps.get("provinces", {})
    cc = df["dataset_name"].map(lambda d: (cmap.get(d) or [None, None])[0])
    ccode = df["dataset_name"].map(lambda d: (cmap.get(d) or [None, None])[1])
    code_r = pd.to_numeric(df["region"], errors="coerce")
    code_p = pd.to_numeric(df["province"], errors="coerce") if "province" in df.columns \
        else pd.Series(np.nan, index=df.index)
    districts = maps.get("districts", {})
    code_d = pd.to_numeric(df["district"], errors="coerce") if "district" in df.columns \
        else pd.Series(np.nan, index=df.index)
    sub = pd.Series(pd.NA, index=df.index, dtype="object")
    matched = pd.Series(np.nan, index=df.index)
    dist = pd.Series(pd.NA, index=df.index, dtype="object")
    dmatched = pd.Series(np.nan, index=df.index)
    for ds, g in df.groupby("dataset_name", sort=False):
        rm = regions.get(ds); pm = provinces.get(ds); dm = districts.get(ds)
        idx = g.index
        # admin-1 (CP_subnational) from `region` (primary), else `province`
        for cd, mp in ((code_r.loc[idx], rm), (code_p.loc[idx], pm)):
            if not mp:
                continue
            need = sub.loc[idx].isna() & cd.notna()
            if not need.any():
                continue
            nm = cd[need].map(lambda x: mp.get(str(x), [None, None])[0])
            fl = cd[need].map(lambda x: mp.get(str(x), [None, None])[1])
            sub.loc[nm.index] = nm.values
            matched.loc[fl.index] = pd.to_numeric(fl, errors="coerce").values
        # admin-2 (CP_district) from `district`
        if dm:
            cd = code_d.loc[idx]
            nm = cd.map(lambda x: dm.get(str(x), [None, None])[0] if pd.notna(x) else None)
            fl = cd.map(lambda x: dm.get(str(x), [None, None])[1] if pd.notna(x) else None)
            dist.loc[idx] = nm.values
            dmatched.loc[idx] = pd.to_numeric(fl, errors="coerce").values
    return cc, ccode, sub, matched, dist, dmatched


def process_table(table, maps, verify):
    path = Path(TABLES[table])
    df = pd.read_parquet(path)
    if verify:
        for c in (CP_C, CP_CC, CP_S, CP_SM, CP_D, CP_DM):
            n = int(df[c].notna().sum()) if c in df.columns else 0
            nds = df.loc[df[c].notna(), "dataset_name"].nunique() if c in df.columns else 0
            print(f"  [{table}] {c}: non-null={n} / {nds} ds")
        return
    if not path.with_suffix(".parquet.bak_p27").exists():
        shutil.copy2(path, path.with_suffix(".parquet.bak_p27"))
    cc, ccode, sub, matched, dist, dmatched = _apply_cols(df, maps)
    df[CP_C] = cc.values
    df[CP_CC] = ccode.values
    df[CP_S] = sub.values
    df[CP_SM] = matched.values
    df[CP_D] = dist.values
    df[CP_DM] = dmatched.values
    df.to_parquet(path, index=False)
    print(f"  [{table}] country={df[CP_C].notna().sum()} / subnational={df[CP_S].notna().sum()} "
          f"({df.loc[df[CP_S].notna(),'dataset_name'].nunique()} ds) / district={df[CP_D].notna().sum()} "
          f"({df.loc[df[CP_D].notna(),'dataset_name'].nunique()} ds)")


def _col(cur, table, col):
    cur.execute("""SELECT data_type FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    r = cur.fetchone()
    return r[0] if r else None


def sync_db(table, maps, verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = f'"{table}"'
    if verify:
        for c in (CP_C, CP_CC, CP_S, CP_SM, CP_D, CP_DM):
            cur.execute(f'SELECT COUNT("{c}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{c}" IS NOT NULL) FROM {T}')
            print(f"  [{table}] db {c}: {cur.fetchone()}")
        conn.close(); return

    pcols = ["dataset_name", "region", CP_C, CP_CC, CP_S, CP_SM, CP_D, CP_DM]
    has_prov = _col(cur, table, "province") is not None
    has_dist = _col(cur, table, "district") is not None
    if has_prov:
        pcols.insert(2, "province")
    if has_dist:
        pcols.insert(3, "district")
    df = pd.read_parquet(TABLES[table], columns=pcols)
    for c, t in ((CP_C, "TEXT"), (CP_CC, "TEXT"), (CP_S, "TEXT"), (CP_SM, "SMALLINT"),
                 (CP_D, "TEXT"), (CP_DM, "SMALLINT")):
        if not _col(cur, table, c):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{c}" {t}')
    cur.execute(f'UPDATE {T} SET "{CP_C}"=NULL,"{CP_CC}"=NULL,"{CP_S}"=NULL,"{CP_SM}"=NULL,'
                f'"{CP_D}"=NULL,"{CP_DM}"=NULL')

    # CP_country/code: one row per dataset
    cpc = df.drop_duplicates("dataset_name")[["dataset_name", CP_C, CP_CC]].dropna(subset=[CP_C])
    cur.execute("CREATE TEMP TABLE _c(dataset text, cn text, cc text) ON COMMIT DROP")
    buf = io.StringIO(); cpc.to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
    cur.copy_expert("COPY _c(dataset,cn,cc) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", buf)
    cur.execute(f'UPDATE {T} f SET "{CP_C}"=m.cn, "{CP_CC}"=m.cc FROM _c m WHERE f.dataset_name=m.dataset')

    # CP_subnational/matched is a deterministic function of (dataset, region code,
    # province code) — one composite-key LUT reproduces the parquet exactly (nulls
    # map to a sentinel so the join matches them).
    SENT = -999999.0

    def _cast(col):
        t = _col(cur, table, col)
        if t in ("double precision", "real", "numeric", "integer", "bigint", "smallint"):
            expr = f"f.{col}"
        else:
            expr = f"(CASE WHEN f.{col} ~ '^-?[0-9.]+$' THEN f.{col}::double precision END)"
        return f"COALESCE(ROUND({expr}::numeric, 6), {SENT})"  # round → dodge float round-trip drift

    # CP is a deterministic function of (dataset, region code, province code); round both
    # sides to 6 dp so a contaminated float `province` (e.g. Mongolia 2018) still matches.
    lut = df.dropna(subset=[CP_S]).copy()
    rc = pd.to_numeric(lut["region"], errors="coerce").round(6)
    pc = (pd.to_numeric(lut["province"], errors="coerce").round(6)
          if has_prov else pd.Series(np.nan, index=lut.index))
    lut["_rc"] = rc.fillna(SENT)
    lut["_pc"] = pc.fillna(SENT)
    lut = lut.drop_duplicates(["dataset_name", "_rc", "_pc"])[
        ["dataset_name", "_rc", "_pc", CP_S, CP_SM]]
    lut[CP_SM] = lut[CP_SM].astype("Int64")
    cur.execute("CREATE TEMP TABLE _s(dataset text, rc double precision, pc double precision, "
                "nm text, mt smallint) ON COMMIT DROP")
    b = io.StringIO(); lut.to_csv(b, index=False, header=False, na_rep="\\N"); b.seek(0)
    cur.copy_expert("COPY _s(dataset,rc,pc,nm,mt) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", b)
    cur.execute("CREATE INDEX ON _s(dataset,rc,pc)")
    pc_e = _cast("province") if has_prov else str(SENT)
    cur.execute(f'UPDATE {T} f SET "{CP_S}"=m.nm, "{CP_SM}"=m.mt FROM _s m '
                f'WHERE f.dataset_name=m.dataset AND {_cast("region")}=m.rc AND {pc_e}=m.pc')

    # CP_district/matched: per (dataset, district code)
    n_d = 0
    if has_dist:
        dl = df.dropna(subset=[CP_D]).copy()
        dl["_dc"] = pd.to_numeric(dl["district"], errors="coerce").round(6)
        dl = dl.dropna(subset=["_dc"]).drop_duplicates(["dataset_name", "_dc"])[
            ["dataset_name", "_dc", CP_D, CP_DM]]
        dl[CP_DM] = dl[CP_DM].astype("Int64")
        n_d = len(dl)
        if n_d:
            cur.execute("CREATE TEMP TABLE _d(dataset text, dc double precision, nm text, mt smallint) ON COMMIT DROP")
            b2 = io.StringIO(); dl.to_csv(b2, index=False, header=False, na_rep="\\N"); b2.seek(0)
            cur.copy_expert("COPY _d(dataset,dc,nm,mt) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", b2)
            cur.execute("CREATE INDEX ON _d(dataset,dc)")
            cur.execute(f'UPDATE {T} f SET "{CP_D}"=m.nm, "{CP_DM}"=m.mt FROM _d m '
                        f'WHERE f.dataset_name=m.dataset AND {_cast("district")}=m.dc')
    print(f"  [{table}] db: country {len(cpc)} ds; subnational {len(lut)}; district {n_d} combos")
    conn.commit(); conn.close()


def main():
    if "--build" in sys.argv:
        print("P27 geolocation — BUILD MAPS"); build_maps(); return
    verify = "--verify" in sys.argv
    print(f"P27 geolocation — {'VERIFY' if verify else 'APPLY'}")
    maps = {} if verify else _maps()
    for table in TABLES:
        process_table(table, maps, verify)
        sync_db(table, maps, verify)
    print("Done.")


if __name__ == "__main__":
    main()
