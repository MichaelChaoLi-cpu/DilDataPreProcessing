"""
Merge all MICS .sav files into per-module Parquet datasets.

For each module (hh, hl, wm, ch, bh, fs, gm):
  1. Scan all country/round folders
  2. Apply variable renaming from variable_mapping.ROUND_RENAME
  3. Drop MICS2 variables not in the MICS3-6 standard variable set
  4. Concatenate with country + mics_round columns added
  5. Write <module>.parquet to PROCESSED_DATA_DIR
"""

import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from config import MODULES, PROCESSED_DATA_DIR, RAW_DATA_DIR
from variable_mapping import ROUND_RENAME

SKIP_FOLDERS = {
    "Mar 11, 2022",
    "ScienceDirect_articles_08Jun2022_09-03-49.547",
    "ML_2021_MIS_10222022_17_109632",
    "SN_2020-21_MIS_09172022_79_109632",
}

MODULE_PAT = {
    mod: re.compile(rf"^{mod}\w*\.sav$", re.IGNORECASE) for mod in MODULES
}


def detect_round(name: str) -> str:
    n = name.upper()
    for tag in ["MICS6", "MICS5", "MICS4", "MICS3", "MICS2"]:
        if tag in n:
            return tag
    if re.search(r"\b(2005|2006|2007|2008)\b", name):
        return "MICS3"
    if re.search(r"\b(1999|2000|2001|2002)\b", name):
        return "MICS2"
    return "UNKNOWN"


def extract_country(name: str) -> str:
    s = name
    for pat in [
        r"_?MICS\s*[0-9]\s*\d*[\w\s]*Datasets?",
        r"\s*MICS\s*[0-9][\w\s]*Datasets?",
        r"\s*MICS\s+\d{4}[\w\s]*",
        r"\s+\d{4}[\s_]*MICS[\w\s_]*",
        r"_LSIS_Datasets?",
        r"\s+SPSS\s+Datasets?",
        r"\s+Datasets?$",
    ]:
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
    return s.replace("_", " ").strip() or name


def find_sav_files(folder: Path) -> list[tuple[str, Path]]:
    results = []
    for root, _, files in os.walk(folder):
        for fname in files:
            for mod, pat in MODULE_PAT.items():
                if pat.match(fname):
                    results.append((mod, Path(root) / fname))
    return results


def apply_rename(df: pd.DataFrame, module: str, mics_round: str) -> pd.DataFrame:
    rename_map = ROUND_RENAME.get(mics_round, {}).get(module, {})
    if not rename_map:
        return df
    # MICS2 conflict: when both PSU and HI1 exist, drop PSU (HI1 → HH1)
    if mics_round == "MICS2":
        if "HI1" in df.columns and "PSU" in df.columns:
            df = df.drop(columns=["PSU"])
        if "HI2" in df.columns and "HOUSE" in df.columns:
            df = df.drop(columns=["HOUSE"])
    active = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=active)
    # Drop any duplicate columns that arose from renaming (keep first occurrence)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep="first")]
    return df


def load_mics36_standard(inventory_path: Path) -> dict[str, set[str]]:
    with open(inventory_path) as f:
        inv = json.load(f)
    standard: dict[str, set[str]] = {}
    for mod in MODULES:
        cols: set[str] = set()
        for rnd in ["MICS3", "MICS4", "MICS5", "MICS6"]:
            cols.update(inv.get(rnd, {}).get(mod, []))
        standard[mod] = cols
    return standard


def _safe_unify_schemas(schemas: list[pa.Schema]) -> pa.Schema:
    """Unify schemas; resolve type conflicts by falling back to large_string."""
    merged: dict[str, pa.DataType] = {}
    for schema in schemas:
        for field in schema:
            if field.name not in merged:
                merged[field.name] = field.type
            elif merged[field.name] != field.type:
                merged[field.name] = pa.large_string()
    return pa.schema([pa.field(n, t) for n, t in merged.items()])


def _cast_to_schema(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Align a table to target schema: add missing columns as null, cast types."""
    cols = {}
    for field in schema:
        if field.name in table.schema.names:
            col = table.column(field.name)
            if col.type != field.type:
                try:
                    col = col.cast(field.type, safe=False)
                except Exception:
                    col = col.cast(pa.large_string(), safe=False)
            cols[field.name] = col
        else:
            cols[field.name] = pa.array([None] * len(table), type=field.type)
    return pa.table(cols)


def _normalise_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure all object columns are either float64 or clean string (no mixed types).

    PyArrow requires consistent types within a column. Object columns with a mix
    of numbers and empty strings cause ArrowInvalid errors at parquet write time.
    """
    for col in df.select_dtypes(include="object").columns:
        if col in {"country", "mics_round"}:
            continue
        # Replace empty strings with NaN before type inference
        s = df[col].replace("", pd.NA)
        converted = pd.to_numeric(s, errors="coerce")
        non_null = s.notna().sum()
        if non_null == 0 or converted.notna().sum() >= non_null * 0.99:
            # Column is effectively numeric → store as float64
            df[col] = converted
        else:
            # Mixed or string column → ensure uniform string, NaN stays NaN
            df[col] = s.where(s.isna(), s.astype(str))
    return df


def drop_mics2_nonstandard(
    df: pd.DataFrame, module: str, standard: dict[str, set[str]]
) -> pd.DataFrame:
    keep = standard.get(module, set()) | {"country", "mics_round"}
    drop = [c for c in df.columns if c not in keep]
    return df.drop(columns=drop)


def _process_module(
    module: str,
    top_folders: list[Path],
    mics36_standard: dict[str, set[str]],
) -> None:
    """Stream-write one module to parquet: each country written immediately to disk.

    Two-pass approach:
      Pass 1 — write each country as a small staging parquet, collect schemas.
      Pass 2 — unify schemas, re-read staging files one-by-one into final parquet.
    Peak memory = largest single country file, not the whole module.
    """
    staging_dir = PROCESSED_DATA_DIR / "_staging" / module
    staging_dir.mkdir(parents=True, exist_ok=True)

    total = len(top_folders)
    staging_files: list[Path] = []
    schemas: list[pa.Schema] = []

    # Pass 1: write each country to a small staging parquet
    for i, folder in enumerate(top_folders, 1):
        if not folder.is_dir() or folder.name in SKIP_FOLDERS:
            continue
        mics_round = detect_round(folder.name)
        if mics_round == "UNKNOWN":
            continue
        country = extract_country(folder.name)

        for root, _, files in os.walk(folder):
            for fname in files:
                if not MODULE_PAT[module].match(fname):
                    continue
                filepath = Path(root) / fname
                try:
                    df, _ = pyreadstat.read_sav(
                        str(filepath),
                        apply_value_formats=False,
                        formats_as_category=False,
                    )
                    df = apply_rename(df, module, mics_round)
                    if mics_round == "MICS2":
                        df = drop_mics2_nonstandard(df, module, mics36_standard)
                    df.insert(0, "country", country)
                    df.insert(1, "mics_round", mics_round)
                    df = _normalise_dtypes(df)
                    table = pa.Table.from_pandas(df, preserve_index=False)
                    out = staging_dir / f"{len(staging_files):05d}.parquet"
                    pq.write_table(table, out)
                    staging_files.append(out)
                    schemas.append(table.schema)
                    print(
                        f"  [{i}/{total}] {mics_round}  {country}"
                        f"  ({len(df):,} rows, {len(df.columns)} cols)"
                    )
                except Exception as e:
                    print(f"  [{i}/{total}] ERROR  {filepath}: {e}")

    if not staging_files:
        print(f"  {module}: no data, skipping")
        shutil.rmtree(staging_dir, ignore_errors=True)
        return

    # Pass 2: unify schemas, combine staging files into final parquet
    unified = _safe_unify_schemas(schemas)
    out_path = PROCESSED_DATA_DIR / f"{module}.parquet"
    total_rows = 0
    with pq.ParquetWriter(out_path, unified) as writer:
        for f in staging_files:
            t = pq.read_table(f)
            t = _cast_to_schema(t, unified)
            writer.write_table(t)
            total_rows += len(t)

    shutil.rmtree(staging_dir, ignore_errors=True)
    print(f"  → {total_rows:,} rows × {len(unified)} cols  saved to {out_path}")


def main() -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    inventory_path = Path(__file__).parent / "variable_inventory.json"
    mics36_standard = load_mics36_standard(inventory_path)
    top_folders = sorted(RAW_DATA_DIR.iterdir())

    for module in MODULES:
        print(f"\n=== Module: {module} ===")
        _process_module(module, top_folders, mics36_standard)


if __name__ == "__main__":
    main()
