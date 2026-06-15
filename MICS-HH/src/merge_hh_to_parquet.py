"""
Merge all HH SAV files into a single parquet using alignment_v2.yaml.

Inputs:
  RAW_DATA_DIR/{dataset}/hh.sav        (from config.py / .env)
  data/HH/alignment_v2.yaml
  data/HH/questionnaire_dedup_v2/{dataset}/dup.yaml

Output:
  data/HH/processed_data/hh_merged.parquet

Derivation rules (source_kind == "derived"):
  extract_day/month/year/hour/minute  -- extract component from a date/time column.

Duplicate handling:
  When dup.yaml marks a canonical variable as duplicate_candidate, the primary_source
  column is preferred over whatever column alignment_v2.yaml recorded.

Alignment error fix:
  Some datasets (e.g. Mongolia MICS4) have multiple derived entries for the same
  canonical variable.  When this happens the correct source column is chosen by
  matching the column_label_in_english against a keyword for that derivation type.
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pyreadstat
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DATA_DIR, DATA_DIR

_MICS_HH_DIR = Path(__file__).parent.parent
ALIGNMENT_FILE = _MICS_HH_DIR / "data" / "HH" / "alignment_v2.yaml"
DEDUP_DIR = _MICS_HH_DIR / "data" / "HH" / "questionnaire_dedup_v2"
OUTPUT_DIR = DATA_DIR / "HH" / "processed_data"
LOG_FILE = _MICS_HH_DIR / "logs" / "merge_hh.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

_DERIVATION_KEYWORDS: dict[str, list[str]] = {
    "extract_day":    ["day"],
    "extract_month":  ["month"],
    "extract_year":   ["year"],
    "extract_hour":   ["hour"],
    "extract_minute": ["minute"],
}


def _apply_derivation(series: pd.Series, derivation: str) -> pd.Series:
    try:
        if pd.api.types.is_datetime64_any_dtype(series):
            dt = series
        else:
            dt = pd.to_datetime(series, errors="coerce")
        if derivation == "extract_day":
            return dt.dt.day
        if derivation == "extract_month":
            return dt.dt.month
        if derivation == "extract_year":
            return dt.dt.year
        if derivation == "extract_hour":
            return dt.dt.hour
        if derivation == "extract_minute":
            return dt.dt.minute
    except Exception as exc:
        logger.warning("Derivation %s failed: %s", derivation, exc)
    return pd.Series([None] * len(series), index=series.index, dtype="object")


def _load_alignment() -> dict[str, list[dict]]:
    with open(ALIGNMENT_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _build_dataset_map(
    alignment: dict[str, list[dict]],
) -> dict[str, dict[str, list[dict]]]:
    """Return {dataset_name: {canonical_varname: [entries]}}.

    For derived entries with multiple misaligned sources, disambiguation is done
    here and a single-element list is returned.  For explicit entries, all
    candidates are kept so _process_dataset can coalesce them.
    """
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for canonical_varname, entries in alignment.items():
        for entry in entries:
            candidates[(entry["dataset_name"], canonical_varname)].append(entry)

    result: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for (dataset_name, canonical_varname), entries in candidates.items():
        if len(entries) == 1:
            result[dataset_name][canonical_varname] = entries
            continue

        if entries[0]["source_kind"] == "derived":
            derivation = entries[0]["derivation"]
            keywords = _DERIVATION_KEYWORDS.get(derivation, [])
            best = next(
                (
                    e for e in entries
                    if any(kw in (e.get("column_label_in_english") or "").lower()
                           for kw in keywords)
                ),
                None,
            )
            if best is None:
                logger.warning(
                    "Cannot disambiguate derived entries for %s / %s; using first",
                    dataset_name, canonical_varname,
                )
                best = entries[0]
            result[dataset_name][canonical_varname] = [best]
        else:
            # Keep all explicit entries; _process_dataset will coalesce them.
            result[dataset_name][canonical_varname] = entries

    return result


def _load_dedup_primary(dataset_name: str) -> dict[str, str]:
    """Return {canonical_varname: primary_column} from dup.yaml."""
    dup_file = DEDUP_DIR / dataset_name / "dup.yaml"
    if not dup_file.exists():
        return {}
    with open(dup_file, encoding="utf-8") as f:
        dup_data = yaml.safe_load(f) or {}
    result: dict[str, str] = {}
    for group in dup_data.get("groups", []):
        if group.get("decision") == "duplicate_candidate":
            result[group["canonical_varname"]] = group["primary_source"]["column_in_raw_sav"]
    return result


def _find_hh_sav(folder: Path) -> Path | None:
    exact = folder / "hh.sav"
    if exact.exists():
        return exact
    matches = [
        p for p in folder.iterdir()
        if p.is_file() and "hh" in p.stem.lower() and p.suffix.lower() == ".sav"
    ]
    if len(matches) == 1:
        return matches[0]
    triple_h = [p for p in matches if "hhh" in p.stem.lower()]
    return triple_h[0] if len(triple_h) == 1 else None


def _col_lookup(df: pd.DataFrame, raw_col: str) -> str | None:
    """Case-insensitive column lookup; returns the actual column name or None."""
    target = raw_col.lower()
    for col in df.columns:
        if col.lower() == target:
            return col
    return None


def _process_dataset(
    dataset_name: str,
    canonical_map: dict[str, list[dict]],
    dedup_primary: dict[str, str],
) -> pd.DataFrame | None:
    folder = RAW_DATA_DIR / dataset_name
    sav_path = _find_hh_sav(folder)
    if sav_path is None:
        logger.warning("No hh.sav: %s", dataset_name)
        return None

    try:
        df, _ = pyreadstat.read_sav(str(sav_path))
    except Exception as exc:
        logger.error("Failed to read %s: %s", dataset_name, exc)
        return None

    output_cols: dict[str, pd.Series] = {}

    for canonical_varname, entries in canonical_map.items():
        entry = entries[0]

        if entry["source_kind"] == "derived":
            # Single disambiguated entry; apply derivation function.
            actual_col = _col_lookup(df, entry["column_in_raw_sav"])
            if actual_col is None:
                logger.debug(
                    "%s: derived column %s not found (canonical=%s)",
                    dataset_name, entry["column_in_raw_sav"], canonical_varname,
                )
                continue
            output_cols[canonical_varname] = _apply_derivation(
                df[actual_col], entry["derivation"]
            )
            continue

        # Explicit: build ordered column list — dedup primary first, then others.
        primary_col = dedup_primary.get(canonical_varname)
        seen: set[str] = set()
        col_order: list[str] = []
        if primary_col:
            col_order.append(primary_col)
            seen.add(primary_col.lower())
        for e in entries:
            raw = e["column_in_raw_sav"]
            if raw.lower() not in seen:
                col_order.append(raw)
                seen.add(raw.lower())

        # Coalesce: primary fills first; NaN slots are filled from subsequent columns.
        series: pd.Series | None = None
        for raw_col in col_order:
            actual_col = _col_lookup(df, raw_col)
            if actual_col is None:
                continue
            if series is None:
                series = df[actual_col].copy()
            else:
                series = series.combine_first(df[actual_col])

        if series is None:
            logger.debug(
                "%s: no columns found for canonical=%s",
                dataset_name, canonical_varname,
            )
            continue
        output_cols[canonical_varname] = series

    if not output_cols:
        logger.warning("No columns extracted for %s", dataset_name)
        return None

    result = pd.DataFrame(output_cols)
    result.insert(0, "dataset_name", dataset_name)
    return result


def main() -> None:
    alignment = _load_alignment()
    dataset_map = _build_dataset_map(alignment)

    total = len(dataset_map)
    logger.info("Starting merge: %d datasets", total)

    frames: list[pd.DataFrame] = []
    ok = skipped = failed = 0

    for i, dataset_name in enumerate(sorted(dataset_map.keys()), 1):
        logger.info("[%d/%d] %s", i, total, dataset_name)
        dedup_primary = _load_dedup_primary(dataset_name)
        df = _process_dataset(dataset_name, dataset_map[dataset_name], dedup_primary)
        if df is None:
            skipped += 1
            continue
        frames.append(df)
        ok += 1

    if not frames:
        logger.error("No data extracted; aborting")
        return

    logger.info("Concatenating %d frames...", len(frames))
    merged = pd.concat(frames, ignore_index=True, sort=False)

    # Columns with mixed str/numeric values across datasets must be cast to string
    # so pyarrow can write a consistent schema.
    for col in merged.columns:
        if merged[col].dtype == object:
            has_str = merged[col].dropna().map(type).eq(str).any()
            has_num = merged[col].dropna().map(lambda x: isinstance(x, (int, float))).any()
            if has_str and has_num:
                merged[col] = merged[col].astype(str).where(merged[col].notna(), other=None)

    out_path = OUTPUT_DIR / "hh_merged.parquet"
    merged.to_parquet(out_path, index=False)
    logger.info(
        "Saved %s  (%d rows x %d cols)",
        out_path, len(merged), len(merged.columns),
    )
    logger.info("ok=%d  skipped=%d  failed=%d", ok, skipped, failed)


if __name__ == "__main__":
    main()
