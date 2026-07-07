# Data Patch Log

Records post-hoc corrections to canonical variables. Each entry documents what changed, the current sync state between the PostgreSQL database and the source parquet files, and the code that implements the fix.

**DB** = `localhost:5432 / mda`
**Parquet root** = per-module `data/<XX>/processed_data/<xx>_merged.parquet`

---

## Patch Index

| ID | Date | Module | Variable(s) | DB | Parquet | Code |
|----|------|--------|-------------|-----|---------|------|
| P01 | 2026-06-29 | WM | `woman_age` → `woman_age` + `woman_age_group` | ✅ | ✅ | `MICS-WM/src/patch_woman_age.py` |
| P02 | 2026-07-01 | WM | `education_level_harmonized` (ISCED 4-level) | ✅ | ✅ | `MICS-WM/src/patch_education_harmonized.py` |
| P03 | 2026-07-01 | CH | `mother_education_harmonized` (ISCED 4-level) | ✅ | ✅ | `MICS-CH/src/patch_mother_education_harmonized.py` |
| P04 | 2026-07-01 | WM | `media_tv_frequency_harmonized` (4-level freq) | ✅ | ✅ | `MICS-WM/src/patch_media_tv_harmonized.py` |
| P05 | 2026-07-01 | WM | `media_radio_frequency_harmonized` (4-level freq) | ✅ | ✅ | `MICS-WM/src/patch_media_frequency_harmonized.py` |
| P06 | 2026-07-01 | WM | `media_newspaper_frequency_harmonized` (4-level freq) | ✅ | ✅ | `MICS-WM/src/patch_media_frequency_harmonized.py` |
| P07 | 2026-07-04 | CH | `child_age_months` (year-coded→NULL) + `child_age_years` (all datasets) | ✅ | ✅ | `MICS-CH/src/patch_child_age.py` |

---

## P01 — Split `woman_age` into actual age and age group

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`)

### Problem

The canonical variable `woman_age` merged two incompatible source variables:

| Raw column | Values | Meaning |
|------------|--------|---------|
| `WAGE` | 1–7 | Age group (1=15-19, 2=20-24, …, 7=45-49) |
| `WB2` | 15–49 | Actual age in years |

Because the merge pipeline's dedup marked these as `duplicate_needs_review`, the merged parquet only retained WB2 (actual age) for ~83 datasets and set WAGE-source datasets to NULL.

### Fix

Split into two canonical variables:

| Variable | Source | Values | Coverage |
|----------|--------|--------|----------|
| `woman_age` | `WB2` and equivalents | 15–49 (actual age) | ~83 datasets |
| `woman_age_group` | `WAGE` directly; derived from `WB2` where WAGE absent | 1–7 (5-year group) | 83 datasets (derived); WAGE datasets pending pipeline fix |

### DB status: ✅ Done

Applied via SQL directly on `final_WM_MICS`:
- `woman_age_group` column added
- `woman_age_group` populated from `woman_age` where value 1–7 (WAGE), or derived via `FLOOR((age-15)/5)+1` where value 15–49 (WB2)
- `woman_age` set to NULL where value was 1–7 (no actual age available)
- `ind_que_WM_MICS` updated: 532 WAGE-source rows renamed to `woman_age_group`; 9 derived rows inserted for WB2-source datasets

### Parquet status: ✅ Done (2026-06-29)

Full pipeline re-run with corrected `alignment_v2.yaml`:
1. 248 WAGE/agegrp entries moved from `woman_age` → `woman_age_group` in yaml
2. `merge_wm_to_parquet.py` re-run (251 datasets, 2,960,835 rows)
3. `upload_wm_to_postgres.py` re-run
4. Sentinel values (0, 8–10, 97, 99) in `woman_age_group` set to NULL (5,136 rows)

Final coverage: `woman_age_group` non-null = 2,725,292 rows across **244 datasets** (92.2%)

### Code

`MICS-WM/src/patch_woman_age.py`

- `patch_parquet()` — transforms the parquet in-place (DB-independent, safe to re-run)
- `reupload_final()` — drops and recreates `final_WM_MICS` from patched parquet
- `update_ind_que()` — updates `ind_que_WM_MICS` (renames WAGE rows, inserts derived rows)

---

## P02 — Add `education_level_harmonized` (ISCED 4-level)

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`)

### Problem

`education_level` uses incompatible coding schemes across countries:
- 228 datasets: simple sequential codes (0–9), but scale varies (3–9 categories, different meanings)
- 4 datasets: extended codes (10–18, e.g. Sudan, Turks & Caicos)
- 4 datasets: decade codes (20–69, e.g. Azerbaijan, Chad, DRC, Ghana)
- 1 dataset: string value (Cameroon 2006)

Cross-country comparison with raw `education_level` is invalid.

### Fix

New variable `education_level_harmonized` maps all country-specific codes to ISCED 4-level:

| Value | Meaning |
|-------|---------|
| 0 | No education / Pre-primary |
| 1 | Primary (complete or incomplete) |
| 2 | Secondary (lower + upper + vocational) |
| 3 | Higher / Tertiary |
| NULL | Sentinel (96/97/98/99) or unmapped |

### Method

1. `scan_education_labels.py` — scanned all 255 `wm.yaml` files, extracted value labels for the 23 raw columns mapped to `education_level`, auto-classified 2502/2505 label entries using keyword rules (multilingual: EN/FR/ES/PT/RU/ID). Remaining 3 = Cameroon string column (intentionally NaN).
2. Built mapping table: `data/WM/education_harmonize_map.csv` — 1268/1273 (dataset, value) pairs mapped (5 unmapped = undocumented codes in SAV, <700 rows total).
3. `patch_education_harmonized.py` applied mapping via PostgreSQL temp-table JOIN UPDATE (no full re-upload).

### DB status: ✅ Done (2026-07-01)

- `education_level_harmonized DOUBLE PRECISION` column added to `final_WM_MICS`
- 2,579,030 rows updated (87.1% of 2,960,835 total)
- `ind_que_WM_MICS`: 240 derived rows inserted

Coverage: **0=348,077 · 1=880,952 · 2=988,753 · 3=361,248 · NULL=381,805**

### Parquet status: ✅ Done (2026-07-01)

`education_level_harmonized` added to `wm_merged.parquet` (same distribution as DB).

### Code

`MICS-WM/src/scan_education_labels.py` → generates `data/WM/education_label_scan.csv` and `education_harmonize_map.csv`

`MICS-WM/src/patch_education_harmonized.py`
- `patch_parquet()` — adds column to parquet in-place
- `patch_db()` — ALTER + temp-table JOIN UPDATE + ind_que insert

---

## P03 — Add `mother_education_harmonized` (ISCED 4-level)

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`)

### Problem

`mother_education` uses incompatible coding schemes across countries (same root cause as P02 in WM). Primary raw column is `melevel`/`MELEVEL` (219/221 datasets), with `MEDUC` in 2 Indonesia MICS2 datasets. Scale varies: 5–8 categories, different meanings per country/round.

### Fix

New variable `mother_education_harmonized` maps all country-specific codes to ISCED 4-level:

| Value | Meaning |
|-------|---------|
| 0 | No education / Pre-primary |
| 1 | Primary (complete or incomplete) |
| 2 | Secondary (lower + upper + vocational) |
| 3 | Higher / Tertiary |
| NULL | Sentinel ("not in HH", 96/97/98/99) or unmapped |

### Method

1. `scan_mother_education_labels.py` — scanned all ch.yaml files, extracted value labels for `melevel`/`MELEVEL`/`MEDUC`, auto-classified 1242/1243 label entries using multilingual keyword rules. 1 remaining = intentional sentinel.
2. Built mapping table: `data/CH/mother_education_harmonize_map.csv` — 874 valid (dataset, value) pairs mapped.
3. `patch_mother_education_harmonized.py` applied mapping via PostgreSQL temp-table JOIN UPDATE (no full re-upload). Key difference from P02: `mother_education` is `DOUBLE PRECISION` in DB (not TEXT), so temp table and JOIN use numeric matching.

### DB status: ✅ Done (2026-07-01)

- `mother_education_harmonized DOUBLE PRECISION` column added to `final_CH_MICS`
- 1,508,391 rows updated (89.6% of 1,684,203 total)
- `ind_que_CH_MICS`: 221 derived rows inserted

Coverage: **0=538,045 · 1=417,673 · 2=435,778 · 3=116,895 · NULL=175,812**

### Parquet status: ✅ Done (2026-07-01)

`mother_education_harmonized` added to `ch_merged.parquet` (same distribution as DB).

### Code

`MICS-CH/src/scan_mother_education_labels.py` → generates `data/CH/mother_education_label_scan.csv` and `mother_education_harmonize_map.csv`

`MICS-CH/src/patch_mother_education_harmonized.py`
- `patch_parquet()` — adds column to parquet in-place
- `patch_db()` — ALTER + temp-table JOIN UPDATE + ind_que insert
