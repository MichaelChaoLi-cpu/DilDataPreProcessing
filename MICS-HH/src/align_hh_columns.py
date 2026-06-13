"""
Build cross-questionnaire alignment:
  data/HH/alignment.yaml

Algorithm:
1. Load all columns from translate/, excluding col_b entries from dup.yaml.
2. Load their embeddings from translate_embedding/.
3. Compute pairwise cosine similarity between columns from DIFFERENT datasets.
4. Union-Find clustering: merge columns with similarity >= threshold.
5. For each cluster, sort datasets alphabetically; the first column's
   column_label_in_english becomes the varname (lowercase, strip, spaces→_).
6. Write alignment.yaml.
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

import csv

import numpy as np
import pandas as pd
import yaml

_MICS_HH_DIR = Path(__file__).parent.parent
TRANSLATE_DIR = _MICS_HH_DIR / "data" / "HH" / "translate"
EMBED_DIR     = _MICS_HH_DIR / "data" / "HH" / "translate_embedding"
DEDUP_DIR     = _MICS_HH_DIR / "data" / "HH" / "questionnaire_dedup"
OUT_FILE      = _MICS_HH_DIR / "data" / "HH" / "alignment.yaml"
OUT_CSV       = _MICS_HH_DIR / "data" / "HH" / "alignment_summary.csv"
LOG_FILE      = _MICS_HH_DIR / "logs" / "align.log"

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

SIMILARITY_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_varname(label: str) -> str:
    return label.strip().lower().replace(" ", "_")


def _load_excluded(dedup_yaml_path: Path) -> set[str]:
    """Return the set of column_in_raw_sav values to exclude (col_b of each pair)."""
    if not dedup_yaml_path.exists():
        return set()
    with open(dedup_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {p["col_b"]["column_in_raw_sav"] for p in (data.get("pairs") or [])}


def _load_dataset(dataset_name: str) -> list[dict]:
    """Return list of {dataset_name, column_in_raw_sav, column_label_in_english, embedding}."""
    tr_path   = TRANSLATE_DIR / dataset_name / "hh.yaml"
    emb_path  = EMBED_DIR     / dataset_name / "hh.csv"
    dup_path  = DEDUP_DIR     / dataset_name / "dup.yaml"

    if not tr_path.exists() or not emb_path.exists():
        return []

    excluded = _load_excluded(dup_path)

    with open(tr_path, encoding="utf-8") as f:
        tr_data = yaml.safe_load(f)
    label_map = {
        c["column_in_raw_sav"]: c.get("column_label_in_english", "")
        for c in tr_data.get("columns", [])
    }

    emb_df = pd.read_csv(emb_path)
    records = []
    for _, row in emb_df.iterrows():
        col_id = row["column_in_raw_sav"]
        if col_id in excluded:
            continue
        english_label = label_map.get(col_id, "")
        records.append({
            "dataset_name":          dataset_name,
            "column_in_raw_sav":     col_id,
            "column_label_in_english": english_label,
            "embedding":             row.iloc[1:].values.astype(np.float32),
        })
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD)
    args = parser.parse_args()
    threshold = args.threshold

    # 1. Collect all columns across all datasets (alphabetical order)
    dataset_names = sorted(
        d for d in (TRANSLATE_DIR.iterdir())
        if d.is_dir() and (EMBED_DIR / d.name / "hh.csv").exists()
    )
    dataset_names = [d.name for d in dataset_names]

    logger.info("START datasets=%d threshold=%.2f", len(dataset_names), threshold)

    all_records: list[dict] = []
    for ds in dataset_names:
        recs = _load_dataset(ds)
        all_records.extend(recs)
        logger.info("LOAD dataset=%s cols=%d", ds, len(recs))

    n = len(all_records)
    logger.info("TOTAL_COLUMNS %d", n)

    # 2. Stack embeddings and normalise
    vecs = np.stack([r["embedding"] for r in all_records])  # (n, 3072)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    vecs = (vecs / norms).astype(np.float32)

    # dataset index per column (for cross-dataset filtering)
    ds_idx = np.array([dataset_names.index(r["dataset_name"]) for r in all_records])

    # 3. Union-Find clustering via chunked similarity computation
    uf = _UF(n)
    CHUNK = 512
    logger.info("CLUSTERING chunk_size=%d", CHUNK)

    for start in range(0, n, CHUNK):
        end = min(start + CHUNK, n)
        sim_block = vecs[start:end] @ vecs.T          # (chunk, n)
        for local_i, global_i in enumerate(range(start, end)):
            row = sim_block[local_i]
            # only consider j > global_i (upper triangle) from different datasets
            row[:global_i + 1] = 0.0
            same_ds = ds_idx == ds_idx[global_i]
            row[same_ds] = 0.0
            matches = np.where(row >= threshold)[0]
            for j in matches:
                uf.union(global_i, int(j))

        if (start // CHUNK) % 4 == 0:
            logger.info("CLUSTERING_PROGRESS %d/%d", end, n)

    # 4. Group records by cluster root
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[uf.find(i)].append(i)

    logger.info("CLUSTERS total=%d", len(clusters))

    # 5. Build alignment: sort cluster entries by dataset_name (already alphabetical)
    alignment: dict[str, list[dict]] = {}
    varname_counts: dict[str, int] = defaultdict(int)

    for root in sorted(clusters):
        indices = clusters[root]
        # sort by (dataset_name, column_in_raw_sav) for determinism
        indices.sort(key=lambda i: (all_records[i]["dataset_name"], all_records[i]["column_in_raw_sav"]))
        first = all_records[indices[0]]
        base_varname = _make_varname(first["column_label_in_english"]) or first["column_in_raw_sav"].lower()

        varname_counts[base_varname] += 1
        count = varname_counts[base_varname]
        varname = base_varname if count == 1 else f"{base_varname}_{count}"

        alignment[varname] = [
            {
                "dataset_name":            all_records[i]["dataset_name"],
                "column_in_raw_sav":       all_records[i]["column_in_raw_sav"],
                "column_label_in_english": all_records[i]["column_label_in_english"],
            }
            for i in indices
        ]

    # 6. Write yaml
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(
            alignment,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=True,
        )

    # 7. Write summary csv (sorted by dataset_count desc)
    rows = [
        {
            "varname": varname,
            "dataset_count": len(entries),
            "first_label": entries[0]["column_label_in_english"],
        }
        for varname, entries in alignment.items()
    ]
    rows.sort(key=lambda r: r["dataset_count"], reverse=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["varname", "dataset_count", "first_label"])
        writer.writeheader()
        writer.writerows(rows)

    multi = sum(1 for v in alignment.values() if len(v) > 1)
    logger.info("DONE variables=%d multi_dataset=%d single=%d",
                len(alignment), multi, len(alignment) - multi)
    logger.info("OUTPUT yaml=%s csv=%s", OUT_FILE, OUT_CSV)


if __name__ == "__main__":
    main()
