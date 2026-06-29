# Data Patch Log

Records post-hoc corrections to canonical variables. Each entry documents what changed, the current sync state between the PostgreSQL database and the source parquet files, and the code that implements the fix.

**DB** = `localhost:5432 / mda`
**Parquet root** = per-module `data/<XX>/processed_data/<xx>_merged.parquet`

---

## Patch Index

| ID | Date | Module | Variable(s) | DB | Parquet | Code |
|----|------|--------|-------------|-----|---------|------|
| P01 | 2026-06-29 | WM | `woman_age` → `woman_age` + `woman_age_group` | ✅ | ⚠️ partial | `MICS-WM/src/patch_woman_age.py` |

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

### Parquet status: ⚠️ Partial

`wm_merged.parquet` was patched for the `woman_age` column (1-7 cleared to NaN) and `woman_age_group` added for the 83 WB2-source datasets. **The 184 WAGE-source datasets have `woman_age_group = NULL` in the parquet** because the merge pipeline discarded WAGE due to `duplicate_needs_review` in the dedup step.

**To fully fix the parquet**, the pipeline must be re-run with corrected alignment:
1. In `alignment_v2.yaml`: remap `WAGE` → `woman_age_group`, keep `WB2` → `woman_age`
2. Update affected `questionnaire_dedup_v2/<dataset>/dup.yaml` decisions
3. Re-run `merge_wm_to_parquet.py`
4. Re-run `upload_wm_to_postgres.py`

### Code

`MICS-WM/src/patch_woman_age.py`

- `patch_parquet()` — transforms the parquet in-place (DB-independent, safe to re-run)
- `reupload_final()` — drops and recreates `final_WM_MICS` from patched parquet
- `update_ind_que()` — updates `ind_que_WM_MICS` (renames WAGE rows, inserts derived rows)
