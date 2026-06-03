"""
Scan all MICS raw folders, detect round, collect variable names per module.
Output: variable inventory as JSON for building the mapping dictionary.
"""

import os
import re
import json
import pyreadstat
from pathlib import Path
from collections import defaultdict

from config import RAW_DATA_DIR

MODULE_PATTERNS = {
    "hh": re.compile(r"^hh\w*\.sav$", re.IGNORECASE),
    "hl": re.compile(r"^hl\w*\.sav$", re.IGNORECASE),
    "wm": re.compile(r"^wm\w*\.sav$", re.IGNORECASE),
    "ch": re.compile(r"^ch\w*\.sav$", re.IGNORECASE),
    "bh": re.compile(r"^bh\w*\.sav$", re.IGNORECASE),
    "fs": re.compile(r"^fs\w*\.sav$", re.IGNORECASE),
    "gm": re.compile(r"^gm\w*\.sav$", re.IGNORECASE),
}

SKIP_FOLDERS = {
    "Mar 11, 2022",
    "ScienceDirect_articles_08Jun2022_09-03-49.547",
    "ML_2021_MIS_10222022_17_109632",
    "SN_2020-21_MIS_09172022_79_109632",
}


def detect_round(folder_name: str) -> str:
    name = folder_name.upper()
    if "MICS6" in name or "MICS 6" in name:
        return "MICS6"
    if "MICS5" in name or "MICS 5" in name:
        return "MICS5"
    if "MICS4" in name or "MICS 4" in name:
        return "MICS4"
    if "MICS3" in name or "MICS 3" in name:
        return "MICS3"
    if "MICS2" in name or "MICS 2" in name:
        return "MICS2"
    if re.search(r"\b(2005|2006|2007|2008)\b", folder_name):
        return "MICS3"
    if re.search(r"\b(1999|2000|2001|2002)\b", folder_name):
        return "MICS2"
    return "UNKNOWN"


def detect_module(filename: str) -> str | None:
    for module, pattern in MODULE_PATTERNS.items():
        if pattern.match(filename):
            return module
    return None


def find_sav_files(folder: Path) -> list[tuple[str, Path]]:
    """Return list of (module, filepath) for all .sav files under folder."""
    results = []
    for root, _, files in os.walk(folder):
        for fname in files:
            module = detect_module(fname)
            if module:
                results.append((module, Path(root) / fname))
    return results


def main():
    # inventory[round][module] = set of variable names
    inventory: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    # examples[round][module] = list of (country_folder, filepath)
    examples: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    top_folders = sorted(RAW_DATA_DIR.iterdir())
    total = len(top_folders)

    for i, folder in enumerate(top_folders, 1):
        if not folder.is_dir():
            continue
        if folder.name in SKIP_FOLDERS:
            print(f"[{i}/{total}] SKIP  {folder.name}")
            continue

        mics_round = detect_round(folder.name)
        sav_files = find_sav_files(folder)

        if not sav_files:
            print(f"[{i}/{total}] {mics_round}  {folder.name}  — no .sav found")
            continue

        for module, filepath in sav_files:
            try:
                _, meta = pyreadstat.read_sav(str(filepath), row_limit=0)
                cols = list(meta.column_names)
                inventory[mics_round][module].update(cols)
                examples[mics_round][module].append(
                    {"country": folder.name, "file": str(filepath)}
                )
                print(f"[{i}/{total}] {mics_round}  {module}  {folder.name}  ({len(cols)} cols)")
            except Exception as e:
                print(f"[{i}/{total}] ERROR  {filepath}: {e}")

    # Convert sets to sorted lists for JSON serialisation
    output = {
        rnd: {mod: sorted(cols) for mod, cols in modules.items()}
        for rnd, modules in inventory.items()
    }

    out_path = Path(__file__).parent / "variable_inventory.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Inventory saved to {out_path}")

    # Summary
    print("\n=== Summary ===")
    for rnd in ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6", "UNKNOWN"]:
        if rnd in output:
            for mod, cols in sorted(output[rnd].items()):
                print(f"  {rnd}  {mod}: {len(cols)} unique variables")


if __name__ == "__main__":
    main()
