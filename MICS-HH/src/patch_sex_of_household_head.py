"""
P10 — Clean sex_of_household_head (HH module).

Verified beforehand (SAV metadata scan, 247 datasets): coding is uniformly
1 = Male, 2 = Female. No reversals. Remaining issues fixed here:

1. Mozambique MICS 2008: mapped from OV3C_1/2/3 — "Sexo" of deceased household
   members in the orphanhood module, NOT the head. → NULL + HL backfill.
2. 11 datasets with no mapping at all → backfill from the HL roster
   (sex of the member with relationship_to_head == 1).
3. Sentinel/error codes 3/7/9 (105 rows) → NULL.
4. alignment_v2.yaml: OV3C entries removed; backfilled datasets documented as
   derived rows in ind_que.

Usage:
  python patch_sex_of_household_head.py parquet
  python patch_sex_of_household_head.py db        (re-upload + ind_que)
  python patch_sex_of_household_head.py all
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import yaml

_PROJECT_ROOT = Path(__file__).parent.parent.parent
HH_ROOT = _PROJECT_ROOT / "MICS-HH" / "data" / "HH"
HH_PARQUET = HH_ROOT / "processed_data" / "hh_merged.parquet"
HL_PARQUET = _PROJECT_ROOT / "MICS-HL" / "data" / "HL" / "processed_data" / "hl_merged.parquet"
UPLOAD_SCRIPT = _PROJECT_ROOT / "MICS-HH" / "src" / "upload_hh_to_postgres.py"
PY = str(_PROJECT_ROOT / ".venv" / "bin" / "python")

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

WRONG_SOURCE = {"Mozambique MICS 2008 Datasets"}  # OV3C_* is not head sex
BACKFILL_DATASETS = WRONG_SOURCE | {
    "Cote d'Ivoire 2006 MICS_Datasets",
    "Cameroon MICS 2006 SPSS Datasets",
    "Kyrgyzstan MICS 2005-06 SPSS Datasets",
    "Montenegro (Roma Settlements)_MICS5_Datasets",
    "Indonesia MICS2 2000_Datasets",
    "Trinidad and Tobago 2000 MICS_Datasets",
    "Iraq 2000 MICS_Datasets",
    "Central African Republic 2000 MICS_Datasets",
    "Togo MICS 2006 SPSS Datasets",
    "Cameroon 2000 MICS_Datasets",
    "Niger 2000 MICS_Datasets",
}
# relationship_to_head is unmapped in HL for these; the head is the roster
# member on line 1 (validated globally: 2,238,349/2,238,367 = 100.0% agreement)
LINE1_PROXY_DATASETS = {"Central African Republic 2000 MICS_Datasets"}


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def build_head_sex() -> pd.DataFrame:
    """(dataset, cluster, household) → head sex from the HL roster.

    Strict: NaN keys and ambiguous keys (several households sharing the same
    cluster+household code, e.g. Niger 2000 where codes are 100% non-unique)
    are excluded — a wrong-household match is worse than a missing value.
    """
    hl = pd.read_parquet(HL_PARQUET, columns=[
        "dataset_name", "cluster_number", "household_number",
        "line_number", "relationship_to_head", "sex"])
    hl = hl[hl["dataset_name"].isin(BACKFILL_DATASETS)].copy()
    for c in ("cluster_number", "household_number", "line_number",
              "relationship_to_head", "sex"):
        hl[c] = _num(hl[c])
    is_head = (hl.relationship_to_head == 1) | (
        hl.dataset_name.isin(LINE1_PROXY_DATASETS) & (hl.line_number == 1))
    heads = hl[is_head & hl.sex.isin([1.0, 2.0])]
    heads = heads.dropna(subset=["cluster_number", "household_number"])
    # a key carried by more than one head row is ambiguous → drop entirely
    heads = heads.drop_duplicates(
        subset=["dataset_name", "cluster_number", "household_number"], keep=False)
    return heads[["dataset_name", "cluster_number", "household_number", "sex"]] \
        .rename(columns={"sex": "head_sex"})


def patch_parquet() -> None:
    print(f"loading {HH_PARQUET} ...")
    df = pd.read_parquet(HH_PARQUET)
    sex = _num(df["sex_of_household_head"])
    before = sex.notna().sum()

    # 1. reset ALL backfill datasets (wrong source or empty; idempotent re-run)
    in_backfill = df["dataset_name"].isin(BACKFILL_DATASETS)
    n_wrong = (in_backfill & sex.notna()).sum()
    sex[in_backfill] = np.nan

    # 2. sentinels → NULL
    bad = sex.notna() & ~sex.isin([1.0, 2.0])
    n_bad = bad.sum()
    sex[bad] = np.nan

    # 3. HL backfill — strict key matching
    heads = build_head_sex()
    print(f"  HL head-sex lookup (unique keys only): {len(heads):,} households")
    keys = df[["dataset_name", "cluster_number", "household_number"]].copy()
    keys["cluster_number"] = _num(keys["cluster_number"])
    keys["household_number"] = _num(keys["household_number"])
    # HH rows with NaN or within-dataset duplicated keys cannot be matched safely
    valid_key = keys["cluster_number"].notna() & keys["household_number"].notna()
    dup_hh = keys.duplicated(
        subset=["dataset_name", "cluster_number", "household_number"], keep=False)
    merged = keys.merge(heads, how="left",
                        on=["dataset_name", "cluster_number", "household_number"])
    fill = (sex.isna() & in_backfill & valid_key & ~dup_hh
            & merged["head_sex"].notna().values)
    sex[fill] = merged.loc[fill.values, "head_sex"].values

    df["sex_of_household_head"] = sex
    after = sex.notna().sum()
    print(f"  wrong-source nulled: {n_wrong:,}")
    print(f"  sentinels nulled:    {n_bad:,}")
    print(f"  HL backfilled:       {fill.sum():,}")
    print(f"  non-null: {before:,} → {after:,} "
          f"({sex.notna().mean():.1%}) across "
          f"{df.loc[sex.notna(), 'dataset_name'].nunique()} datasets")
    print(f"  female share: {(sex == 2).sum() / max((sex.isin([1, 2])).sum(), 1):.3f}")

    df.to_parquet(HH_PARQUET, index=False)
    print(f"  saved {HH_PARQUET}")

    # 4. remove OV3C entries from alignment yaml
    yml = HH_ROOT / "alignment_v2.yaml"
    with open(yml, encoding="utf-8") as f:
        alignment = yaml.safe_load(f)
    entries = alignment.get("sex_of_household_head", [])
    kept = [e for e in entries
            if not (e["dataset_name"] in WRONG_SOURCE
                    and (e.get("column_in_raw_sav") or "").upper().startswith("OV3C"))]
    if len(kept) != len(entries):
        shutil.copy2(yml, yml.with_suffix(".yaml.bak_p10"))
        alignment["sex_of_household_head"] = kept
        with open(yml, "w", encoding="utf-8") as f:
            yaml.safe_dump(alignment, f, allow_unicode=True, sort_keys=True)
        print(f"  alignment: removed {len(entries) - len(kept)} OV3C entries "
              f"(backup {yml.name}.bak_p10)")


def patch_db() -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    snap = pd.read_sql(
        'SELECT * FROM "ind_que_HH_MICS" WHERE source_kind = \'derived\'', conn)
    conn.close()
    print(f"snapshot: {len(snap)} derived ind_que rows")

    print(f"re-uploading via {UPLOAD_SCRIPT.name} ...")
    r = subprocess.run([PY, str(UPLOAD_SCRIPT)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:]); print(r.stderr[-1500:])
        sys.exit("upload failed")

    conn = psycopg2.connect(**DB_PARAMS)
    with conn.cursor() as cur:
        # reinsert only patch-derived canonicals the rebuild doesn't regenerate
        cur.execute('''SELECT DISTINCT canonical_varname FROM "ind_que_HH_MICS"
                       WHERE source_kind = 'derived' ''')
        rebuilt = {row[0] for row in cur.fetchall()}
        keep = snap[~snap.canonical_varname.isin(rebuilt)]
        if not keep.empty:
            cols = ", ".join(f'"{c}"' for c in keep.columns)
            ph = ", ".join(["%s"] * len(keep.columns))
            cur.executemany(
                f'INSERT INTO "ind_que_HH_MICS" ({cols}) VALUES ({ph})',
                keep.where(pd.notna(keep), None).values.tolist())
        print(f"  reinserted {len(keep)} derived rows")

        # derived rows for the HL-backfilled datasets
        cur.execute('''DELETE FROM "ind_que_HH_MICS"
                       WHERE canonical_varname = 'sex_of_household_head'
                         AND source_kind = 'derived' ''')
        text = ("Derived: sex of household head backfilled from HL roster "
                "(sex of member with relationship_to_head=1) — P10")
        cur.executemany(
            '''INSERT INTO "ind_que_HH_MICS"
               (canonical_varname, dataset_name, column_in_raw_sav,
                column_label_in_english, source_kind, measure_type, canonical_text)
               VALUES ('sex_of_household_head', %s, 'HL:sex+relationship_to_head',
                       %s, 'derived', 'household_background', %s)''',
            [(ds, text, text) for ds in sorted(BACKFILL_DATASETS)])
        print(f"  inserted {len(BACKFILL_DATASETS)} derived rows for backfill")

        cur.execute('''SELECT COUNT(*), COUNT(sex_of_household_head),
                              AVG(CASE WHEN sex_of_household_head = 2 THEN 1.0
                                       WHEN sex_of_household_head = 1 THEN 0.0 END)
                       FROM "final_HH_MICS"''')
        total, nn, fs = cur.fetchone()
        print(f"  final_HH_MICS: {total:,} rows, sex_of_household_head "
              f"non-null {nn:,}, female share {fs:.3f}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("parquet", "all"):
        patch_parquet()
    if mode in ("db", "all"):
        patch_db()
