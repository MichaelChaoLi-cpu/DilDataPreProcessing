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
