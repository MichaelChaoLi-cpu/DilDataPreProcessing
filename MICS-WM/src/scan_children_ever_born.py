"""
P13 step 1 (scan only, no data changes) — Look for an unmapped
"children ever born" (CEB) column in the raw WM SAV metadata of the datasets
that currently have ZERO values for the canonical `children_ever_born`.

CEB is a women's-questionnaire fertility total; cross-module backfill is
impossible, and deriving it from the sons/daughters breakdown proved unreliable
(only ~16% exact agreement). So the only way to fill a fully-missing dataset is
to find a CEB column in its own raw SAV that alignment never mapped.

Raw column NAMES are unreliable here (CM8/CM9/CM10/CM11/CM17... mean different
things across MICS rounds), so matching is LABEL-first: "children ever born",
"total children born (alive)", FR "enfants nes vivants / total des enfants",
ES "hijos nacidos vivos / total de hijos", PT "filhos nascidos vivos". Only the
unambiguous total names (CEB / CTOT / celtot) are trusted on name alone.
Components (sons/daughters living/dead), children under 5, births in the last
2 years, and "children living with you" are excluded.

This script writes NOTHING to parquet or the database.

Usage:
    .venv/bin/python MICS-WM/src/scan_children_ever_born.py

Output:
    MICS-WM/data/WM/children_ever_born_gap_scan.csv
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import psycopg2
import yaml

ROOT = Path(__file__).parent.parent / "data" / "WM"
RAW = ROOT / "raw"
TARGET = "children_ever_born"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

# Unambiguous "total CEB" names — trusted on name alone.
NAME_TOTAL = {"CEB", "CTOT", "CELTOT", "NEV", "NSV"}

# Label = total children ever born (EN/FR/ES/PT).
LABEL_INCL = re.compile(
    r"children ever born"
    r"|(total|number) (of )?(children|births|live births) (ever )?(born|had)"
    r"|ever born (alive|to)"
    r"|total live births"
    r"|enfants n[eé]s vivants|total des enfants|nombre total d'enfants"
    r"|nombre d'enfants n[eé]s vivants"
    r"|hijos nacidos vivos|total de hijos|n[uú]mero de hijos nacidos"
    r"|filhos nascidos vivos|total de filhos|n[uú]mero de filhos",
    re.I,
)
# Exclude subsets/components/other-fertility that are NOT the CEB total.
LABEL_EXCL = re.compile(
    r"living|alive|surviv|currently|en vida|vivos actualmente|vivant.? actuel"
    r"|dead|died|death|d[eé]c[eé]d|muerto|falec|morto"
    r"|under (5|five)|menores de|de moins de 5"
    r"|last (2|two) years?|derni[eè]res? (2|deux) ann|[uú]ltimos (2|dos)"
    r"|living with (you|her)|habitent avec|viven con|vivem com"
    r"|this household|dans le m[eé]nage|en el hogar|no agregado"
    r"|in the last year|born (this|last) year|last birth|first birth"
    r"|elsewhere|ailleurs|en otro|noutro"
    r"|son|daughter|fils|fille|hijo|hija|filho|filha|boys|girls",
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
                   HAVING COUNT(children_ever_born) = 0
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
    # trust only unambiguous total names when label is silent
    return col.upper() in NAME_TOTAL


def main() -> None:
    mapped = load_alignment()
    missing = missing_datasets()
    print(f"{len(missing)} datasets with zero children_ever_born.\n")

    rows, hit = [], set()
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
            hit.add(ds)
            current = mapped.get(ds, {}).get(col.lower()) or "UNMAPPED"
            vlab = c.get("value_labels") or {}
            sent = ";".join(f"{k}={v}" for k, v in list(vlab.items())[:6])
            rows.append((ds, col, label[:70], current, sent))
        if not found:
            rows.append((ds, "", "no_candidate_column", "", ""))

    out = ROOT / "children_ever_born_gap_scan.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_name", "raw_col", "label", "current_mapping", "value_labels"])
        w.writerows(rows)

    print(f"{'DATASET':52} {'COL':8} {'MAPPING':16} LABEL")
    for ds, col, label, cur, _ in rows:
        if col:
            print(f"{ds[:52]:52} {col:8} {cur[:16]:16} {label}")
    print(f"\n{len(hit)}/{len(missing)} missing datasets HAVE a candidate CEB column.")
    none = [r[0] for r in rows if r[2] in ("no_candidate_column", "NO_RAW_YAML")]
    print(f"{len(none)} have none.")
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    main()
