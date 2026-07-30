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
