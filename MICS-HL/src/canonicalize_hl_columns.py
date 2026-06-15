"""
Build rule-based canonical HL column metadata from translated labels.

Input:  MICS-HL/data/HL/translate/{dataset}/hl.yaml
Output: MICS-HL/data/HL/canonical/{dataset}/hl.yaml
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from canonical_hl import canonicalize_label

_MICS_HL_DIR = Path(__file__).parent.parent
TRANSLATE_DIR = _MICS_HL_DIR / "data" / "HL" / "translate"
CANONICAL_DIR = _MICS_HL_DIR / "data" / "HL" / "canonical"
LOG_FILE = _MICS_HL_DIR / "logs" / "canonicalize_hl.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def process_dataset(translate_yaml_path: Path, out_yaml_path: Path) -> dict[str, int]:
    with open(translate_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    out_columns = []
    n_entries = n_derived = n_review = n_compound = 0

    for col in data.get("columns", []):
        english_label = str(col.get("column_label_in_english", "") or "")
        entries = canonicalize_label(english_label)
        entry_dicts = [entry.to_dict() for entry in entries]
        n_entries  += len(entry_dicts)
        n_derived  += sum(1 for e in entry_dicts if e.get("source_kind") == "derived")
        n_review   += sum(1 for e in entry_dicts if e.get("needs_review"))
        n_compound += sum(1 for e in entry_dicts if e.get("is_compound"))

        out_col = {
            "column_in_raw_sav": col.get("column_in_raw_sav", ""),
            "column_label_in_raw_sav": col.get("column_label_in_raw_sav", ""),
            "column_label_in_english": english_label,
            "canonical": {
                "method": "rules_v1",
                "entries": entry_dicts,
            },
        }
        for key in ("value_labels", "readstat_variable_type",
                    "original_variable_type", "variable_measure", "missing_ranges"):
            if key in col:
                out_col[key] = col[key]
        out_columns.append(out_col)

    out_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "origin_language": data.get("origin_language"),
                "canonicalization_method": "rules_v1",
                "columns": out_columns,
            },
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    return {"columns": len(out_columns), "entries": n_entries,
            "derived": n_derived, "needs_review": n_review, "compound": n_compound}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--dataset", help="process only this dataset")
    args = parser.parse_args()

    translate_paths = sorted(TRANSLATE_DIR.rglob("hl.yaml"))
    if args.dataset:
        translate_paths = [p for p in translate_paths if p.parent.name == args.dataset]

    logger.info("START total_datasets=%d rerun=%s", len(translate_paths), args.rerun)

    total_entries = total_review = 0
    for translate_yaml_path in translate_paths:
        dataset_name = translate_yaml_path.parent.name
        out_yaml_path = CANONICAL_DIR / dataset_name / "hl.yaml"
        if not args.rerun and out_yaml_path.exists():
            logger.info("SKIP dataset=%s", dataset_name)
            continue
        try:
            stats = process_dataset(translate_yaml_path, out_yaml_path)
            total_entries += stats["entries"]
            total_review  += stats["needs_review"]
            logger.info(
                "DONE dataset=%s columns=%d entries=%d derived=%d needs_review=%d",
                dataset_name, stats["columns"], stats["entries"],
                stats["derived"], stats["needs_review"],
            )
        except Exception as e:
            logger.error("ERROR dataset=%s error=%s", dataset_name, e)

    logger.info(
        "SUMMARY total_entries=%d needs_review=%d recognized=%d",
        total_entries, total_review, total_entries - total_review,
    )


if __name__ == "__main__":
    main()
