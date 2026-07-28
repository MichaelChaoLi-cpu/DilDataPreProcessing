"""
P12 step 1 (scan only, no data changes) — Look for an unmapped "age at first
union/marriage" column in the raw WM SAV metadata of the datasets that currently
have ZERO values for the canonical `age_at_first_union`.

Cross-module backfill (HL/HH/CH) is impossible: marriage history is collected
only in the women's questionnaire. The only way to fill the fully-missing
datasets is to find an age-at-first-union column in their own raw SAV that
alignment_v2.yaml never mapped. This script reports what (if anything) exists;
it writes NOTHING to parquet or the database.

Report columns whose NAME or LABEL says "age at first marriage/union", excluding
husband/partner age (MA2-style). For each candidate we show the raw column, its
English label, its declared sentinel value-labels, and whether it is already
mapped to some other canonical in alignment_v2.yaml.

Usage:
    .venv/bin/python MICS-WM/src/scan_age_first_union.py

Output:
    MICS-WM/data/WM/age_first_union_gap_scan.csv
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
RAW = ROOT / "raw"
TARGET = "age_at_first_union"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

# Known MICS marriage-module columns that record the WOMAN's age at first
# marriage/union (NOT the partner's age, which is MA2 / "age of husband").
NAME_HINTS = {
    "MA6", "MA6A", "MA8", "MA8C", "MA9", "MA9C", "MA9CA", "MA11", "MA11C",
    "AGEM", "AGEM1", "AGEM2", "WAGEM", "CU1A",
}
# Label says age at first marriage/union/cohabitation (EN/FR/ES/PT).
# Must be about MARRIAGE/UNION age specifically — not sex, birth, or duration.
LABEL_INCL = re.compile(
    r"age at first (marriage|union|cohabitation)"
    r"|age (at|of) first marriage"
    r"|first married|married for the first"
    r"|(age|old).{0,20}(began|start|first).{0,20}(living with|union|married)"
    r"|[aâ]ge au premier (mariage|union)"
    r"|[aâ]ge (au|de|du) (premier )?mariage"
    r"|edad (a|al|en) (la |el )?primer[ao] (matrimonio|uni[oó]n)"
    r"|edad (al|a) casar|edad (al|a la) primera uni"
    r"|idade.{0,20}(primeir[ao]|1a?).{0,20}(casamento|uni[aã]o)"
    r"|idade.{0,25}(viver com|começou a viver).{0,20}primeir"
    r"|idade (com que|ao) casou",
    re.I,
)
# Never treat partner/husband/spouse age, first SEX, first BIRTH, or marriage
# DURATION as the woman's age at first union.
LABEL_EXCL = re.compile(
    r"husband|partner|spouse|conjoint|[ée]poux|marido|esposo|c[oô]njuge"
    r"|of (the )?man|du mari|del esposo"
    r"|sexual|first sex|premier rapport|primera relaci|sexualmente|sexually"
    r"|birth|na[sc]cimento|accouch|nacido|first live birth"
    r"|how long|lasted|dur[ée]e|dura[çc]|duration|cu[aá]nto (tiempo|dur)",
    re.I,
)


def load_alignment() -> dict[str, dict[str, str]]:
    with open(ROOT / "alignment_v2.yaml", encoding="utf-8") as f:
        alignment = yaml.safe_load(f) or {}
    mapped: dict[str, dict[str, str]] = {}
    for canonical, entries in alignment.items():
        for e in entries:
            raw = (e.get("column_in_raw_sav") or "").lower()
            if raw:
                mapped.setdefault(e["dataset_name"], {})[raw] = canonical
    return mapped


def missing_datasets() -> list[str]:
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    cur.execute('''SELECT dataset_name FROM "final_WM_MICS"
                   GROUP BY dataset_name
                   HAVING COUNT(age_at_first_union) = 0
                   ORDER BY dataset_name''')
    ds = [r[0] for r in cur.fetchall()]
    conn.close()
    return ds


def is_candidate(col: str, label: str) -> bool:
    label = label or ""
    if LABEL_EXCL.search(label):
        return False
    if LABEL_INCL.search(label):
        return True
    return col.upper() in NAME_HINTS


def main() -> None:
    mapped = load_alignment()
    missing = missing_datasets()
    print(f"{len(missing)} datasets with zero age_at_first_union.\n")

    rows = []
    hit_ds = set()
    for ds in missing:
        yml = RAW / ds / "wm.yaml"
        if not yml.exists():
            rows.append((ds, "", "NO_RAW_YAML", "", ""))
            continue
        with open(yml, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or []
        cols = loaded.get("columns", []) if isinstance(loaded, dict) else loaded
        cols = [c for c in cols if isinstance(c, dict)]

        found = False
        for c in cols:
            col = c.get("column_in_raw_sav") or ""
            label = c.get("column_label_in_raw_sav") or ""
            if not is_candidate(col, label):
                continue
            found = True
            hit_ds.add(ds)
            current = mapped.get(ds, {}).get(col.lower())
            vlab = c.get("value_labels") or {}
            sentinels = ";".join(f"{k}={v}" for k, v in list(vlab.items())[:6])
            rows.append((ds, col, label[:70],
                         current or "UNMAPPED", sentinels))
        if not found:
            rows.append((ds, "", "no_candidate_column", "", ""))

    # CSV
    import csv
    out = ROOT / "age_first_union_gap_scan.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_name", "raw_col", "label",
                    "current_mapping", "value_labels"])
        w.writerows(rows)

    # Summary
    print(f"{'DATASET':52} {'COL':8} {'MAPPING':22} LABEL")
    for ds, col, label, cur, _ in rows:
        if col:
            print(f"{ds[:52]:52} {col:8} {cur[:22]:22} {label}")
    print(f"\n{len(hit_ds)}/{len(missing)} missing datasets HAVE a candidate "
          f"age-at-first-union column in their raw SAV.")
    no_cand = [r[0] for r in rows if r[2] in ("no_candidate_column", "NO_RAW_YAML")]
    print(f"{len(no_cand)} have none (likely never collected — mostly MICS2).")
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    main()
