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
from pathlib import Path

import pandas as pd
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
    return df.rename(columns=active)


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


def _normalise_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Convert object columns to numeric where all values are numeric or NaN."""
    for col in df.select_dtypes(include="object").columns:
        if col in {"country", "mics_round"}:
            continue
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().sum() >= df[col].notna().sum() * 0.99:
            df[col] = converted
    return df


def drop_mics2_nonstandard(
    df: pd.DataFrame, module: str, standard: dict[str, set[str]]
) -> pd.DataFrame:
    keep = standard.get(module, set()) | {"country", "mics_round"}
    drop = [c for c in df.columns if c not in keep]
    return df.drop(columns=drop)


def main() -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    inventory_path = Path(__file__).parent / "variable_inventory.json"
    mics36_standard = load_mics36_standard(inventory_path)

    frames: dict[str, list[pd.DataFrame]] = {mod: [] for mod in MODULES}

    top_folders = sorted(RAW_DATA_DIR.iterdir())
    total = len(top_folders)

    for i, folder in enumerate(top_folders, 1):
        if not folder.is_dir() or folder.name in SKIP_FOLDERS:
            continue
        mics_round = detect_round(folder.name)
        if mics_round == "UNKNOWN":
            print(f"[{i}/{total}] SKIP (unknown round)  {folder.name}")
            continue

        country = extract_country(folder.name)
        sav_files = find_sav_files(folder)
        if not sav_files:
            continue

        for module, filepath in sav_files:
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
                frames[module].append(df)
                print(
                    f"[{i}/{total}] {mics_round}  {module}  {country}"
                    f"  ({len(df):,} rows, {len(df.columns)} cols)"
                )
            except Exception as e:
                print(f"[{i}/{total}] ERROR  {filepath}: {e}")

    print("\n=== Writing Parquet files ===")
    for module in MODULES:
        if not frames[module]:
            print(f"  {module}: no data, skipping")
            continue
        combined = pd.concat(frames[module], ignore_index=True, sort=False)
        combined = _normalise_dtypes(combined)
        out_path = PROCESSED_DATA_DIR / f"{module}.parquet"
        combined.to_parquet(out_path, index=False)
        print(
            f"  {module}: {len(combined):,} rows × {len(combined.columns)} cols"
            f" → {out_path}"
        )


if __name__ == "__main__":
    main()
