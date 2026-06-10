"""
For each dataset, compute pairwise cosine similarity of column embeddings and
write potential duplicate pairs (similarity >= threshold) to:
  data/HH/questionnaire_dedup/{dataset}/dup.yaml

Skip logic: skip if dup.yaml already exists, unless --rerun is passed.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

_MICS_HH_DIR = Path(__file__).parent.parent
TRANSLATE_DIR = _MICS_HH_DIR / "data" / "HH" / "translate"
EMBED_DIR     = _MICS_HH_DIR / "data" / "HH" / "translate_embedding"
DEDUP_DIR     = _MICS_HH_DIR / "data" / "HH" / "questionnaire_dedup"
LOG_FILE      = _MICS_HH_DIR / "logs" / "dedup.log"

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


def _load_labels(translate_yaml_path: Path) -> dict[str, dict]:
    """Return {column_in_raw_sav: {column_in_raw_sav, column_label_in_raw_sav, column_label_in_english}}."""
    with open(translate_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {
        c["column_in_raw_sav"]: {
            "column_in_raw_sav":        c["column_in_raw_sav"],
            "column_label_in_raw_sav":  c.get("column_label_in_raw_sav", ""),
            "column_label_in_english":  c.get("column_label_in_english", ""),
        }
        for c in data.get("columns", [])
    }


def _cosine_similarity_matrix(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    normed = vecs / norms
    return normed @ normed.T


def process_dataset(
    translate_yaml_path: Path,
    embed_csv_path: Path,
    out_yaml_path: Path,
    threshold: float = SIMILARITY_THRESHOLD,
) -> int:
    """Returns the number of duplicate pairs found."""
    labels = _load_labels(translate_yaml_path)

    df = pd.read_csv(embed_csv_path)
    col_ids = df["column_in_raw_sav"].tolist()
    vecs = df.iloc[:, 1:].values.astype(np.float32)

    sim_matrix = _cosine_similarity_matrix(vecs)

    pairs = []
    n = len(col_ids)
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(sim_matrix[i, j])
            if sim >= threshold:
                col_a = labels.get(col_ids[i], {"column_in_raw_sav": col_ids[i], "column_label_in_raw_sav": "", "column_label_in_english": ""})
                col_b = labels.get(col_ids[j], {"column_in_raw_sav": col_ids[j], "column_label_in_raw_sav": "", "column_label_in_english": ""})
                pairs.append({
                    "similarity": round(sim, 4),
                    "col_a": col_a,
                    "col_b": col_b,
                })

    pairs.sort(key=lambda p: p["similarity"], reverse=True)

    out_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            {"threshold": threshold, "pairs": pairs},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    return len(pairs)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true", help="reprocess already-completed datasets")
    parser.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD,
                        help=f"cosine similarity threshold (default: {SIMILARITY_THRESHOLD})")
    args = parser.parse_args()

    threshold = args.threshold

    embed_csv_paths = sorted(EMBED_DIR.rglob("hh.csv"))
    logger.info("START total_datasets=%d threshold=%.2f rerun=%s",
                len(embed_csv_paths), threshold, args.rerun)

    total_pairs = 0
    for embed_csv_path in embed_csv_paths:
        dataset_name = embed_csv_path.parent.name
        translate_yaml_path = TRANSLATE_DIR / dataset_name / "hh.yaml"
        out_yaml_path = DEDUP_DIR / dataset_name / "dup.yaml"

        if not translate_yaml_path.exists():
            logger.warning("SKIP_NO_TRANSLATE dataset=%s", dataset_name)
            continue

        if not args.rerun and out_yaml_path.exists():
            logger.info("SKIP dataset=%s", dataset_name)
            continue

        logger.info("PROC dataset=%s", dataset_name)
        try:
            n_pairs = process_dataset(translate_yaml_path, embed_csv_path, out_yaml_path, threshold)
            total_pairs += n_pairs
            logger.info("DONE dataset=%s dup_pairs=%d", dataset_name, n_pairs)
        except Exception as e:
            logger.error("ERROR dataset=%s error=%s", dataset_name, e)

    logger.info("FINISH total_dup_pairs=%d", total_pairs)


if __name__ == "__main__":
    main()
