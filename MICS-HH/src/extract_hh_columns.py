"""
Scan all dataset folders under RAW_DATA_DIR, extract hh.sav column names and
labels, and write per-dataset hh.yaml files to DATA_DIR/HH/raw/{dataset}/hh.yaml.
Folders without hh.sav are recorded in a log file.
"""

import logging
from pathlib import Path

import pyreadstat
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DATA_DIR, DATA_DIR

OUTPUT_ROOT = DATA_DIR / "HH" / "raw"
LOG_FILE = OUTPUT_ROOT / "extract_hh_columns.log"


def setup_logging() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def find_hh_sav(folder: Path) -> Path | None:
    exact = folder / "hh.sav"
    if exact.exists():
        return exact
    matches = [p for p in folder.iterdir() if p.is_file() and "hh" in p.stem.lower() and p.suffix.lower() == ".sav"]
    if len(matches) == 1:
        return matches[0]
    # 多个匹配时，取 stem 含 hhh 的（国家代码+hh → 如 BHhh → bhhh 含 hhh，BHhl 不含）
    triple_h = [p for p in matches if "hhh" in p.stem.lower()]
    return triple_h[0] if len(triple_h) == 1 else None


def _metadata_value(meta, attr: str, col: str, default=None):
    value = getattr(meta, attr, default)
    if isinstance(value, dict):
        return value.get(col, default)
    return default


def _value_labels(meta, col: str) -> dict:
    labels = _metadata_value(meta, "variable_value_labels", col, None)
    if labels is None:
        label_name = _metadata_value(meta, "variable_to_label", col, None)
        labels = getattr(meta, "value_labels", {}).get(label_name, {}) if label_name else {}
    return dict(labels or {})


def extract_dataset(folder: Path) -> None:
    sav_path = find_hh_sav(folder)
    if sav_path is None:
        logging.warning("No hh.sav: %s", folder.name)
        return
    if sav_path.name != "hh.sav":
        logging.info("Matched %s -> %s", folder.name, sav_path.name)

    try:
        _, meta = pyreadstat.read_sav(str(sav_path), metadataonly=True)
    except Exception as e:
        logging.error("ERROR reading %s (%s): %s", folder.name, sav_path.name, e)
        return

    columns = [
        {
            "column_in_raw_sav": col,
            "column_label_in_raw_sav": meta.column_names_to_labels.get(col, ""),
            "value_labels": _value_labels(meta, col),
            "readstat_variable_type": _metadata_value(meta, "readstat_variable_types", col, ""),
            "original_variable_type": _metadata_value(meta, "original_variable_types", col, ""),
            "variable_measure": _metadata_value(meta, "variable_measure", col, ""),
            "missing_ranges": _metadata_value(meta, "missing_ranges", col, []),
        }
        for col in meta.column_names
    ]

    out_dir = OUTPUT_ROOT / folder.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hh.yaml"

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump({"columns": columns}, f, allow_unicode=True, sort_keys=False)

    logging.info("OK: %s  (%d columns)", folder.name, len(columns))


def main() -> None:
    setup_logging()
    logging.info("RAW_DATA_DIR: %s", RAW_DATA_DIR)

    folders = sorted(p for p in RAW_DATA_DIR.iterdir() if p.is_dir())
    logging.info("Found %d dataset folders", len(folders))

    for folder in folders:
        extract_dataset(folder)

    logging.info("Done.")


if __name__ == "__main__":
    main()
