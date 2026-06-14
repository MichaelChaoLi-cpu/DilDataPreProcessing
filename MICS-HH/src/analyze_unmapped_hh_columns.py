"""
Cluster high-frequency HH variables not covered by canonical rules.

This script does not call an LLM. It uses existing translated-label embeddings
from data/HH/translate_embedding/ and records zero token usage in the log.

Inputs:
  data/HH/canonical/{dataset}/hh.yaml
  data/HH/translate_embedding/{dataset}/hh.csv

Outputs:
  data/HH/unmapped_clusters.csv
  data/HH/unmapped_cluster_examples.yaml
"""
from __future__ import annotations

import csv
import logging
import math
import re
import sys
from collections import defaultdict
from pathlib import Path


_MICS_HH_DIR = Path(__file__).parent.parent
CANONICAL_DIR = _MICS_HH_DIR / "data" / "HH" / "canonical"
EMBED_DIR = _MICS_HH_DIR / "data" / "HH" / "translate_embedding"
OUT_CSV = _MICS_HH_DIR / "data" / "HH" / "unmapped_clusters.csv"
OUT_YAML = _MICS_HH_DIR / "data" / "HH" / "unmapped_cluster_examples.yaml"
LOG_FILE = _MICS_HH_DIR / "logs" / "analyze_unmapped.log"

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

_NP = None
_YAML = None


def _get_np():
    global _NP
    if _NP is None:
        logger.info("IMPORT numpy")
        import numpy as np
        _NP = np
        logger.info("IMPORT_DONE numpy")
    return _NP


def _get_yaml():
    global _YAML
    if _YAML is None:
        logger.info("IMPORT yaml")
        import yaml
        _YAML = yaml
        logger.info("IMPORT_DONE yaml")
    return _YAML


class _UF:
    def __init__(self, n: int) -> None:
        self._p = list(range(n))
        self._r = [0] * n

    def find(self, x: int) -> int:
        while self._p[x] != x:
            self._p[x] = self._p[self._p[x]]
            x = self._p[x]
        return x

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self._r[px] < self._r[py]:
            px, py = py, px
        self._p[py] = px
        if self._r[px] == self._r[py]:
            self._r[px] += 1


def _normalize_label(label: str) -> str:
    text = str(label or "").strip().lower()
    text = text.replace("_", " ")
    text = text.replace("’", "'")
    text = re.sub(r"^[a-z]{1,5}\d+[a-z0-9_]*[.)]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :;,.?")


def _short_list(values: list[str], limit: int) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _load_embeddings(dataset_name: str, wanted_cols: set[str]) -> dict[str, object]:
    path = EMBED_DIR / dataset_name / "hh.csv"
    if not path.exists():
        return {}
    if not wanted_cols:
        return {}
    np = _get_np()
    embeddings = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return {}
        for row in reader:
            if not row:
                continue
            col_id = str(row[0])
            if col_id not in wanted_cols:
                continue
            embeddings[col_id] = np.asarray([float(v) for v in row[1:]], dtype=np.float32)
            if len(embeddings) == len(wanted_cols):
                break
    return embeddings


def _iter_unmapped_records(canonical_path: Path) -> list[dict]:
    dataset_name = canonical_path.parent.name
    yaml = _get_yaml()
    with open(canonical_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    unmapped_columns = []
    wanted_cols = set()
    for col in data.get("columns", []):
        entries = col.get("canonical", {}).get("entries", [])
        if not any(entry.get("needs_review") for entry in entries):
            continue
        col_id = str(col.get("column_in_raw_sav", ""))
        wanted_cols.add(col_id)
        unmapped_columns.append(col)

    embeddings = _load_embeddings(dataset_name, wanted_cols)
    if not embeddings and unmapped_columns:
        logger.warning("NO_EMBEDDINGS dataset=%s", dataset_name)
        return []

    records = []
    for col in unmapped_columns:
        col_id = str(col.get("column_in_raw_sav", ""))
        embedding = embeddings.get(col_id)
        if embedding is None:
            continue
        label = str(col.get("column_label_in_english", "") or "")
        records.append({
            "dataset_name": dataset_name,
            "column_in_raw_sav": col_id,
            "column_label_in_english": label,
            "normalized_label": _normalize_label(label),
            "embedding": embedding,
        })
    return records


def _build_exact_groups(records: list[dict]) -> list[dict]:
    np = _get_np()
    grouped: dict[str, dict] = {}
    for record in records:
        key = record["normalized_label"]
        if key not in grouped:
            grouped[key] = {
                "normalized_label": key,
                "source_count": 0,
                "datasets": set(),
                "labels": [],
                "column_names": [],
                "examples": [],
                "vector_sum": np.zeros_like(record["embedding"], dtype=np.float32),
            }
        group = grouped[key]
        group["source_count"] += 1
        group["datasets"].add(record["dataset_name"])
        group["labels"].append(record["column_label_in_english"])
        group["column_names"].append(record["column_in_raw_sav"])
        if len(group["examples"]) < 8:
            group["examples"].append({
                "dataset_name": record["dataset_name"],
                "column_in_raw_sav": record["column_in_raw_sav"],
                "column_label_in_english": record["column_label_in_english"],
            })
        group["vector_sum"] += record["embedding"]

    exact_groups = []
    for group in grouped.values():
        source_count = group["source_count"]
        vector = group["vector_sum"] / max(source_count, 1)
        exact_groups.append({
            "normalized_label": group["normalized_label"],
            "source_count": source_count,
            "dataset_count": len(group["datasets"]),
            "datasets": sorted(group["datasets"]),
            "top_labels": _short_list(group["labels"], 8),
            "top_column_names": _short_list(group["column_names"], 8),
            "examples": group["examples"],
            "embedding": vector.astype(np.float32),
        })
    return exact_groups


def _cluster_groups(groups: list[dict], threshold: float, chunk_size: int) -> list[list[int]]:
    if not groups:
        return []
    np = _get_np()
    vecs = np.stack([g["embedding"] for g in groups]).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    vecs = vecs / norms

    uf = _UF(len(groups))
    for start in range(0, len(groups), chunk_size):
        end = min(start + chunk_size, len(groups))
        sim_block = vecs[start:end] @ vecs.T
        for local_i, global_i in enumerate(range(start, end)):
            row = sim_block[local_i]
            row[:global_i + 1] = 0.0
            matches = np.where(row >= threshold)[0]
            for j in matches:
                uf.union(global_i, int(j))
        logger.info("CLUSTER_PROGRESS groups=%d/%d", end, len(groups))

    clusters_by_root: dict[int, list[int]] = defaultdict(list)
    for i in range(len(groups)):
        clusters_by_root[uf.find(i)].append(i)
    return list(clusters_by_root.values())


def _cluster_summary(cluster_indices: list[int], groups: list[dict], cluster_id: str) -> dict:
    cluster_groups = [groups[i] for i in cluster_indices]
    datasets = sorted({ds for group in cluster_groups for ds in group["datasets"]})
    source_count = sum(group["source_count"] for group in cluster_groups)
    labels = []
    column_names = []
    examples = []
    for group in sorted(cluster_groups, key=lambda g: g["source_count"], reverse=True):
        labels.extend(group["top_labels"])
        column_names.extend(group["top_column_names"])
        examples.extend(group["examples"])

    return {
        "cluster_id": cluster_id,
        "dataset_count": len(datasets),
        "source_count": source_count,
        "exact_group_count": len(cluster_groups),
        "top_labels": _short_list(labels, 10),
        "top_column_names": _short_list(column_names, 10),
        "example_datasets": datasets[:10],
        "examples": examples[:12],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.92, help="embedding similarity threshold")
    parser.add_argument("--min-source-count", type=int, default=2, help="minimum exact-label source count before embedding clustering")
    parser.add_argument("--min-dataset-count", type=int, default=2, help="minimum exact-label dataset count before embedding clustering")
    parser.add_argument("--top", type=int, default=200, help="number of clusters to write")
    parser.add_argument("--chunk-size", type=int, default=512)
    args = parser.parse_args()

    logger.info(
        "START threshold=%.3f min_source_count=%d min_dataset_count=%d top=%d llm_calls=0 input_tokens=0 output_tokens=0 thoughts_tokens=0 total_tokens=0",
        args.threshold,
        args.min_source_count,
        args.min_dataset_count,
        args.top,
    )

    records = []
    for canonical_path in sorted(CANONICAL_DIR.rglob("hh.yaml")):
        dataset_records = _iter_unmapped_records(canonical_path)
        records.extend(dataset_records)
        logger.info("LOAD dataset=%s unmapped=%d", canonical_path.parent.name, len(dataset_records))

    exact_groups = _build_exact_groups(records)
    candidate_groups = [
        group for group in exact_groups
        if group["source_count"] >= args.min_source_count
        and group["dataset_count"] >= args.min_dataset_count
    ]
    logger.info(
        "GROUPS records=%d exact_groups=%d candidate_groups=%d",
        len(records),
        len(exact_groups),
        len(candidate_groups),
    )

    clusters = _cluster_groups(candidate_groups, args.threshold, args.chunk_size)
    summaries = [
        _cluster_summary(indices, candidate_groups, f"unmapped_{i + 1:05d}")
        for i, indices in enumerate(clusters)
    ]
    summaries.sort(key=lambda s: (s["dataset_count"], s["source_count"], s["exact_group_count"]), reverse=True)
    summaries = summaries[:args.top]
    for i, summary in enumerate(summaries, start=1):
        summary["cluster_id"] = f"unmapped_{i:05d}"

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "cluster_id",
                "dataset_count",
                "source_count",
                "exact_group_count",
                "top_labels",
                "top_column_names",
                "example_datasets",
            ],
        )
        writer.writeheader()
        for summary in summaries:
            writer.writerow({
                "cluster_id": summary["cluster_id"],
                "dataset_count": summary["dataset_count"],
                "source_count": summary["source_count"],
                "exact_group_count": summary["exact_group_count"],
                "top_labels": " | ".join(summary["top_labels"]),
                "top_column_names": " | ".join(summary["top_column_names"]),
                "example_datasets": " | ".join(summary["example_datasets"]),
            })

    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml = _get_yaml()
        yaml.dump(
            {
                "method": "exact_label_groups_then_embedding_clusters",
                "llm_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "thoughts_tokens": 0,
                "total_tokens": 0,
                "threshold": args.threshold,
                "min_source_count": args.min_source_count,
                "min_dataset_count": args.min_dataset_count,
                "clusters": summaries,
            },
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    logger.info(
        "DONE records=%d exact_groups=%d candidate_groups=%d clusters=%d written=%d output_csv=%s output_yaml=%s llm_calls=0 input_tokens=0 output_tokens=0 thoughts_tokens=0 total_tokens=0",
        len(records),
        len(exact_groups),
        len(candidate_groups),
        len(clusters),
        len(summaries),
        OUT_CSV,
        OUT_YAML,
    )


if __name__ == "__main__":
    main()
