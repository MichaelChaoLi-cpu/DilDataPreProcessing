"""
P22 — Carefully process `received_anc` -> `CP_received_anc` (+ `CP_received_anc_derived`).

Problem found
-------------
`received_anc` was aligned to BOTH the yes/no ANC question (MN1 in MICS4/5, MN2 in
MICS6) AND the visit-count (MN3/MN5) in most datasets, and in a handful the yes/no
column was missing entirely so a count/timing column (MN2A2, F9, MN2AA/AB, ...) won
the merge — contaminating the binary variable with counts. Only 158 datasets had any
value, and 153 of those were genuine yes/no; the older MICS2/MICS3 rounds never asked
a single "did you receive ANC?" question at all — they used a provider checklist
("whom did you see for antenatal care?": doctor / nurse / ... / no one), which IS the
ANC question for those rounds (and matches UNICEF's ANC-coverage definition).

Fix (three parts, all land in CP_received_anc = 1 received / 0 not received / NULL)
-----------------------------------------------------------------------------------
1. HARMONIZE (153 datasets with a verified yes/no column): CP = 1 if base==1(Yes),
   0 if base==2(No), NULL otherwise (nulls sentinels 9/98/99 and any leaked count).
   `CP_received_anc_derived = 0` (self-reported).
2. DIRECT recovery (10 datasets): an unmapped MN1/MN2 yes/no "received ANC" question
   exists in the raw SAV; read it and map Yes->1 / No->0. derived = 0.
3. DERIVE from the provider checklist (77 datasets, MICS2/MICS3-era): read the whole
   MN2-family (^MN2[A-Z]?$) from the raw SAV and classify each cell by its value
   label (provider / no-one / no / missing) across three coding schemes:
     * MICS2 numeric  (Senegal):   0=Non, k=provider-code, 7=Missing
     * MICS4-6 string (Ghana/Thai): ''=not-selected, 'A'..'Y'=letter, '?'=Missing
     * yes/no grid    (Zambia):    1=Yes, 2=No per provider column
   received = 1 if ANY provider cell positive; 0 if a "no one" cell positive or every
   answered cell is a plain "No"; NULL if all missing. derived = 1.

11 datasets genuinely never collected ANC in the WM module (no MN-prenatal columns,
mostly MICS2/2000-era or reduced questionnaires) — left NULL and reported (NONE_NO_ANC).

Recovery rows are aligned POSITIONALLY to the SAV, guarded: a dataset is recovered
ONLY if hh_number == HH2 for every row; otherwise skipped and reported. New raw-column
mappings are written to alignment_v2.yaml so a full rebuild reproduces them.

Usage:
    .venv/bin/python MICS-WM/src/patch_received_anc.py --validate  # derivation gate
    .venv/bin/python MICS-WM/src/patch_received_anc.py             # apply
    .venv/bin/python MICS-WM/src/patch_received_anc.py --verify    # check
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

ROOT = Path(__file__).parent.parent / "data" / "WM"
PARQUET = ROOT / "processed_data" / "wm_merged.parquet"
ALIGN = ROOT / "alignment_v2.yaml"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "received_anc"
CP = "CP_received_anc"
FLAG = "CP_received_anc_derived"

# 10 datasets with an unmapped direct MN1/MN2 yes/no "received ANC" question.
DIRECT_COL = {
    "Algeria MICS6 Datasets": "MN2",
    "Argentina_MICS4_Datasets": "MN1",
    "Congo_MICS5_Datasets": "MN1",
    "Costa Rica_MICS4_Datasets": "MN1",
    "Dominican Republic_MICS5_Datasets": "MN1",
    "Mali_MICS5_Datasets": "MN1",
    "Mexico_MICS5_Datasets": "MN1",
    "Panama_MICS5_Datasets": "MN1",
    "Suriname 2000 MICS_Datasets": "MN2",
    "Uruguay_MICS4_Datasets": "MN1",
}

# 77 datasets with a provider checklist -> derive received_anc from the MN2-family.
FAMILY = [
    "Albania MICS 2005 SPSS Datasets", "Albania MICS2 2000", "Azerbaijan MICS2 2000",
    "Bangladesh 2006 MICS_Datasets", "Belarus 2005 MICS_Datasets",
    "Belize MICS 2006 SPSS Datasets", "Bolivia 2000 MICS_Datasets",
    "Bosnia and Herzegovina 2006 MICS_Datasets", "Burkina Faso MICS 2006 SPSS Datasets",
    "Burundi MICS 2005 SPSS Datasets", "Cameroon 2000 MICS_Datasets",
    "Cameroon MICS 2006 SPSS Datasets", "Central African Republic 2000 MICS_Datasets",
    "Central African Republic MICS 2006 SPSS Datasets", "Chad 2000 MICS_Datasets",
    "Congo, Democratic Republic of 2001 MICS_Datasets", "Cote d'Ivoire 2000 MICS_Datasets",
    "Cote d'Ivoire 2006 MICS_Datasets", "Djibouti MICS 2006 SPSS Datasets",
    "Dominican Republic 2000 MICS_Datasets", "Equatorial Guinea 2000 MICS_Datasets",
    "Gambia 2000 MICS_Datasets", "Gambia 2005-06 MICS_Datasets",
    "Georgia MICS 2005 SPSS Datasets", "Ghana MICS 2006 SPSS Datasets",
    "Guinea Bissau 2000 MICS_Datasets", "Guinea-Bissau MICS 2006 SPSS Datasets",
    "Guyana 2000 MICS_Datasets", "Guyana MICS 2006-07 SPSS Datasets",
    "Iraq 2000 MICS_Datasets", "Iraq 2006 MICS_Datasets", "Jamaica 2005 MICS_Datasets",
    "Kazakhstan MICS 2006 SPSS Datasets",
    "Kenya (Mombasa Informal Settlements)_MICS4_Datasets",
    "Kenya (Nyanza Province)_MICS4_Datasets", "Kyrgyzstan MICS 2005-06 SPSS Datasets",
    "Lao PDR MICS 2006 SPSS Datasets", "Lao PDR MICS2 2000_Datasets",
    "Lesotho 2000 MICS_Datasets", "Macedonia 2005-06 MICS_Datasets",
    "Madagascar 2000 MICS_Datasets", "Malawi MICS 2006 SPSS Datasets",
    "Mauritania MICS 2007 SPSS Datasets", "Mongolia MICS 2005 SPSS Datasets",
    "Montenegro 2005-06 MICS_Datasets", "Mozambique MICS 2008 Datasets",
    "Niger 2000 MICS_Datasets", "Nigeria MICS 2007 SPSS Datasets",
    "Palestinians in Lebanon MICS 2006 SPSS Datasets", "Philippines 1999 MICS_Datasets",
    "Rwanda 2000 MICS_Datasets", "Sao Tome and Principle 2000 MICS_Datasets",
    "Senegal 2000 MICS_Datasets", "Serbia 2005-06 MICS_Datasets",
    "Sierra Leone 2000 MICS_Datasets", "Sierra Leone 2005 MICS_Datasets",
    "Somalia 2006 MICS_Datasets", "Suriname MICS 2006 SPSS Datasets",
    "Syria MICS 2006 SPSS Datasets", "Tajikistan MICS 2005 SPSS Datasets",
    "Thailand 2005-06 MICS_Datasets", "Togo 2000 MICS_Datasets",
    "Togo MICS 2006 SPSS Datasets", "Trinidad and Tobago 2000 MICS_Datasets",
    "Trinidad and Tobago MICS 2006 SPSS Datasets", "Turkmenistan_MICS3_Datasets",
    "Ukraine MICS 2005 SPSS Datasets", "Uzbekistan MICS 2006 SPSS Datasets",
    "Vanuatu MICS 2007 SPSS Datasets", "Venezuela 2000 MICS_Datasets",
    "Viet Nam 2000 MICS_Datasets", "Vietnam_Datasets", "Yemen MICS 2006 SPSS Datasets",
    "Zambia 1999 MICS_Datasets", "Zimbabwe_Datasets",
    "Tajikistan MICS2 2000_Datasets", "Sao Tome and Principe_MICS5_Datasets",
]

# genuinely no ANC question in the WM module — reported, left NULL.
NONE_NO_ANC = [
    "Cuba MICS 2006 SPSS Datasets", "Cuba_MICS4_Datasets", "Guinea Bissau MICS6 Datasets",
    "Guinea Bissau_MICS5_Datasets", "Indonesia MICS2 2000_Datasets",
    "Moldova MICS2 2000_Datasets", "Myanmar 2000 MICS_Datasets",
    "Sao Tome and Principe MICS6 Datasets", "Sao Tome and Principe MICS6 Datasets (1)",
    "Sudan 2000 MICS (North only)_Datasets", "Sudan 2000 MICS (South only)_Datasets",
]

FAM_RE = re.compile(r"^MN2[A-Z]?$", re.I)   # MN2, MN2A..MN2Z  (excludes MN20, MN2AU, ...)
SENTINELS = {7.0, 8.0, 9.0, 97.0, 98.0, 99.0}

_MISS = re.compile(r"missing|manquant|em falta|omit|no sabe|nsp|ne sait|n.?/?a\b|"
                   r"don.?t know|\bdk\b|\bns\b|special|no responde|no aplica|refus|"
                   r"9998|9999|s/?d|sin dato", re.I)
_NONE = re.compile(r"no ?one|nobody|no ?body|personne|nadie|ningu[eé]m|ningun[oa]|"
                   r"aucun|did ?n.?t|did not|no fue|no recib|n[aã]o viu|no vio|"
                   r"sin atenci|not receiv|no prenatal|didnt", re.I)
_NEG = re.compile(r"^\s*(no|non|n[ãa]o|нет|yo.?q|hapana|hay[ıi]r|xeyr|нема|na|nein|"
                  r"tidak|hindi|khong|kh[oô]ng)\s*$", re.I)
_YES = re.compile(r"^\s*(yes|s[ií]|oui|sim|да|bali|b[əe]li|ha|ndiyo|evet|po|jah|"
                  r"kyll[aä]|ya|oo|iva|có)\b", re.I)


_NONE_NAME = re.compile(r"^MN2[YZ]$", re.I)   # MICS "no one" checkbox (Y in MICS4-6, Z in MICS2-3)


def _is_none_col(col: str, clab: str, vlab: dict) -> bool:
    """A checkbox column that records 'saw no one', by MICS naming or by label."""
    if _NONE_NAME.match(col or ""):
        return True
    if clab and _NONE.search(clab.lower()):
        return True
    return any(_NONE.search(str(v).lower()) for v in (vlab or {}).values())


def _cell(v, vlab, is_none_col: bool) -> str:
    """Classify one checkbox cell -> PROV | NONE | NEG | MISS.
    Role (provider vs 'no one') is fixed by the COLUMN; the cell only decides
    selected / not-selected / missing. Robust to numeric, letter, and yes/no
    schemes AND to letter columns that carry no value labels (Mozambique/Zimbabwe)."""
    if v is None:
        return "MISS"
    s = str(v).strip()
    if s in {"", "?", ".", "nan", "NaN", "None", " ", "<NA>", ".a", ".b"}:
        return "MISS"
    L = ("" if vlab is None else str(vlab)).strip().lower()
    if L and _MISS.search(L):
        return "MISS"
    if L and _NEG.match(L):
        return "NEG"
    if L and _NONE.search(L):
        return "NONE"
    try:
        fv = float(s)
    except ValueError:
        fv = None
    if fv is not None:
        if fv in SENTINELS and L == "":
            return "MISS"
        if fv == 0 and L == "":                    # unlabeled 0 = not-selected
            return "NONE" if is_none_col else "NEG"
    return "NONE" if is_none_col else "PROV"        # a real selection


def _derive(sav: pd.DataFrame, cols: list[str], vlabels: dict, clabels: dict) -> pd.Series:
    """Row-level received_anc from a set of MN2-family (or single yes/no) columns."""
    n = len(sav)
    prov = np.zeros(n, bool); none = np.zeros(n, bool); neg = np.zeros(n, bool)
    for col in cols:
        vl = vlabels.get(col, {}) or {}
        is_none = _is_none_col(col, clabels.get(col, ""), vl)
        raw = sav[col]
        uniq = pd.unique(raw)                       # map each distinct value once
        klass = {u: _cell(u, vl.get(u, vl.get(_num(u), "")), is_none) for u in uniq}
        k = raw.map(klass).to_numpy()
        prov |= (k == "PROV"); none |= (k == "NONE"); neg |= (k == "NEG")
    out = np.full(n, np.nan)
    out[neg | none] = 0.0
    out[prov] = 1.0                                # provider takes precedence
    return pd.Series(out, index=sav.index)


def _num(u):
    try:
        return float(u)
    except (TypeError, ValueError):
        return u


def _find(cols, name):
    low = {c.lower(): c for c in cols}
    return low.get(name.lower())


def _harmonize_base(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors="coerce")
    return pd.Series(np.where(v == 1, 1.0, np.where(v == 2, 0.0, np.nan)), index=s.index)


def _read_sav(ds):
    import pyreadstat
    sav = RAW / ds / "wm.sav"
    if not sav.exists():
        for alt in RAW.glob(f"{ds}/*.sav"):
            if "wm" in alt.name.lower():
                sav = alt; break
    if not sav.exists():
        return None, None, None, "no SAV"
    df, meta = pyreadstat.read_sav(str(sav), apply_value_formats=False)
    return df, meta.variable_value_labels, meta.column_names_to_labels, "ok"


# household-id columns to guard positional alignment, in priority order. MICS2/2000
# WM files name it WIHHNO or HI2, not HH2; some (Zimbabwe) use wm2.
GUARD_KEYS = ["HH2", "hh2", "WM2", "wm2", "WIHHNO", "wihhno", "HI2", "hi2", "hhno", "HHNO"]


def _recover_one(ds, parquet_ds):
    """Return (cp_series, derived_flag, note) positionally aligned to parquet_ds, or (None,..,note)."""
    df, vlabels, clabels, note = _read_sav(ds)
    if df is None:
        return None, None, note
    if len(df) != len(parquet_ds):
        return None, None, f"row mismatch SAV {len(df)} vs pq {len(parquet_ds)}"
    a = pd.to_numeric(parquet_ds["hh_number"].reset_index(drop=True), errors="coerce")
    key, best = None, 0.0
    for cand in GUARD_KEYS:
        c = _find(df.columns, cand)
        if c is None:
            continue
        b = pd.to_numeric(df[c].reset_index(drop=True), errors="coerce")
        m = (a == b).mean()
        if m > best:
            key, best = c, m
        if m >= 0.999:
            break
    if best < 0.999:
        return None, None, f"guard hh_number==key {best:.3%} (best {key})"
    df = df.reset_index(drop=True)
    if ds in DIRECT_COL:
        col = _find(df.columns, DIRECT_COL[ds])
        if col is None:
            return None, None, f"direct col {DIRECT_COL[ds]} absent"
        cp = _derive(df, [col], {col: vlabels.get(col, {})}, {col: clabels.get(col, "")})
        return cp, 0, f"direct {col} n={int(cp.notna().sum())}"
    fam = [c for c in df.columns if FAM_RE.match(c)]
    if not fam:
        return None, None, "no MN2-family columns"
    cp = _derive(df, fam, {c: vlabels.get(c, {}) for c in fam},
                 {c: clabels.get(c, "") for c in fam})
    return cp, 1, f"family {fam} n={int(cp.notna().sum())}"


# ---------------------------------------------------------------------------

def validate():
    """Derivation gate: on clean yes/no datasets that ALSO have an MN2-family,
    does the checklist derivation reproduce the self-reported yes/no answer?"""
    df = pd.read_parquet(PARQUET, columns=["dataset_name", BASE, "hh_number"])
    clean = sorted(df.loc[df[BASE].isin([1, 2]), "dataset_name"].unique())
    checked, agrees, rows = 0, [], 0
    for ds in clean:
        sub = df[df.dataset_name == ds]
        cp, flag, _ = _recover_one(ds, sub)
        if cp is None or flag == 0:
            continue
        base = _harmonize_base(sub[BASE].reset_index(drop=True))
        m = base.notna() & cp.reset_index(drop=True).notna()
        if m.sum() < 50:
            continue
        agr = (base[m] == cp.reset_index(drop=True)[m]).mean()
        agrees.append((ds, m.sum(), agr)); checked += 1; rows += int(m.sum())
    agrees.sort(key=lambda x: x[2])
    print(f"  validated derivation on {checked} clean datasets w/ MN2-family, {rows} overlap rows")
    if agrees:
        vals = [a for _, _, a in agrees]
        print(f"  agreement: median={np.median(vals):.3f} mean={np.mean(vals):.3f} min={min(vals):.3f}")
        print("  worst 10:")
        for ds, n, a in agrees[:10]:
            print(f"    {a:.3f}  n={n:5d}  {ds}")


def _harmonize_set(df):
    """Clean yes/no datasets to harmonize from base — excludes any dataset that is
    recovered/derived (DIRECT/FAMILY), so count-contaminated bases never leak in."""
    recover = set(DIRECT_COL) | set(FAMILY)
    return sorted(d for d in df.loc[df[BASE].isin([1, 2]), "dataset_name"].unique()
                  if d not in recover)


def patch_parquet(verify: bool):
    df = pd.read_parquet(PARQUET)
    harmonize = _harmonize_set(df)
    if verify:
        n = int(df[CP].notna().sum()) if CP in df.columns else 0
        nds = df.loc[df[CP].notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int(df.loc[df[CP].notna() & ~df[CP].isin([0, 1])].shape[0]) if CP in df.columns else -1
        rec = df.loc[df[FLAG] == 1, "dataset_name"].nunique() if FLAG in df.columns else 0
        print(f"  parquet: {CP} present={CP in df.columns}; valid(0/1)={n} across {nds} ds; "
              f"out-of-range={bad}; derived datasets={rec}")
        return [], []

    if not PARQUET.with_suffix(".parquet.bak_p22").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p22"))

    cp = pd.Series(np.nan, index=df.index)
    flag = pd.Series(np.nan, index=df.index)

    # 1. harmonize the 153 clean yes/no datasets
    hmask = df.dataset_name.isin(harmonize)
    cp[hmask] = _harmonize_base(df.loc[hmask, BASE]).values
    flag[hmask] = np.where(cp[hmask].notna(), 0.0, np.nan)

    # 2+3. recover DIRECT + FAMILY from raw SAV, guarded positional
    applied_direct, applied_fam, skipped = [], [], []
    for ds in list(DIRECT_COL) + FAMILY:
        mask = df.dataset_name == ds
        if not mask.any():
            skipped.append((ds, "not in parquet")); continue
        series, dflag, note = _recover_one(ds, df.loc[mask])
        if series is None:
            skipped.append((ds, note)); continue
        cp.loc[mask] = series.values
        flag.loc[mask] = np.where(series.notna().values, float(dflag), np.nan)
        (applied_direct if dflag == 0 else applied_fam).append(ds)
        print(f"  [ok]   {ds}: {note}")
    for ds, note in skipped:
        print(f"  [skip] {ds}: {note}")

    df[CP] = cp.values
    df[FLAG] = flag.values
    df.to_parquet(PARQUET, index=False)
    nds = df.loc[df[CP].notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(df[CP].notna().sum())} across {nds} datasets; "
          f"direct={len(applied_direct)} family={len(applied_fam)} skipped={len(skipped)}")
    return applied_direct, applied_fam


def patch_yaml(applied):
    if not applied:
        print("  yaml: nothing to add"); return
    with open(ALIGN, encoding="utf-8") as f:
        al = yaml.safe_load(f) or {}
    entries = al.get(BASE, [])
    have = {e.get("dataset_name") for e in entries}
    if not ALIGN.with_suffix(".yaml.bak_p22").exists():
        shutil.copy2(ALIGN, ALIGN.with_suffix(".yaml.bak_p22"))
    added = 0
    for ds in applied:
        if ds in have:
            continue
        col = DIRECT_COL.get(ds, "MN2")
        entries.append({
            "canonical_text": "Received antenatal care", "canonical_varname": BASE,
            "column_in_raw_sav": col,
            "column_label_in_english": "Received antenatal care (recovered P22)",
            "component": None, "confidence": "high", "dataset_name": ds,
            "derivation": None if ds in DIRECT_COL else "MN2-family checklist",
            "entities": [], "entity_operator": None, "event": None,
            "is_compound": ds not in DIRECT_COL, "measure_type": "antenatal_care",
            "needs_review": False, "relation": None, "response_type": "yes_no",
            "source_kind": "explicit" if ds in DIRECT_COL else "derived",
        })
        added += 1
    al[BASE] = entries
    with open(ALIGN, "w", encoding="utf-8") as f:
        yaml.safe_dump(al, f, allow_unicode=True, sort_keys=True)
    print(f"  yaml: added {added} {BASE} mappings")


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(applied_direct, applied_fam, verify):
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = '"final_WM_MICS"'
    I = '"ind_que_WM_MICS"'

    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                    f'FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL '
                    f'AND "{CP}" NOT IN (0,1)')
        bad = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(DISTINCT dataset_name) FROM {T} WHERE "{FLAG}"=1')
        rec = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        ind = cur.fetchone()[0]
        print(f"  db: {CP} non-null={n} across {nds} datasets; out-of-range={bad}; "
              f"derived datasets={rec}; ind_que CP_ rows={ind}")
        conn.close()
        return

    pdf = pd.read_parquet(PARQUET)
    applied = applied_direct + applied_fam
    harmonize = _harmonize_set(pdf)

    for col in (CP, FLAG):
        if not _col_exists(cur, "final_WM_MICS", col):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" DOUBLE PRECISION')

    # 1. harmonize (in-place per-row transform) for the 153 clean datasets
    cur.execute(
        f'UPDATE {T} SET "{CP}" = CASE WHEN {BASE}=1 THEN 1 WHEN {BASE}=2 THEN 0 ELSE NULL END, '
        f'"{FLAG}" = CASE WHEN {BASE} IN (1,2) THEN 0 ELSE NULL END '
        f'WHERE dataset_name = ANY(%s)', (harmonize,))
    print(f"  db: harmonized {len(harmonize)} clean datasets")

    # 2+3. re-insert recovered datasets from patched parquet
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_WM_MICS'""")
    dbtype = dict(cur.fetchall())
    cols = list(pdf.columns)
    assert all(c in dbtype for c in cols), "DB missing a parquet column"
    for ds in applied:
        sub = pdf[pdf["dataset_name"] == ds].copy()
        for c in cols:
            if dbtype.get(c) == "bigint":
                sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
            elif dbtype.get(c) == "double precision":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
        buf = io.StringIO()
        sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
        buf.seek(0)
        collist = ", ".join(f'"{c}"' for c in cols)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    print(f"  db: re-inserted {len(applied)} recovered datasets")

    # ind_que: base rows for recovered datasets, then mirror all base -> CP_
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{CP}'")
    for ds in applied:
        col = DIRECT_COL.get(ds, "MN2")
        cur.execute(f"DELETE FROM {I} WHERE canonical_varname='{BASE}' AND dataset_name=%s", (ds,))
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (BASE, ds, col, "Received antenatal care (recovered P22)",
             "explicit" if ds in DIRECT_COL else "derived", "antenatal_care",
             "Received antenatal care"))
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


def main():
    if "--validate" in sys.argv:
        print("P22 received_anc — VALIDATE derivation"); validate(); return
    verify = "--verify" in sys.argv
    print(f"P22 received_anc -> CP_ — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); ad, af = patch_parquet(verify)
    if not verify:
        print("== yaml =="); patch_yaml(ad + af)
    print("== database =="); patch_db(ad, af, verify)
    print("Done.")


if __name__ == "__main__":
    main()
