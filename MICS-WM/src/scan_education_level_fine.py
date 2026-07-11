"""
P09 step 1 — Fine-grained education level classification (splits secondary
into lower/upper where the dataset distinguishes them).

Fine scale:
  0  = None / pre-primary
  1  = Primary
  2  = Secondary, combined/unspecified (dataset does not split)
  21 = Lower secondary
  22 = Upper secondary
  3  = Higher / tertiary
 -1  = Sentinel / missing / not-in-household

WM: reuses the coarse classification in data/WM/education_label_scan.csv (P02)
    and only refines the secondary rows.
HL: fresh scan of hl.yaml value labels for columns mapped to
    highest_education_level, coarse rules imported from scan_education_labels
    (P02), then the same secondary refinement.

Usage:
  python scan_education_level_fine.py wm
  python scan_education_level_fine.py hl

Output:
  MICS-WM/data/WM/education_level_fine_map.csv
  MICS-HL/data/HL/education_level_fine_map.csv
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scan_education_labels import classify_label, _fix_mojibake  # noqa: E402

_PROJECT_ROOT = Path(__file__).parent.parent.parent
WM_ROOT = _PROJECT_ROOT / "MICS-WM" / "data" / "WM"
HL_ROOT = _PROJECT_ROOT / "MICS-HL" / "data" / "HL"

LOWER_SEC = re.compile(
    r"lower sec|junior sec|junior high|basic \(lower"
    r"|secondaire 1\b|secondary 1\b|secondaire i\b|1er cycle|premier cycle|first cycle"
    r"|coll[eè]ge|moyen|fondamental 2"
    r"|middle|preparatory|intermediate"
    r"|\bjss\b|\bsmp\b"                       # junior secondary school, Sekolah Menengah Pertama
    r"|eeb \(3er ciclo\)|3er\.? ciclo|b[aá]sica 7"
    r"|grades? 5-9|grades? 6-9|grades? 7-9|forms? 1-3",
    re.I,
)
UPPER_SEC = re.compile(
    r"upper sec|senior sec|senior high|high school|highschool"
    r"|secondaire 2\b|secondary 2\b|secondaire ii\b|2n?d cycle|2e cycle|deuxi[eè]me cycle|second cycle"
    r"|lyc[ée]e|bachillerato|baccalaur[ée]at|preuniversit|pre-?university"
    r"|\bsma\b|\bsmu\b|\bsm\b"                # Sekolah Menengah Atas/Umum
    r"|educ\.? media|media superior|ense[ñn]anza media|\bmedia\b"
    r"|troisi[eè]me|premi[eè]re|terminale"
    r"|grades? 10-1[12]|forms? 4-[56]"
    r"|senior secondary 2nd level",
    re.I,
)


# ---------------------------------------------------------------------------
# Manual overrides from P09-1 review. Two kinds:
#   LABEL_OVERRIDES — typos and country-specific terms the keyword rules miss;
#                     applied by normalized label text (any dataset)
#   SYSTEM_OVERRIDES — (dataset substring, label regex) → fine level; fixes
#                     country ladders the generic keywords misplace
# ---------------------------------------------------------------------------

LABEL_OVERRIDES: dict[str, float] = {
    "interactivo/ transicion o preparatoria": 0,          # Costa Rica pre-primary
    "early chidlhood education": 0,                        # Samoa (typo)
    "ecd": 0,                                              # Nepal
    "elemantary": 1,                                       # Lebanon Palestinians (typo)
    "1 º nivel": 1, "2 º nivel": 1,                        # Angola ensino de base I/II
    "3 º nivel": 21, "nivel medio": 22,                    # Angola base III / medio
    "obrero": 2,                                           # Cuba skilled-worker track
    "voc./comm/tech": 2, "voc/comm/ tech": 2,              # Ghana
    "vocacional": 2,                                       # Panama
    "cursos técnicos de utu": 2,                           # Uruguay technical secondary
    "preuniv/téc": 22, "técnico medio": 22,                # Cuba upper-secondary tracks
    "metric": 22,                                          # Pakistan AJK matric (typo)
    "estudios técnicos o comerciales con preparatoria terminada": 3,  # Mexico
    "normal de licenciatura": 3, "maestría": 3,            # Mexico tertiary
    "univercity": 3,                                       # Montenegro/Serbia (typo)
    "higer studies": 3,                                    # Yemen (typo)
    "inconsistant": -1,                                    # Pakistan KP sentinel
    "enseñanza especial": -1,                              # Panama special ed, unplaceable
}

SYSTEM_OVERRIDES: list[tuple[str, str, float]] = [
    # Pakistan ladder: middle 6-8 (lower sec), matric 9-10 (upper sec)
    ("Pakistan", r"matric", 22),
    # Moldova lyceum covers grades 10-12
    ("Moldova_MICS4", r"lyceum", 22),
    # Bhutan ladder: lower sec 7-8, middle sec 9-10, higher sec 11-12
    ("Bhutan_MICS4", r"middle secondary", 22),
    # Soviet-system professional tracks enter after grade 9
    ("Kyrgyz", r"professional (primary/middle|middle|secondary/middle)", 22),
]


def apply_overrides(dataset: str, label: str, fine: float | None) -> float | None:
    lab = _fix_mojibake(str(label)).strip().lower()
    for ds_sub, pat, val in SYSTEM_OVERRIDES:
        if ds_sub.lower() in dataset.lower() and re.search(pat, lab, re.I):
            return val
    if lab in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[lab]
    return fine


def refine_secondary(label: str) -> int:
    """Given a coarse-secondary label, return 21, 22, or 2."""
    lab = _fix_mojibake(str(label))
    lower = bool(LOWER_SEC.search(lab))
    upper = bool(UPPER_SEC.search(lab))
    if lower and not upper:
        return 21
    if upper and not lower:
        return 22
    return 2  # combined, unsplit, or contradictory


def run_wm() -> None:
    src = WM_ROOT / "education_label_scan.csv"
    df = pd.read_csv(src)
    df["fine_level"] = df["isced"]
    mask = df["isced"] == 2.0
    df.loc[mask, "fine_level"] = df.loc[mask, "raw_label"].map(refine_secondary)
    df["fine_level"] = df.apply(
        lambda r: apply_overrides(r["dataset_name"], r["raw_label"], r["fine_level"]), axis=1
    )
    out = WM_ROOT / "education_level_fine_map.csv"
    df.to_csv(out, index=False)
    print(f"WM: {len(df)} rows")
    print(df["fine_level"].value_counts(dropna=False).to_string())
    print(f"secondary split: {mask.sum()} → "
          f"21:{(df.fine_level==21).sum()} 22:{(df.fine_level==22).sum()} 2:{(df.fine_level==2).sum()}")
    print(f"saved: {out}")


def run_hl() -> None:
    with open(HL_ROOT / "alignment_v2.yaml", encoding="utf-8") as f:
        alignment = yaml.safe_load(f)
    level_cols: dict[str, set[str]] = {}
    for e in alignment.get("highest_education_level", []):
        raw = e.get("column_in_raw_sav")
        if raw:
            level_cols.setdefault(e["dataset_name"], set()).add(raw.lower())

    rows = []
    for ds, cols in sorted(level_cols.items()):
        yml = HL_ROOT / "raw" / ds / "hl.yaml"
        if not yml.exists():
            continue
        with open(yml, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or []
        entries = loaded.get("columns", []) if isinstance(loaded, dict) else loaded
        for c in entries:
            if not isinstance(c, dict):
                continue
            col = (c.get("column_in_raw_sav") or "")
            if col.lower() not in cols:
                continue
            for code, label in (c.get("value_labels") or {}).items():
                try:
                    code_f = float(code)
                except (TypeError, ValueError):
                    code_f = None
                coarse = classify_label(code_f, str(label))
                fine = coarse
                if coarse == 2:
                    fine = refine_secondary(str(label))
                fine = apply_overrides(ds, str(label), fine)
                rows.append({
                    "dataset_name": ds,
                    "column_in_raw_sav": col,
                    "raw_code": code_f,
                    "raw_label": label,
                    "isced": coarse,
                    "fine_level": fine,
                    "needs_review": fine is None,
                })

    df = pd.DataFrame(rows)
    out = HL_ROOT / "education_level_fine_map.csv"
    df.to_csv(out, index=False)
    print(f"HL: {len(df)} label rows across {df.dataset_name.nunique()} datasets")
    print(df["fine_level"].value_counts(dropna=False).to_string())
    print(f"unclassified (needs_review): {df.needs_review.sum()}")
    print(f"saved: {out}")


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "wm"
    if mode == "wm":
        run_wm()
    else:
        run_hl()
