"""
P20 — Carefully process `place_of_delivery` -> `CP_place_of_delivery` (WM):
a harmonised 5-category place of delivery.

Raw `place_of_delivery` uses the MICS/DHS scheme where numeric codes vary across
datasets and rounds (1x home, 2x public, 3x private, 4x/5x/6x other/NGO/UNRWA,
96 other, 9x missing) — plus single-digit country-specific schemes. So mapping
is **per-dataset, driven by value labels** (multilingual EN/FR/ES/PT), exactly
like education harmonisation (P02).

CP_place_of_delivery:
  1 = Home
  2 = Public health facility (government hospital/clinic/health centre/post, ...)
  3 = Private health facility (private hospital/clinic/maternity/practitioner)
  4 = Other health facility (NGO/mission/faith/UNRWA, or facility with sector
      unspecified, incl. "DK public or private")
  5 = Other / en route (other, on the road, at a checkpoint)
  NULL = DK / missing / incoherent / unmappable (incl. duration-miscoded
         datasets whose column is actually a time, and yes/no mis-maps)

The raw `place_of_delivery` is left unchanged. CP_ depends only on
(dataset, raw code) so the DB update is a single keyless map join.

Usage:
    .venv/bin/python MICS-WM/src/patch_place_of_delivery.py            # apply
    .venv/bin/python MICS-WM/src/patch_place_of_delivery.py --verify   # check
"""
from __future__ import annotations

import io
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "place_of_delivery"
CP = "CP_place_of_delivery"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")

# Alignment gap: these datasets DID collect place of delivery but it was never
# mapped (raw "Lieu d'accouchement" / "Lugar del parto" / "Where did you give
# birth" columns). Validated: each column's value labels classify to place
# categories (not "who assisted/decided" or duration). Recovered by guarded
# positional backfill (household_number == HH2 = 100%); datasets whose alignment
# can't be verified are skipped + reported.
RECOVER = {
    "Algeria MICS6 Datasets": "MN20", "Algeria_MICS4_Datasets": "MN18",
    "Argentina MICS6 Datasets": "MN20", "Bolivia 2000 MICS_Datasets": "NN3",
    "Burkina Faso MICS 2006 SPSS Datasets": "MN8", "Burundi MICS 2005 SPSS Datasets": "MN8",
    "Cameroon MICS 2006 SPSS Datasets": "MN8", "Central African Republic MICS 2006 SPSS Datasets": "MN8",
    "Chad_MICS4_Datasets": "MN18", "Congo_MICS5_Datasets": "MN18",
    "Costa Rica MICS6 Datasets": "MN20", "Cote d'Ivoire 2006 MICS_Datasets": "MN8",
    "Cuba MICS6 Datasets": "MN20", "Cuba_MICS5_Datasets": "MN18",
    "DRCongo MICS6 SPSS Datafiles": "MN20", "Djibouti MICS 2006 SPSS Datasets": "MN8",
    "Dominican Republic_MICS5_Datasets": "MN18", "Guinea Bissau MICS6 Datasets": "MN20",
    "Guinea Bissau_MICS5_Datasets": "MN18", "Guinea-Bissau MICS 2006 SPSS Datasets": "MN8",
    "Honduras MICS6 Datasets": "MN20", "Kyrgyzstan MICS 2005-06 SPSS Datasets": "mn8",
    "Mauritania MICS 2007 SPSS Datasets": "MN8", "Mauritania_MICS5_Datasets": "MN18",
    "Mauritania_MICS5_Datasets 2": "MN18", "Mongolia (Khuvsgul Aimag)_MICS4_Datasets": "MN18",
    "Mongolia (Khuvsgul Aimag)_MICS5_Datasets": "MN18", "Mongolia (Nalaikh District)_MICS4_Datasets": "MN18",
    "Mongolia (Nalaikh District)_MICS5_Datasets": "MN18", "Mongolia MICS 2005 SPSS Datasets": "MN8",
    "Mongolia_MICS4_Datasets": "MN18", "Panama_MICS5_Datasets": "MN18",
    "Sao Tome and Principe_MICS5_Datasets": "MN18", "Senegal 2000 MICS_Datasets": "MN3AA",
    "Thailand_MICS4_Datasets": "MN18", "Togo MICS 2006 SPSS Datasets": "mn8",
    "Uruguay_MICS4_Datasets": "MN18", "Mozambique MICS 2008 Datasets": "MN8",
}

_MISS = re.compile(
    r"missing|no response|no answer|don'?t know|^dk$|\bdk\b|inconsist|incoher|refus"
    r"|not applicable|sans objet|non d[eé]clar|n[ãa]o declarad|manquant|\bnsp\b"
    r"|non r[eé]ponse|pas de r[eé]ponse|sem resposta|^\s*$"
    r"|^hours?$|^days?$|^weeks?$|^months?$|heures|jours|semaines"
    r"|^yes$|^no$|^oui$|^non$", re.I)
_FAC_UNK = re.compile(r"public or private|whether public|dk (public|whether)", re.I)
_HOME = re.compile(
    r"\bhome\b|at home|respondent'?s (home|house)|other home|house of|house/apartment"
    r"|\bhouse\b|apartment|\bhut\b|\bmaison\b|domicile|[àa] la maison|en casa|\bcasa\b"
    r"|em casa|domic[ií]lio|na (sua )?casa|\bchez\b", re.I)
_PRIV = re.compile(r"priv[ae]t|priv[ée]|privad|private practitioner|cabinet m[eé]dical priv", re.I)
_PUB = re.compile(
    r"government|govt\b|public|gouvernement|publique|p[uú]blic|estatal|\bphcf\b|soum"
    r"|dispensaire public", re.I)
_NGO = re.compile(r"\bngo\b|\bong\b|mission|faith|church|unrwa|israeli|\bcham\b", re.I)
_FAC = re.compile(
    r"hospital|h[oô]pital|clinic|clinique|cl[ií]nica|maternit|dispensaire"
    r"|health (facility|centre|center|post|institution|unit|office)|centre de sant"
    r"|centro de sa[uú]de|posto de sa[uú]de|case de sant|\bcentre\b|\bcenter\b|\bcentro\b"
    r"|\bposto\b|nursing station|salle de soins|cabinet (de soins|d'accouch|m[eé]dical)"
    r"|unit[eé] (villageoise|de sant)|\bebais\b|\bcscom\b|\bcsref\b|\bcma\b|\bchu\b|\bcms\b"
    r"|\bpmi\b|\bbhu\b|\bfhu\b|\bphcu\b|\bfpan\b|poly ?clin|family doctor|health office"
    r"|outreach|facility|villageoise", re.I)
_ENROUTE = re.compile(
    r"on the (road|way)|en route|way to|road while|checkpoint|outside of country"
    r"|outside country|\bother\b|\bautre\b|\botro\b|\boutro\b", re.I)


def _classify(label):
    t = str(label).strip()
    if _FAC_UNK.search(t): return 4.0
    if _MISS.search(t): return None
    if _HOME.search(t): return 1.0
    if _PRIV.search(t): return 3.0
    if _PUB.search(t): return 2.0
    if _NGO.search(t): return 4.0
    if _FAC.search(t): return 4.0
    if _ENROUTE.search(t): return 5.0
    return None


def _value_labels(ds, raw):
    yml = ROOT / "raw" / ds / "wm.yaml"
    if not raw or not yml.exists():
        return {}
    loaded = yaml.safe_load(open(yml, encoding="utf-8")) or []
    cols = loaded.get("columns", []) if isinstance(loaded, dict) else loaded
    for c in cols:
        if isinstance(c, dict) and (c.get("column_in_raw_sav") or "").lower() == raw.lower():
            return c.get("value_labels") or {}
    return {}


def _labels_to_map(vl):
    m = {}
    for k, v in (vl or {}).items():
        try:
            code = float(k)
        except (TypeError, ValueError):
            continue
        cat = _classify(v)
        if cat is not None:
            m[code] = cat
    return m


def _find_wm_sav(ds):
    d = RAW / ds
    if (d / "wm.sav").exists():
        return d / "wm.sav"
    cands = [p for p in d.glob("*.sav") if p.stem.lower().startswith("wm")] if d.exists() else []
    return cands[0] if cands else None


def _recover(ds, col, parquet_ds):
    """Read the place col from the WM SAV, guarded positional alignment."""
    import pyreadstat
    sav = _find_wm_sav(ds)
    if sav is None:
        return None, "no WM SAV"
    df, _ = pyreadstat.read_sav(str(sav))
    low = {c.lower(): c for c in df.columns}
    cc = low.get(col.lower())
    hh = next((low[k] for k in ("hh2", "whhhno", "chhhno", "hh02", "hhnum") if k in low), None)
    if cc is None or hh is None:
        return None, f"col {col}({cc}) or hh-key({hh}) absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["hh_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[hh].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 1.0:
        return None, f"guard hh_number=={hh} {(a==b).mean():.2%}"
    return pd.to_numeric(df[cc].reset_index(drop=True), errors="coerce"), "ok"


def _build_maps(observed_by_ds):
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    raws_by_ds = defaultdict(list)
    for e in al.get(BASE, []):
        raws_by_ds[e["dataset_name"]].append(e.get("column_in_raw_sav") or "")
    for ds, col in RECOVER.items():          # ensure recovered cols' labels are read
        if col not in raws_by_ds[ds]:
            raws_by_ds[ds].append(col)
    maps = {}
    for ds, raws in raws_by_ds.items():
        obs = observed_by_ds.get(ds, set())
        cands = [m for m in (_labels_to_map(_value_labels(ds, r)) for r in raws) if m]
        if not cands:
            maps[ds] = {}
            continue
        # pick the raw column whose codes best cover the values actually present
        maps[ds] = max(cands, key=lambda m: (len(obs & set(m)), len(m)))
    return maps


def _observed(df):
    base = pd.to_numeric(df[BASE], errors="coerce")
    return {ds: set(s.dropna().unique()) for ds, s in base.groupby(df["dataset_name"])}


def _apply(df, maps):
    base = pd.to_numeric(df[BASE], errors="coerce")
    cp = pd.Series(np.nan, index=df.index)
    for ds, m in maps.items():
        dm = df["dataset_name"] == ds
        if dm.any() and m:
            cp.loc[dm] = base[dm].map(m)
    return cp


def patch_parquet(verify):
    if verify:
        df = pd.read_parquet(PARQUET, columns=["dataset_name", BASE, CP])
        cp = _apply(df, _build_maps(_observed(df)))
        ok = df[CP].equals(cp)
        cp_ds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={int(cp.notna().sum())} "
              f"across {cp_ds} datasets; dist={ {int(k):int(v) for k,v in cp.value_counts().sort_index().items()} }")
        return []
    df = pd.read_parquet(PARQUET)
    df[BASE] = df[BASE].astype(object)  # base is arrow-string; allow writing codes
    # recover: backfill base from unmapped place columns (guarded)
    applied = []
    for ds, col in RECOVER.items():
        mask = (df["dataset_name"] == ds).values
        if not mask.any():
            continue
        s, note = _recover(ds, col, df.loc[mask])
        if s is None:
            print(f"  [skip] {ds[:40]}: {note}")
            continue
        idx = df.index[mask]
        strv = pd.Series([str(v) if pd.notna(v) else None for v in s.values], index=idx)
        df.loc[idx[strv.notna()], BASE] = strv[strv.notna()].values
        applied.append(ds)
        print(f"  [ok]   {ds[:40]}: base <- {col} ({int(s.notna().sum())} rows)")
    full = df
    full[CP] = _apply(full, _build_maps(_observed(full)))
    if not PARQUET.with_suffix(".parquet.bak_p20").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p20"))
    full.to_parquet(PARQUET, index=False)
    cpf = full[CP]
    print(f"  parquet: {CP} non-null={int(cpf.notna().sum())} across "
          f"{full.loc[cpf.notna(),'dataset_name'].nunique()} datasets; recovered {len(applied)}; "
          f"dist={ {int(k):int(v) for k,v in cpf.value_counts().sort_index().items()} }")
    return applied


def patch_yaml(applied):
    if not applied:
        print("  yaml: nothing to add"); return
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    entries = al.setdefault(BASE, [])
    have = {(e["dataset_name"], (e.get("column_in_raw_sav") or "")) for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p20").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p20"))
    added = 0
    for ds in applied:
        if (ds, RECOVER[ds]) in have:
            continue
        entries.append({
            "canonical_text": "Place of delivery", "canonical_varname": BASE,
            "column_in_raw_sav": RECOVER[ds], "column_label_in_english": "Place of delivery",
            "component": None, "confidence": "high", "dataset_name": ds, "derivation": None,
            "entities": [], "entity_operator": None, "event": None, "is_compound": False,
            "measure_type": "maternal_health", "needs_review": False, "relation": None,
            "response_type": "categorical", "source_kind": "explicit",
        })
        added += 1
    yaml.safe_dump(al, open(ALIGN, "w", encoding="utf-8"), allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {BASE} mappings")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied, verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'; I = '"ind_que_WM_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL), '
                    f'COUNT(*) FILTER (WHERE "{CP}" NOT IN (1,2,3,4,5)) FROM {T}')
        n, nds, bad = cur.fetchone()
        cur.execute(f'SELECT "{CP}", COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL GROUP BY 1 ORDER BY 1')
        dist = {int(k): v for k, v in cur.fetchall()}
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} datasets; invalid={bad}; dist={dist}; "
              f"ind_que rows={cur.fetchone()[0]}")
        conn.close(); return

    pdf = pd.read_parquet(PARQUET)
    maps = _build_maps(_observed(pdf[["dataset_name", BASE]]))
    if not _col_exists(cur, "final_WM_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    cur.execute(f'UPDATE {T} SET "{CP}" = NULL')
    # keyless map join for datasets whose base is unchanged (not recovered)
    rows = [(ds, code, cat) for ds, m in maps.items() if ds not in applied
            for code, cat in m.items()]
    cur.execute("CREATE TEMP TABLE _pmap(ds text, raw double precision, cp double precision) ON COMMIT DROP")
    b = io.StringIO(); pd.DataFrame(rows, columns=["ds", "raw", "cp"]).to_csv(b, index=False, header=False); b.seek(0)
    cur.copy_expert("COPY _pmap FROM STDIN WITH (FORMAT CSV)", b)
    cur.execute(f"UPDATE {T} f SET \"{CP}\" = m.cp FROM _pmap m "
                f"WHERE f.dataset_name = m.ds "
                f"AND f.{BASE} ~ '^-?[0-9]+(\\.[0-9]+)?$' AND f.{BASE}::float = m.raw")
    print(f"  db: CP_ mapped via {len(rows)} (dataset,code) rules")

    # recovered datasets: base changed -> delete + re-insert from patched parquet
    if applied:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name='final_WM_MICS'""")
        dbtype = dict(cur.fetchall()); cols = list(pdf.columns)
        assert all(c in dbtype for c in cols), "DB missing a parquet column"
        for ds in applied:
            sub = pdf[pdf["dataset_name"] == ds].copy()
            for c in cols:
                if dbtype.get(c) == "bigint":
                    sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
                elif dbtype.get(c) == "double precision":
                    sub[c] = pd.to_numeric(sub[c], errors="coerce")
            cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
            buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
            collist = ", ".join(f'"{c}"' for c in cols)
            cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        print(f"  db: re-inserted {len(applied)} recovered datasets")

    # ind_que: base rows for recovered datasets + mirror base -> CP_
    for ds in applied:
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{BASE}' AND dataset_name=%s "
                    f"AND column_in_raw_sav=%s", (ds, RECOVER[ds]))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (BASE, ds, RECOVER[ds], "Place of delivery", "explicit",
             "maternal_health", "Place of delivery"))
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{BASE}' ''')
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que {CP} rows={cur.fetchone()[0]}")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P20 place_of_delivery -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(applied)
    print("== database =="); patch_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
