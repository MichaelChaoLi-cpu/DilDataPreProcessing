"""
Scan all MICS raw .sav files, collect variable labels per module.
Output: variable_dictionary.yaml

Structure:
  module:
    VARNAME:
      rounds: [MICS2, MICS3, ...]
      labels:
        - text: "Label text"
          sources:
            - round: MICS6
              country: "Folder name"
"""

import os
import re
import yaml
from pathlib import Path
from collections import defaultdict

import pyreadstat
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


def main():
    # data[module][varname]["rounds"] = set of rounds
    # data[module][varname]["labels"] = {label_text: [{"round": ..., "country": ...}, ...]}
    data: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"rounds": set(), "labels": defaultdict(list)})
    )

    top_folders = sorted(RAW_DATA_DIR.iterdir())
    total = len(top_folders)

    for i, folder in enumerate(top_folders, 1):
        if not folder.is_dir():
            continue
        if folder.name in SKIP_FOLDERS:
            print(f"[{i}/{total}] SKIP  {folder.name}")
            continue

        mics_round = detect_round(folder.name)
        country = folder.name

        for root, _, files in os.walk(folder):
            for fname in files:
                module = detect_module(fname)
                if not module:
                    continue
                filepath = Path(root) / fname
                try:
                    _, meta = pyreadstat.read_sav(str(filepath), row_limit=0)
                    labels_map: dict[str, str] = meta.column_names_to_labels
                    for varname in meta.column_names:
                        entry = data[module][varname]
                        entry["rounds"].add(mics_round)
                        label = (labels_map.get(varname) or "").strip()
                        if label:
                            entry["labels"][label].append(
                                {"round": mics_round, "country": country}
                            )
                    print(f"[{i}/{total}] {mics_round}  {module}  {folder.name}")
                except Exception as e:
                    print(f"[{i}/{total}] ERROR  {filepath}: {e}")

    # Build YAML-serialisable structure
    round_order = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6", "UNKNOWN"]
    output: dict[str, dict] = {}

    for module in sorted(data.keys()):
        output[module] = {}
        for varname in sorted(data[module].keys()):
            entry = data[module][varname]
            rounds_sorted = sorted(
                entry["rounds"], key=lambda r: round_order.index(r) if r in round_order else 99
            )
            labels_list = [
                {"text": label_text, "sources": sources}
                for label_text, sources in sorted(entry["labels"].items())
            ]
            output[module][varname] = {
                "rounds": rounds_sorted,
                "labels": labels_list,
            }

    out_path = Path(__file__).parent / "variable_dictionary.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"\nDone. Saved to {out_path}")

    # Summary
    print("\n=== Summary ===")
    for module, variables in output.items():
        print(f"  {module}: {len(variables)} unique variables")


if __name__ == "__main__":
    main()
