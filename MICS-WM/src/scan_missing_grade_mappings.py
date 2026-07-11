"""
P08 step 1 — Scan raw yaml metadata for grade variables missing from alignment_v2.yaml.

For each dataset in a module (WM or HL), find raw SAV columns that record
educational attainment grade ("highest grade completed/attended at that level",
MICS2 "Highest school grade", French "Classe atteinte", etc.) or a
grade-completion yes/no flag (WB7 / ED6), and report the ones that are not yet
mapped to the target canonical variable in alignment_v2.yaml.

Target canonicals:
  WM: education_grade, education_grade_completed
  HL: highest_grade_completed, ever_completed_grade

Usage:
  python scan_missing_grade_mappings.py wm
  python scan_missing_grade_mappings.py hl

Output:
  data/<MOD>/grade_mapping_gap_scan.csv
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import yaml

_PROJECT_ROOT = Path(__file__).parent.parent.parent

MODULES = {
    "wm": {
        "root": _PROJECT_ROOT / "MICS-WM" / "data" / "WM",
        "raw_yaml": "wm.yaml",
        "grade_canonical": "education_grade",
        "completed_canonical": "education_grade_completed",
    },
    "hl": {
        "root": _PROJECT_ROOT / "MICS-HL" / "data" / "HL",
        "raw_yaml": "hl.yaml",
        "grade_canonical": "highest_grade_completed",
        "completed_canonical": "ever_completed_grade",
    },
}

# Column names that are attainment-grade in MICS questionnaires
GRADE_NAMES = {
    "WB5", "WB51", "WB5P", "WB6B", "WM12",
    "ED4B", "ED5B", "ED3B", "ED6B", "ED6",
}
# Column names that are "completed that grade" yes/no
COMPLETED_NAMES = {"WB7", "ED5C", "ED7"}

# Attainment labels (EN/FR/ES/PT), must NOT be current/previous-year enrollment
GRADE_LABEL = re.compile(
    r"highest (school )?grade"
    r"|grade (completed|attended) at (that|this) level"
    r"|highest grade (at|completed|attended)"
    r"|derni[eè]re?e? classe (achev|atteint)"
    r"|classe atteinte"
    r"|plus haut grade"
    r"|[uú]ltimo grado"
    r"|classe mais elevada"
    r"|maior grau|grau mais elevad"
    r"|grado (o a[ñn]o )?(de estudios )?m[aá]s alto"
    r"|highest class",
    re.I,
)
EXCLUDE_LABEL = re.compile(
    r"this year|current|actual|actuelle|en (curso|cours)|cette ann[ée]e|ann[ée]e (en cours|scolaire)"
    r"|presente a[ñn]o|del presente|durante es[te]e? a[ñn]o|durante est?e ano|ano lectivo"
    r"|last year|l'?ann.e derni|a[ñn]o pasado|ano passado|previous year|during previous"
    r"|during (the )?(school year|20\d\d|19\d\d)|school year of (19|20)\d\d"
    r"|attended in (19|20)\d\d"
    r"|which grade is|is \(name\) attending"
    r"|husband|partner|conjoint|spouse|marido|esposo"
    r"|father|mother|p[eè]re|m[eè]re|madre|padre"
    r"|langu|l[ií]ngua|idioma|questionnaire|questionário"
    r"|puede leer|read (this|the) sentence|able to read|literac"
    r"|fr[ée]quent[ée] l'[ée]cole|attend(ed)? school|asisti[oó]( usted)?( alguna vez)? a la escuela"
    r"|alguna vez a la escuela|foi a escola|va a la escuela"
    r"|\d+\s*(-|a|à)\s*\d+\s*an[os]|idade \d|ag[ée] de \d|edad (de )?\d|edad cuando"
    r"|a qu[ée] nivel|à quel niveau|which level|nivel corresponde"
    r"|old and new|education\s+system",
    re.I,
)

# Columns whose identity is ambiguous across MICS rounds — flag for manual review
REVIEW_NAMES = {"ED6B", "ED3", "WB4A", "WI4AD", "WB7C", "ED5BA"}
YES_NO_LABEL = re.compile(r"^(yes|no|oui|non|sim|n[aã]o|si|s[ií])$", re.I)


def classify(col: str, label: str, value_labels: dict) -> str | None:
    """Return 'grade', 'completed', or None."""
    name = col.upper()
    label = label or ""

    if EXCLUDE_LABEL.search(label):
        return None

    # yes/no value labels → completion flag
    substantive = {
        str(v).strip() for k, v in (value_labels or {}).items()
        if not re.match(r"^(9[0-9]?|[0-9]*9[89])(\.0)?$", str(k))
    }
    looks_yesno = bool(substantive) and all(YES_NO_LABEL.match(v) for v in substantive)

    # completion flag: explicit y/n phrasing, or a known name carrying yes/no labels
    if re.search(r"ever complet|grade completion|achev(e|é)ment|a complété"
                 r"|termin[ée]? la derni|completo ese|complet(ed|é) (that|cette)",
                 label, re.I):
        return "completed"
    if name in COMPLETED_NAMES and looks_yesno:
        return "completed"
    if name in GRADE_NAMES or GRADE_LABEL.search(label):
        # ED6-style ambiguity: yes/no labels mean it's a completion flag
        return "completed" if looks_yesno else "grade"
    if name in COMPLETED_NAMES and GRADE_LABEL.search(label):
        return "grade"
    return None


def load_alignment(root: Path) -> dict[str, dict[str, str]]:
    """Return {dataset: {raw_col_lower: canonical}}."""
    with open(root / "alignment_v2.yaml", encoding="utf-8") as f:
        alignment = yaml.safe_load(f) or {}
    mapped: dict[str, dict[str, str]] = {}
    for canonical, entries in alignment.items():
        for e in entries:
            ds = e["dataset_name"]
            raw = (e.get("column_in_raw_sav") or "").lower()
            if raw:
                mapped.setdefault(ds, {})[raw] = canonical
    return mapped


def main() -> None:
    mod_key = sys.argv[1].lower() if len(sys.argv) > 1 else "wm"
    mod = MODULES[mod_key]
    root = mod["root"]

    mapped = load_alignment(root)
    raw_dir = root / "raw"

    rows = []
    for ds_dir in sorted(raw_dir.iterdir()):
        yml = ds_dir / mod["raw_yaml"]
        if not yml.exists():
            continue
        ds = ds_dir.name
        with open(yml, encoding="utf-8") as f:
            try:
                loaded = yaml.safe_load(f) or []
            except yaml.YAMLError as exc:
                print(f"  ! yaml error in {ds}: {exc}")
                continue
        cols = loaded.get("columns", []) if isinstance(loaded, dict) else loaded
        cols = [c for c in cols if isinstance(c, dict)]

        ds_mapped = mapped.get(ds, {})
        for c in cols:
            col = c.get("column_in_raw_sav") or ""
            label = c.get("column_label_in_raw_sav") or ""
            vlabels = c.get("value_labels") or {}
            kind = classify(col, label, vlabels)
            if kind is None:
                continue
            target = mod["grade_canonical"] if kind == "grade" else mod["completed_canonical"]
            current = ds_mapped.get(col.lower())
            if current == target:
                status = "already_mapped"
            elif current is not None:
                status = f"mapped_to_other:{current}"
            else:
                status = "MISSING"
            needs_review = (
                col.upper() in REVIEW_NAMES
                or len(label.strip()) < 8          # bare labels like "Grade", "Classe"
            )
            rows.append({
                "dataset_name": ds,
                "column_in_raw_sav": col,
                "column_label": label,
                "kind": kind,
                "target_canonical": target,
                "status": status,
                "n_value_labels": len(vlabels),
                "needs_review": needs_review,
            })

    df = pd.DataFrame(rows)
    out = root / "grade_mapping_gap_scan.csv"
    df.to_csv(out, index=False)

    print(f"\n=== {mod_key.upper()} scan ===")
    print(f"candidates: {len(df)}  datasets: {df['dataset_name'].nunique()}")
    print(df.groupby(["kind", "status"]).size().to_string())
    missing = df[df["status"] == "MISSING"]
    print(f"\nMISSING: {len(missing)} columns in {missing['dataset_name'].nunique()} datasets"
          f" (needs_review: {missing['needs_review'].sum()})")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
