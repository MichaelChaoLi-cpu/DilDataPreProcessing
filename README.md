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
