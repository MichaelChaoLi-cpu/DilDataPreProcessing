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
| P08 | 2026-07-10 | WM+HL | education grade backfill: `education_grade`/`education_grade_completed` (WM), `highest_grade_completed`/`ever_completed_grade` (HL) | ✅ | ✅ | `MICS-WM/src/scan_missing_grade_mappings.py`, `MICS-WM/src/patch_grade_mappings.py` |
| P09 | 2026-07-11 | WM+HL+CH | `education_years`/`education_years_estimated` (WM, HL), `mother_education_years`/`mother_education_years_estimated` (CH) | ✅ | ✅ | `MICS-WM/src/scan_education_level_fine.py`, `build_school_duration_table.py`, `patch_education_years.py`, `sync_p09_to_db.py` |
| P10 | 2026-07-14 | HH | `sex_of_household_head` cleanup (coding verified, wrong source fixed, HL backfill) | ✅ | ✅ | `MICS-HH/src/patch_sex_of_household_head.py` |
| P11 | 2026-07-27 | WM+HL+CH+HH | `CP_` naming convention: duplicate every P01-P10 column as `CP_<name>` (carefully processed) | ✅ | ✅ | `src/patch_cp_prefix.py` |
| P12 | 2026-07-28 | WM | `CP_age_at_first_union` (valid 8-49) + Mozambique 2008 recovered from raw `AGEM` | ✅ | ✅ | `MICS-WM/src/patch_age_first_union.py`, `scan_age_first_union.py` |
| P13 | 2026-07-28 | WM | `CP_children_ever_born` (valid 0-20) + 9 datasets recovered from raw CEB columns | ✅ | ✅ | `MICS-WM/src/patch_children_ever_born.py`, `scan_children_ever_born.py` |
| P14 | 2026-07-28 | CH | `CP_bmi_for_age_zscore` (clean \|z\|≤6 + WHO-2006 derivation, 33 datasets) | ✅ | ✅ | `MICS-CH/src/patch_bmi_for_age.py` |
| P15 | 2026-07-29 | CH | `CP_diarrhea_last_2_weeks` (per-dataset label harmonization 1=Yes/0=No) + Congo_MICS5 source fix CA2→CA1 | ✅ | ✅ | `MICS-CH/src/patch_diarrhea.py` |
| P16 | 2026-07-29 | CH | `CP_fever_last_2_weeks` (per-dataset label harmonization 1=Yes/0=No) + 9 datasets recovered from unmapped/mis-mapped `ML1`/`CA6AA`/`PCA6` | ✅ | ✅ | `MICS-CH/src/patch_fever.py` |
| P17 | 2026-07-30 | CH | `CP_cough_last_2_weeks` (per-dataset label harmonization 1=Yes/0=No) + 5 datasets recovered from unmapped `CI6`/`CA7`/`CA5` | ✅ | ✅ | `MICS-CH/src/patch_cough.py` |
| P18 | 2026-07-30 | WM | `CP_first_birth_year` (Gregorian CE; CMC-derived + Buddhist/Bikram-Sambat calendar conversion); coverage 116→190 | ✅ | ✅ | `MICS-WM/src/patch_first_birth_year.py` |
| P19 | 2026-07-30 | WM | `CP_age_at_first_birth` (+`_estimated`) derived from CMC diff (calendar-agnostic) with year-method fallback; 167 datasets | ✅ | ✅ | `MICS-WM/src/patch_age_at_first_birth.py` |
| P20 | 2026-07-30 | WM | `CP_place_of_delivery` (harmonized 5-category via value labels) + 34 datasets recovered from unmapped `MN18`/`MN20`/`MN8`/`NN3` | ✅ | ✅ | `MICS-WM/src/patch_place_of_delivery.py` |
| P21 | 2026-07-31 | CH | `CP_child_sample_weight` (scale-harmonized: outlier datasets normalized to mean 1) + 30 datasets recovered from unmapped `chweight` | ✅ | ✅ | `MICS-CH/src/patch_child_sample_weight.py` |
| P22 | 2026-08-01 | WM | `CP_received_anc` (harmonized binary 1/0) + `CP_received_anc_derived`; 10 datasets recovered from unmapped `MN1`/`MN2`, 58 MICS2/MICS3-era datasets derived from the `MN2` provider checklist; coverage 158→221 | ✅ | ✅ | `MICS-WM/src/patch_received_anc.py`, `scan_received_anc.py` |
| P23 | 2026-08-01 | WM | `CP_first_trimester_anc` (1 = first ANC ≤3 months/≤13 weeks) + `CP_first_trimester_anc_derived`; derived from first-visit timing, 41 datasets recovered from unmapped `MN2AN`/`MN2AAN`/`MN4AN`/… ; coverage 74→115 | ✅ | ✅ | `MICS-WM/src/patch_first_trimester_anc.py` |
| P24 | 2026-08-02 | HH+WM+CH+HL | `CP_area_type` (1 Urban / 2 Rural / 3 Refugee-camp) — harmonized area of residence in all 4 tables via per-dataset value-label classification; contaminated/unaligned datasets recovered from HH6 (guarded), members filled via household join; HH 241 / WM 225 / CH 229 / HL 213 | ✅ | ✅ | `src/patch_area_type.py` |
| P25 | 2026-08-02 | HH+WM+CH+HL | `CP_survey_year` + `CP_survey_month` — Gregorian interview year/month in all 4 tables; Thailand Buddhist-Era (−543) and Nepal Bikram-Sambat (embedded BS calendar) converted; cmc cross-check year 100 %/month 99.9 %; HH 242 / WM 244 / CH 243 / HL 210 | ✅ | ✅ | `src/patch_survey_date.py` |
| P26 | 2026-08-02 | WM | `CP_woman_age` rebuilt to REAL age (was the 5-yr group code for 153 datasets) via HL-listing join; `CP_woman_birth_year` (+`_estimated`) Gregorian, exact from birth-date else survey_year−age; CP_woman_age 216 ds, CP_woman_birth_year 245 ds | ✅ | ✅ | `MICS-WM/src/patch_woman_birth_year.py` |
| P27 | 2026-08-04 | HH+WM+CH+HL | `CP_country`/`CP_country_code` (ISO3) + `CP_subnational`/`CP_subnational_matched` — dataset→country.json (255/255) & region-code SAV label→state.json admin-1 names (fuzzy≤2, raw fallback); country all rows, subnational 164–191 (region+province admin-1) + CP_district (admin-2, 26–34 ds); dict in `_geo_dict` | ✅ | ✅ | `src/patch_geolocation.py` |
| P28 | 2026-08-05 | WM | `CP_time_to_breastfeed_hours` + `CP_early_initiation_breastfeeding` (<=1h) + `CP_breastfed_within_24h` — early initiation of breastfeeding; unit by label; 36 datasets recovered from unmapped non-English `MN25/MN37/MN13` pairs; 154→190 | ✅ | ✅ | `MICS-WM/src/patch_breastfeed_initiation.py` |
| P29 | 2026-08-05 | CH | `CP_ever_breastfed` (1=Yes/0=No) — harmonized 205 + recovered 28 datasets whose ever-breastfed column (BF1/BD2) was unmapped due to non-English labels; 205→233 | ✅ | ✅ | `MICS-CH/src/patch_ever_breastfed.py` |
| P30 | 2026-08-05 | CH | `CP_still_breastfeeding` (1=Yes/0=No) — harmonized 240 + recovered 1 (DR Congo 2001); 240→241, near ceiling | ✅ | ✅ | `MICS-CH/src/patch_still_breastfeeding.py` |
| P46 | 2026-08-14 | CH | `CP_fed_vitamin_a_fruits_yesterday` — ripe mango/papaya/apricot/melon etc. (1/0) from raw BD8G; Pakistan-KP reads BD8F; 65 → 108 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_vitamin_a_fruit.py` |
| P45 | 2026-08-14 | CH | `CP_fed_dark_green_leafy_vegetables_yesterday` — spinach/broccoli/kale etc. (1/0) from raw BD8F; multilingual green-leafy recovery; 92 → 107 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_green_leafy.py` |
| P44 | 2026-08-14 | CH | `CP_fed_vitamin_a_vegetables_yesterday` — pumpkin/carrots/squash/orange sweet potato (1/0) from raw BD8D; fixes Fiji/Georgia multi-source; 100 → 107 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_vitamin_a_veg.py` |
| P43 | 2026-08-14 | CH | `CP_fed_eggs_yesterday` — eggs (1/0) from raw BD8K; Pakistan-KP reads BD8I (its BD8K=legumes); 101 → 107 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_eggs.py` |
| P42 | 2026-08-14 | CH | `CP_fed_fish_seafood_yesterday` — fish/seafood (1/0) from raw BD8L; Pakistan-KP reads BD8J (its BD8L=cheese), Guyana BD8L not BD7C broth; 100 → 108 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_fish.py` |
| P41 | 2026-08-14 | CH | `CP_fed_meat_poultry_yesterday` — meat/poultry (1/0) from raw BD8J; Pakistan-KP reads BD8H (its BD8J=fish), Vietnam BF9-broth excluded; 102 → 108 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_meat_poultry.py` |
| P40 | 2026-08-14 | CH | `CP_fed_organ_meat_yesterday` — liver/kidney/heart/organ meat (1/0) from raw BD8I; excludes Pakistan-KP BD8I=eggs mislabel; 100 → 107 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_organ_meat.py` |
| P39 | 2026-08-14 | CH | `CP_fed_cheese_other_dairy_yesterday` — cheese/other milk food (1/0) REBUILT from raw BD8N; fixes dd_dairy contamination (BD8A yogurt / BD7P-Q); 54 → 112 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_cheese.py` |
| P38 | 2026-08-14 | CH | `CP_fed_yogurt_yesterday` — drank/ate yogurt (1/0) REBUILT from raw (OR of BD8A + BD7F yogurt-drink); fixes infant_fed_yogurt_yesterday times-count (3/4/7) + cheese contamination; 148 → 155 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_yogurt.py` |
| P37 | 2026-08-13 | CH | `CP_fed_pulses_nuts_seeds_yesterday` — beans/peas/lentils/nuts (1/0) REBUILT from raw BD8M; fixes dd_legumes_nuts contamination (BD8G fruit / BD7D formula / IM8-IM12 vaccine); 112 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_pulses_nuts.py` |
| P36 | 2026-08-13 | CH | `CP_fed_roots_tubers_plantains_yesterday` — ate white roots/tubers/plantains (1/0) from raw BD8E; harmonized 94 + recovered 19; 94 → 113 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_roots_tubers.py` |
| P35 | 2026-08-13 | CH | `CP_fed_grain_based_fortified_baby_food_yesterday` — ate fortified baby food (cerelac etc.) 1/0 from raw BD8B; harmonized 107 + recovered 7; 107 → 114 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_fortified_baby_food.py` |
| P34 | 2026-08-13 | CH | `CP_fed_grains_yesterday` — ate grains yesterday (1/0) from raw BD8C only; harmonized 55 + recovered 59 unmapped non-English BD8C; 55 → 114 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_grains_yesterday.py` |
| P33 | 2026-08-13 | CH | `CP_child_age_months` — rebuilt from raw CAGE + interview−birth date (CMC); coverage 42 → 248 datasets; guarded (0-59 scale + household/age-year alignment) | ✅ | ✅ | `MICS-CH/src/patch_child_age_months.py` |
| P32 | 2026-08-05 | CH | `CP_breastfeeding_status` — 3-category current breastfeeding status (0 never / 1 weaned / 2 currently), derived from `CP_ever_breastfed` + `CP_still_breastfeeding`; 241 datasets | ✅ | ✅ | `MICS-CH/src/patch_breastfeeding_status.py` |
| P31 | 2026-08-05 | CH | `CP_fed_milk_yesterday` — re-derived (drank formula OR animal milk); fixes systematic MICS6 mis-alignment (BD8N=cheese mapped to milk) + juice/fish; 50 datasets' animal-milk BD7E recovered from SAV; 227 datasets | ✅ | ✅ | `MICS-CH/src/patch_fed_milk_yesterday.py` |

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

---

## P08 — Backfill unmapped education grade variables (WM + HL)

**Modules:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`), HL (`final_HL_MICS`, `ind_que_HL_MICS`, `hl_merged.parquet`)

### Problem

MICS raw SAVs record educational attainment as two questions: highest **level** attended plus highest **grade within that level** (WM: `WB5`/`WB6B`/`WM12`; HL: `ED3B`/`ED4B`/`ED5B`; MICS2: `ED16B` "Highest school grade"). The original alignment missed the grade column in many datasets — `education_grade` covered only 150/240 WM datasets and `highest_grade_completed` only 155/225 HL datasets, although the raw data exists. This blocks constructing years-of-schooling (planned P09).

### Fix

1. `scan_missing_grade_mappings.py {wm|hl}` — scans all raw yaml metadata for attainment-grade and grade-completion columns not mapped in `alignment_v2.yaml`. Multilingual name+label rules (EN/FR/ES/PT); yes/no value labels distinguish completion flags from grade numbers. Output: `data/<MOD>/grade_mapping_gap_scan.csv`.
2. Manual review of ambiguous columns by SAV value inspection (see `FORCE_INCLUDE`/`FORCE_EXCLUDE` in patch script). Key decisions:
   - MICS3-era HL `ED6B` = current-school-year grade, never attainment → excluded globally
   - Cameroon MICS5 `WB5`/`ED4B` use compound level×10+grade coding → decoded `value % 10`
   - Chad 2000 `ED16B`/`ED20B` mixed coding with no reliable decode → excluded, documented
   - Nepal MICS6 `ED5B` is cumulative class 0–14 → excluded in favour of within-level `ED5Ba`
   - CAR/CIV 2006 compound `ED3` → excluded (within-level `ED3B` exists in same datasets)
3. `patch_grade_mappings.py {wm|hl}` — extracts columns from raw SAVs and assigns by row position into the merged parquet. Safety checks per dataset: SAV row count == parquet block count, and an already-mapped reference column must agree ≥99%. Value sanity checks: grades 0–30 (+ sentinels 77/88/90/94–99, ≤0.5% stray garbage tolerated), completion flags ⊆ {1,2,7,8,9,97,98,99}. Outcome per column: `data/<MOD>/grade_patch_report.csv`.
4. `alignment_v2.yaml` updated (+134 WM, +98 HL entries; backups `alignment_v2.yaml.bak_p08`) so future pipeline re-runs keep the mappings.

⚠️ **Semantics caveat for consumers**: `education_grade`/`highest_grade_completed` mix two codings across datasets — *grade within level* (standard MICS) and *cumulative class count* (some francophone MICS2/3, e.g. CAR, Mauritania, Senegal-style "dernière classe achevée"). Per-dataset disambiguation happens in P09 (planned) by cross-checking against the education level variable. Do not compare raw grade values across datasets without that step.

### DB status: ✅ Done (2026-07-10)

Full re-upload from patched parquets (drop + recreate + COPY):
- `final_WM_MICS`: `education_grade` non-null 1,297,190 → **2,046,820** (150 → 244 datasets); `education_grade_completed` → 634,242 (65 datasets)
- `final_HL_MICS`: `highest_grade_completed` non-null 5,397,778 → **7,510,643** (155 → 225 datasets); `ever_completed_grade` → 1,515,676 (49 datasets)
- `ind_que_WM_MICS` rebuilt from yaml (+134 explicit rows); 530 patch-derived rows (P01/P02/P04–P06) snapshotted and re-inserted (`data/WM/ind_que_derived_snapshot_p08.csv`)
- `ind_que_HL_MICS` rebuilt from yaml (+98 explicit rows)
- Verified previous patch columns intact after re-upload (`education_level_harmonized` 2,579,030 · `media_tv_frequency_harmonized` 1,128,967 · `woman_age_group` 2,725,292)

### Parquet status: ✅ Done (2026-07-10)

Same distributions as DB.

### Known gaps

- Angola 2001, Bosnia and Herzegovina MICS2 2000, Uzbekistan MICS2 2000 (WM), Angola 2001 (HL): datasets absent from the merged parquets entirely (pre-existing pipeline gap, out of P08 scope)
- Chad 2000 grade columns excluded (mixed coding, see above)
- Truly no grade data anywhere: Indonesia MICS2 2000, Trinidad and Tobago 2000, Zambia 1999

### Code

`MICS-WM/src/scan_missing_grade_mappings.py` (parameterized wm|hl)
`MICS-WM/src/patch_grade_mappings.py` (parameterized wm|hl, `--dry-run` supported)

---

## P09 — Years-of-schooling variables (WM + HL + CH)

**Modules:** WM, HL, CH (`final_*_MICS`, `ind_que_*_MICS`, `*_merged.parquet`)

### Problem

The harmonized education variables (P02/P03) collapse attainment into 4 ISCED levels, losing within-level variation. Raw MICS data records level + grade-within-level, from which years of schooling can be constructed — but codings are country- and round-specific.

### Construction

```
education_years = base(fine_level, school-system durations at school-entry year)
                + grade_within_level
```

- **Fine level scale** (`education_level_fine_map.csv`, WM + HL): 0 none/pre-primary · 1 primary · 2 secondary-combined · 21 lower secondary · 22 upper secondary · 3 higher · −1 sentinel. Built by `scan_education_level_fine.py` (multilingual keywords + manual overrides for Pakistan matric→22, Moldova lyceum→22, Bhutan middle secondary→22, Soviet professional tracks→22, and ~20 typo/country-specific labels).
- **Durations** (`school_durations.csv`): WB API `SE.PRM.DURS`/`SE.SEC.DURS.LO`/`SE.SEC.DURS.UP` per country-year 1970–2023; Kosovo injected manually (4+4+4 → 5+4+3 at the 2002/03 reform). Looked up at each person's school-entry year = survey_year − age + 6 (dataset median age when missing). Fallback: nearest year, then 6-3-3.
- **Dataset→ISO3** (`dataset_iso3_map.csv`): all 252 datasets matched (manual keys + unicode normalization).
- **Per-dataset coding auto-detection** (in `patch_education_years.py`):
  - *compound* (level×10+grade, e.g. Zimbabwe/Lao/Nigeria/Samoa, 23 WM + 8 HL datasets): ≥50% of grades in 10–39 → decode `grade % 10`
  - *cumulative* (continuous class count, e.g. Soviet systems, 120 WM + 100 HL datasets): ≥10% of school-level grades exceed level duration + 1 → `years = grade` directly; tertiary rows get base+2 estimated
  - *attended vs completed*: label-based; attended-coded grades reduced by 1 when the completion flag says No
  - *conflicting level columns* (e.g. Vanuatu 2007): candidate map chosen by Jaccard match between observed parquet codes and each raw column's yaml codes
- **Estimates** (`*_estimated = 1`): grade missing but level known → base + level_duration/2 (higher → base+2). "Never attended school" → 0 years, exact.
- Years capped at 25.

### CH linkage (mother_education_years)

Three-tier source, in priority order:
1. **WM link** (mother's own interview): `(dataset, cluster_number, hh_number, line_number)` via `mother_caretaker_line_number` — 1,195,436 rows (73.8%)
2. **HL fallback** (household roster): same key vs HL `line_number` — +155,516 rows (9.6%)
3. **Coarse midpoint** from `mother_education_harmonized` (4-level) with `age_of_mother` entry-year durations — +268,758 rows (16.6%, all flagged estimated)

### Validation

Monotonicity against the ISCED 4-level harmonized variables (exact rows):

| Level | WM mean yrs | CH mean yrs |
|-------|-------------|-------------|
| 0 None | 0.00 | 0.97 |
| 1 Primary | 4.41 | 4.25 |
| 2 Secondary | 7.44 | 8.08 |
| 3 Higher | 14.70 | 13.84 |

No dataset mean > 14.7 (max: Cuba, plausible). Previous outliers fixed during construction: Zimbabwe compound coding (was 20.3 → 9.3), Azerbaijan cumulative (was 15.7 → 11.1), Vanuatu conflicting level columns (was 15.5 → 7.4).

### DB status: ✅ Done (2026-07-11)

Full re-upload of all three finals from patched parquets:
- `final_WM_MICS.education_years` non-null **2,618,569** (88.4%, 241 datasets; estimated 17.9%)
- `final_HL_MICS.education_years` non-null **8,510,070** (72.4%, 216 datasets; estimated 6.2%)
- `final_CH_MICS.mother_education_years` non-null **1,619,710** (96.2%, 246 datasets; estimated 25.7%)
- ind_que: derived rows inserted per module; patch-derived snapshots (WM 530, CH 475) reinserted after rebuild; verified P01–P08 columns intact after re-upload

### Parquet status: ✅ Done (2026-07-11)

Same distributions as DB.

### Known limitations

- Level variable itself unmapped in some datasets (e.g. Cameroon MICS5, Algeria MICS6, Dominican Republic 2000): `education_years` NULL there except never-attended → 0 rows. A future patch could backfill level mappings the same way P08 backfilled grades.
- Vocational/non-standard tracks are approximated by their host level's duration.
- Tertiary years in cumulative-coded datasets are level-midpoint estimates (school grade counts carry no university information).
- `education_years_estimated = 1` rows (level midpoints) should be excluded or dummied in analyses sensitive to measurement error.

### Code

`MICS-WM/src/scan_education_level_fine.py` — fine level classification (wm|hl)
`MICS-WM/src/build_school_duration_table.py` — WB durations + ISO3 map
`MICS-WM/src/patch_education_years.py` — construction (wm|hl|ch, --dry-run)
`MICS-WM/src/sync_p09_to_db.py` — three-table DB sync with ind_que handling

---

## P10 — Clean `sex_of_household_head` (HH)

**Module:** HH (`final_HH_MICS`, `ind_que_HH_MICS`, `hh_merged.parquet`)

### Coding verification

SAV metadata scan of all 247 mapped (dataset, raw column) pairs — multilingual male/female label matching (EN/FR/ES/PT/RU/TR): **coding is uniformly 1 = Male, 2 = Female. No reversals anywhere.** Note: the HH raw yaml metadata does not carry value labels, so verification reads SAV headers directly.

### Problems found & fixed

1. **Mozambique MICS 2008 — wrong source.** `sex_of_household_head` was mapped from `OV3C_1/2/3` ("Sexo" of deceased household members in the orphanhood module, not the head). 13,955 wrong values → NULL; the 3 OV3C entries removed from `alignment_v2.yaml` (backup `.bak_p10`). HL backfill impossible (HL cluster_number entirely NULL there; household_number only has 206 distinct values) → stays NULL.
2. **Sentinel codes** 3/7/9 (105 rows) → NULL.
3. **11 datasets with no mapping** → backfilled from the HL roster where safe:
   - Head = member with `relationship_to_head = 1`; for CAR 2000 (relationship unmapped in HL) head = roster line 1, validated globally at 2,238,349/2,238,367 = 100.0% agreement.
   - Strict key matching on `(dataset, cluster_number, household_number)`: NaN keys and keys duplicated on either side are excluded — a wrong-household match is worse than a missing value.
   - Filled: Cameroon 2006 (9,667) · Côte d'Ivoire 2006 (7,600) · Togo 2006 (6,492) · Montenegro Roma MICS5 (615) · CAR 2000 (13,862, line-1 proxy) = **38,236 rows**. Female shares 0.15–0.25, all plausible.

### Not fixable (documented)

- Niger 2000: `(cluster, household)` keys 100% non-unique in HH → no safe join.
- Kyrgyzstan 2005-06: HL keys entirely unmapped.
- Cameroon 2000, Indonesia MICS2, Iraq 2000, Trinidad & Tobago 2000: absent from `final_HL_MICS`.

### Result

- Value domain now exactly {1, 2, NULL}
- Non-null: 2,526,046 → **2,550,242** (91.9% of 2,774,775) across 248 datasets
- Female-headed share: 23.1% (plausible; verified per dataset — the 45–51% outliers Cuba/Belarus/Argentina/Barbados reflect genuinely high self-declared female headship, not coding errors; Afghanistan 1.1% / Pakistan Sindh 4.7% culturally consistent)

### DB status: ✅ Done (2026-07-14)

Full re-upload from patched parquet. Verified: value domain exactly {1, 2, NULL} (1=1,962,235 · 2=588,007 · NULL=224,533), non-null matches parquet (2,550,242), female share 0.231. `ind_que_HH_MICS`: 46 yaml-derived rows regenerated by rebuild; 12 derived provenance rows inserted for the HL-backfilled datasets.

### Parquet status: ✅ Done (2026-07-14)

### Code

`MICS-HH/src/patch_sex_of_household_head.py`
- `patch_parquet()` — idempotent (resets backfill datasets before refilling); updates alignment yaml
- `patch_db()` — full re-upload + ind_que derived-row snapshot/reinsert + backfill provenance rows

---

## P11 — `CP_` ("carefully processed") column-name convention

**Modules:** WM, HL, CH, HH (all `final_*` + `ind_que_*` tables)

### Motivation

Nothing in a column's *name* distinguished a coarsely-aligned raw variable
(just the SPSS column renamed, sentinels and country-specific codings intact)
from one that a patch had cleaned, split, harmonized, derived, or backfilled.
An analyst reading `education_years` or `sex_of_household_head` could not tell,
from the name alone, that the values are the deliberate product of
post-processing.

### Convention

A column whose name starts with **`CP_`** is the *carefully processed* version
of a variable — its values come from a patch (P01–P10), not a raw rename.
Prefer `CP_` columns for cross-dataset analysis.

**Going forward:** any variable a patch creates or alters gets a `CP_` name.

### What this patch did

Rather than rename (which would break prior projects), P11 **duplicates** each
processed column into a `CP_<name>` copy and **retains the original** unchanged
— so earlier code/projects stay reproducible. The pair holds identical values
today; they diverge only if a future patch revises the `CP_` version.

Retrofitted for the 20 columns touched by P01–P10:

| Module | Columns duplicated as `CP_<name>` |
|--------|-----------------------------------|
| WM | `woman_age`, `woman_age_group`, `education_level_harmonized`, `media_tv_frequency_harmonized`, `media_radio_frequency_harmonized`, `media_newspaper_frequency_harmonized`, `education_grade`, `education_grade_completed`, `education_years`, `education_years_estimated` |
| HL | `highest_grade_completed`, `ever_completed_grade`, `education_years`, `education_years_estimated` |
| CH | `mother_education_harmonized`, `child_age_months`, `child_age_years`, `mother_education_years`, `mother_education_years_estimated` |
| HH | `sex_of_household_head` |

`ind_que_*` provenance rows are mirrored under the `CP_` name so provenance
queries resolve symmetrically.

### DB status: ✅ Done (2026-07-27)

`CP_` columns added to all four `final_*` tables (same type, values copied);
`ind_que_*` CP_ provenance rows mirrored. Column comments regenerated by
`src/build_db_documentation.py` (CP_ comments auto-derived from the base
column's comment); new `_guide` section `cp_prefix` documents the convention.

### Parquet status: ✅ Done (2026-07-27)

`CP_` columns added to all four `processed_data/*_merged.parquet`; pre-patch
snapshots kept as `*.parquet.bak_p11`.

### Code

`src/patch_cp_prefix.py`
- `patch_parquet()` — idempotent; backs up to `.bak_p11`, adds `CP_` copies
- `patch_db()` — idempotent; adds `CP_` columns + copies values + mirrors
  `ind_que_*` provenance rows
- `--verify` flag re-checks CP_ presence and value equality without writing

---

## P12 — `CP_age_at_first_union` (careful clean) + Mozambique 2008 recovery

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`, `alignment_v2.yaml`)

### Problem

`age_at_first_union` mixed valid ages with sentinel codes (97/98/99), zeros,
negatives and implausibly low values (1–7). Separately, 41 datasets had **zero**
coverage. (An apparent "70% of values exceed the woman's own age" was a false
alarm — an artifact of `woman_age` being stored as 5-year group codes 1–7 in
many datasets; compared against real ages, the impossible rate is ~0%.)

### Investigation (scan, no changes): `scan_age_first_union.py`

- **Cross-module backfill is impossible** — marriage history (`age_at_first_union`,
  `ever/currently_married`, `date_marriage_cmc`, `first_union_year/month`,
  `times_married`) is collected **only in the women's questionnaire**. HL/HH/CH
  have none of it.
- Of the 41 fully-missing datasets, **0** have any alternative in-DB source
  (`date_marriage_cmc` / `first_union_year` / `ever_married`).
- Raw-SAV rescan of all 41: only **Mozambique MICS 2008** has an unmapped
  age-at-first-union column (`AGEM` "Idade na 1a união/casamento", and `MA8`).
  The other 40 (mostly MICS2, 2000) never collected it.

### Fix

1. **`CP_age_at_first_union`** — carefully-processed copy keeping only plausible
   ages **8–49**; sentinels, 0, negatives, <8 and >49 → NULL. Ages 8–9 are kept
   (they concentrate in known child-marriage countries — Ghana, Bangladesh,
   Nigeria, Afghanistan, Sierra Leone, CAR — and are genuine). The raw
   `age_at_first_union` is left unchanged (cleaning lives only in the CP_ copy).
   NULL also legitimately marks never-married women.

2. **Mozambique 2008 recovery** — mapped raw `AGEM` → `age_at_first_union`.
   Parquet keys there are broken (cluster_number/line_number all NULL, per P10),
   so rows were aligned **positionally** to the SAV, guarded by a check that
   `hh_number == HH2` for all 15,060 rows (verified 100%). Added to
   `alignment_v2.yaml` (backup `.bak_p12`) so a full rebuild reproduces it.
   14,188 raw values added; ~11,537 survive the 8–49 clean into CP_.

### Result

- `CP_age_at_first_union` valid (8–49): **~1.78M** values across **211** datasets
  (was 210). No out-of-range values remain in the CP_ column.

### DB status: ✅ Done (2026-07-28)

`CP_age_at_first_union` added; whole-table clean UPDATE; Mozambique rows
delete + re-inserted from patched parquet (broken keys preclude keyed UPDATE);
`ind_que_WM_MICS` gained the Mozambique `AGEM` row and mirrored `CP_` provenance
rows. Column comments + `_data_issues` P12 recorded via `build_db_documentation.py`.

### Parquet status: ✅ Done (2026-07-28)

`age_at_first_union` Mozambique-filled; `CP_age_at_first_union` added.
Pre-patch snapshot `wm_merged.parquet.bak_p12`.

### Code

`MICS-WM/src/scan_age_first_union.py` — gap scan (report only)
`MICS-WM/src/patch_age_first_union.py`
- `patch_yaml()` — adds Mozambique `AGEM` mapping
- `patch_parquet()` — guarded positional Mozambique backfill + CP_ clean copy
- `patch_db()` — CP_ column + clean UPDATE + Mozambique delete/re-insert + ind_que
- `--verify` — checks coverage, range, and parquet/DB consistency

---

## P13 — `CP_children_ever_born` (careful clean) + 9-dataset recovery

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`, `alignment_v2.yaml`)

### Problem

`children_ever_born` (CEB) was already very clean (median 2, p99 10, no
negatives) but carried sentinel 99 (2 rows) and rare implausibly-high values
(21–30, 6 rows). Separately, 39 datasets had zero coverage. Minor cross-variable
inconsistencies exist (5,343 rows CEB < children_dead; 3,452 CEB≥1 with
ever_given_birth=no; 391 CEB > age−12) — these are **intentionally left as-is**
(not clearly CEB's fault).

### Investigation (scan, no changes): `scan_children_ever_born.py`

- **Cross-module backfill impossible** — CEB is a women's-questionnaire total.
- **Component derivation rejected** — sum of the six sons/daughters columns
  (living_with / living_elsewhere / dead) matches CEB only ~16% exactly
  (41% within ±1), even after sentinel-cleaning; too unreliable to use.
- Raw-SAV rescan of the 39: **13** have a candidate CEB column (label-first
  match; names CM8–CM20/CEB/CTOT vary by round). Distribution check kept the
  real ones (mean 1.8–4.4) and dropped empties.

### Fix

1. **`CP_children_ever_born`** — carefully-processed copy keeping counts **0–20**;
   sentinel 99 and >20 → NULL. Cross-variable inconsistencies untouched. Raw
   `children_ever_born` left unchanged except the additive backfill.

2. **Recovery of 9 datasets** from a validated raw CEB column, aligned
   POSITIONALLY to the SAV, guarded by `hh_number == HH2` (100% required):

   | Dataset | Raw col | Rows filled |
   |---------|---------|-------------|
   | Benin MICS5 | `CEB` | 15,815 |
   | Mauritania MICS5 | `CEB` | 14,342 |
   | Mauritania MICS5 (dup "2") | `CEB` | 14,342 |
   | Mauritania MICS4 | `CEB` | 12,754 |
   | Mauritania 2007 | `ceb` | 12,535 |
   | Mexico MICS5 | `CEB` | 12,110 |
   | Cameroon MICS5 | `CEB` | 9,861 |
   | Senegal (Dakar) MICS5 | `CEB` | 9,404 |
   | Burundi 2005 | `CM9` | 5,819 |

   Mappings added to `alignment_v2.yaml` (backup `.bak_p13`).

### Not recovered

- **Kyrgyzstan 2005-06** — candidate `ceb` exists but the positional guard
  failed (`hh_number != HH2`, 0% match — broken/reordered keys); skipped to
  avoid wrong-row assignment. Stays NULL.
- **Barbados MICS4** — `CEB` column present but 100% empty in the SAV (explains
  its "mapped but all-NULL" state).
- **Dominican Republic MICS5** — only an empty `CTOT` check column found.
- **Cameroon 2000** — SAV not at the expected path.
- Remaining 26 of 39 — no CEB column collected.

### Result

- `CP_children_ever_born` valid (0–20): **~2.43M** values across **221** datasets
  (was 212). No out-of-range values in the CP_ column.

### DB status: ✅ Done (2026-07-28)

`CP_children_ever_born` added; whole-table clean UPDATE; the 9 recovered datasets
delete + re-inserted from patched parquet (uniform, robust to broken keys);
`ind_que_WM_MICS` gained 9 base CEB rows + mirrored `CP_` provenance rows.
Comments + `_data_issues` P13 via `build_db_documentation.py`.

### Parquet status: ✅ Done (2026-07-28)

Snapshot `wm_merged.parquet.bak_p13`.

### Code

`MICS-WM/src/scan_children_ever_born.py` — gap scan (report only)
`MICS-WM/src/patch_children_ever_born.py`
- `patch_parquet()` — guarded positional backfill (per dataset) + CP_ clean copy
- `patch_yaml()` — adds recovered mappings
- `patch_db()` — CP_ column + clean UPDATE + per-dataset delete/re-insert + ind_que
- `--verify`

---

## P14 — `CP_bmi_for_age_zscore` (clean to |z|≤6 + WHO-2006 derivation)

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`)

### Problem

`bmi_for_age_zscore` (WHO BMI-for-age z) ranged −15.57 to 999.99 (999.99 =
sentinel, plus implausible extremes) and covered only 61.4% of children / **94
countries** — ~14pp below the sibling WHO z-scores, because MICS does not
routinely pre-compute BMI-for-age for under-5.

### Fix — two parts

**1. Clean** → `CP_bmi_for_age_zscore` keeps values with **|z| ≤ 6** (a more
reasonable bound than the WHO |z|≤5 flag); 999.99 and extremes → NULL. Raw
`bmi_for_age_zscore` unchanged.

**2. Derive** the fully-missing datasets. Cross-module backfill is impossible
(women/child-anthropometry only) and summing the sons/daughters breakdown was
rejected earlier (unrelated). BMI-for-age z is instead computed from
`child_weight_kg` / `child_height_or_length_cm` / age / `sex_of_child` via the
**WHO 2006 Child Growth Standards** (BMI-for-age LMS embedded in the patch;
age from `child_age_days`, else months, else birth/interview dates).

Validated against the 143 datasets that already have z: median |diff| **0.004**,
r **0.989** — the method reproduces MICS's own values.

**Guard against serious error.** Naive derivation on the missing datasets
produced wild distributions (SD 2–12, up to 94% |z|>6) because their raw
weight/height contain uncleaned sentinels. So inputs are cleaned (weight 1–40
kg, height 38–140 cm), z clipped to |z|≤6, and a dataset is derived ONLY if its
resulting distribution is healthy: **drop ≤5%, SD 0.7–1.8, |mean| ≤1.5, n≥100**.
**33 datasets pass; 11 are excluded** (SD>1.8 after cleaning — systematic
measurement/unit problems): Djibouti, Albania MICS2, Guinea-Bissau, Nigeria
2007, Syria, Burkina Faso, DR Congo, Bosnia, Belize, Albania 2005, Palestinians
in Lebanon. The gate runs in-code, so the split is reproducible.

`CP_bmi_for_age_zscore_derived`: 1 = derived here, 0 = MICS-provided, NULL =
CP_ NULL. Separates/sensitivity-tests derived values.

### Result

- `CP_bmi_for_age_zscore`: **1,165,590** rows across **178 datasets / 106
  countries** (was ~960k / 145 / 94). Derived: **186,990** rows across 33
  datasets, adding **+12 countries** (Belarus, Benin, Côte d'Ivoire, Gambia,
  Guinea, Macedonia, Madagascar, Niger, Senegal, Somalia, Tajikistan, Zimbabwe).
- No out-of-range values in the CP_ column.

### DB status: ✅ Done (2026-07-29)

`CP_bmi_for_age_zscore` + `CP_bmi_for_age_zscore_derived` added; existing rows
re-cleaned to |z|≤6 in place; the 33 derived datasets delete + re-inserted from
patched parquet; `ind_que_CH_MICS` mirrored `CP_` rows + derived-source rows.

### Parquet status: ✅ Done (2026-07-29)

Snapshot `ch_merged.parquet.bak_p14` (pre-P14).

### Code

`MICS-CH/src/patch_bmi_for_age.py` — embedded WHO 2006 BMI-for-age LMS,
`_zscore()`, in-code data-quality gate, `patch_parquet()` + `patch_db()` +
`--verify`.

---

## P15 — `CP_diarrhea_last_2_weeks` (per-dataset label harmonization) + Congo source fix

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`, `alignment_v2.yaml`)

### Problem

`diarrhea_last_2_weeks` (yes/no) uses **inconsistent coding across datasets**, so
a global 1→Yes/2→No is unsafe:

- 214 datasets: standard `1=Yes, 2=No` (+ sentinels 7/8/9).
- **Iraq 2006 & Yemen 2006**: `1=Yes, 2=Yes-without-blood, 3=No` — here **2 is
  YES**; a global "2=No" would flip them.
- 7 datasets (DR Congo 2001, Dominican Rep 2000, Guinea Bissau 2000, Indonesia
  MICS2, Madagascar 2000, Niger 2000, Venezuela 2000): unlabeled, values
  `{0,100}`.
- **Congo_MICS5**: `diarrhea_last_2_weeks` was MIS-MAPPED to `CA2` ("fluid intake
  during diarrhea", 1=much less…5=nothing), not the real question `CA1` ("had
  diarrhoea in last 2 weeks", 1=Oui/2=Non).

### Investigation

- `{0,100}` decoded as **100=Yes, 0=No**: downstream diarrhea-care vars filled
  24% for =100 vs 3% for =0; implied 2-week prevalence 6–36% (plausible). If 0
  were Yes, prevalence would be 78–94% (absurd).
- Congo_MICS5 raw `ch.yaml` **does** contain `CA1` (1=Oui, 2=Non, 8=NSP,
  9=Non Déclarée) — the data existed, only the alignment was wrong. Only this
  one dataset is mis-mapped (full-scan of all datasets' value labels).

### Fix

- **Per-dataset, label-driven mapping**: a code whose value-label reads Yes
  (incl. "yes without blood") → 1; No → 0; DK/missing/unlabeled/other → NULL.
  Unlabeled datasets fall back to `{1:1, 2:0, 100:1, 0:0}`. Target: **1=Yes,
  0=No, NULL=DK/missing/unknown**. This auto-handles the Iraq/Yemen flip and
  ignores non-yes/no labels.
- **Congo_MICS5 source fix**: `alignment_v2.yaml` remapped `CA2→CA1` (backup
  `.bak_p15`); base recovered from raw `CA1` (positional, guarded
  `household_number == HH2` = 100% over 9,271 rows), then mapped normally
  (1=Oui→1, 2=Non→0). Congo diarrhea now 1,643 Yes / 7,514 No (prevalence 18%).
- Original `diarrhea_last_2_weeks` unchanged except the Congo source correction
  (its CA2 values were never valid diarrhea data).

### Result

- `CP_diarrhea_last_2_weeks`: 1=Yes / 0=No, domain exactly {0,1,NULL} across the
  CH table. (Run `--verify` for live counts.)

### DB status: ✅ Done (2026-07-29)

`CP_diarrhea_last_2_weeks` added; set via a `(dataset_name, raw_code) → cp` map
join (keyless — CP_ depends only on dataset + raw value); Congo_MICS5 delete +
re-inserted from patched parquet (base CA1 + CP_); `ind_que_CH_MICS` Congo raw
col fixed to CA1 and `CP_` provenance mirrored.

### Parquet status: ✅ Done (2026-07-29)

Snapshot `ch_merged.parquet.bak_p15`.

### Code

`MICS-CH/src/patch_diarrhea.py` — per-dataset label classifier (reads each
dataset's `ch.yaml` value labels), Congo CA1 recovery, `patch_yaml()` +
`patch_parquet()` + `patch_db()` + `--verify`.

---

## P16 — `CP_fever_last_2_weeks` (per-dataset label harmonization)

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`)

### Problem

Same family as P15 (diarrhea): `fever_last_2_weeks` is a yes/no child-symptom
variable whose coding varies across datasets (standard 1=Yes/2=No; a set of
MICS2/2000 datasets use {0,100}; sentinels 7/8/9). No scale flips (no
Iraq/Yemen "yes-without-blood").

**Alignment gap — reviewed the raw metadata of ALL 93 uncovered datasets**
(don't trust "missing" = "not collected"). Findings:
- **9 actually collected fever but were unmapped or mis-mapped** — the "fever in
  last 2 weeks" question sits in the **malaria module `ML1`** (MICS4-6
  francophone), a Spanish `CA6AA`, or Palestine's `PCA6` (which was
  **mis-mapped to `respondent_name`**). The CA-module-only fever alignment
  missed them.
- The remaining ~84 genuinely lack a *fever-occurrence* question: ~53 have no
  fever column at all (mostly non-malaria-module MICS4/5/6 — Kazakhstan,
  Mongolia, Serbia, Cuba, Qatar…), and ~31 have only *different* fever concepts
  (symptom-recognition `CA14C`/`CI11C` "child develops a fever", or treatment
  `ML5`–`ML8` "gave medicine for fever") — correctly NOT mapped to
  fever_last_2_weeks.

### Fix

`CP_fever_last_2_weeks` via **per-dataset value-label mapping** → 1=Yes, 0=No,
NULL=DK/missing/unknown. Sentinel codes 7/8/9 forced NULL; {0,100} datasets
decoded 100=Yes, 0=No (implied prevalence 3–28%).

**Recovered all 9 gap datasets** by mapping their raw column →
`fever_last_2_weeks` (added to `alignment_v2.yaml`, backup `.bak_p16`) and
backfilling base positionally, guarded `household_number == HH2`/`CHHHNO` = 100%:
Burkina Faso 2006, Djibouti 2006, Guinea-Bissau 2006, Mauritania 2007, Togo 2006
(`ML1`); Dominican Republic MICS5, Paraguay MICS5 (`CA6AA`); Sao Tome 2000
(`ML1`, via `ChST.sav` / key `CHHHNO`); State of Palestine MICS4 (`PCA6`, "Did
(name) have fever at any time during the past two weeks", which had been
mis-mapped to `respondent_name` — that separate mis-map is noted for follow-up).
Mali MICS4 `IM17` correctly excluded (yellow-fever *vaccination*, not illness).
Raw column otherwise unchanged.

### Guard caught a real bug (coverage-aware map selection)

The first run silently NULLed **19 datasets / 124,170 rows**: these are
multi-source datasets whose merged `fever_last_2_weeks` base holds `{0,100}`
(from the `FEVER` column) while alignment also maps a 1/2-labelled column — the
label-based picker chose `{1:Yes,2:No}`, which matches none of the `{0,100}`
base values → all NULL. Fix: choose, among a dataset's candidate maps plus the
`{0,100}` fallback, the one that **covers the values actually present in the
base column** (tie → tightest, non-fallback). A post-patch check (base-non-null
datasets must equal CP_-non-null datasets) is what surfaced it. (P15/diarrhea
was unaffected — verified 221/221 datasets.)

### Result

- `CP_fever_last_2_weeks`: **1,185,212** non-null across **167 datasets**
  (was 158 before recovery; +9 datasets). Yes 269,123 / No 916,089 (prevalence
  22.7%). Domain exactly {0,1,NULL}.

### DB status: ✅ Done (2026-07-29)

`CP_fever_last_2_weeks` set via a keyless `(dataset_name, raw_code)→cp` map join
for unchanged datasets; the 9 recovered datasets delete + re-inserted from the
patched parquet (base changed); `ind_que_CH_MICS` gained the ML1/CA6AA/PCA6 base
rows and mirrored `CP_` rows.

### Parquet status: ✅ Done (2026-07-29)

Snapshot `ch_merged.parquet.bak_p16`.

### Code

`MICS-CH/src/patch_fever.py` — per-dataset label classifier (sentinel codes →
NULL; multi-source + coverage-aware column selection); `RECOVER` map + guarded
`_recover()` for the ML1/CA6AA gap; `patch_parquet()` + `patch_yaml()` +
`patch_db()` + `--verify`.

---

## P17 — `CP_cough_last_2_weeks` (per-dataset label harmonization) + 5-dataset recovery

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`, `alignment_v2.yaml`)

### Problem

Same family as P15/P16: `cough_last_2_weeks` is a yes/no child-symptom variable
whose coding varies across datasets (standard 1=Yes/2=No; Indonesia MICS2 uses
0=No/1=Yes; sentinels 7/8/9). Cleaner than fever — 222 datasets already covered,
no {0,100}, no scale flips.

### Alignment gap — reviewed all 29 uncovered datasets' raw metadata

- **5 actually collected cough but were never mapped**: the cough-occurrence
  question sits in an unmapped `CI6` (MICS2), Spanish `CA7`, or `CA5` — Cameroon
  2000, Indonesia MICS2, Dominican Republic MICS5, Paraguay MICS5, Palestinians
  in Lebanon 2006.
- **Correctly NOT cough**: the `CA8`/`ca6` "did the child breathe faster while
  ill with cough" columns (Chad/Mali/Mauritania/Mongolia×3, Kyrgyzstan) are a
  pneumonia/fast-breathing sign, a different concept — excluded.
- The remaining ~17 genuinely have no cough column (mostly non-ARI-module MICS6
  — Serbia, Montenegro, Kosovo, North Macedonia, Thailand MICS6, Cuba, Ukraine…).

### Fix

`CP_cough_last_2_weeks` via **per-dataset value-label mapping** → 1=Yes, 0=No,
NULL=DK/missing/unknown (sentinels 7/8/9 → NULL; coverage-aware map selection).
**Recovered all 5 gap datasets** by mapping raw `CI6`/`CA7`/`CA5` →
`cough_last_2_weeks` (added to `alignment_v2.yaml`, backup `.bak_p17`) and
backfilling base positionally, guarded `household_number == HH2`/`CHHHNO` = 100%.
Raw column otherwise unchanged.

### Result

- `CP_cough_last_2_weeks`: **1,426,630** non-null across **227 datasets** (was
  222; +5 recovered). Yes 387,413 / No 1,039,217 (prevalence 27.2%). Domain
  exactly {0,1,NULL}.

### DB status: ✅ Done (2026-07-30)

Keyless `(dataset_name, raw_code)→cp` map join for unchanged datasets; the 5
recovered datasets delete + re-inserted from patched parquet; `ind_que_CH_MICS`
gained the CI6/CA7/CA5 base rows and mirrored `CP_` rows.

### Parquet status: ✅ Done (2026-07-30)

Snapshot `ch_merged.parquet.bak_p17`.

### Code

`MICS-CH/src/patch_cough.py` — per-dataset label classifier + coverage-aware
selection; `RECOVER` map + guarded `_recover()`; `patch_parquet()` +
`patch_yaml()` + `patch_db()` + `--verify`.

---

## P18 — `CP_first_birth_year` (Gregorian CE; CMC-derived + calendar harmonisation)

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`)

### Problem

Raw `first_birth_year` is not cross-country usable:
- only **116/251 datasets** populated;
- sentinels 9997/9998/9999 (~42.7k rows);
- **non-Gregorian calendars** — Thailand stores the **Buddhist Era** year
  (2513–2559 = 1970–2016; BE = CE + 543); Nepal MICS5 stores the **Bikram
  Sambat** year (2035–2071 = 1978–2014; BS ≈ CE + 57);
- Palestinians in Lebanon 2006 uses a 2-digit year (0–99).

### Investigation

`first_child_birth_date_cmc` (Gregorian century-month code) is present in **138**
datasets. Converted via `1900 + floor((cmc-1)/12)` it reproduces the Gregorian
year field **exactly** (100% on 487,969 rows where both exist) and is
**calendar-agnostic** — Thailand's CMC already yields CE (1976–2019), so
CMC-derivation sidesteps the BE/BS problem entirely. Nepal MICS5's CMC is NOT
Gregorian (out of range) → Nepal must use the BS year field − 57. Thailand's 4
datasets have NO CMC → must use the BE year field − 543.

### Fix

`CP_first_birth_year` (Gregorian CE, valid **1950–2024**), per row:
1. CMC-derived year `1900 + floor((cmc-1)/12)` if in [1950, 2024]; else
2. the year field converted to CE per the dataset's calendar — Thailand −543,
   Nepal −57, Palestinians 2-digit pivot (yy≤24→2000+yy else 1900+yy), else
   as-is — if in range; else NULL.

Sentinels and out-of-calendar values fall outside [1950, 2024] and become NULL
automatically. Raw `first_birth_year` is unchanged; CP_ is a pure per-row
function of existing columns (no SAV / yaml changes, no re-insertion).

### Result

- `CP_first_birth_year`: **1,433,972** non-null across **190 datasets** (was
  116; +74 via CMC), range exactly **1950–2024** (BE/BS correctly converted).

### DB status: ✅ Done (2026-07-30)

Single `UPDATE` computing the COALESCE(CMC-derived, calendar-converted-year)
expression; `ind_que_WM_MICS` mirrored base `first_birth_year` rows to `CP_`
plus a `derived` (source `first_child_birth_date_cmc`) row for each CMC-only
dataset.

### Parquet status: ✅ Done (2026-07-30)

Snapshot `wm_merged.parquet.bak_p18`.

### Code

`MICS-WM/src/patch_first_birth_year.py` — `_compute()` (CMC-derive + calendar
convert), `patch_parquet()` + `patch_db()` + `--verify`.

---

## P19 — Derive `CP_age_at_first_birth` (+ `_estimated`)

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`)

### Motivation

No clean "age at first birth" variable existed — only ~5 datasets surveyed it
directly (`agefb`/`wafb`/`CM1A`/`TTWM32`); it is otherwise a derived quantity.
Requested for fertility analysis.

### Method

`CP_age_at_first_birth` = woman's age in completed years at first live birth,
valid **10–49**, per row:
- **A (primary, CMC difference):** `floor((first_child_birth_date_cmc −
  woman_birth_date_cmc) / 12)`. A difference of two century-month codes is
  **calendar-agnostic** (any Buddhist-Era / Bikram-Sambat offset cancels) and
  **month-precise**. 134 datasets.
- **B (fallback, year method):** `CP_first_birth_year − (interview_year_CE −
  woman_age)`, `interview_year_CE = 1900 + floor((interview_date_cmc−1)/12)`.
  Year-level, so ±1 vs A (validated: A vs B agree 68% exact, **100% within 1
  year**). Uses the already calendar-harmonised CP_first_birth_year (P18). Adds
  ~33 datasets.

`CP_age_at_first_birth = A if in [10,49] else B if in [10,49] else NULL`.
`CP_age_at_first_birth_estimated` = 0 if from A (CMC-exact), 1 if from B
(year-level), NULL if the value is NULL.

Pure per-row function of existing columns (no SAV / alignment_v2.yaml changes,
no re-insertion). Distribution: p1 13, median 20, p99 34 — as expected.

### Result

- `CP_age_at_first_birth`: **1,221,378** non-null across **167 datasets**
  (CMC-exact 1,062,761; year-estimated 158,617). Range 10–49.

### DB status: ✅ Done (2026-07-30)

Single `UPDATE` computing both columns; `ind_que_WM_MICS` gains a derived
provenance row per covered dataset.

### Parquet status: ✅ Done (2026-07-30)

Snapshot `wm_merged.parquet.bak_p19`.

### Code

`MICS-WM/src/patch_age_at_first_birth.py` — `_compute()` (CMC diff + year
fallback), `patch_parquet()` + `patch_db()` + `--verify`.

---

## P20 — `CP_place_of_delivery` (harmonized 5-category) + 33-dataset recovery

**Module:** WM (`final_WM_MICS`, `ind_que_WM_MICS`, `wm_merged.parquet`, `alignment_v2.yaml`)

### Problem

`place_of_delivery` uses the MICS/DHS scheme with country-specific numeric codes
(1x home, 2x public, 3x private, 4x/5x/6x other/NGO/UNRWA, 96 other, 9x missing;
plus single-digit country schemes) — not cross-country comparable. Only 176
datasets were mapped, and:
- **Philippines 1999** was mis-mapped to `F14` = "Who **decided** the place of
  delivery" (not where) → left NULL.
- One dataset's column was actually a post-partum **duration** (Hours/Days/Weeks).
- **34 datasets** with no coverage actually collected place of delivery in an
  unmapped column (`MN18`/`MN20`/`MN8`/`NN3` — "Lieu d'accouchement" / "Lugar del
  parto" / "Where did you give birth" / "Onde teve o parto"), found by reviewing
  each uncovered dataset's raw metadata and validating labels via the classifier
  (excludes "who assisted/decided", duration, and Mozambique 2008's "where did
  you WANT to give birth").

### Fix

`CP_place_of_delivery` via **per-dataset value-label mapping** (multilingual
EN/FR/ES/PT), like education harmonisation (P02):
| CP_ | meaning |
|-----|---------|
| 1 | Home |
| 2 | Public health facility |
| 3 | Private health facility |
| 4 | Other health facility (NGO/mission/faith/UNRWA, or sector unspecified incl. "DK public or private") |
| 5 | Other / en route (other, on the road, checkpoint) |
| NULL | DK / missing / incoherent / unmappable (incl. duration & yes/no mis-maps) |

**Recovered 34 datasets** by mapping their raw place column (incl. Mozambique 2008 `MN8`, whose earlier candidate `MN7_A` was the *intended* place and correctly rejected) → `place_of_delivery`
(added to `alignment_v2.yaml`, backup `.bak_p20`), backfilling base positionally
(guarded `hh_number == HH2` = 100%), then classifying. 4 candidates skipped
(guard could not verify alignment even via key-join — Sao Tome MICS5,
Kyrgyzstan, Bolivia 2000, Senegal 2000: no usable household key or 0%
positional/join match). The other ~38 uncovered datasets genuinely lack a
place-of-delivery question.

### Result

- `CP_place_of_delivery`: **543,011** non-null across **209 datasets** (was 175;
  +34 recovered). Distribution: 1 Home 185,376 / 2 Public 230,287 / 3 Private
  58,912 / 4 Other-facility 64,164 / 5 Other 4,272.

### DB status: ✅ Done (2026-07-30)

Keyless `(dataset_name, raw_code)→cp` map join (guarded numeric cast, base is
TEXT) for unchanged datasets; the 34 recovered datasets delete + re-inserted
from patched parquet; `ind_que_WM_MICS` gained the recovered base rows and
mirrored `CP_` rows.

### Parquet status: ✅ Done (2026-07-30)

Snapshot `wm_merged.parquet.bak_p20`.

### Code

`MICS-WM/src/patch_place_of_delivery.py` — 5-category multilingual label
classifier; `RECOVER` map + guarded `_recover()`; `patch_parquet()` +
`patch_yaml()` + `patch_db()` + `--verify`.

---

## P21 — `CP_child_sample_weight` (scale harmonization) + 30-dataset recovery

**Module:** CH (`final_CH_MICS`, `ind_que_CH_MICS`, `ch_merged.parquet`, `alignment_v2.yaml`)

### Problem

1. **Scale inconsistency.** 131/134 covered datasets store a normalised child
   weight (mean ≈ 1 within the survey — the MICS standard), but three store
   un-normalised expansion weights: Thailand 2005-06 (mean 514), Costa Rica MICS6
   (98.5), Panama MICS5 (60.9). Pooling them un-normalised would weight those
   surveys' cases 60–500×.
2. **Alignment gap.** 51 uncovered datasets have a raw `chweight`/`CHWEIGHT`
   ("child sample weight" / "pondération enfant" / "ponderador de niños") column
   that was never mapped (found by reviewing raw metadata; the household/women
   weights `HHWEIGHT`/`WMWEIGHT` and body-weight `POIDS`/`AN1` columns were
   excluded).

### Fix

`CP_child_sample_weight = child_sample_weight / (dataset mean if that mean > 5
else 1)` — normalises each dataset to mean 1 for poolable cross-country use;
already-normalised datasets are unchanged; weight 0 (excluded case) is kept.

**Recovered 30 of 51** datasets by mapping raw `chweight` → `child_sample_weight`
(added to `alignment_v2.yaml`, backup `.bak_p21`) and backfilling base
positionally (guarded `household_number == HH2`/`CHHHNO` = 100%). 21 skipped —
mostly MICS2/2000 datasets whose SAV has no usable household key or 0% positional
match (and Rwanda/Suriname 2000 with no CH SAV at the raw path). The recovery
surfaced 3 further un-normalised datasets (Indonesia MICS2 mean 4949, Venezuela
2000 1235, Senegal 2000 146), which the mean>5 rule normalised automatically —
so 6 datasets total are normalised.

### Result

- `CP_child_sample_weight`: **1,104,528** non-null across **164 datasets** (was
  134; +30 recovered), overall mean ≈ 1 (poolable). Raw column unchanged except
  the additive recovery backfill.

### DB status: ✅ Done (2026-07-31)

`UPDATE CP_ = base`, then divide the 3 non-recovered outliers by their mean; the
30 recovered datasets delete + re-inserted in one batch from patched parquet;
`ind_que_CH_MICS` gained the recovered base rows and mirrored `CP_` rows.

### Parquet status: ✅ Done (2026-07-31)

Snapshot `ch_merged.parquet.bak_p21`.

### Code

`MICS-CH/src/patch_child_sample_weight.py` — `_divisors()` (per-dataset
normalisation), `RECOVER` map + guarded `_recover()`, `patch_parquet()` +
`patch_yaml()` + `patch_db()` + `--verify`.

---

## P22 — `CP_received_anc` (harmonized binary) + provider-checklist derivation

**Date:** 2026-08-01 · **Module:** WM · **Columns:** `CP_received_anc`,
`CP_received_anc_derived`

### Problem

1. **Count contamination.** `received_anc` was aligned to BOTH the yes/no ANC
   question (`MN1` in MICS4/5, `MN2` in MICS6) AND the visit-count (`MN3`/`MN5`)
   in most datasets, so the binary was polluted with visit counts (values 3–16).
2. **Mis-mapped datasets.** In 5 datasets the yes/no column was absent and a
   count/timing column won the merge (`MN2A2` no-of-times, `F9` months-when-first,
   `MN2AA`/`MN2AB`, ...).
3. **Apparent "missing" that was really a different question format.** Only 158
   datasets had any value. The MICS2/MICS3 rounds (mostly 2000–2006) never asked a
   single "did you receive ANC?" question — they used a **provider checklist**
   ("whom did you see for antenatal care?": doctor / nurse / midwife / TBA / ... /
   no one). That checklist *is* the ANC question for those rounds and matches
   UNICEF's ANC-coverage indicator, so those datasets were recoverable, not empty.

### Investigation

Per-dataset value-label review split the 251 datasets into: **153** with a verified
yes/no column (code 1 = Yes in every one, no exceptions); **10** with an unmapped
direct `MN1`/`MN2` yes/no question (Algeria MICS6, Argentina/Costa Rica/Uruguay
MICS4, Congo/Mali/Mexico/Panama/Dominican-Rep MICS5, Suriname 2000); **77** with
only a provider checklist; **11** with genuinely no ANC question in the WM module.

The provider checklist appears in three raw coding schemes, all handled by a
row-level classifier keyed on each column's *role* (provider vs "no one", fixed by
MICS naming `MN2[YZ]` / label) and each cell's value label:
- MICS2 numeric (Senegal): `0`=Non, `k`=provider-code, `7`=Missing;
- MICS4-6 string (Ghana/Thailand): `''`=not-selected, `'A'..'Y'`=letter, `'?'`=Missing;
- yes/no grid (Zambia): `1`=Yes / `2`=No per provider column.
Two datasets (Mozambique 2008, Zimbabwe) store letter checkboxes with **no value
labels at all** — handled by treating any non-empty non-`?` cell in a provider
column as selected.

### Validation (derivation gate)

On the **150** clean yes/no datasets that also carry an `MN2` checklist (347,388
overlap rows), the checklist derivation reproduces the self-reported yes/no answer
at **median 100 %, mean 99.5 %** agreement — confirming the derived construct
equals the direct question. (The one low case, Malawi 2006 at 0.245, is itself a
count-contaminated base and is re-derived here.)

### Fix

`CP_received_anc` = 1 received / 0 not received / NULL. `CP_received_anc_derived`
= 0 self-reported, 1 checklist-derived. Harmonized 153 clean datasets (base
1→1 / 2→0, nulling sentinels 9/98/99 and any leaked count); recovered 10 direct
`MN1`/`MN2`; derived 58 checklist datasets. Recovery reads the raw SAV and aligns
positionally, **guarded** `hh_number == {HH2, WM2, WIHHNO, HI2, ...}` = 100 %
(older MICS2 files name the household id `WIHHNO`/`HI2`, not `HH2`). New mappings
written to `alignment_v2.yaml` (backup `.bak_p22`).

### Result

- `CP_received_anc`: **557,131** non-null across **221 datasets** (was 158) —
  163 self-reported + 58 derived; values strictly {0,1}, out-of-range = 0.
- **19 skipped**: 3 have no WM SAV (DR Congo 2001, Gambia 2000, Guyana 2000);
  Kyrgyzstan / Vietnam / Sao Tome MICS5 and 13 MICS2/2000 datasets (Senegal, Chad,
  CAR, Côte d'Ivoire, ...) whose parquet `hh_number` matches no raw household
  column (0 %), so positional alignment can't be verified — left NULL to avoid
  mis-alignment.
- **11 genuinely never collected ANC** in the WM module (Cuba 2006/MICS4, Guinea
  Bissau MICS5/6, Indonesia MICS2, Moldova MICS2, Myanmar 2000, Sao Tome MICS6 ×2,
  Sudan N/S 2000) — reported, left NULL.

### DB status: ✅ Done (2026-08-01)

`UPDATE CP_ = base` for the 153 harmonized datasets; the 68 recovered datasets
delete + re-inserted from patched parquet; `ind_que_WM_MICS` gained recovered base
rows and mirrored `CP_` rows (363 rows).

### Parquet status: ✅ Done (2026-08-01)

Snapshot `wm_merged.parquet.bak_p22`.

### Code

`MICS-WM/src/patch_received_anc.py` — `_cell()`/`_is_none_col()`/`_derive()`
(role-based checklist classifier), `_recover_one()` (multi-key guard), DIRECT/
FAMILY/NONE_NO_ANC lists, `--validate` gate, `patch_parquet/yaml/db` + `--verify`.
`MICS-WM/src/scan_received_anc.py` — read-only recovery-method classifier.

---

## P23 — `CP_first_trimester_anc` (first-trimester ANC) + timing recovery

**Date:** 2026-08-01 · **Module:** WM · **Columns:** `CP_first_trimester_anc`,
`CP_first_trimester_anc_derived`

### Problem

There was no first-trimester-ANC indicator. The underlying "how many weeks or
months pregnant were you at the first antenatal visit?" question was aligned
(split into `anc_first_visit_timing_number` + `anc_first_visit_timing_unit`,
unit 1=weeks / 2=months) for only **74** datasets — but reviewing the raw
metadata of the datasets that lacked it showed ~44 more had asked the same
question under an unmapped column: MICS5 `MN2AN`/`MN2AU` and `MN2AAN`/`MN2AAU`,
MICS6 `MN4AN`/`MN4AU` and `MN4N`/`MN4U`, and single month/week columns
(`MN2AA`, `MN3C`, `MN2B1`, `MN2A_CS`). Several false leads were excluded:
Kazakhstan `CM12G2` (prior pregnancy), Moldova/Palestine folic-acid items, BiH
`CM12I*` (per-birth pregnancy duration), South Sudan `SB3U` (time since sex),
Algeria `MN5A` (number of visits, not timing).

### Fix

`CP_first_trimester_anc` = 1 if the first ANC visit was in the first trimester
(**≤3 completed months** or **≤13 weeks**), 0 if later, NULL if missing.
Plausible ranges months 1–9 / weeks 1–42; sentinels 0/98/99 and unit 9 → NULL.
`CP_first_trimester_anc_derived` = 0 (from the mapped timing number+unit) / 1
(recovered from a raw timing column). For number-only columns the unit is fixed
from the column label (months vs weeks); Madagascar (South) `MN2A_CS` is treated
as months per its label ("âge en mois"), ignoring the mismatched `MN11BU`.

Recovery reads the raw SAV and aligns positionally, **guarded**
`hh_number == {HH2, WM2, WIHHNO, HI2, ...}` = 100 % (Unicode NFC/NFD tolerant so
"Côte d'Ivoire" resolves). New mappings written to `alignment_v2.yaml`
(backup `.bak_p23`).

### Result

- `CP_first_trimester_anc`: **277,613** non-null across **115 datasets** (was 74;
  +41 recovered); values strictly {0,1}, out-of-range = 0; overall first-trimester
  rate 0.59. Per-dataset rate 0.16–0.98, none degenerate (confirms recovered
  columns are timing, not visit counts).
- **3 skipped**: Côte d'Ivoire MICS5 (raw SAV not at the expected path), Dominican
  Republic MICS6 and Sao Tome MICS5 (parquet `hh_number` matches no raw household
  key, 0 %) — left NULL to avoid mis-alignment.

### DB status: ✅ Done (2026-08-01)

`UPDATE CP_ = derive(number,unit)` for the 74 mapped datasets; the 41 recovered
datasets delete + re-inserted from patched parquet; `ind_que_WM_MICS` gained
recovered timing rows and mirrored `CP_` rows (115).

### Parquet status: ✅ Done (2026-08-01)

Snapshot `wm_merged.parquet.bak_p23`.

### Code

`MICS-WM/src/patch_first_trimester_anc.py` — `_ft()` (trimester cutoff),
`RECOVER` map (44 datasets), `_recover_one()` (multi-key guard, NFC-tolerant),
`patch_parquet/yaml/db` + `--verify`.

---

## P24 — `CP_area_type` (harmonized urban / rural / refugee-camp), all 4 tables

**Date:** 2026-08-02 · **Modules:** HH + WM + CH + HL · **Column:** `CP_area_type`

### Problem

The raw `area` (HH6 "Area of residence") is not comparable across surveys:
- coding differs — usually 1=urban / 2=rural, but **Zambia 1999 is reversed**, so
  the value **label** is authoritative, not the code;
- **>2 categories** in ~31 surveys that must collapse: Mongolia capital / aimag
  centre / soum centre → urban; Lao "rural with/without road" → rural; Suriname
  coastal / interior → rural; Bangladesh municipality / metro / slum → urban,
  tribal → rural; city-name strata (Ouagadougou, Kigali, Antananarivo) → urban;
  peri-urban → rural; Egypt sub-national is a pure **region** coding (no urban/rural);
- `area` was **mis-aligned** to a region / cluster column in ~26 datasets, so the
  base is contaminated with region codes (10–95) that are not HH6.

Only three surveys carry a genuine refugee-**camp** category: **State of Palestine
MICS4 / MICS5 / MICS6** (HH6 = Camp). Kenya (Mombasa) HH6=Slum is urban-informal,
not a camp.

### Fix

`CP_area_type` = **1 Urban / 2 Rural / 3 Refugee-camp / NULL**, in all four tables.
Per user: slum → Urban, **peri-urban → Rural**, refugee camp → 3, region-only /
"Other" → NULL. A multilingual (EN/FR/ES/PT) classifier maps each HH6 value label
to a category; a per-dataset {raw code → category} map is applied to each table's
own `area` column.

- **HH (source of truth):** direct-map the base; where the base is contaminated or
  `area` was never aligned, **recover HH6 from the HH SAV** (guarded positional,
  `hh_number == {HH2 / WIHHNO / HI2 / …}` = 100 %).
- **WM / CH / HL:** direct-map each table's own `area`, then fill still-NULL rows
  from HH via the household join (`dataset_name + cluster_number + household id`) —
  fast, no per-module SAV reads.

Datasets with no HH6 labels but base values in {1,2} default to 1=urban / 2=rural.

### Result

- `CP_area_type` valid / datasets: **HH 2,483,904 / 241**, WM 2,681,169 / 225,
  CH 1,542,315 / 229, HL 10,959,375 / 213. Values strictly {1,2,3}, out-of-range 0.
- Refugee-camp (3): the 3 State-of-Palestine surveys (HH 4,390 / WM 4,876 /
  CH 3,152 / HL 23,067 rows).
- HH skipped 8 datasets (broken household key / no SAV / no HH6): Albania MICS2,
  Argentina MICS4 & MICS6, Gambia 2000, Sao Tome MICS5 & MICS6 ×2, Senegal (Dakar).

### DB status: ✅ Done (2026-08-02)

Per table: `ADD COLUMN CP_area_type SMALLINT`; direct-mapped datasets updated via a
`(dataset, area code) → category` temp-table join; recovered / join-filled datasets
delete + re-inserted from patched parquet. `ind_que_*` mirror the `area` rows to
`CP_area_type`.

### Parquet status: ✅ Done (2026-08-02)

Snapshots `*.parquet.bak_p24` in all four modules.

### Code

`src/patch_area_type.py` — `_cat()` (label classifier), `build_maps()` (HH6 labels
from SAV), `_direct_map()`, `_recover_hh6()` (guarded SAV recovery), `process_table()`
(HH SAV-recover / member HH-join), `sync_db()`, `--verify`.

---

## P25 — `CP_survey_year` + `CP_survey_month` (Gregorian interview date), all 4 tables

**Date:** 2026-08-02 · **Modules:** HH + WM + CH + HL · **Columns:** `CP_survey_year`,
`CP_survey_month`

### Problem

No harmonized interview year/month existed. Raw `interview_year` / `interview_month`
carry sentinels (9999 / 99 / 0) and, for two countries, non-Gregorian calendars:
- **Thailand** — `interview_year` is **Buddhist Era** (e.g. 2549, 2562); Gregorian
  = year − 543. The month is unchanged (BE months == Gregorian months). Note the
  cmc is BE in Thailand 2005-06 but Gregorian in Thailand MICS6, so cmc is *not* a
  safe source there — `interview_year − 543` is.
- **Nepal** — `interview_year` / `month` / `day` are **Bikram Sambat** (e.g. 2071,
  2076); both the year and the month differ from Gregorian (BS new year ≈ mid-April).

### Investigation / validation

For all non-Thai/Nepal rows the cmc-derived date already matches `interview_year` /
`interview_month` (**year 100 %, month 99.93 %** over 2.05 M WM rows), so the raw
fields are Gregorian and reliable. Thailand −543 reproduces the known fieldwork
(2005-06 → 2005/2006, MICS6 → 2019). Nepal BS→Gregorian was validated to land every
interview in the correct Gregorian year (MICS5 → 2014, MICS6 → 2019) with a
contiguous, plausible month spread.

### Fix

`CP_survey_year` (Gregorian, valid **1998–2025**) and `CP_survey_month` (1–12):
- normal datasets — cleaned `interview_year` / `interview_month`; WM fills 7
  cmc-only datasets (Gambia 2005-06, Mongolia MICS4 ×3, Palestinians in Lebanon,
  Trinidad 2006, Viet Nam 2000) from `interview_date_cmc`;
- **Thailand** — `interview_year − 543`, month unchanged;
- **Nepal** — `interview_year/month/day` converted BS→Gregorian with an **embedded
  BS calendar** (month lengths for BS 2070–2078 + the Gregorian date of Baishakh 1
  per year, so a month-length error can never compound across years).

Each table uses its **own** interview date (household / woman / child interviews
occur on different days) — no cross-table propagation. Sentinels → NULL.

### Result

- `CP_survey_year` valid / datasets: HH 2,681,514 / 242, WM 2,853,155 / 244,
  CH 1,643,683 / 243, HL 10,829,280 / 210.
- `CP_survey_month` valid: HH 2,695,006, WM 2,853,167, CH 1,669,977, HL 11,140,759
  (slightly more than year — a sentinel year can coexist with a valid month).
- Out-of-range = 0 in all tables; parquet == DB.

### DB status: ✅ Done (2026-08-02)

Per table: `ADD COLUMN CP_survey_year/month SMALLINT`; non-special datasets updated
via a `(dataset, interview_year, interview_month) → (year, month)` temp-table join;
special datasets (Nepal — depends on day; WM cmc-only — no year field) delete +
re-inserted from patched parquet. `ind_que_*` mirror interview_year → CP_survey_year
and interview_month → CP_survey_month.

### Parquet status: ✅ Done (2026-08-02)

Snapshots `*.parquet.bak_p25` in all four modules.

### Code

`src/patch_survey_date.py` — `_bs_to_ad()` (embedded BS calendar), `derive()`
(per-table calendar logic), `process_table()` / `sync_db()` (temp-LUT + special
reinsert), `--validate` (cmc cross-check), `--verify`.

---

## P26 — `CP_woman_age` (real age) + `CP_woman_birth_year` (WM)

**Date:** 2026-08-02 · **Module:** WM · **Columns:** `CP_woman_age` (rebuilt),
`CP_woman_birth_year`, `CP_woman_birth_year_estimated`

### Problem

1. `woman_age` — and its P11 copy `CP_woman_age` — is **contaminated**: 153 datasets
   store the 5-year **age-GROUP code (1–7)**, not the real age (identical to
   `woman_age_group`); only 86 hold the real 15–49 age. So `CP_woman_age` was
   misleading (looked like age, was a band code).
2. No harmonized woman **birth year** existed. `woman_birth_year` (raw) has sentinels
   (9998/9999/0) and, for Nepal/Thailand, non-Gregorian calendars; `woman_birth_date_
   cmc` likewise; and some datasets' birth-year field is mis-aligned (Algeria MICS6
   → median 2008, implying age 11).

### Fix

The **real age** lives in the household listing (HL) — every woman is a household
member with her actual age (calendar-independent). Joining WM↔HL on
`(dataset, cluster, household, line)` recovers it.

- **`CP_woman_age`** (10–64) = raw `woman_age` where already real, else the
  HL-recovered age. **216 datasets.** NULL for 31 group-code datasets whose WM file
  has **no woman line number** (`line_number` all-NULL) so the HL row can't be
  identified (their age band remains in `CP_woman_age_group`); the 3 additional
  broken-key ones are included in that 31.
- **`CP_woman_birth_year`** (Gregorian 1940–2010), hybrid:
  * **exact** (`CP_woman_birth_year_estimated=0`) — `woman_birth_date_cmc` → year
    (primary) or raw `woman_birth_year` (fill), for non-Nepal/Thailand datasets
    (Gregorian there);
  * **age-based** (`=1`, ±1 yr) — `CP_survey_year − CP_woman_age`, for Nepal
    (Bikram Sambat), Thailand (Buddhist Era) and any dataset lacking a Gregorian
    birth field.
  A **plausibility guard** nulls any birth year implying a woman age <12 or >60
  (drops the mis-aligned birth-year fields, e.g. most of Algeria MICS6). **245
  datasets**; implied age 12–58 (median 29).

### Validation

cmc-derived vs raw `woman_birth_year` agree 88.6 % (cmc preferred as primary);
age-based vs birth-date agree within-1 year 86 % (age is integer → ±1). Nepal
(→ born median 1986/1991) and Thailand (→ 1972/1985) land at plausible ages. HL
age join covers ≥95 % of rows for the recoverable group-code datasets, 100 % for
Thailand 2005-06 / MICS6 and Nepal.

### Result

- `CP_woman_age`: 2,497,796 rows / **216 datasets** (real age; was 245 datasets of
  which 153 were group codes). Out-of-range 0.
- `CP_woman_birth_year`: 2,801,480 rows / **245 datasets** (exact 2,495,469 /
  age-based 306,011). Out-of-range 0. 6 datasets have no usable source and stay NULL
  (Thailand_MICS5 & _14_Provinces, Dominican Republic MICS5, Indonesia MICS2,
  Kyrgyzstan 2005-06, Philippines 1999).
- Raw `woman_age` unchanged (still the group code where it was).

### DB status: ✅ Done (2026-08-02)

Values are row-level (HL-recovered age, hybrid birth year) and WM row keys have
~11 % duplicates / 555 k null keys (no reliable update key), so the whole table was
rebuilt from the patched parquet (`TRUNCATE` + grouped `COPY`, 2,960,835 rows /
251 datasets preserved). `ind_que_WM_MICS` mirrors `woman_age → CP_woman_age` and
`woman_birth_year → CP_woman_birth_year` / `_estimated`.

### Parquet status: ✅ Done (2026-08-02)

Snapshot `wm_merged.parquet.bak_p26`.

### Code

`MICS-WM/src/patch_woman_birth_year.py` — `_hl_age_lookup()` (HL join),
`derive()` (real-age rebuild + hybrid birth year + plausibility guard),
`sync_db()` (TRUNCATE + grouped COPY), `--verify`.

---

## P27 — `CP_country` + `CP_subnational` (standardised geography), all 4 tables

**Date:** 2026-08-04 · **Modules:** HH + WM + CH + HL · **Columns:** `CP_country`,
`CP_country_code`, `CP_subnational`, `CP_subnational_matched` · **Reference table:**
`_geo_dict`

### Problem

Geography was only implicit: the country lived in `dataset_name` (many spellings,
plus subnational surveys), and the subnational unit was an **unlabeled numeric
`region` code** (the state/province/governorate *names* live only in the SAV value
labels, not in the aligned data). A user-supplied reference was added:
`data/geolocation/country.json` (ISO3 + canonical country names) and `state.json`
(3661 canonical admin-1 names across 230 countries).

### Fix

- **`CP_country` / `CP_country_code`** — `dataset_name` → country.json, via accent-
  folding + an alias table (DRCongo, Lao PDR→Laos, Viet Nam→Vietnam, Swaziland,
  North Macedonia, São Tomé, Kyrgyz Republic, …). Subnational surveys map to the
  mother country (Pakistan (Punjab)→Pakistan, Kenya (…County)→Kenya, Egypt
  (Sub-national)→Egypt, Somalia (Somaliland)→Somalia, Roma-Settlements→base);
  **Palestinians-in-Lebanon → Lebanon** (geographic residence). **255/255 datasets.**
- **`CP_subnational` / `CP_subnational_matched`** — each dataset's HH-module SAV
  value labels give `region code → raw name`; each raw name is canonicalised to the
  state.json admin-1 name for that country (exact → accent/case-fold → strip
  region/province words → safe fuzzy, Levenshtein ≤2, **no substring guessing**). If
  it matches, `matched=1` and the value is the state.json spelling; otherwise the
  cleaned raw label is kept (`=0`). **~52 % of region codes match** the reference
  (Nigeria 35/37, Ghana 10/10 vs macro-region/transliteration cases 0 %). Only SAV
  *metadata* is read (once) to build the map; application maps the existing `region`
  code column — no per-row SAV reads.

### Result

- `CP_country`/`CP_country_code`: **every row** (HH 255 / WM 251 / CH 251 / HL 228
  datasets).
- `CP_subnational`/`_matched`: HH 1,869,486 / **191 ds**, WM 1,669,689 / 171 ds,
  CH 1,008,339 / 176 ds, HL 7,033,130 / 164 ds. The admin-1 code is read from `region`
  and, where that is absent, from the `province` column (several surveys' HH7 was
  aligned into `province`, not `region` — both are admin-1). Coverage is bounded by
  rows with a populated admin-1 code; datasets whose admin-1 sits only in a
  `district`/`stratum` column (admin-2 / composite) are left NULL to keep the column
  a single, comparable admin level. A separate **CP_district / CP_district_matched** (admin-2 — district/arrondissement labels, standardised to state.json only where a small country's 'district' IS admin-1, e.g. Lesotho) adds the finer level for HH 34 / WM 29 / CH 32 / HL 26 datasets without polluting CP_subnational.
- `_geo_dict`: one row per (dataset, region code) — country, code, region code,
  subnational name, matched — 2,328 rows. The country-level dictionary.

### DB status: ✅ Done (2026-08-04)

Per table: `ADD COLUMN` (TEXT ×3, SMALLINT); `CP_country` set per dataset and
`CP_subnational` per `(dataset, region code, province code)` (rounded to 6 dp to dodge float round-trip drift on a contaminated `province` float) via temp-table joins (no reinsert).
`_geo_dict` built from the map cache. `ind_que_*` mirror `region → CP_subnational`.

### Parquet status: ✅ Done (2026-08-04)

Snapshots `*.parquet.bak_p27` in all four modules. Map cache
`data/geolocation/_geo_maps_cache.json` (gitignored; rebuild with `--build`).

### Code

`src/patch_geolocation.py` — `build_maps()` (country matcher + region canonicaliser + Levenshtein, from country.json/state.json + SAV metadata; builds both `region` and `province` admin-1 maps), `_apply_cols()` (region→province fallback),
`sync_db()` (temp-LUT), `--build` / `--verify`.

---

## P28 — early initiation of breastfeeding (WM)

**Date:** 2026-08-05 · **Module:** WM · **Columns:** `CP_time_to_breastfeed_hours`,
`CP_early_initiation_breastfeeding`, `CP_breastfed_within_24h`

### Problem
No early-initiation indicator existed. The "how long after birth was the child first
put to the breast?" question (number + unit) was aligned for **154** datasets, but the
unit code means different things across surveys (0/1/2 Immediately/Hours/Days is usual,
some use 1/2/3, one Minutes). And — the issue the user flagged — **39 more datasets had
the question UNMAPPED in their raw SAV under a non-English label** ("Enfant mis au sein
pour la première fois", "Cuánto tiempo después del nacimiento le dio pecho", ...), a
translation gap.

### Fix
`CP_time_to_breastfeed_hours` = hours to first breastfeed, with the unit interpreted by
its **label** (immediately=0 / minutes/60 / hours / days*24), sentinels (98/99/998/999,
unit=Special/DK, implausible n) -> NULL. `CP_early_initiation_breastfeeding` = 1 if <=1h,
`CP_breastfed_within_24h` = 1 if <=24h. Recovered **36** unmapped datasets by guarded
positional backfill of the correct `MN25/MN37/MN13` number+unit pair, **excluding
look-alikes**: MN26 (time bathed), PN2 (facility stay), PN12 (postnatal check), MN13B
(breastfeeding duration). Accent-folding fixed 14 French datasets whose "Immédiatement"
label had been missed.

### Result
- 459,108 rows / **190 datasets** (154 mapped + 36 recovered); values {0,1}; early-init
  (<=1h) rate 0.56, within-24h 0.89. Skipped 3 (Côte d'Ivoire MICS5 no SAV on drive,
  Dominican Rep MICS6 & Kyrgyzstan broken keys). Argentina MICS4 lacks the question.

### DB status: ✅ Done (2026-08-05)
Mapped datasets updated via a `(dataset, number, unit)` temp-LUT; 36 recovered datasets
delete + re-inserted from patched parquet; `ind_que` mirrored.

### Parquet status: ✅ Done (2026-08-05)
Snapshot `wm_merged.parquet.bak_p28`.

### Code
`MICS-WM/src/patch_breastfeed_initiation.py` — `_utype()`/`_hours()` (label-based unit),
`RECOVER` (39 pairs), `_recover()` (guarded), `--verify`.

---

## P29 — `CP_ever_breastfed` (CH)

**Date:** 2026-08-05 · **Module:** CH · **Column:** `CP_ever_breastfed`

### Problem
"Has (name) ever been breastfed?" was aligned for **205** datasets, but **31** more had
it UNMAPPED in their raw SAV under a non-English label — French "L'enfant a été
allaité", Spanish "El niño fue amamantado", Portuguese "Alimentado com leite materno"
(BF1 in MICS2-5, BD2 in MICS6) — the translation gap the user flagged.

### Fix
`CP_ever_breastfed` = 1 Yes / 0 No / NULL (sentinels 7/8/9 DK/missing). Coding is a
uniform 1=Yes/2=No across all mapped datasets. Recovered **28** of the 31 unmapped
datasets by guarded positional backfill (household_number == HH2/…), the value
classified from each column's own SAV value labels; diarrhoea (CA1), "still
breastfeeding" and "…yesterday" look-alikes are excluded by construction.

### Result
- 1,205,888 rows / **233 datasets** (205 + 28); values {0,1}; overall ever-breastfed
  rate 0.95. Skipped 3: Côte d'Ivoire MICS5 (no CH SAV on drive), Madagascar 2000 &
  Rwanda 2000 (2000-era CH SAV has no recognised household key). Remaining unmapped
  datasets genuinely never asked the question (old MICS2/2000 reduced questionnaires).

### DB status: ✅ Done (2026-08-05)
Mapped datasets updated in place (1->1/2->0); 28 recovered datasets delete + re-inserted
from patched parquet; `ind_que` mirrored.

### Parquet status: ✅ Done (2026-08-05)
Snapshot `ch_merged.parquet.bak_p29`.

### Code
`MICS-CH/src/patch_ever_breastfed.py` — `_classify()` (label-driven yes/no), `RECOVER`
(31 columns), `_recover()` (guarded), `--verify`.

---

## P30 — `CP_still_breastfeeding` (CH)

**Date:** 2026-08-05 · **Module:** CH · **Column:** `CP_still_breastfeeding`

### Problem / Fix
"Is (name) still being breastfed?" was aligned for **240** datasets (uniform 1=Yes/2=No,
multilingual). 2 more had it unmapped in the raw SAV (DR Congo 2001 `BF2` "Continue
d'être allaité", Kyrgyzstan `bf2`). Added `CP_still_breastfeeding` (1/0/NULL): harmonized
the 240 (1->1/2->0, sentinels null) and recovered 1 by guarded positional backfill
(**Kyrgyzstan skipped — broken household key**).

### Result
- 1,174,676 rows / **241 datasets**; still-breastfeeding rate 0.44. Near the ceiling —
  the remaining 9 missing datasets (Burundi 2005, Cameroon 2000, Indonesia/Moldova
  MICS2, Philippines 1999, Senegal 2000, Uruguay MICS4, Venezuela 2000, Yemen 2006)
  genuinely never asked it. Consistency: `still=1 & ever=0` stays 57 rows (pre-existing
  raw-data noise; the recovery added none).

### DB / Parquet: ✅ Done (2026-08-05)
Mapped updated in place; 1 recovered dataset reinserted; `ind_que` mirrored. Snapshot
`ch_merged.parquet.bak_p30`.

### Code
`MICS-CH/src/patch_still_breastfeeding.py`.

---

## P31 — `CP_fed_milk_yesterday` (CH), re-derived — fixes a mis-alignment

**Date:** 2026-08-05 · **Module:** CH · **Column:** `CP_fed_milk_yesterday`

### Problem (alignment error found in audit)
`infant_fed_milk_yesterday` was semantically inconsistent and **mis-aligned**: for
**~52 MICS6 datasets** it was mapped to `BD8N` = "child ate **cheese** or other food
made from milk" (a solid dairy FOOD, not milk drinking); Cuba MICS4 -> `BF8` juice;
Sao Tome MICS5 -> `BD8L` fish. Even the correctly-mapped datasets mixed different
items (formula `BD7D` / animal milk `BD7E` / combined). So the raw variable cannot be
harmonized as-is.

### Fix (re-derivation)
`CP_fed_milk_yesterday` = 1 if the child drank **infant formula OR animal/other milk**
yesterday, 0 if neither, NULL if both missing:
- formula from `infant_fed_formula_yesterday` (per-dataset yes/no-or-times-count);
- milk from `infant_fed_milk_yesterday` where that column is a genuine milk-drink item;
  for the 55 mis-aligned datasets the real animal-milk item **`BD7E`** is recovered from
  the raw SAV (guarded positional). Cheese/juice/fish are excluded.

### Result
- 1,016,081 rows / **227 datasets**; values {0,1}; drank-milk rate **0.39**. The
  formerly cheese-contaminated MICS6 datasets now read as milk-drinking (e.g. Ghana
  0.15, Bangladesh 0.25, Nepal 0.43). BD7E recovered for **50** datasets; 4 skipped
  (Kosovo / Montenegro ×2 / N.Macedonia-Roma — guard <99.9 %) fall back to formula
  only; Cuba MICS4 has no animal-milk item (formula only).

### DB / Parquet: ✅ Done (2026-08-05)
CH rebuilt via `TRUNCATE` + grouped `COPY` (1,684,203 rows / 251 datasets preserved);
`ind_que` mirrored. Snapshot `ch_merged.parquet.bak_p31`.

### Code
`MICS-CH/src/patch_fed_milk_yesterday.py` — `_to_yesno()` (yes/no-or-count),
`RECOVER_BD7E` (54), `_recover_bd7e()` (guarded), `derive()`/`_combine()`, `--verify`.

---

## P32 — `CP_breastfeeding_status` (CH), derived 3-category current status

**Date:** 2026-08-05 · **Module:** CH · **Column:** `CP_breastfeeding_status`

### Motivation
Breastfeeding was split across two axes with no single status variable:
`CP_ever_breastfed` (P29, lifetime) and `CP_still_breastfeeding` (P30, current).
A combined 3-category status is the standard MICS "current breastfeeding status".

### Derivation (pure function of two existing CP_ columns — no SAV read)
- `2` currently breastfeeding — `CP_still_breastfeeding = 1` (applied last, so it
  wins; a child breastfeeding now was obviously ever breastfed — overrides ~57
  stray `ever=0` rows);
- `0` never breastfed — `CP_ever_breastfed = 0` (and not currently);
- `1` ever breastfed but stopped/weaned — `CP_ever_breastfed = 1 AND CP_still_breastfeeding = 0`;
- `NULL` indeterminate — ever unknown & not-current, or `ever=1` with `still` unknown.

### Result
1,217,377 rows / **241 datasets** (= union of ever & still). Distribution:
0 never = 54,847 · 1 weaned = 642,319 · 2 currently = 520,211. Values {0,1,2}.

### DB / Parquet: ✅ Done (2026-08-05)
Parquet snapshot `ch_merged.parquet.bak_p32`. DB updated in place via a single SQL
`CASE` identical to the pandas logic (pure function of two existing DB columns — no
reupload). `ind_que` mirrors the union of the ever/still provenance, `source_kind='derived'`.

### Code
`MICS-CH/src/patch_breastfeeding_status.py` — `_derive()` / `CASE_SQL` (kept in
lock-step), `--verify`.

---

## P33 — `CP_child_age_months` (CH), rebuilt from raw — coverage 42 → 248

**Date:** 2026-08-13 · **Module:** CH · **Column:** `CP_child_age_months`

### Problem
`CP_child_age_months` carried the merged `child_age_months`, populated for only
**42 datasets**. The historical alignment had mapped `child_age_months` to a
grab-bag of raw columns (age BANDS like `CAGE_6`/`CAGE_11`, DOB CMC, line numbers)
and produced a valid 0-59 month value for almost none — even though the raw child
SAVs nearly universally carry **`CAGE` = "Age (months)"** (0-59), plus the survey
and birth date components needed to back-calculate it.

### Fix (rebuild from raw, per your spec)
Per child, take the first available:
1. **`CAGE`** — child's age in completed months (label "Age (months)"/"Âge (mois)"/
   "Edad (meses)"), kept when 0-59. Present in ~248 datasets.
2. **date back-calculation** — `interview_cmc − birth_cmc`, cmc = (year−1900)·12+month:
   - MICS4/5: interview `UF8M`/`UF8Y`, birth `AG1M`/`AG1Y`
   - MICS6:   interview `UF7M`/`UF7Y`, birth `UB1M`/`UB1Y`
   Calendar-guarded (year 1990-2025, month 1-12 → drops 9999/9997 sentinels), kept
   when 0-60 (60 = 5y boundary → clamped to 59). Used only where CAGE is absent/null.
3. existing `child_age_months` — final fallback.

Guarded positional backfill — a dataset is written only if **row-count matches**,
the values form a **real 0-59 scale** (max ≥ 48 — excludes Cuba's `cage` capped at
23 and Indonesia-2000's constant 1), and the **rows are aligned**: household id
matches ≥ 99.9%, OR (for datasets whose household id was recoded — Kosovo, Argentina,
Montenegro, …) `age//12` agrees with `child_age_years` ≥ 90%. `child_age_years` can
only *confirm* alignment, never veto it, because it is itself broken for several
datasets (see below).

### Result
**42 → 248 datasets**, 278,913 → **1,625,468 rows**, range 0-59 (mean 29.3). Global
`age//12 == child_age_years` agreement 0.96. Skipped (7): Cuba-06 & Indonesia-2000
(miscoded `cage`), Kyrgyzstan-05 (SAV row order misaligned), Myanmar-2000 (no
alignment anchor), CAR-2000 (no CAGE/date) + Guyana/Iraq-2000 (no SAV).

### Side finding (not fixed here)
`child_age_years` is broken (all-zero, or only 1-2 year values) for ~12 datasets —
e.g. **Malawi / Sierra Leone / Uzbekistan MICS6, Guinea MICS5, Philippines 1999,
Lao PDR 2006, Palestinians-in-Lebanon 2006**. For these, `CP_child_age_months` is
now the reliable age variable. Logged separately in `_data_issues`.

### DB / Parquet: ✅ Done (2026-08-13)
Parquet snapshot `ch_merged.parquet.bak_p33`. DB rebuilt via `TRUNCATE` + grouped
`COPY` (1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind
`derived`, raw `CAGE`).

### Code
`MICS-CH/src/patch_child_age_months.py` — `_from_raw()` (CAGE + CMC date, guards),
`_cmc()`, `--verify`. Scan: `src/scan_child_age.py`.

---

## P34 — `CP_fed_grains_yesterday` (CH), harmonized + recovered from BD8C

**Date:** 2026-08-13 · **Module:** CH · **Column:** `CP_fed_grains_yesterday`

### Problem
The 24-hour grains food-group question — **`BD8C`** "Child ate bread, rice, noodles,
porridge or other foods made from grains yesterday" — was mapped (as
`infant_fed_grains_yesterday`) for only **55 datasets**, though `BD8C` is present in the
raw SAV of **115**. The 60 unmapped ones carry non-English labels (French "aliments
faits à base de grains", Spanish "Alimentos elaborados con granos", Portuguese
"alimentos feitos a partir de grãos"). Separately, `dd_grains` is contaminated: it maps
BD8C for most datasets but for ~16 points to mis-aligned raw columns — `BD7C` clear
broth, `BD7O` rice water, `BD7X` watery porridge, `BD8E` roots/cassava, `BD8P` sweets,
`CI3B` diarrhoea gruel, `BF15` thin porridge — so it cannot serve as a clean grains flag.

### Fix (BD8C only)
`CP_fed_grains_yesterday` = harmonized `BD8C`: 1=Yes → 1, 2=No → 0, sentinels (7
incoherent, 8/9 DK/missing) → NULL. Base 55 mapped datasets updated in place; **59
more recovered** from the raw SAV by guarded positional backfill (row-count match +
`household_number` == SAV HH id ≥ 99.9%), value classified from that column's own
multilingual labels. **BD8C-only** keeps the construct identical across datasets — the
MICS4 grains items under other codes (DD1F/BF16A/BF19A/BF15, and thin-porridge BF15)
were deliberately excluded from this scope.

### Result
**55 → 114 datasets**, **400,584 rows**, values {0,1}, global ate-grains rate 0.64
(e.g. Nepal 0.79, Thailand 0.80, Nigeria 0.70). 1 skipped: Kosovo-Roma MICS5
(household guard 98.2% — same recoding issue as the breastfeeding batch).

### DB / Parquet: ✅ Done (2026-08-13)
Parquet snapshot `ch_merged.parquet.bak_p34`. Mapped datasets updated in place; 59
recovered datasets reinserted (DELETE + COPY). `ind_que` mirrored. CH rows preserved
(1,684,203 / 251).

### Code
`MICS-CH/src/patch_fed_grains_yesterday.py` — `_classify()` (multilingual yes/no),
`RECOVER` (60 BD8C datasets), `_recover()` / `_sav_dir()` (NFC/NFD-robust), `--verify`.

---

## P35 — `CP_fed_grain_based_fortified_baby_food_yesterday` (CH), from BD8B

**Date:** 2026-08-13 · **Module:** CH · **Column:** `CP_fed_grain_based_fortified_baby_food_yesterday`

### Problem
The commercial fortified baby-food item — **`BD8B`** (a.k.a. `BD8B1`) "Child ate
fortified baby food (cerelac, gerber, hero, nestum, etc.) yesterday" — was mapped (as
`infant_fed_fortified_baby_food`) for only **107 datasets**, though `BD8B` is present in
the raw SAV of **115**.

### Fix (BD8B only)
`CP_fed_grain_based_fortified_baby_food_yesterday` = harmonized `BD8B`: 1=Yes → 1,
2=No → 0, sentinels (7 incoherent, 8/9 DK/missing) → NULL. Base 107 mapped datasets
updated in place; **7 more recovered** from the raw SAV by guarded positional backfill
(row-count match + `household_number` == SAV HH id ≥ 99.9%), value classified from that
column's own multilingual labels (verified BD8B = fortified baby food across EN/FR/ES/PT,
no mis-labels). A broad label sweep found NO fortified-baby-food question outside BD8B —
it is a MICS5/6-only item, so 115 is the coverage ceiling.

### Result
**107 → 114 datasets**, **400,790 rows**, values {0,1}, global rate 0.12 (e.g. Dominican
Republic 0.49, Lesotho 0.08, Cameroon 0.06). 1 skipped: Kosovo-Roma MICS5 (household
guard 98.2% — same recoding issue as the breastfeeding/grains recoveries).

### DB / Parquet: ✅ Done (2026-08-13)
Parquet snapshot `ch_merged.parquet.bak_p35`. Mapped datasets updated in place; 7
recovered reinserted (DELETE + COPY). `ind_que` mirrored. CH rows preserved (1,684,203 / 251).

### Code
`MICS-CH/src/patch_fed_fortified_baby_food.py` — `_classify()` (multilingual yes/no),
`RECOVER` (8 BD8B datasets), `_recover()`/`_sav_dir()` (BD8B→BD8B1 fallback, NFC/NFD-robust),
`--verify`.

---

## P36 — `CP_fed_roots_tubers_plantains_yesterday` (CH), from BD8E

**Date:** 2026-08-13 · **Module:** CH · **Column:** `CP_fed_roots_tubers_plantains_yesterday`

### Problem
The white-roots-and-tubers food-group item — **`BD8E`** "Child ate white potatoes,
white yams, manioc, cassava or any other foods made from roots yesterday" (some datasets
also list plantains, e.g. Cuba "plátano verde") — existed only as `dd_white_roots_tubers`,
mapped for **94 datasets** though `BD8E` is present in the raw SAV of **115**.

### Fix (BD8E only)
`CP_fed_roots_tubers_plantains_yesterday` = harmonized: 1=Yes → 1, 2=No → 0, sentinels
(7/8/9) → NULL. Base = `dd_white_roots_tubers` (94 datasets: 93 from BD8E + 1 Madagascar-
South `BF15DX` "aliments à base de racines", verified roots) updated in place; **19 more
recovered** from the raw SAV by guarded positional backfill (row-count + `household_number`
== SAV HH id ≥ 99.9%), value classified from each column's own multilingual labels
(verified BD8E = white roots/tubers across EN/FR/ES/PT, all value labels yes/no).

**BD8E-only scope.** A broad look-behind found genuine MICS4 roots items under other
codes — Ghana `DD1H`, CAR `BF19C`, Mali `BF16C` — deliberately left out to keep the
construct identical (same choice as P34 grains).

### Result
**94 → 113 datasets**, **397,532 rows**, values {0,1}, global rate 0.30 (e.g. Paraguay
0.62, Congo 0.46, DRCongo 0.37). 3 skipped: Guinea Bissau MICS6 (household guard 0.9%)
and Sao Tome MICS6 ×2 (0.9% / 99.0%) — same recoding/misalignment issues seen in P33.

### DB / Parquet: ✅ Done (2026-08-13)
Parquet snapshot `ch_merged.parquet.bak_p36`. Mapped datasets updated in place; 19
recovered reinserted (DELETE + COPY). `ind_que` mirrored. CH rows preserved (1,684,203 / 251).

### Code
`MICS-CH/src/patch_fed_roots_tubers.py` — `_classify()` (multilingual yes/no), `RECOVER`
(22 BD8E datasets), `_recover()`/`_sav_dir()` (NFC/NFD-robust), `--verify`.

---

## P37 — `CP_fed_pulses_nuts_seeds_yesterday` (CH), rebuilt from raw BD8M

**Date:** 2026-08-13 · **Module:** CH · **Column:** `CP_fed_pulses_nuts_seeds_yesterday`

### Problem (contamination found)
The legumes/nuts food-group item is **`BD8M`** "Child ate beans, peas, lentils or nuts
or any food made from these, yesterday". The existing `dd_legumes_nuts` (101 datasets)
was silently **contaminated**: several datasets have multiple raw columns mapped to it in
`ind_que`, and the merge took the WRONG one for some — verified **Algeria MICS6
`dd_legumes_nuts` == `BD8G`** "figues, pommes, poires" (vitamin-A FRUIT, matches at 1.000;
BD8M only 0.78). Others carried `BD7D` infant formula or `IM8`/`IM12` immunization columns.
Additionally **Pakistan-KP MICS5**'s `BD8M` is actually labelled "other solid food" — its
food-group letters are shifted (legumes live under `BD8K`).

### Fix (rebuild fresh from raw — do NOT trust the merged column)
`CP_fed_pulses_nuts_seeds_yesterday` read per dataset directly from the raw SAV:
1. read `BD8M`; require its **variable label to be legumes/nuts** (excludes the shifted /
   mislabelled cases) and the rows to align (SAV row count == parquet; `household_number`
   == SAV HH id ≥ 99.9%); classify from BD8M's own multilingual labels (1→1, 2→0, 7/8/9→NULL);
2. two shifted-letter datasets read from their real legumes column: Pakistan-KP `BD8K`,
   Madagascar-South `BF15LX`;
3. for **single-BD8M-source** datasets whose raw re-read fails only the household guard
   (id-recoded: Kosovo/Montenegro MICS6), keep the merged `dd_legumes_nuts` value — it is
   trustworthy there (only one source, so no wrong-column risk).

### Result
**112 datasets**, **397,239 rows**, values {0,1}, global rate 0.19 (Nepal 0.37, Montenegro
0.19, Ghana 0.13). Algeria now reads BD8M legumes instead of BD8G fruit. 4 skipped:
Guinea Bissau MICS6, N. Macedonia-Roma MICS6, Sao Tome MICS6 ×2 (multi-source AND household
guard fail — cannot safely resolve).

### DB / Parquet: ✅ Done (2026-08-13)
Parquet snapshot `ch_merged.parquet.bak_p37`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8M).

### Code
`MICS-CH/src/patch_fed_pulses_nuts.py` — `_from_raw()` (BD8M + legumes-label + household
guard), `_single_bd8m_datasets()` (trusted fallback), `SPECIAL` (BD8K/BF15LX), `--verify`.

---

## P38 — `CP_fed_yogurt_yesterday` (CH), rebuilt from raw (BD8A + BD7F)

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_yogurt_yesterday`

### Problem (contamination found)
`infant_fed_yogurt_yesterday` (148 datasets) was contaminated: most datasets map it to
BOTH the yes/no item AND its **times-count companion** — `BD8A`/`BF13` "drank or ate
yogurt" (1/2) plus `BD8A1`/`BD8AN`/`BF14` "Times drank or ate yogurt" (values 3/4/7
leaked in). A few datasets also had cheese / mixed-dairy / diarrhoea-liquid columns
mapped to it.

### Fix (rebuild fresh from raw, label-driven, OR-combined)
`CP_fed_yogurt_yesterday` read per dataset from the raw SAV: select **every** column
whose label is yogurt AND is a yes/no item, and OR-combine (yes if any yogurt item is
yes) — capturing both the eaten and drunk forms:
- `BD8A` "Child drank or ate yogurt yesterday" (MICS5/6, already covers both forms);
- `BD7F`/`BD7F2` "drank (sweet) yogurt / ayran / kefir yogurt drinks" (MICS6-2023 split
  the liquid form out; Algeria "yaourt liquide");
- `BF13` "L'enfant a bu ou mangé des yaourts hier" (MICS4);
- `BF3I` "Child received yogurt", `ca2e` "Yoghurt drink".
Excluded by label: **times-count** companions (times/nombre/fois/number), **cheese /
mixed dairy** ("cheese, yogurt or other milk products"; "fromage ou yaourt"; Mexico
"…excepto yogurt"), and **diarrhoea catch-all liquids** ("Other (yogurt, sour milk,
tea, sugar…)"; "autre liquide"). Value 1→1, 2→0, 7/8/9→NULL. Guard: row count +
`household_number` == SAV HH id ≥ 99.9%.

### Result
**148 → 155 datasets**, **715,487 rows**, values strictly {0,1} (times-counts gone),
global rate 0.19 (Algeria 0.54, Nepal 0.09, Lao-2023 0.03). 9 skipped: id-recoded MICS6
(Kosovo/Montenegro/N.Macedonia/Sao Tome/Guinea Bissau) + Moldova MICS4 (household guard).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p38`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`).

### Code
`MICS-CH/src/patch_fed_yogurt.py` — `_select_cols()` (yogurt yes/no, excl counts/cheese/
catch-alls), `_from_raw()` (OR-combine + household guard), `--verify`.

---

## P39 — `CP_fed_cheese_other_dairy_yesterday` (CH), rebuilt from raw BD8N

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_cheese_other_dairy_yesterday`

### Problem
The cheese/other-milk-food group is **`BD8N`** "Child ate cheese or other food made from
milk yesterday" (distinct from yogurt [P38] and milk-drinking [P31]). The existing
`dd_dairy` covered only **54 datasets** though `BD8N` is present in **114**, and it was
contaminated for multi-source datasets — Cameroon/CAR `dd_dairy` == `BD8A` yogurt (Cameroon
old rate 0.070 yogurt vs true cheese 0.023), Georgia == `BD7P`/`BD7Q1`.

### Fix (rebuild fresh from raw BD8N)
Read per dataset from the raw SAV: require `BD8N` present AND its label to be a cheese /
"food made from milk" item; SAV row count == parquet; `household_number` == SAV HH id ≥
99.9%. Value classified from BD8N's own multilingual labels (1→1, 2→0, 7/8/9→NULL). Two
shifted-letter cheese items read from their real column (Pakistan-KP `BD8L`, Madagascar-
South `BF15MX`); single-BD8N id-recoded datasets kept from the merged value.

### Result
**54 → 112 datasets**, **401,469 rows**, values {0,1}, global rate 0.12 (Algeria 0.35,
Pakistan-KP 0.11, Nepal 0.05). 4 skipped: Kosovo/Montenegro/N. Macedonia-Roma MICS6
(unmapped dd_dairy + household guard fail). Mixed cheese+yogurt MICS4 items (Cameroon-2006
bf3i, CAR BF19L, Ghana DD1Q) left out to avoid double-counting yogurt.

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p39`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8N).

### Code
`MICS-CH/src/patch_fed_cheese.py` — `_from_raw()` (BD8N + cheese-label + household guard),
`SPECIAL` (BD8L/BF15MX), `_single_bd8n_datasets()` (trusted fallback), `--verify`.

---

## P40 — `CP_fed_organ_meat_yesterday` (CH), rebuilt from raw BD8I

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_organ_meat_yesterday`

### Problem
The organ-meat food group is **`BD8I`** "Child ate liver, kidney, heart or other organ
meat yesterday". `dd_organ_meat` (100 datasets) is single-source but one dataset's BD8I is
mislabelled: **Pakistan-KP MICS5 `BD8I` == "Child ate eggs"** — its food-group letters are
shifted (BD8H meat / BD8I eggs / BD8J fish …) and it has no separate organ-meat item, so
its `dd_organ_meat` value was actually eggs. BD8I is present in **115** raw SAVs vs 100 mapped.

### Fix (rebuild fresh from raw BD8I)
Read per dataset from the raw SAV: require `BD8I` present AND its label to be an organ-meat
item (liver/kidney/heart/foie/rognon/abats/vísceras…); SAV row count == parquet;
`household_number` == SAV HH id ≥ 99.9%. Value classified from BD8I's own multilingual
labels (1→1, 2→0, 7/8/9→NULL). Madagascar-South MICS4 reads its shifted column `BF15HX`.

### Result
**100 → 107 datasets**, **382,785 rows**, values {0,1}, global rate 0.06 (Nepal 0.08,
Algeria 0.05, Madagascar 0.01). Pakistan-KP correctly excluded (BD8I=eggs). 8 more skipped:
id-recoded MICS6 (Guinea Bissau/Kosovo/Montenegro/N. Macedonia-Roma/Sao Tome, household
guard). Overlooked MICS4 organ-meat under other codes (Ghana DD1L, CAR BF19G, Mali BF16G)
left out (BD8I-only scope).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p40`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8I).

### Code
`MICS-CH/src/patch_fed_organ_meat.py` — `_from_raw()` (BD8I + organ-label + household guard),
`SPECIAL` (Madagascar BF15HX), `_single_bd8i_datasets()`, `--verify`.

---

## P41 — `CP_fed_meat_poultry_yesterday` (CH), rebuilt from raw BD8J

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_meat_poultry_yesterday`

### Problem
The flesh-meat/poultry group is **`BD8J`** "Child ate meat, such as beef, pork, lamb, goat,
chicken, duck yesterday". `dd_meat_poultry` (102 datasets) is mis-sourced for a few:
**Pakistan-KP MICS5 `BD8J` == "fresh or dried fish"** (its BD8x letters are shifted; its meat
is `BD8H`), and **Vietnam MICS4** came from `BF9` "meat SOUP/broth" (a liquid, not meat-eating).
BD8J is present in **115** raw SAVs.

### Fix (rebuild fresh from raw BD8J)
Read per dataset from the raw SAV: require `BD8J` present AND its label to be a flesh-meat item
(meat/beef/pork/lamb/goat/chicken/duck/viande/carne…, excluding soup/broth); SAV row count ==
parquet; `household_number` == SAV HH id ≥ 99.9%. Value 1→1, 2→0, 7/8/9→NULL. Shifted-letter
datasets read their real meat column: Pakistan-KP `BD8H`, Madagascar-South `BF15IX`.

### Result
**102 → 108 datasets**, **395,465 rows**, values {0,1}, global rate 0.26 (Algeria 0.27,
Nepal 0.14, Pakistan-KP 0.12, Madagascar 0.14). Pakistan-KP correctly reads meat (BD8H) not
fish; Vietnam MICS4 broth excluded. 8 skipped: id-recoded MICS6 (household guard). Overlooked
MICS4 meat under other codes (Ghana DD1M) left out (BD8J-only scope); Mongolia/Vietnam BF9
"meat soup" is broth, not meat-eating.

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p41`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8J).

### Code
`MICS-CH/src/patch_fed_meat_poultry.py` — `_from_raw()` (BD8J + meat-label excl broth +
household guard), `SPECIAL` (Pakistan-KP BD8H / Madagascar BF15IX), `--verify`.

---

## P42 — `CP_fed_fish_seafood_yesterday` (CH), rebuilt from raw BD8L

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_fish_seafood_yesterday`

### Problem
The fish/seafood group is **`BD8L`** "Child ate fresh or dried fish or shellfish yesterday".
`dd_fish_seafood` (100 datasets) is mis-sourced for a few: **Pakistan-KP MICS5 `BD8L` ==
"cheese"** (its BD8x letters are shifted; its fish is `BD8J`), and **Guyana MICS6** is
multi-source (`BD7C` broth + `BD8L`). BD8L is present in **115** raw SAVs.

### Fix (rebuild fresh from raw BD8L)
Read per dataset from the raw SAV: require `BD8L` present AND its label to be a fish/seafood
item (fish/seafood/shellfish/poisson/pescado/mariscos…); SAV row count == parquet;
`household_number` == SAV HH id ≥ 99.9%. Value 1→1, 2→0, 7/8/9→NULL. Shifted-letter datasets
read their real fish column: Pakistan-KP `BD8J`, Madagascar-South `BF15KX`.

### Result
**100 → 108 datasets**, **395,904 rows**, values {0,1}, global rate 0.18 (Bangladesh 0.25,
Guyana 0.18, Madagascar 0.17, Nepal 0.02, Pakistan-KP 0.01). Pakistan-KP correctly reads fish
(BD8J) not cheese; Guyana reads BD8L not BD7C broth. 8 skipped: id-recoded MICS6 (household guard).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p42`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8L).

### Code
`MICS-CH/src/patch_fed_fish.py` — `_from_raw()` (BD8L + fish-label + household guard),
`SPECIAL` (Pakistan-KP BD8J / Madagascar BF15KX), `--verify`.

---

## P43 — `CP_fed_eggs_yesterday` (CH), rebuilt from raw BD8K

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_eggs_yesterday`

### Problem
The eggs group is **`BD8K`** "Child ate eggs yesterday". `dd_eggs` (101 datasets) is
mis-sourced for a few: **Pakistan-KP MICS5 `BD8K` == "beans/legumes"** (its BD8x letters are
shifted; its eggs are `BD8I`), and **Azerbaijan MICS6-2023** is multi-source (`BD8F1` + `BD8K`).
BD8K is present in **115** raw SAVs.

### Fix (rebuild fresh from raw BD8K)
Read per dataset from the raw SAV: require `BD8K` present AND its label to be an eggs item
(egg/oeuf/huevo/ovo); SAV row count == parquet; `household_number` == SAV HH id ≥ 99.9%.
Value 1→1, 2→0, 7/8/9→NULL. Shifted-letter datasets read their real eggs column: Pakistan-KP
`BD8I`, Madagascar-South `BF15JX`.

### Result
**101 → 107 datasets**, **379,598 rows**, values {0,1}, global rate 0.22 (Pakistan-KP 0.28,
Ghana 0.14, Nepal 0.13, Madagascar 0.03). Pakistan-KP correctly reads eggs (BD8I) not legumes.
8 skipped: id-recoded MICS6 (household guard).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p43`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8K).

### Code
`MICS-CH/src/patch_fed_eggs.py` — `_from_raw()` (BD8K + egg-label + household guard),
`SPECIAL` (Pakistan-KP BD8I / Madagascar BF15JX), `--verify`.

---

## P44 — `CP_fed_vitamin_a_vegetables_yesterday` (CH), rebuilt from raw BD8D

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_vitamin_a_vegetables_yesterday`

### Problem
The vitamin-A-rich vegetable group is **`BD8D`** "Child ate pumpkin, carrots, squash etc.
that are yellow or orange inside yesterday". `dd_vitamin_a_veg` (100 datasets) is multi-source
for **Fiji / Georgia MICS6** (BD7B1/BD7B2 liquids mixed with BD8D). BD8D is present in **115**
raw SAVs; unlike later letters it has no shift issue (BD8D is correct even for Pakistan-KP).

### Fix (rebuild fresh from raw BD8D)
Read per dataset from the raw SAV: require `BD8D` present AND its label to be a vit-A vegetable
item (pumpkin/carrot/squash/sweet potato/yellow-orange…); SAV row count == parquet;
`household_number` == SAV HH id ≥ 99.9%. Value 1→1, 2→0, 7/8/9→NULL.

### Result
**100 → 107 datasets**, **393,014 rows**, values {0,1}, global rate 0.19 (Fiji 0.50, Georgia
0.34, Pakistan-KP 0.12, Nepal 0.09). Fiji/Georgia now read BD8D not the BD7B liquids. 8 skipped:
id-recoded MICS6 (household guard). Madagascar-South BF15CX (yellow/orange "inside" foods)
conflates veg+fruit and was left out.

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p44`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8D).

### Code
`MICS-CH/src/patch_fed_vitamin_a_veg.py` — `_from_raw()` (BD8D + vit-A-veg label + household
guard), `_single_bd8d_datasets()`, `--verify`.

---

## P45 — `CP_fed_dark_green_leafy_vegetables_yesterday` (CH), rebuilt from raw BD8F

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_dark_green_leafy_vegetables_yesterday`

### Problem
The dark-green-leafy-vegetable group is **`BD8F`** "Child ate green leafy vegetables yesterday"
in the STANDARD MICS6. `dd_green_leafy_veg` covered only **92 datasets**. The food-group
letters differ by questionnaire version: the letter-shifted **Pakistan-KP MICS5** has NO
green-leafy item at all and its `BD8F` is vitamin-A FRUIT (mangoes/papaya).

### Fix (rebuild fresh from raw BD8F)
Read per dataset from the raw SAV: require `BD8F` present AND its label to be a green-leafy
item — multilingual (green leafy / dark green / spinach / broccoli / Swiss chard / kale /
collard / feuilles vertes / légumes à feuilles / hoja verde / verdura de hoja / couve /
repolho / folhas). SAV row count == parquet; `household_number` == SAV HH id ≥ 99.9%. Value
1→1, 2→0, 7/8/9→NULL. Madagascar-South MICS4 reads `BF15EX`. Pakistan-KP `BD8F` (mango) is
rejected by the label guard.

### Result
**92 → 107 datasets**, **383,349 rows**, values {0,1}, global rate 0.26 (Nepal 0.48, El
Salvador 0.28, Cuba 0.12, Guinea Bissau 0.04). Recovered Spanish/Portuguese-labelled datasets
(Cuba, El Salvador, Guinea Bissau, Sao Tome MICS5) that a strict English regex missed.
8 skipped: id-recoded MICS6 (household guard); Pakistan-KP excluded (no green-leafy item).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p45`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8F).

### Code
`MICS-CH/src/patch_fed_green_leafy.py` — `_from_raw()` (BD8F + multilingual green-leafy label +
household guard), `SPECIAL` (Madagascar BF15EX), `--verify`.

---

## P46 — `CP_fed_vitamin_a_fruits_yesterday` (CH), rebuilt from raw BD8G

**Date:** 2026-08-14 · **Module:** CH · **Column:** `CP_fed_vitamin_a_fruits_yesterday`

### Problem
The vitamin-A-rich fruit group is **`BD8G`** "Child ate ripe mangoes, papayas etc. any other
vitamin-A-rich fruits yesterday" (locally adapted: mango/papaya in the tropics, apricot/melon/
persimmon in temperate regions; Algeria uses local figs/apples framed as vit-A fruit).
`dd_vitamin_a_fruit` covered only **65** of 115 BD8G datasets. Letter-shift: **Pakistan-KP
MICS5 `BD8G`** is "any other fruits or vegetables" (its vit-A fruit is `BD8F`).

### Fix (rebuild fresh from raw BD8G)
Read per dataset from the raw SAV: require `BD8G` present AND its label to be a vit-A-fruit item
(multilingual — mango/mangue/manga/papaya/papaye/apricot/melon/persimmon/guava/"riches en
Vitamine A"/mûres/maduro…). SAV row count == parquet; `household_number` == SAV HH id ≥ 99.9%.
Value 1→1, 2→0, 7/8/9→NULL. Shifted-letter datasets read their real vit-A fruit column
(Pakistan-KP `BD8F`, Madagascar-South `BF15FX`).

### Result
**65 → 108 datasets** (largest recovery in the food-group series), **395,655 rows**, values
{0,1}, global rate 0.15 (Algeria 0.15, Cameroon 0.12, Nepal 0.05, Pakistan-KP 0.03). 7 skipped:
id-recoded MICS6 (household guard).

### DB / Parquet: ✅ Done (2026-08-14)
Parquet snapshot `ch_merged.parquet.bak_p46`. DB rebuilt via `TRUNCATE` + grouped `COPY`
(1,684,203 rows / 251 datasets preserved). `ind_que` mirrored (source_kind `derived`, BD8G).

### Code
`MICS-CH/src/patch_fed_vitamin_a_fruit.py` — `_from_raw()` (BD8G + multilingual vit-A-fruit
label + household guard), `SPECIAL` (Pakistan-KP BD8F / Madagascar BF15FX), `--verify`.
