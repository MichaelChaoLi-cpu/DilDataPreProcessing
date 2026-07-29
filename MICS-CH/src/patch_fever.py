"""
P16 — Carefully process `fever_last_2_weeks` -> `CP_fever_last_2_weeks` (CH).

Same family as diarrhea (P15): a yes/no child-symptom variable with coding that
varies across datasets, so mapping is **per-dataset, driven by value labels**.
Target: 1=Yes, 0=No, NULL=DK/missing/unknown.

fever is cleaner than diarrhea — investigation found:
  * most datasets: standard 1=Yes, 2=No (+ sentinels 7/8/9 -> NULL);
  * 5 unlabeled datasets (Angola 2001, CAR 2006, Indonesia MICS2, Madagascar
    2000, Venezuela 2000): values {0,100} -> 100=Yes, 0=No (confirmed by implied
    prevalence 3-28%); handled by FALLBACK;
  * Sao Tome MICS5: Portuguese labels (Sim/Não) with mojibake -> FALLBACK maps
    1->Yes/2->No correctly;
  * NO scale flips (no Iraq/Yemen-style "yes without blood") and NO mis-mappings.

Because no dataset needs a source correction, `fever_last_2_weeks` (raw) is left
untouched and CP_ depends only on (dataset, raw value) — so the DB update is a
single keyless (dataset, code)->cp map join, no row re-insertion.

Usage:
    .venv/bin/python MICS-CH/src/patch_fever.py            # apply
    .venv/bin/python MICS-CH/src/patch_fever.py --verify   # check only
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

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "fever_last_2_weeks"
CP = "CP_fever_last_2_weeks"

_YES = re.compile(r"\byes\b|\boui\b|\bs[ií]\b|\bsim\b", re.I)
_NO = re.compile(r"^\s*n[o0]\b|\bno\b|\bnon\b|\bn[aã]o\b", re.I)
# DK/missing/refused — checked FIRST (many contain "no"/"non").
_MISS = re.compile(
    r"non d[eé]clar|not declared|not stated|missing|manquant|sans objet"
    r"|n[ãa]o declarad|sem resposta|no response|no answer|pas de r[eé]ponse"
    r"|ne sait|\bnsp\b|\bdk\b|don'?t know|inconsist|refus|no sabe|no responde"
    r"|sin (dato|informaci)|no aplica|not applicable", re.I)
# Sentinel codes are ALWAYS DK/missing for a yes/no item, whatever the (often
# mojibake/localised) label says.
SENTINEL_CODES = {7.0, 8.0, 9.0, 97.0, 98.0, 99.0}
FALLBACK = {1.0: 1.0, 2.0: 0.0, 100.0: 1.0, 0.0: 0.0}  # unlabeled datasets


def _classify(label: str):
    t = str(label)
    if _MISS.search(t):
        return None
    if _YES.search(t):
        return 1.0
    if _NO.search(t):
        return 0.0
    return None


def _value_labels(ds: str, raw: str) -> dict:
    yml = ROOT / "raw" / ds / "ch.yaml"
    if not raw or not yml.exists():
        return {}
    loaded = yaml.safe_load(open(yml, encoding="utf-8")) or []
    cols = loaded.get("columns", []) if isinstance(loaded, dict) else loaded
    for c in cols:
        if isinstance(c, dict) and (c.get("column_in_raw_sav") or "").lower() == raw.lower():
            return c.get("value_labels") or {}
    return {}


def _labels_to_map(vl: dict) -> dict:
    m = {}
    for k, v in (vl or {}).items():
        code = float(k)
        if code in SENTINEL_CODES:
            continue
        cp = _classify(v)
        if cp is not None:
            m[code] = cp
    return m


def _build_maps(observed_by_ds: dict):
    """{dataset: {raw_code: 1.0/0.0}}.

    A dataset may map the canonical from several raw columns AND the merged base
    column may hold values from a DIFFERENT source than the nicest-labelled one
    (e.g. MICS2 datasets whose base is {0,100} but which also map a 1/2-labelled
    column). So the chosen map must MATCH THE ACTUAL base values: among each
    dataset's candidate label-maps plus FALLBACK, pick the one covering the most
    of the values actually present (tie -> the tightest, non-FALLBACK map).
    `observed_by_ds[ds]` = set of non-null base values present for that dataset.
    """
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    raws_by_ds = defaultdict(list)
    for e in al.get(BASE, []):
        raws_by_ds[e["dataset_name"]].append(e.get("column_in_raw_sav") or "")
    # ensure the recovered (ML1/CA6AA) columns are candidates even before the
    # yaml is rewritten, so the recovery propagates to CP_ within one run.
    for ds, col in RECOVER.items():
        if col not in raws_by_ds[ds]:
            raws_by_ds[ds].append(col)
    maps, nonstd = {}, []
    for ds, raws in raws_by_ds.items():
        obs = observed_by_ds.get(ds, set())
        labelmaps = [m for m in (_labels_to_map(_value_labels(ds, r)) for r in raws) if m]
        options = labelmaps + [dict(FALLBACK)]
        # maximise coverage of actually-observed codes; tie -> fewer keys,
        # and a real label-map beats the generic FALLBACK.
        m = max(options, key=lambda mp: (len(obs & set(mp)), -len(mp),
                                         mp != FALLBACK))
        maps[ds] = m
        if m.get(2.0) == 1.0 or set(m) - {1.0, 2.0}:
            nonstd.append((ds, m))
    return maps, nonstd


def _observed(df: pd.DataFrame) -> dict:
    base = pd.to_numeric(df[BASE], errors="coerce")
    out = {}
    for ds, s in base.groupby(df["dataset_name"]):
        vals = set(s.dropna().unique()) - SENTINEL_CODES
        out[ds] = vals
    return out


# Alignment gap: "fever in last 2 weeks" was not mapped for these datasets — the
# question sits in the malaria module (ML1) or a Spanish CA6AA column that the
# fever alignment (CA-module only) missed. Recover base from these raw columns
# (positional, guarded household_number==HH2 100%).
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
RECOVER = {
    "Burkina Faso MICS 2006 SPSS Datasets": "ML1",
    "Djibouti MICS 2006 SPSS Datasets": "ML1",
    "Guinea-Bissau MICS 2006 SPSS Datasets": "ML1",
    "Mauritania MICS 2007 SPSS Datasets": "ML1",
    "Togo MICS 2006 SPSS Datasets": "ml1",
    "Dominican Republic_MICS5_Datasets": "CA6AA",
    "Paraguay_MICS5_Datasets": "CA6AA",
    "Sao Tome and Principle 2000 MICS_Datasets": "ML1",   # SAV=ChST.sav, key=CHHHNO
    "State of Palestine_MICS4_Datasets": "PCA6",          # was mis-mapped to respondent_name
}


def _find_ch_sav(ds: str):
    d = RAW / ds
    if (d / "ch.sav").exists():
        return d / "ch.sav"
    cands = [p for p in d.glob("*.sav") if p.stem.lower().startswith("ch")] if d.exists() else []
    return cands[0] if cands else None


def _recover(ds: str, col: str, parquet_ds: pd.DataFrame):
    """Read fever col from the CH SAV, guard positional alignment. None on failure.
    Handles alternate SAV names (ChST.sav) and household keys (HH2 / CHHHNO)."""
    import pyreadstat
    sav = _find_ch_sav(ds)
    if sav is None:
        return None, "no CH SAV"
    df, _ = pyreadstat.read_sav(str(sav))
    low = {c.lower(): c for c in df.columns}
    cc = low.get(col.lower())
    hh = low.get("hh2") or low.get("chhhno")
    if cc is None or hh is None:
        return None, f"col {col}({cc}) or hh-key({hh}) absent"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df[hh].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 1.0:
        return None, f"guard household_number=={hh} {(a==b).mean():.3%}"
    return pd.to_numeric(df[cc].reset_index(drop=True), errors="coerce"), "ok"


def _apply_cp(df: pd.DataFrame, maps: dict) -> pd.Series:
    base = pd.to_numeric(df[BASE], errors="coerce")
    cp = pd.Series(np.nan, index=df.index)
    for ds, m in maps.items():
        dm = (df["dataset_name"] == ds)
        if dm.any() and m:
            cp.loc[dm] = base[dm].map(m)
    return cp


def patch_parquet(verify: bool):
    df = pd.read_parquet(PARQUET)
    if not verify:
        # recover the alignment-gap datasets: base <- raw ML1/CA6AA (guarded)
        applied = []
        for ds, col in RECOVER.items():
            mask = df["dataset_name"] == ds
            if not mask.any():
                continue
            s, note = _recover(ds, col, df.loc[mask])
            if s is None:
                print(f"  [skip] {ds[:40]}: {note}")
                continue
            df.loc[mask, BASE] = s.values
            applied.append(ds)
            print(f"  [ok]   {ds[:40]}: base <- {col} ({int(s.notna().sum())} rows)")
    maps, nonstd = _build_maps(_observed(df))
    cp = _apply_cp(df, maps)
    if verify:
        ok = CP in df.columns and df[CP].equals(cp)
        n = int(cp.notna().sum()); nds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} ds "
              f"(Yes={int((cp==1).sum())}, No={int((cp==0).sum())})")
        return []
    if not PARQUET.with_suffix(".parquet.bak_p16").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p16"))
    df[CP] = cp
    df.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} non-null={int(cp.notna().sum())} across "
          f"{df.loc[cp.notna(),'dataset_name'].nunique()} datasets "
          f"(Yes={int((cp==1).sum())}, No={int((cp==0).sum())}); recovered {len(applied)} datasets")
    return applied


def patch_yaml(applied: list):
    if not applied:
        print("  yaml: nothing to add"); return
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    entries = al.setdefault(BASE, [])
    have = {(e["dataset_name"], (e.get("column_in_raw_sav") or "")) for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p16").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p16"))
    added = 0
    for ds in applied:
        if (ds, RECOVER[ds]) in have:
            continue
        entries.append({
            "canonical_text": "Had fever in last two weeks", "canonical_varname": BASE,
            "column_in_raw_sav": RECOVER[ds],
            "column_label_in_english": "Had fever in last two weeks",
            "component": None, "confidence": "high", "dataset_name": ds,
            "derivation": None, "entities": [], "entity_operator": None, "event": None,
            "is_compound": False, "measure_type": "child_health", "needs_review": False,
            "relation": None, "response_type": "yes_no", "source_kind": "explicit",
        })
        added += 1
    yaml.safe_dump(al, open(ALIGN, "w", encoding="utf-8"), allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {BASE} mappings (ML1/CA6AA)")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied: list, verify: bool):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor()
    T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL), '
                    f'COUNT(*) FILTER (WHERE "{CP}"=1), COUNT(*) FILTER (WHERE "{CP}"=0), '
                    f'COUNT(*) FILTER (WHERE "{CP}" NOT IN (0,1)) FROM {T}')
        n, nds, yes, no, bad = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} ds (Yes={yes},No={no}); "
              f"invalid(not 0/1)={bad}; ind_que CP_ rows={cur.fetchone()[0]}")
        conn.close(); return

    pdf = pd.read_parquet(PARQUET)
    maps, _ = _build_maps(_observed(pdf[["dataset_name", BASE]]))
    if not _col_exists(cur, "final_CH_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    cur.execute(f'UPDATE {T} SET "{CP}" = NULL')  # idempotent reset
    # keyless (dataset,code)->cp map join for datasets whose base is unchanged
    rows = [(ds, code, cp) for ds, m in maps.items() if ds not in applied
            for code, cp in m.items()]
    cur.execute("CREATE TEMP TABLE _fmap(ds text, raw double precision, cp double precision) ON COMMIT DROP")
    b = io.StringIO(); pd.DataFrame(rows, columns=["ds", "raw", "cp"]).to_csv(b, index=False, header=False); b.seek(0)
    cur.copy_expert("COPY _fmap FROM STDIN WITH (FORMAT CSV)", b)
    cur.execute(f'UPDATE {T} f SET "{CP}" = m.cp FROM _fmap m '
                f'WHERE f.dataset_name = m.ds AND f.{BASE} = m.raw')
    print(f"  db: CP_ mapped via {len(rows)} (dataset,code) rules")

    # recovered datasets: base changed -> delete + re-insert from patched parquet
    if applied:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name='final_CH_MICS'""")
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
            (BASE, ds, RECOVER[ds], "Had fever in last two weeks", "explicit",
             "child_health", "Had fever in last two weeks"))
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
    print(f"P16 fever_last_2_weeks -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); applied = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(applied)
    print("== database =="); patch_db(applied, verify)
    print("Done.")


if __name__ == "__main__":
    main()
