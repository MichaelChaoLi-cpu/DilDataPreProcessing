"""
Process raw hh.yaml files and produce:
  - data/HH/translate/{dataset}/hh.yaml      — labels only (no embedding)
  - data/HH/translate_embedding/{dataset}/hh.csv — column_in_raw_sav + emb_0..emb_3071

Log file: logs/translate.log  (append, one summary line per dataset)

Skip logic: a dataset is skipped if BOTH output files already exist.
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from llm import call_llm, embed_text

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)

_MICS_HH_DIR = Path(__file__).parent.parent
RAW_DIR       = _MICS_HH_DIR / "data" / "HH" / "raw"
TRANSLATE_DIR = _MICS_HH_DIR / "data" / "HH" / "translate"
EMBED_DIR     = _MICS_HH_DIR / "data" / "HH" / "translate_embedding"
LOG_FILE      = _MICS_HH_DIR / "logs" / "translate.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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

_EMB_DIM = 3072


def _detect_language(labels: list[str]) -> tuple[str, int, int, int, int]:
    """Returns (language_name, input_tokens, output_tokens, thoughts_tokens, total_tokens)."""
    sample = "\n".join(f"{i+1}. {l}" for i, l in enumerate(labels[:5]))
    prompt = (
        "Below are column labels from a survey dataset. "
        "What language are they written in? "
        "Reply with only the language name in English (e.g. English, French, Spanish, Arabic). "
        "Do not explain.\n\n"
        f"{sample}"
    )
    r = call_llm(prompt)
    return r.text.strip().strip("."), r.input_tokens, r.output_tokens, r.thoughts_tokens, r.total_tokens


def _translate_to_english(label: str, source_language: str) -> tuple[str, int, int, int, int]:
    """Returns (english_label, input_tokens, output_tokens, thoughts_tokens, total_tokens)."""
    prompt = (
        f"Translate the following survey column label from {source_language} to English. "
        "Reply with only the translated label. Do not explain.\n\n"
        f"{label}"
    )
    r = call_llm(prompt)
    return r.text.strip(), r.input_tokens, r.output_tokens, r.thoughts_tokens, r.total_tokens


def process_dataset(raw_yaml_path: Path, out_yaml_path: Path, out_csv_path: Path) -> None:
    with open(raw_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    columns: list[dict] = data.get("columns", [])
    original_count = len(columns)

    columns = [c for c in columns if "$" not in str(c.get("column_in_raw_sav", ""))]
    filtered_out = original_count - len(columns)

    if not columns:
        logger.warning("NO_COLUMNS_REMAIN path=%s", raw_yaml_path)
        return

    total_input_tokens   = 0
    total_output_tokens  = 0
    total_thoughts_tokens = 0
    total_tokens         = 0

    language, it, ot, tht, tt = _detect_language(
        [str(c.get("column_label_in_raw_sav", "")) for c in columns]
    )
    total_input_tokens   += it
    total_output_tokens  += ot
    total_thoughts_tokens += tht
    total_tokens         += tt
    is_english = language.lower() == "english"

    out_columns_yaml = []
    emb_rows = []

    for idx, col in enumerate(columns):
        raw_label = str(col.get("column_label_in_raw_sav", ""))

        if is_english:
            english_label = raw_label
        else:
            english_label, it, ot, tht, tt = _translate_to_english(raw_label, language)
            total_input_tokens   += it
            total_output_tokens  += ot
            total_thoughts_tokens += tht
            total_tokens         += tt

        embedding = embed_text(english_label)

        out_columns_yaml.append({
            "column_in_raw_sav": col["column_in_raw_sav"],
            "column_label_in_raw_sav": raw_label,
            "column_label_in_english": english_label,
        })
        emb_rows.append([col["column_in_raw_sav"]] + embedding)

        print(
            f"  [{idx+1}/{len(columns)}] {col['column_in_raw_sav']}: {english_label[:60]}",
            flush=True,
        )

    out_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            {"origin_language": language, "columns": out_columns_yaml},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["column_in_raw_sav"] + [f"emb_{i}" for i in range(_EMB_DIM)]
    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(emb_rows)

    logger.info(
        "DONE dataset=%s language=%s columns=%d filtered_out=%d "
        "input_tokens=%d output_tokens=%d thoughts_tokens=%d total_tokens=%d",
        raw_yaml_path.parent.name,
        language,
        len(columns),
        filtered_out,
        total_input_tokens,
        total_output_tokens,
        total_thoughts_tokens,
        total_tokens,
    )


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true", help="reprocess already-completed datasets")
    args = parser.parse_args()

    raw_yaml_paths = sorted(RAW_DIR.rglob("hh.yaml"))
    logger.info("START total_datasets=%d rerun=%s", len(raw_yaml_paths), args.rerun)

    for raw_yaml_path in raw_yaml_paths:
        dataset_name = raw_yaml_path.parent.name
        out_yaml_path = TRANSLATE_DIR / dataset_name / "hh.yaml"
        out_csv_path  = EMBED_DIR / dataset_name / "hh.csv"

        if not args.rerun and out_yaml_path.exists() and out_csv_path.exists():
            logger.info("SKIP dataset=%s", dataset_name)
            continue

        logger.info("PROC dataset=%s", dataset_name)
        try:
            process_dataset(raw_yaml_path, out_yaml_path, out_csv_path)
        except Exception as e:
            logger.error("ERROR dataset=%s error=%s", dataset_name, e)


if __name__ == "__main__":
    main()
