"""
Build cross-questionnaire HH alignment from canonical variables.

Input:
  data/HH/canonical/{dataset}/hh.yaml

Outputs:
  data/HH/alignment_v2.yaml
  data/HH/alignment_summary_v2.csv

The v2 alignment allows one raw source column to contribute multiple derived
canonical variables, e.g. Date of interview -> interview_year/month/day.
"""
from __future__ import annotations

import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

import yaml


_MICS_HH_DIR = Path(__file__).parent.parent
CANONICAL_DIR = _MICS_HH_DIR / "data" / "HH" / "canonical"
OUT_FILE = _MICS_HH_DIR / "data" / "HH" / "alignment_v2.yaml"
OUT_CSV = _MICS_HH_DIR / "data" / "HH" / "alignment_summary_v2.csv"
LOG_FILE = _MICS_HH_DIR / "logs" / "align_v2.log"

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


def _iter_dataset_records(dataset_name: str, canonical_yaml_path: Path) -> list[dict]:
    with open(canonical_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    records = []
    for col in data.get("columns", []):
        for entry in col.get("canonical", {}).get("entries", []):
            records.append({
                "dataset_name": dataset_name,
                "column_in_raw_sav": col.get("column_in_raw_sav", ""),
                "column_label_in_english": col.get("column_label_in_english", ""),
                "canonical_varname": entry.get("canonical_varname", ""),
                "canonical_text": entry.get("canonical_text", ""),
                "measure_type": entry.get("measure_type", ""),
                "relation": entry.get("relation"),
                "response_type": entry.get("response_type"),
                "event": entry.get("event"),
                "component": entry.get("component"),
                "entities": entry.get("entities", []),
                "entity_operator": entry.get("entity_operator"),
                "is_compound": bool(entry.get("is_compound", False)),
                "source_kind": entry.get("source_kind", "explicit"),
                "derivation": entry.get("derivation"),
                "confidence": entry.get("confidence", ""),
                "needs_review": bool(entry.get("needs_review", False)),
            })
    return records


def _record_sort_key(record: dict) -> tuple[str, str, str, str]:
    return (
        str(record.get("dataset_name", "")),
        "0" if record.get("source_kind") == "explicit" else "1",
        str(record.get("column_in_raw_sav", "")),
        str(record.get("derivation", "")),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--include-review", action="store_true", help="include low-confidence fallback variables")
    args = parser.parse_args()

    canonical_paths = sorted(CANONICAL_DIR.rglob("hh.yaml"))
    logger.info("START total_datasets=%d include_review=%s", len(canonical_paths), args.include_review)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for canonical_yaml_path in canonical_paths:
        dataset_name = canonical_yaml_path.parent.name
        records = _iter_dataset_records(dataset_name, canonical_yaml_path)
        kept = 0
        for record in records:
            if record.get("needs_review") and not args.include_review:
                continue
            varname = record.get("canonical_varname")
            if not varname:
                continue
            grouped[str(varname)].append(record)
            kept += 1
        logger.info("LOAD dataset=%s records=%d kept=%d", dataset_name, len(records), kept)

    alignment = {}
    for varname in sorted(grouped):
        records = sorted(grouped[varname], key=_record_sort_key)
        alignment[varname] = records

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(
            alignment,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=True,
        )

    rows = []
    for varname, records in alignment.items():
        datasets = {r["dataset_name"] for r in records}
        explicit_count = sum(1 for r in records if r.get("source_kind") == "explicit")
        derived_count = sum(1 for r in records if r.get("source_kind") == "derived")
        first = records[0]
        rows.append({
            "varname": varname,
            "dataset_count": len(datasets),
            "source_count": len(records),
            "explicit_count": explicit_count,
            "derived_count": derived_count,
            "measure_type": first.get("measure_type", ""),
            "canonical_text": first.get("canonical_text", ""),
        })
    rows.sort(key=lambda r: (r["dataset_count"], r["source_count"], r["varname"]), reverse=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "varname",
                "dataset_count",
                "source_count",
                "explicit_count",
                "derived_count",
                "measure_type",
                "canonical_text",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info("DONE variables=%d output_yaml=%s output_csv=%s", len(alignment), OUT_FILE, OUT_CSV)


if __name__ == "__main__":
    main()
