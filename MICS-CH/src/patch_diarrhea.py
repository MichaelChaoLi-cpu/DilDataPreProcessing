"""
P15 — Carefully process `diarrhea_last_2_weeks` -> `CP_diarrhea_last_2_weeks` (CH).

The raw variable is a yes/no with INCONSISTENT coding across datasets, which makes
a global 1->Yes/2->No mapping dangerous:
  * 214 datasets: standard 1=Yes, 2=No (+ sentinels 7/8/9).
  * Iraq 2006 & Yemen 2006: 1=Yes, 2=Yes-without-blood, 3=No  -> here **2 is YES**,
    so a global "2=No" would flip them.
  * 7 datasets (DRC 2001, Dominican Rep 2000, Guinea Bissau 2000, Indonesia MICS2,
    Madagascar 2000, Niger 2000, Venezuela 2000): unlabeled, values {0,100}.
    Downstream-var fill and implied prevalence (6-36%) confirm 100=Yes, 0=No.
  * Congo_MICS5: `diarrhea_last_2_weeks` was MIS-MAPPED to CA2 ("fluid intake
    during diarrhea"), not the real question CA1 ("had diarrhoea in last 2 weeks",
    1=Oui/2=Non). Fixed here: alignment remapped CA2->CA1 and base recovered from
    CA1 (positional, guarded household_number==HH2 100%).

So mapping is **per-dataset, driven by each dataset's value labels**: a code whose
label reads Yes (incl. "yes without blood") -> 1; No -> 0; DK/missing/unlabeled/
other -> NULL. Unlabeled datasets fall back to {1:1, 2:0, 100:1, 0:0}. This
naturally excludes non-yes/no labels. Target: 1=Yes, 0=No, NULL=DK/missing/unknown.

Original `diarrhea_last_2_weeks` is unchanged EXCEPT the Congo_MICS5 source fix
(CA2 was never valid diarrhea data).

Usage:
    .venv/bin/python MICS-CH/src/patch_diarrhea.py            # apply
    .venv/bin/python MICS-CH/src/patch_diarrhea.py --verify   # check only
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
import yaml

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "diarrhea_last_2_weeks"
CP = "CP_diarrhea_last_2_weeks"
CONGO = "Congo_MICS5_Datasets"
CONGO_FIX = ("CA2", "CA1")  # (wrong, correct)

_YES = re.compile(r"\byes\b|\boui\b|\bs[ií]\b|\bsim\b", re.I)
_NO = re.compile(r"^\s*n[o0]\b|\bno\b|\bnon\b|\bn[aã]o\b", re.I)
# DK/missing/refused/NA — checked FIRST because many contain "no"/"non"
# (e.g. French 9 = "Non Déclarée" = not declared = missing, NOT "No").
_MISS = re.compile(
    r"non d[eé]clar|not declared|not stated|missing|manquant|sans objet"
    r"|n[ãa]o declarad|sem resposta|no response|no answer|pas de r[eé]ponse"
    r"|ne sait|\bnsp\b|\bdk\b|don'?t know|inconsist|refus|no sabe|no responde"
    r"|sin (dato|informaci)|no aplica|not applicable", re.I)
FALLBACK = {1.0: 1.0, 2.0: 0.0, 100.0: 1.0, 0.0: 0.0}  # unlabeled datasets
# MICS sentinel codes are ALWAYS DK/missing for a yes/no item, regardless of the
# (often mojibake/localised) label text — force them to NULL by code.
SENTINEL_CODES = {7.0, 8.0, 9.0, 97.0, 98.0, 99.0}


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
            continue  # DK/missing -> NULL
        cp = _classify(v)
        if cp is not None:
            m[code] = cp
    return m


def _build_maps():
    """Return {dataset: {raw_code(float): 1.0/0.0}}.

    A dataset can map the canonical from SEVERAL raw columns (e.g. Argentina
    CA1=yes/no, CA2=fluid, CA3=food). Pick the column that is actually the
    yes/no question — the candidate whose labels yield BOTH a Yes and a No, with
    the fewest codes. Unlabeled datasets ({0,100}) fall back to FALLBACK.
    """
    from collections import defaultdict
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    raws_by_ds = defaultdict(list)
    for e in al.get(BASE, []):
        raws_by_ds[e["dataset_name"]].append(e.get("column_in_raw_sav") or "")
    raws_by_ds[CONGO] = ["CA1"]  # source fix: use CA1, not the mis-mapped CA2
    maps, nonstd = {}, []
    for ds, raws in raws_by_ds.items():
        cands = [_labels_to_map(_value_labels(ds, r)) for r in raws]
        yesno = [m for m in cands if 1.0 in m.values() and 0.0 in m.values()]
        if yesno:
            m = min(yesno, key=len)              # the tightest yes/no column
        else:
            m = dict(FALLBACK)                   # unlabeled -> {1,2,0,100}
        maps[ds] = m
        if m.get(2.0) == 1.0 or set(m) - {1.0, 2.0}:  # not the plain 1=Yes/2=No
            nonstd.append((ds, m))
    return maps, nonstd


def _congo_ca1(parquet_congo: pd.DataFrame) -> pd.Series:
    """Recover Congo diarrhea from raw CA1 (positional, guarded)."""
    import pyreadstat
    sav = RAW / CONGO / "ch.sav"
    df, _ = pyreadstat.read_sav(str(sav), usecols=["HH2", "CA1"])
    if len(df) != len(parquet_congo):
        raise RuntimeError(f"Congo row mismatch {len(df)} vs {len(parquet_congo)}")
    a = pd.to_numeric(parquet_congo["household_number"].reset_index(drop=True), errors="coerce")
    b = pd.to_numeric(df["HH2"].reset_index(drop=True), errors="coerce")
    if (a == b).mean() < 1.0:
        raise RuntimeError(f"Congo guard household_number==HH2 {(a==b).mean():.3%}")
    return pd.to_numeric(df["CA1"].reset_index(drop=True), errors="coerce")


def _apply_cp(df: pd.DataFrame, maps: dict) -> pd.Series:
    base = pd.to_numeric(df[BASE], errors="coerce")
    cp = pd.Series(np.nan, index=df.index)
    for ds, m in maps.items():
        dm = (df["dataset_name"] == ds)
        if dm.any() and m:
            cp.loc[dm] = base[dm].map(m)
    return cp


# ---------------------------------------------------------------------------

def patch_parquet(verify: bool):
    df = pd.read_parquet(PARQUET)
    maps, nonstd = _build_maps()
    if verify:
        # recompute for comparison (base already Congo-corrected on disk if applied)
        cp = _apply_cp(df, maps)
        ok = CP in df.columns and df[CP].equals(cp)
        n = int(cp.notna().sum()); nds = df.loc[cp.notna(), "dataset_name"].nunique()
        yes = int((cp == 1).sum()); no = int((cp == 0).sum())
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} ds "
              f"(Yes={yes}, No={no})")
        return
    if not PARQUET.with_suffix(".parquet.bak_p15").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p15"))
    # Congo source fix: base <- CA1
    cm = (df["dataset_name"] == CONGO)
    if cm.any():
        df.loc[cm, BASE] = _congo_ca1(df.loc[cm]).values
        print(f"  parquet: Congo_MICS5 base corrected CA2->CA1 ({int(cm.sum())} rows)")
    df[CP] = _apply_cp(df, maps)
    df.to_parquet(PARQUET, index=False)
    print("  non-standard dataset mappings applied:")
    for ds, m in nonstd:
        print(f"    {ds[:46]:46} {m}")
    print(f"  parquet: {CP} non-null={int(df[CP].notna().sum())} across "
          f"{df.loc[df[CP].notna(),'dataset_name'].nunique()} datasets "
          f"(Yes={int((df[CP]==1).sum())}, No={int((df[CP]==0).sum())})")


def patch_yaml():
    al = yaml.safe_load(open(ALIGN, encoding="utf-8")) or {}
    changed = False
    for e in al.get(BASE, []):
        if e["dataset_name"] == CONGO and (e.get("column_in_raw_sav") or "") == CONGO_FIX[0]:
            e["column_in_raw_sav"] = CONGO_FIX[1]
            e["column_label_in_english"] = "Had diarrhoea in last two weeks"
            changed = True
    if changed:
        if not ALIGN.with_suffix(".yaml.bak_p15").exists():
            shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p15"))
        yaml.safe_dump(al, open(ALIGN, "w", encoding="utf-8"), allow_unicode=True, sort_keys=True)
        print(f"  yaml: Congo_MICS5 {BASE} remapped {CONGO_FIX[0]}->{CONGO_FIX[1]}")
    else:
        print("  yaml: Congo mapping already fixed")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(verify: bool):
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

    maps, _ = _build_maps()
    pdf = pd.read_parquet(PARQUET)
    if not _col_exists(cur, "final_CH_MICS", CP):
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" DOUBLE PRECISION')
    cur.execute(f'UPDATE {T} SET "{CP}" = NULL')  # idempotent reset

    # map-update for all datasets EXCEPT Congo (Congo's DB base is still wrong CA2)
    rows = [(ds, code, cp) for ds, m in maps.items() if ds != CONGO
            for code, cp in m.items()]
    cur.execute("CREATE TEMP TABLE _dmap(ds text, raw double precision, cp double precision) ON COMMIT DROP")
    io_buf = io.StringIO()
    pd.DataFrame(rows, columns=["ds", "raw", "cp"]).to_csv(io_buf, index=False, header=False)
    io_buf.seek(0)
    cur.copy_expert("COPY _dmap FROM STDIN WITH (FORMAT CSV)", io_buf)
    cur.execute(f'UPDATE {T} f SET "{CP}" = m.cp FROM _dmap m '
                f'WHERE f.dataset_name = m.ds AND f.{BASE} = m.raw')
    print(f"  db: CP_ mapped via {len(rows)} (dataset,code) rules")

    # Congo: delete + reinsert from patched parquet (base corrected + CP_)
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_CH_MICS'""")
    dbtype = dict(cur.fetchall()); cols = list(pdf.columns)
    assert all(c in dbtype for c in cols), "DB missing a parquet column"
    sub = pdf[pdf["dataset_name"] == CONGO].copy()
    for c in cols:
        if dbtype.get(c) == "bigint":
            sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
        elif dbtype.get(c) == "double precision":
            sub[c] = pd.to_numeric(sub[c], errors="coerce")
    cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (CONGO,))
    buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    print(f"  db: Congo_MICS5 re-inserted ({len(sub)} rows, source CA1)")

    # ind_que: fix Congo base raw col, mirror base -> CP_
    cur.execute(f"UPDATE {I} SET column_in_raw_sav='CA1', "
                f"column_label_in_english='Had diarrhoea in last two weeks' "
                f"WHERE canonical_varname='{BASE}' AND dataset_name=%s", (CONGO,))
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
    print(f"P15 diarrhea_last_2_weeks -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    if not verify:
        print("== yaml =="); patch_yaml()
    print("== parquet =="); patch_parquet(verify)
    print("== database =="); patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
