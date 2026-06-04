"""
Shared utilities for module data reports.
"""

import json
from pathlib import Path

import pyreadstat

ROOT = Path(__file__).parents[1]
INVENTORY_PATH = ROOT / "src" / "variable_inventory.json"
RAW_DIR = Path("/Volumes/MikesDataBackup/MICS/raw")

# Representative MICS5/MICS4 files for English variable labels
LABEL_SOURCES = {
    "hh": [
        RAW_DIR / "Bangladesh_MICS5_Datasets/Bangladesh MICS 2012-13 SPSS Datasets/hh.sav",
        RAW_DIR / "Afghanistan_MICS4_Datasets/Afghanistan MICS 2010-2011 SPSS Datasets/hh.sav",
        RAW_DIR / "Albania MICS 2005 SPSS Datasets/hh.sav",
    ],
    "hl": [
        RAW_DIR / "Bangladesh_MICS5_Datasets/Bangladesh MICS 2012-13 SPSS Datasets/hl.sav",
        RAW_DIR / "Afghanistan_MICS4_Datasets/Afghanistan MICS 2010-2011 SPSS Datasets/hl.sav",
        RAW_DIR / "Albania MICS 2005 SPSS Datasets/hl.sav",
    ],
    "wm": [
        RAW_DIR / "Bangladesh_MICS5_Datasets/Bangladesh MICS 2012-13 SPSS Datasets/wm.sav",
        RAW_DIR / "Afghanistan_MICS4_Datasets/Afghanistan MICS 2010-2011 SPSS Datasets/wm.sav",
    ],
    "ch": [
        RAW_DIR / "Bangladesh_MICS5_Datasets/Bangladesh MICS 2012-13 SPSS Datasets/ch.sav",
        RAW_DIR / "Afghanistan_MICS4_Datasets/Afghanistan MICS 2010-2011 SPSS Datasets/ch.sav",
    ],
}


def get_standard_variables(module: str, threshold: float = 0.5) -> list[str]:
    """Return variables appearing in ≥ threshold fraction of MICS3-6 surveys."""
    with open(INVENTORY_PATH, encoding="utf-8") as f:
        inv = json.load(f)

    from collections import Counter
    all_surveys: list[set] = []
    for rnd in ["MICS3", "MICS4", "MICS5", "MICS6"]:
        # inventory gives union per round; approximate per-survey by treating each
        # round as one observation — good enough for a ≥3/4 rounds criterion
        cols = inv.get(rnd, {}).get(module, [])
        if cols:
            all_surveys.append(set(cols))

    if not all_surveys:
        return []

    freq = Counter()
    for s in all_surveys:
        freq.update(s)

    total = len(all_surveys)
    standard = sorted(v for v, c in freq.items() if c / total >= threshold)
    return standard


def get_variable_labels(module: str) -> dict[str, str]:
    """Read variable labels from representative English SPSS files."""
    labels: dict[str, str] = {}
    sources = LABEL_SOURCES.get(module, [])
    for path in sources:
        if not path.exists():
            continue
        try:
            _, meta = pyreadstat.read_sav(str(path), row_limit=0)
            for col, lbl in meta.column_names_to_labels.items():
                if col not in labels and lbl:
                    # Strip prefixes like "HH1." or "HH1. " from MICS3 labels
                    clean = lbl.strip()
                    if clean.startswith(col + "."):
                        clean = clean[len(col) + 1:].strip()
                    labels[col] = clean
        except Exception:
            continue
    return labels


def standard_vars_table(module: str, threshold: float = 0.5) -> str:
    """Return a markdown table of standard variables with labels and round presence."""
    with open(INVENTORY_PATH, encoding="utf-8") as f:
        inv = json.load(f)

    standard = get_standard_variables(module, threshold)
    labels = get_variable_labels(module)

    round_sets = {
        rnd: set(inv.get(rnd, {}).get(module, []))
        for rnd in ["MICS3", "MICS4", "MICS5", "MICS6"]
    }

    lines = [
        f"共 **{len(standard)}** 个标准变量（出现在 ≥{int(threshold*100)}% 的轮次中）\n",
        "| 变量名 | 含义 | MICS3 | MICS4 | MICS5 | MICS6 |",
        "|--------|------|:-----:|:-----:|:-----:|:-----:|",
    ]
    for var in standard:
        lbl = labels.get(var, "")
        presence = " | ".join(
            "✓" if var in round_sets[r] else "—"
            for r in ["MICS3", "MICS4", "MICS5", "MICS6"]
        )
        lines.append(f"| `{var}` | {lbl} | {presence} |")

    return "\n".join(lines)
