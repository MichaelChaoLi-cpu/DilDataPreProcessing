"""
P08 step 2 — Extract missing grade columns from raw SAVs into the merged parquet,
and append the corresponding entries to alignment_v2.yaml.

Consumes:  data/<MOD>/grade_mapping_gap_scan.csv   (from scan_missing_grade_mappings.py)
Patches:   data/<MOD>/processed_data/<mod>_merged.parquet
           data/<MOD>/alignment_v2.yaml            (backup written alongside)
Reports:   data/<MOD>/grade_patch_report.csv       (per-column outcome)

Row alignment safety: merge_*_to_parquet.py preserves SAV row order per dataset
with no filtering, so values are assigned by position after two checks:
  1. SAV row count == parquet block row count
  2. an already-mapped reference column agrees >= 99% between SAV and parquet

Usage:
  python patch_grade_mappings.py wm [--dry-run]
  python patch_grade_mappings.py hl [--dry-run]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import yaml

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from config import RAW_DATA_DIR  # noqa: E402

MODULES = {
    "wm": {
        "root": _PROJECT_ROOT / "MICS-WM" / "data" / "WM",
        "parquet": _PROJECT_ROOT / "MICS-WM" / "data" / "WM" / "processed_data" / "wm_merged.parquet",
        "sav_stem": "wm",
        "grade_canonical": "education_grade",
        "completed_canonical": "education_grade_completed",
        "measure_type": "woman_background",
    },
    "hl": {
        "root": _PROJECT_ROOT / "MICS-HL" / "data" / "HL",
        "parquet": _PROJECT_ROOT / "MICS-HL" / "data" / "HL" / "processed_data" / "hl_merged.parquet",
        "sav_stem": "hl",
        "grade_canonical": "highest_grade_completed",
        "completed_canonical": "ever_completed_grade",
        "measure_type": "household_member_background",
    },
}

# ---------------------------------------------------------------------------
# Manual resolutions from P08-1 review (dataset, column) — see DATA_PATCH_LOG P08
# ---------------------------------------------------------------------------

# Verified by SAV value inspection: include despite ambiguous name/label
FORCE_INCLUDE: set[tuple[str, str]] = {
    ("Central African Republic 2000 MICS_Datasets", "WI4AD"),   # grade 1-7
    ("Lesotho_MICS6_datasets", "WB7C"),                          # y/n completion
    ("Mongolia_MICS5_Datasets", "WB4A"),                         # y/n completion
    ("Nepal MICS6 Datasets", "ED5Ba"),                           # within-level grade
    ("Kyrgyzstan MICS 2005-06 SPSS Datasets", "ed3b"),           # MICS3 attainment
    ("Mozambique MICS 2008 Datasets", "ED3B"),                   # MICS3 attainment
}

# Verified exclusions
FORCE_EXCLUDE: set[tuple[str, str]] = {
    # compound level*100+grade; within-level ED3B exists in the same datasets
    ("Central African Republic MICS 2006 SPSS Datasets", "ED3"),
    ("Cote d'Ivoire 2006 MICS_Datasets", "ED3"),
    # cumulative class 0-14 (Nepal-specific); ED5Ba carries within-level grade
    ("Nepal MICS6 Datasets", "ED5B"),
    # mixed plain/decade coding, no reliable decode rule (0-6 plain + 11-33 + 42×188)
    ("Chad 2000 MICS_Datasets", "ED16B"),
    ("Chad 2000 MICS_Datasets", "ED20B"),
}

# MICS3-era HL ED6B is current-school-year grade, never attainment
EXCLUDE_COLNAMES = {"ED6B"}

# Compound level*10+grade coding, verified by value inspection (10-16/20-27/30-35):
# decode grade = value % 10 before storing
DECODE_MOD10: set[tuple[str, str]] = {
    ("Cameroon_MICS5_Datasets", "WB5"),    # WM
    ("Cameroon_MICS5_Datasets", "ED4B"),   # HL
}

GRADE_SENTINELS = {77, 88, 90, 94, 95, 96, 97, 98, 99}
COMPLETED_VALID = {1, 2, 7, 8, 9, 97, 98, 99}


def find_sav(folder: Path, stem: str) -> Path | None:
    exact = folder / f"{stem}.sav"
    if exact.exists():
        return exact
    other = ("hh", "hl", "ch", "bh", "mn", "wm")
    cands = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".sav"
        and (p.stem.lower().endswith(stem) or p.stem.lower().startswith(stem))
        and not any(p.stem.lower().endswith(q) for q in other if q != stem)
    ]
    return cands[0] if len(cands) == 1 else None


def sanity_check(series: pd.Series, kind: str) -> tuple[bool, str]:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) == 0:
        return False, "all null/non-numeric"
    if kind == "grade":
        substantive = vals[~vals.isin(GRADE_SENTINELS)]
        if len(substantive) == 0:
            return False, "only sentinel values"
        # tolerate stray data-entry garbage (<0.5% of substantive rows)
        out_frac = ((substantive < 0) | (substantive > 30)).mean()
        if out_frac > 0.005:
            return False, (f"out of range: {substantive.min()}–{substantive.max()} "
                           f"({out_frac:.1%} outside 0–30)")
    else:  # completed
        bad = vals[~vals.isin(COMPLETED_VALID)]
        if len(bad) / len(vals) > 0.01:
            return False, f"non-y/n values: {sorted(set(bad))[:8]}"
    return True, "ok"


def pick_reference_column(align_entries: list[dict], sav_cols: list[str],
                          pq_cols: set[str]) -> tuple[str, str] | None:
    """Pick (canonical, raw_col) present in both parquet and SAV for row-order check."""
    sav_lower = {c.lower(): c for c in sav_cols}
    for e in align_entries:
        canonical = e["canonical_varname"]
        raw = (e.get("column_in_raw_sav") or "")
        if e.get("source_kind") == "derived":
            continue
        if canonical in pq_cols and raw.lower() in sav_lower:
            return canonical, sav_lower[raw.lower()]
    return None


def main() -> None:
    mod_key = sys.argv[1].lower()
    dry_run = "--dry-run" in sys.argv
    mod = MODULES[mod_key]
    root = mod["root"]

    # --- load work list -----------------------------------------------------
    scan = pd.read_csv(root / "grade_mapping_gap_scan.csv")
    work = scan[scan.status == "MISSING"].copy()

    def decide(row) -> bool:
        key = (row.dataset_name, row.column_in_raw_sav)
        if key in FORCE_INCLUDE:
            return True
        if key in FORCE_EXCLUDE:
            return False
        if row.column_in_raw_sav.upper() in EXCLUDE_COLNAMES:
            return False
        if row.needs_review:
            return False  # unresolved review rows stay out
        return True

    work["include"] = work.apply(decide, axis=1)
    dropped = work[~work.include]
    work = work[work.include]
    print(f"work list: {len(work)} columns in {work.dataset_name.nunique()} datasets "
          f"(dropped by resolution: {len(dropped)})")

    # --- load parquet + alignment -------------------------------------------
    print(f"loading {mod['parquet']} ...")
    pq = pd.read_parquet(mod["parquet"])
    ds_index: dict[str, np.ndarray] = {
        ds: idx.values for ds, idx in pq.groupby("dataset_name").groups.items()
    }

    with open(root / "alignment_v2.yaml", encoding="utf-8") as f:
        alignment = yaml.safe_load(f)
    align_by_ds: dict[str, list[dict]] = {}
    for canonical, entries in alignment.items():
        for e in entries:
            align_by_ds.setdefault(e["dataset_name"], []).append(e)

    # template entries for new yaml rows
    def template(canonical: str) -> dict:
        base = alignment.get(canonical, [{}])
        return base[0] if base else {}

    report_rows = []
    new_yaml_entries: dict[str, list[dict]] = {}
    patched_cols = 0

    for ds, grp in work.groupby("dataset_name"):
        if ds not in ds_index:
            for _, r in grp.iterrows():
                report_rows.append({**r.to_dict(), "outcome": "dataset not in parquet"})
            continue

        sav_path = find_sav(RAW_DATA_DIR / ds, mod["sav_stem"])
        if sav_path is None:
            for _, r in grp.iterrows():
                report_rows.append({**r.to_dict(), "outcome": "no SAV found"})
            continue

        _, meta = pyreadstat.read_sav(str(sav_path), metadataonly=True)
        sav_cols = meta.column_names
        sav_lower = {c.lower(): c for c in sav_cols}

        block_idx = ds_index[ds]
        ref = pick_reference_column(align_by_ds.get(ds, []), sav_cols, set(pq.columns))

        want = [sav_lower.get(c.lower()) for c in grp.column_in_raw_sav]
        want = [c for c in want if c]
        read_cols = want + ([ref[1]] if ref and ref[1] not in want else [])
        if not want:
            for _, r in grp.iterrows():
                report_rows.append({**r.to_dict(), "outcome": "column not in SAV"})
            continue

        sav_df, sav_meta = pyreadstat.read_sav(str(sav_path), usecols=read_cols)

        # check 1: row counts
        if len(sav_df) != len(block_idx):
            for _, r in grp.iterrows():
                report_rows.append({**r.to_dict(),
                    "outcome": f"row mismatch sav={len(sav_df)} pq={len(block_idx)}"})
            continue

        # check 2: reference column agreement
        if ref is not None:
            pq_ref = pd.to_numeric(pq.loc[block_idx, ref[0]], errors="coerce").values
            sv_ref = pd.to_numeric(sav_df[ref[1]], errors="coerce").values
            both = ~(pd.isna(pq_ref) | pd.isna(sv_ref))
            agree = (pq_ref[both] == sv_ref[both]).mean() if both.sum() > 0 else np.nan
            if both.sum() > 0 and agree < 0.99:
                for _, r in grp.iterrows():
                    report_rows.append({**r.to_dict(),
                        "outcome": f"ref column {ref[0]} agreement {agree:.3f} < 0.99"})
                continue

        # assign values per target canonical
        for _, r in grp.iterrows():
            actual = sav_lower.get(r.column_in_raw_sav.lower())
            if actual is None:
                report_rows.append({**r.to_dict(), "outcome": "column not in SAV"})
                continue
            series = sav_df[actual]
            if (ds, r.column_in_raw_sav) in DECODE_MOD10:
                dec = pd.to_numeric(series, errors="coerce")
                series = dec.where(~dec.between(10, 39), dec % 10)
            ok, why = sanity_check(series, r.kind)
            if not ok:
                report_rows.append({**r.to_dict(), "outcome": f"sanity fail: {why}"})
                continue

            target = r.target_canonical
            if target not in pq.columns:
                pq[target] = np.nan
            existing = pq.loc[block_idx, target]
            vals = pd.to_numeric(series, errors="coerce").values
            fill = existing.isna().values
            col_pos = pq.columns.get_loc(target)
            row_pos = pq.index.get_indexer(block_idx[fill])
            pq.iloc[row_pos, col_pos] = vals[fill]
            n_new = int((~pd.isna(vals[fill])).sum())
            patched_cols += 1
            report_rows.append({**r.to_dict(), "outcome": f"patched ({n_new} values)"})

            tmpl = template(target)
            new_yaml_entries.setdefault(target, []).append({
                **{k: tmpl.get(k) for k in tmpl},
                "canonical_varname": target,
                "dataset_name": ds,
                "column_in_raw_sav": actual,
                "column_label_in_english": r.column_label,
                "source_kind": "explicit",
                "confidence": "high",
                "needs_review": False,
                "measure_type": mod["measure_type"],
                "derivation": None,
            })

    # --- write outputs -------------------------------------------------------
    report = pd.DataFrame(report_rows)
    report_path = root / "grade_patch_report.csv"
    report.to_csv(report_path, index=False)
    outcome_summary = report.outcome.str.replace(r" \(.*", "", regex=True).value_counts()
    print(f"\noutcomes:\n{outcome_summary.to_string()}")
    print(f"report: {report_path}")

    if dry_run:
        print("\n--dry-run: no files written.")
        return

    for canonical, entries in new_yaml_entries.items():
        alignment.setdefault(canonical, []).extend(entries)
    yaml_path = root / "alignment_v2.yaml"
    shutil.copy2(yaml_path, yaml_path.with_suffix(".yaml.bak_p08"))
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(alignment, f, allow_unicode=True, sort_keys=True)
    print(f"alignment updated (+{sum(len(v) for v in new_yaml_entries.values())} entries); "
          f"backup: {yaml_path.name}.bak_p08")

    pq.to_parquet(mod["parquet"], index=False)
    print(f"parquet saved: {mod['parquet']}")

    for canonical in (mod["grade_canonical"], mod["completed_canonical"]):
        if canonical in pq.columns:
            nn = pq[canonical].notna().sum()
            nds = pq.loc[pq[canonical].notna(), "dataset_name"].nunique()
            print(f"  {canonical}: non-null {nn:,} rows across {nds} datasets")


if __name__ == "__main__":
    main()
