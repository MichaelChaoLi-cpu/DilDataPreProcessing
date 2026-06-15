"""
Questionnaire-level duplicate and overlap checks based on canonical HL variables.

Unlike the v1 embedding dedup step, this script does not drop columns. It writes
decisions that downstream alignment can inspect:

  data/HL/questionnaire_dedup_v2/{dataset}/dup.yaml
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

import yaml


_MICS_HL_DIR = Path(__file__).parent.parent
CANONICAL_DIR = _MICS_HL_DIR / "data" / "HL" / "canonical"
DEDUP_DIR     = _MICS_HL_DIR / "data" / "HL" / "questionnaire_dedup_v2"
LOG_FILE      = _MICS_HL_DIR / "logs" / "dedup_hl_v2.log"

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


def _iter_canonical_records(canonical_yaml_path: Path) -> list[dict]:
    with open(canonical_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    records = []
    for col in data.get("columns", []):
        for entry in col.get("canonical", {}).get("entries", []):
            records.append({
                "column_in_raw_sav": col.get("column_in_raw_sav", ""),
                "column_label_in_english": col.get("column_label_in_english", ""),
                "value_labels": col.get("value_labels", {}),
                "readstat_variable_type": col.get("readstat_variable_type", ""),
                "original_variable_type": col.get("original_variable_type", ""),
                "variable_measure": col.get("variable_measure", ""),
                "canonical_varname": entry.get("canonical_varname", ""),
                "canonical_text": entry.get("canonical_text", ""),
                "measure_type": entry.get("measure_type", ""),
                "source_kind": entry.get("source_kind", "explicit"),
                "derivation": entry.get("derivation"),
                "response_type": entry.get("response_type"),
                "entities": entry.get("entities", []),
                "entity_operator": entry.get("entity_operator"),
                "is_compound": bool(entry.get("is_compound", False)),
                "confidence": entry.get("confidence", ""),
                "needs_review": bool(entry.get("needs_review", False)),
            })
    return records


def _choose_primary(records: list[dict]) -> dict:
    def sort_key(record: dict) -> tuple[int, int, str]:
        explicit_rank = 0 if record.get("source_kind") == "explicit" else 1
        review_rank   = 1 if record.get("needs_review") else 0
        return (explicit_rank, review_rank, str(record.get("column_in_raw_sav", "")))

    return sorted(records, key=sort_key)[0]


def _value_label_signature(record: dict) -> tuple[str, ...]:
    labels = record.get("value_labels") or {}
    if not isinstance(labels, dict):
        return ()
    return tuple(f"{k}:{v}" for k, v in sorted(labels.items(), key=lambda item: str(item[0])))


def _response_compatible(records: list[dict]) -> bool:
    response_types = {r.get("response_type") for r in records if r.get("response_type")}
    if len(response_types) > 1:
        return False

    signatures = {_value_label_signature(r) for r in records if _value_label_signature(r)}
    if len(signatures) > 1:
        return False

    readstat_types = {r.get("readstat_variable_type") for r in records if r.get("readstat_variable_type")}
    return len(readstat_types) <= 1


def _decision(records: list[dict]) -> str:
    source_kinds = {r.get("source_kind") for r in records}
    if "explicit" in source_kinds and "derived" in source_kinds:
        return "derived_overlap"
    if not _response_compatible(records):
        return "duplicate_needs_review"
    if len(records) > 1:
        return "duplicate_candidate"
    return "unique"


def process_dataset(canonical_yaml_path: Path, out_yaml_path: Path) -> dict[str, int]:
    records = _iter_canonical_records(canonical_yaml_path)
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        varname = record.get("canonical_varname")
        if varname:
            groups[str(varname)].append(record)

    decisions = []
    for varname, group in sorted(groups.items()):
        if len(group) <= 1:
            continue
        primary = _choose_primary(group)
        alternatives = [
            record for record in sorted(group, key=lambda r: str(r.get("column_in_raw_sav", "")))
            if record is not primary
        ]
        decision = _decision(group)
        if decision == "derived_overlap":
            reason = "explicit and derived sources provide the same canonical variable"
        elif decision == "duplicate_needs_review":
            reason = "multiple columns map to the same canonical variable but response metadata differs"
        else:
            reason = "multiple columns map to the same canonical variable"
        decisions.append({
            "canonical_varname": varname,
            "decision": decision,
            "primary_source": primary,
            "alternative_sources": alternatives,
            "reason": reason,
        })

    out_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            {"groups": decisions},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    return {
        "records": len(records),
        "groups": len(decisions),
        "derived_overlap": sum(1 for d in decisions if d["decision"] == "derived_overlap"),
        "duplicate_candidate": sum(1 for d in decisions if d["decision"] == "duplicate_candidate"),
        "duplicate_needs_review": sum(1 for d in decisions if d["decision"] == "duplicate_needs_review"),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true", help="reprocess already-completed datasets")
    parser.add_argument("--dataset", help="process only this dataset directory name")
    args = parser.parse_args()

    canonical_paths = sorted(CANONICAL_DIR.rglob("hl.yaml"))
    if args.dataset:
        canonical_paths = [p for p in canonical_paths if p.parent.name == args.dataset]

    logger.info("START total_datasets=%d rerun=%s", len(canonical_paths), args.rerun)
    total_groups = total_candidate = total_review = total_overlap = 0
    for canonical_yaml_path in canonical_paths:
        dataset_name = canonical_yaml_path.parent.name
        out_yaml_path = DEDUP_DIR / dataset_name / "dup.yaml"
        if not args.rerun and out_yaml_path.exists():
            logger.info("SKIP dataset=%s", dataset_name)
            continue

        try:
            stats = process_dataset(canonical_yaml_path, out_yaml_path)
            total_groups    += stats["groups"]
            total_candidate += stats["duplicate_candidate"]
            total_review    += stats["duplicate_needs_review"]
            total_overlap   += stats["derived_overlap"]
            logger.info(
                "DONE dataset=%s records=%d groups=%d duplicate_candidate=%d"
                " duplicate_needs_review=%d derived_overlap=%d",
                dataset_name,
                stats["records"],
                stats["groups"],
                stats["duplicate_candidate"],
                stats["duplicate_needs_review"],
                stats["derived_overlap"],
            )
        except Exception as e:
            logger.error("ERROR dataset=%s error=%s", dataset_name, e)

    logger.info(
        "SUMMARY total_groups=%d duplicate_candidate=%d duplicate_needs_review=%d derived_overlap=%d",
        total_groups, total_candidate, total_review, total_overlap,
    )


if __name__ == "__main__":
    main()
