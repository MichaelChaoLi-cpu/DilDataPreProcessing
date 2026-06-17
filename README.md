# DilDataPreProcessing

> 中文版请见 [README_ZH.md](README_ZH.md)

This repository preprocesses survey microdata from the UNICEF Multiple Indicator Cluster Surveys (MICS) into analysis-ready datasets. The goal is to produce harmonised, cross-comparable data that maps each question from every survey wave and country to a stable canonical variable.

---

## Chapter 1 — MICS Household Questionnaire (MICS-HH)

### Overview

MICS household questionnaires (`hh.sav`) have been collected across six survey rounds (MICS2–MICS6) covering more than 100 countries. The same concept may appear under dozens of different column names or in different languages depending on the country and round. This module produces a single merged dataset in which every column corresponds to one canonical variable.

**Current scale**

| Item | Count |
|------|-------|
| Datasets processed | 255 |
| Canonical variables | 298 |
| Alignment entries | 25,748 |
| Rows in merged dataset | 2,774,775 |

---

### Pipeline

```
raw .sav files
      │
      ▼
1. extract_hh_columns.py        Extract column metadata
      │
      ▼
2. translate_hh_yaml.py         Translate non-English labels → English  [LLM]
      │
      ▼
3. canonicalize_hh_columns.py   Map labels to canonical variable names  [rules]
      │
      ▼
4. dedup_hh_columns_v2.py       Flag duplicate columns within each questionnaire
      │
      ▼
5. align_hh_columns_v2.py       Align canonical variables across all datasets
      │
      ▼
6. analyze_unmapped_hh_columns.py   Cluster remaining unmapped variables  [optional]
      │
      ▼
7. merge_hh_to_parquet.py       Merge all .sav files into one parquet
      │
      ▼
8. upload_hh_to_postgres.py     Upload to PostgreSQL
```

---

### Step Details

#### Step 1 — Extract column metadata
**Script:** `MICS-HH/src/extract_hh_columns.py`  
**Input:** `{RAW_DATA_DIR}/{dataset}/hh.sav`  
**Output:** `MICS-HH/data/HH/raw/{dataset}/hh.yaml`

Reads every `hh.sav` using `pyreadstat` and writes each column's name, label, value labels, and variable type to a YAML file.

#### Step 2 — Translate labels
**Script:** `MICS-HH/src/translate_hh_yaml.py`  
**Input:** `data/HH/raw/{dataset}/hh.yaml`  
**Output:** `data/HH/translate/{dataset}/hh.yaml`, `data/HH/translate_embedding/{dataset}/hh.csv`

Calls an LLM to translate column labels that are not in English. Also generates embeddings used in later clustering. Datasets that are already in English are passed through unchanged.

#### Step 3 — Canonicalize
**Script:** `MICS-HH/src/canonicalize_hh_columns.py`  
**Rule engine:** `MICS-HH/src/canonical_hh.py`  
**Input:** `data/HH/translate/{dataset}/hh.yaml`  
**Output:** `data/HH/canonical/{dataset}/hh.yaml`

Applies deterministic rules to assign each column a `canonical_varname`. Key decisions:
- Standalone `Age` and `Sex` in a household questionnaire are treated as `age_of_household_head` and `sex_of_household_head`.
- Full date columns may be split into derived `interview_year`, `interview_month`, `interview_day`.
- Compound asset labels (e.g. `washing machine / dryer`) are not merged into simpler canonical names.
- Response-only labels (`other`, `dk`, `none`) are not assigned a canonical variable.

#### Step 4 — Deduplicate within questionnaires
**Script:** `MICS-HH/src/dedup_hh_columns_v2.py`  
**Input:** `data/HH/canonical/{dataset}/hh.yaml`  
**Output:** `data/HH/questionnaire_dedup_v2/{dataset}/dup.yaml`

Identifies columns within the same questionnaire that map to the same canonical variable. Marks each group with a `primary_source` and lists alternative sources. Does not drop columns — the decision is recorded for downstream steps to apply.

#### Step 5 — Align across datasets
**Script:** `MICS-HH/src/align_hh_columns_v2.py`  
**Input:** `data/HH/canonical/{dataset}/hh.yaml`  
**Output:** `data/HH/alignment_v2.yaml`, `data/HH/alignment_summary_v2.csv`

Aggregates all per-dataset canonical mappings into a single cross-questionnaire alignment dictionary. Each canonical variable lists every (dataset, raw column) pair that contributes to it.

#### Step 6 — Inspect unmapped variables *(optional)*
**Script:** `MICS-HH/src/analyze_unmapped_hh_columns.py`  
**Output:** `data/HH/unmapped_clusters.csv`, `data/HH/unmapped_cluster_examples.yaml`

Clusters translated labels that did not receive a canonical assignment, using the embeddings from Step 2. No LLM calls. Used to guide new rule additions.

#### Step 7 — Merge to parquet
**Script:** `MICS-HH/src/merge_hh_to_parquet.py`  
**Input:** raw `.sav` files + `alignment_v2.yaml` + `questionnaire_dedup_v2/`  
**Output:** `data/HH/processed_data/hh_merged.parquet`

Reads each `hh.sav`, renames columns to canonical names, coalesces duplicate columns (primary source first, NaN slots filled from alternatives), applies date derivation functions, and concatenates all datasets. The first column is `dataset_name`.

#### Step 8 — Upload to PostgreSQL
**Script:** `MICS-HH/src/upload_hh_to_postgres.py`  
**Database:** `localhost:5432 / mda`

| Table | Description |
|-------|-------------|
| `final_MICS2MICS6` | Merged household data (2,774,775 rows × 299 cols) |
| `ind_que_MICSMICS` | Variable index: canonical name, dataset, raw column, English label |

---

### Run Commands

```bash
# Full pipeline (from repository root)
uv run MICS-HH/src/extract_hh_columns.py
uv run MICS-HH/src/translate_hh_yaml.py
uv run MICS-HH/src/canonicalize_hh_columns.py
uv run MICS-HH/src/dedup_hh_columns_v2.py
uv run MICS-HH/src/align_hh_columns_v2.py
uv run MICS-HH/src/merge_hh_to_parquet.py
uv run MICS-HH/src/upload_hh_to_postgres.py
```

---

### Data Flow

```
RAW_DATA_DIR/                        (external drive, set in .env)
  {dataset}/hh.sav

MICS-HH/data/HH/
  raw/{dataset}/hh.yaml              column metadata
  translate/{dataset}/hh.yaml        English-translated labels
  translate_embedding/{dataset}/     embeddings for clustering
  canonical/{dataset}/hh.yaml        canonical assignments
  questionnaire_dedup_v2/{dataset}/  duplicate decisions
  alignment_v2.yaml                  cross-dataset alignment
  alignment_summary_v2.csv           summary statistics
  unmapped_clusters.csv              unmapped variable clusters
  processed_data/hh_merged.parquet   final merged dataset

PostgreSQL mda/
  final_MICS2MICS6                   merged data table
  ind_que_MICSMICS                   variable index table
```

---

## Chapter 2 — MICS Household Listing Questionnaire (MICS-HL)

### Overview

MICS household listing questionnaires (`hl.sav`) record one row per household member across all six survey rounds. Each person's line number, sex, age, relationship to head, education, and eligibility pointers for child and women modules are captured here. This module produces a single merged person-level dataset using the same pipeline as MICS-HH.

**Current scale**

| Item | Count |
|------|-------|
| Datasets processed | 228 |
| Canonical variables | 90 |
| Alignment entries | 9,914 |
| Rows in merged dataset | 11,747,970 |

---

### Pipeline

```
raw .sav files
      │
      ▼
1. extract_hl_columns.py        Extract column metadata
      │
      ▼
2. translate_hl_yaml.py         Translate non-English labels → English  [LLM]
      │
      ▼
3. canonicalize_hl_columns.py   Map labels to canonical variable names  [rules]
      │
      ▼
4. dedup_hl_columns_v2.py       Flag duplicate columns within each questionnaire
      │
      ▼
5. align_hl_columns_v2.py       Align canonical variables across all datasets
      │
      ▼
6. merge_hl_to_parquet.py       Merge all .sav files into one parquet
      │
      ▼
7. upload_hl_to_postgres.py     Upload to PostgreSQL
```

---

### Step Details

#### Step 1 — Extract column metadata
**Script:** `MICS-HL/src/extract_hl_columns.py`  
**Input:** `{RAW_DATA_DIR}/{dataset}/hl.sav`  
**Output:** `MICS-HL/data/HL/raw/{dataset}/hl.yaml`

Reads every `hl.sav` using `pyreadstat`. Supports country-prefixed filenames (e.g. `BHhl.sav`). Datasets without an `hl.sav` are logged and skipped.

#### Step 2 — Translate labels
**Script:** `MICS-HL/src/translate_hl_yaml.py`  
**Input:** `data/HL/raw/{dataset}/hl.yaml`  
**Output:** `data/HL/translate/{dataset}/hl.yaml`, `data/HL/translate_embedding/{dataset}/hl.csv`

Same approach as MICS-HH. When the LLM returns an empty response (e.g. due to safety filters), the original labels are kept for that batch.

#### Step 3 — Canonicalize
**Script:** `MICS-HL/src/canonicalize_hl_columns.py`  
**Rule engine:** `MICS-HL/src/canonical_hl.py`  
**Input:** `data/HL/translate/{dataset}/hl.yaml`  
**Output:** `data/HL/canonical/{dataset}/hl.yaml`

Person-level rule differences from MICS-HH:
- `Age` and `Sex` map to `age` and `sex` (not household-head variants).
- Covers eligibility pointers (`eligible_woman_line_number`, `mother_caretaker_line_number`), family links, education, child labour, and mosquito net variables.

#### Step 4 — Deduplicate within questionnaires
**Script:** `MICS-HL/src/dedup_hl_columns_v2.py`  
**Input:** `data/HL/canonical/{dataset}/hl.yaml`  
**Output:** `data/HL/questionnaire_dedup_v2/{dataset}/dup.yaml`

Identifies duplicate column groups within each questionnaire. 1,224 groups found across 230 datasets (540 `duplicate_candidate`, 679 `duplicate_needs_review`, 5 `derived_overlap`).

#### Step 5 — Align across datasets
**Script:** `MICS-HL/src/align_hl_columns_v2.py`  
**Input:** `data/HL/canonical/{dataset}/hl.yaml`  
**Output:** `data/HL/alignment_v2.yaml`, `data/HL/alignment_summary_v2.csv`

Aggregates per-dataset mappings into a single cross-questionnaire alignment dictionary. 90 canonical variables identified.

#### Step 6 — Merge to parquet
**Script:** `MICS-HL/src/merge_hl_to_parquet.py`  
**Input:** raw `.sav` files + `alignment_v2.yaml` + `questionnaire_dedup_v2/`  
**Output:** `data/HL/processed_data/hl_merged.parquet`

Same coalescing and derivation logic as MICS-HH. The first column is `dataset_name`.

#### Step 7 — Upload to PostgreSQL
**Script:** `MICS-HL/src/upload_hl_to_postgres.py`  
**Database:** `localhost:5432 / mda`

| Table | Description |
|-------|-------------|
| `final_HL_MICS2MICS6` | Merged person-level data (11,747,970 rows × 91 cols) |
| `ind_que_HL_MICSMICS` | Variable index: canonical name, dataset, raw column, English label |

---

### Run Commands

```bash
# Full pipeline (from repository root)
uv run MICS-HL/src/extract_hl_columns.py
uv run MICS-HL/src/translate_hl_yaml.py
uv run MICS-HL/src/canonicalize_hl_columns.py
uv run MICS-HL/src/dedup_hl_columns_v2.py
uv run MICS-HL/src/align_hl_columns_v2.py
uv run MICS-HL/src/merge_hl_to_parquet.py
uv run MICS-HL/src/upload_hl_to_postgres.py
```

---

### Data Flow

```
RAW_DATA_DIR/                        (external drive, set in .env)
  {dataset}/hl.sav

MICS-HL/data/HL/
  raw/{dataset}/hl.yaml              column metadata
  translate/{dataset}/hl.yaml        English-translated labels
  translate_embedding/{dataset}/     embeddings for clustering
  canonical/{dataset}/hl.yaml        canonical assignments
  questionnaire_dedup_v2/{dataset}/  duplicate decisions
  alignment_v2.yaml                  cross-dataset alignment
  alignment_summary_v2.csv           summary statistics
  processed_data/hl_merged.parquet   final merged dataset

PostgreSQL mda/
  final_HL_MICS2MICS6                merged person-level data table
  ind_que_HL_MICSMICS                variable index table
```

---

## Chapter 3 — MICS Children's Questionnaire (MICS-CH)

### Overview

MICS children's questionnaires (`ch.sav`) record one row per child under five across six survey rounds (MICS2–MICS6). Topics covered include child demographics, birth registration, early childhood education, vitamin A supplementation, breastfeeding and infant feeding, dietary diversity, diarrhea/ARI, malaria, immunization, anthropometry, child discipline, child functioning, water and sanitation, and household characteristics. This module produces a single merged child-level dataset using the same pipeline as MICS-HH and MICS-HL.

**Current scale**

| Item | Count |
|------|-------|
| Datasets processed | 254 |
| Canonical variables | 448 |
| Alignment entries | 58,088 |
| Rows in merged dataset | 1,684,203 |

---

### Pipeline

```
raw .sav files
      │
      ▼
1. extract_ch_columns.py        Extract column metadata
      │
      ▼
2. translate_ch_yaml.py         Translate non-English labels → English  [LLM]
      │
      ▼
3. canonicalize_ch_columns.py   Map labels to canonical variable names  [rules]
      │
      ▼
4. dedup_ch_columns_v2.py       Flag duplicate columns within each questionnaire
      │
      ▼
5. align_ch_columns_v2.py       Align canonical variables across all datasets
      │
      ▼
6. merge_ch_to_parquet.py       Merge all .sav files into one parquet
      │
      ▼
7. upload_ch_to_postgres.py     Upload to PostgreSQL
```

---

### Step Details

#### Step 1 — Extract column metadata
**Script:** `MICS-CH/src/extract_ch_columns.py`  
**Input:** `{RAW_DATA_DIR}/{dataset}/ch.sav`  
**Output:** `MICS-CH/data/CH/raw/{dataset}/ch.yaml`

Reads every `ch.sav` using `pyreadstat`. Supports country-prefixed filenames (e.g. `BHch.sav`, `CHch.sav`, `chAL.sav`). Datasets without a recognisable `ch.sav` are logged and skipped.

#### Step 2 — Translate labels
**Script:** `MICS-CH/src/translate_ch_yaml.py`  
**Input:** `data/CH/raw/{dataset}/ch.yaml`  
**Output:** `data/CH/translate/{dataset}/ch.yaml`, `data/CH/translate_embedding/{dataset}/ch.csv`

Same approach as MICS-HH. When the LLM returns an empty response (e.g. due to safety filters), the original labels are kept for that batch.

#### Step 3 — Canonicalize
**Script:** `MICS-CH/src/canonicalize_ch_columns.py`  
**Rule engine:** `MICS-CH/src/canonical_ch.py`  
**Input:** `data/CH/translate/{dataset}/ch.yaml`  
**Output:** `data/CH/canonical/{dataset}/ch.yaml`

Child-level rule engine covering all MICS child modules:
- **EC** — early childhood education and ECDI milestones
- **VA** — vitamin A supplementation
- **BF** — breastfeeding and infant feeding
- **DD** — dietary diversity (MICS5/6)
- **CA** — diarrhea and ARI
- **ML** — malaria
- **IM** — immunization (dates and recall)
- **AN** — anthropometry (height, weight, MUAC, WHO flags, BMI)
- **BR** — birth registration
- **CD** — child discipline (MICS5/6)
- **CF** — child functioning/disability (MICS6)
- **WS** — water and sanitation
- **HC** — household characteristics and assets

Overall recognition rate: 72.4% across 254 datasets (67,911 total entries, 49,166 recognised).

#### Step 4 — Deduplicate within questionnaires
**Script:** `MICS-CH/src/dedup_ch_columns_v2.py`  
**Input:** `data/CH/canonical/{dataset}/ch.yaml`  
**Output:** `data/CH/questionnaire_dedup_v2/{dataset}/dup.yaml`

Identifies duplicate column groups within each questionnaire. 8,252 groups found across 254 datasets (3,356 `duplicate_candidate`, 3,873 `duplicate_needs_review`, 1,023 `derived_overlap`).

#### Step 5 — Align across datasets
**Script:** `MICS-CH/src/align_ch_columns_v2.py`  
**Input:** `data/CH/canonical/{dataset}/ch.yaml`  
**Output:** `data/CH/alignment_v2.yaml`, `data/CH/alignment_summary_v2.csv`

Aggregates per-dataset mappings into a single cross-questionnaire alignment dictionary. 448 canonical variables identified.

#### Step 6 — Merge to parquet
**Script:** `MICS-CH/src/merge_ch_to_parquet.py`  
**Input:** raw `.sav` files + `alignment_v2.yaml` + `questionnaire_dedup_v2/`  
**Output:** `data/CH/processed_data/ch_merged.parquet`

Same coalescing and derivation logic as MICS-HH. The first column is `dataset_name`. 251 datasets merged successfully; 3 skipped due to missing or unreadable files.

#### Step 7 — Upload to PostgreSQL
**Script:** `MICS-CH/src/upload_ch_to_postgres.py`  
**Database:** `localhost:5432 / mda`

| Table | Description |
|-------|-------------|
| `final_CH_MICS2MICS6` | Merged child-level data (1,684,203 rows × 449 cols) |
| `ind_que_CH_MICSMICS` | Variable index: canonical name, dataset, raw column, English label |

---

### Run Commands

```bash
# Full pipeline (from repository root)
uv run MICS-CH/src/extract_ch_columns.py
uv run MICS-CH/src/translate_ch_yaml.py
uv run MICS-CH/src/canonicalize_ch_columns.py
uv run MICS-CH/src/dedup_ch_columns_v2.py
uv run MICS-CH/src/align_ch_columns_v2.py
uv run MICS-CH/src/merge_ch_to_parquet.py
uv run MICS-CH/src/upload_ch_to_postgres.py
```

---

### Data Flow

```
RAW_DATA_DIR/                        (external drive, set in .env)
  {dataset}/ch.sav

MICS-CH/data/CH/
  raw/{dataset}/ch.yaml              column metadata
  translate/{dataset}/ch.yaml        English-translated labels
  translate_embedding/{dataset}/     embeddings for clustering
  canonical/{dataset}/ch.yaml        canonical assignments
  questionnaire_dedup_v2/{dataset}/  duplicate decisions
  alignment_v2.yaml                  cross-dataset alignment
  alignment_summary_v2.csv           summary statistics
  processed_data/ch_merged.parquet   final merged dataset

PostgreSQL mda/
  final_CH_MICS2MICS6                merged child-level data table
  ind_que_CH_MICSMICS                variable index table
```

---

## Chapter 4 — MICS Women's Questionnaire (MICS-WM)

### Overview

MICS women's questionnaires (`wm.sav`) record one row per eligible woman (typically aged 15–49) across six survey rounds (MICS2–MICS6). Topics covered include woman background and education, marriage, birth history, fertility preferences, family planning, antenatal care, delivery, postnatal care, newborn cord care, early breastfeeding, child health, domestic violence, sexual behaviour, HIV/AIDS knowledge and testing, tobacco and alcohol, anthropometry, media exposure, wealth, household assets, functional difficulties, discrimination, menstrual hygiene, health insurance, water and sanitation, malaria prevention, migration, ethnicity and religion, and female genital mutilation. This module produces a single merged woman-level dataset using the same pipeline as MICS-HH, MICS-HL, and MICS-CH.

**Current scale**

| Item | Count |
|------|-------|
| Datasets processed | 254 |
| Canonical variables | 461 |
| Alignment entries | 47,589 |
| Rows in merged dataset | 2,960,835 |

---

### Pipeline

```
raw .sav files
      │
      ▼
1. extract_wm_columns.py        Extract column metadata
      │
      ▼
2. translate_wm_yaml.py         Translate non-English labels → English  [LLM]
      │
      ▼
3. canonicalize_wm_columns.py   Map labels to canonical variable names  [rules]
      │
      ▼
4. dedup_wm_columns_v2.py       Flag duplicate columns within each questionnaire
      │
      ▼
5. align_wm_columns_v2.py       Align canonical variables across all datasets
      │
      ▼
6. merge_wm_to_parquet.py       Merge all .sav files into one parquet
      │
      ▼
7. upload_wm_to_postgres.py     Upload to PostgreSQL
```

---

### Step Details

#### Step 1 — Extract column metadata
**Script:** `MICS-WM/src/extract_wm_columns.py`  
**Input:** `{RAW_DATA_DIR}/{dataset}/wm.sav`  
**Output:** `MICS-WM/data/WM/raw/{dataset}/wm.yaml`

Reads every `wm.sav` using `pyreadstat`. Datasets without a recognisable `wm.sav` are logged and skipped.

#### Step 2 — Translate labels
**Script:** `MICS-WM/src/translate_wm_yaml.py`  
**Input:** `data/WM/raw/{dataset}/wm.yaml`  
**Output:** `data/WM/translate/{dataset}/wm.yaml`

Same approach as MICS-HH. When the LLM returns an empty response (e.g. due to safety filters), the original labels are kept for that batch.

#### Step 3 — Canonicalize
**Script:** `MICS-WM/src/canonicalize_wm_columns.py`  
**Rule engine:** `MICS-WM/src/canonical_wm.py`  
**Input:** `data/WM/translate/{dataset}/wm.yaml`  
**Output:** `data/WM/canonical/{dataset}/wm.yaml`

Women-level rule engine covering all MICS women modules:
- **WB** — woman background, age, literacy, education
- **MA** — marriage and union status
- **BH** — birth history and child survival
- **FP** — family planning and contraceptive use
- **ANC** — antenatal care (provider type, frequency, content)
- **DL** — delivery and postnatal care
- **NC** — newborn cord care
- **BF** — breastfeeding initiation and prelacteals
- **CA** — child illness symptoms
- **DV** — domestic violence (physical, sexual, emotional, justification)
- **SB** — sexual behaviour
- **HA** — HIV/AIDS knowledge, testing, and counseling
- **TA** — tobacco and alcohol
- **AN** — anthropometry
- **MD** — media and communication
- **WI** — wealth and household assets
- **FD** — functional difficulties
- **MH** — menstrual hygiene
- **ML** — malaria prevention and net use
- **MG** — migration
- **FG** — female genital mutilation (FGM/C)

Overall recognition rate: 61.1% mean across 254 datasets (47,589 total recognised entries).

#### Step 4 — Deduplicate within questionnaires
**Script:** `MICS-WM/src/dedup_wm_columns_v2.py`  
**Input:** `data/WM/canonical/{dataset}/wm.yaml`  
**Output:** `data/WM/questionnaire_dedup_v2/{dataset}/dup.yaml`

Identifies duplicate column groups within each questionnaire. 4,806 groups found across 254 datasets (2,625 `duplicate_candidate`, 2,181 `duplicate_needs_review`, 0 `derived_overlap`).

#### Step 5 — Align across datasets
**Script:** `MICS-WM/src/align_wm_columns_v2.py`  
**Input:** `data/WM/canonical/{dataset}/wm.yaml`  
**Output:** `data/WM/alignment_v2.yaml`, `data/WM/alignment_summary_v2.csv`

Aggregates per-dataset mappings into a single cross-questionnaire alignment dictionary. 461 canonical variables identified.

#### Step 6 — Merge to parquet
**Script:** `MICS-WM/src/merge_wm_to_parquet.py`  
**Input:** raw `.sav` files + `alignment_v2.yaml` + `questionnaire_dedup_v2/`  
**Output:** `data/WM/processed_data/wm_merged.parquet`

Same coalescing and derivation logic as MICS-HH. The first column is `dataset_name`. 251 datasets merged successfully; 3 skipped due to missing or unreadable files.

#### Step 7 — Upload to PostgreSQL
**Script:** `MICS-WM/src/upload_wm_to_postgres.py`  
**Database:** `localhost:5432 / mda`

| Table | Description |
|-------|-------------|
| `final_WM_MICS2MICS6` | Merged women-level data (2,960,835 rows × 462 cols) |
| `ind_que_WM_MICSMICS` | Variable index: canonical name, dataset, raw column, English label |

---

### Run Commands

```bash
# Full pipeline (from repository root)
uv run MICS-WM/src/extract_wm_columns.py
uv run MICS-WM/src/translate_wm_yaml.py
uv run MICS-WM/src/canonicalize_wm_columns.py
uv run MICS-WM/src/dedup_wm_columns_v2.py
uv run MICS-WM/src/align_wm_columns_v2.py
uv run MICS-WM/src/merge_wm_to_parquet.py
uv run MICS-WM/src/upload_wm_to_postgres.py
```

---

### Data Flow

```
RAW_DATA_DIR/                        (external drive, set in .env)
  {dataset}/wm.sav

MICS-WM/data/WM/
  raw/{dataset}/wm.yaml              column metadata
  translate/{dataset}/wm.yaml        English-translated labels
  canonical/{dataset}/wm.yaml        canonical assignments
  questionnaire_dedup_v2/{dataset}/  duplicate decisions
  alignment_v2.yaml                  cross-dataset alignment
  alignment_summary_v2.csv           summary statistics
  processed_data/wm_merged.parquet   final merged dataset

PostgreSQL mda/
  final_WM_MICS2MICS6                merged women-level data table
  ind_que_WM_MICSMICS                variable index table
```

---
