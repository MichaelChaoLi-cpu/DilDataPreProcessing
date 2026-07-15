# DilDataPreProcessing

Harmonization pipeline for UNICEF MICS survey microdata (MICS2–MICS6, 1999–2023,
~110 countries). Raw SPSS files → per-module merged parquet → PostgreSQL.

## Database (primary interface for analysis)

`localhost:5432 / mda / user lichao` (no password; params also in `.env`)

**The database is self-documenting — start there, not here:**

```sql
SELECT * FROM "_guide" ORDER BY position;   -- usage guide for agents
SELECT * FROM "_catalog";                   -- tables, grain, join keys, caveats
SELECT * FROM "_data_issues";               -- known problems + fix history (P01-P10)
```

Every column of every `final_*` table carries a `COMMENT` (visible via `\d+` or
`pg_description`). Per-dataset variable provenance: `ind_que_<MOD>_MICS` tables.

### Tables

| table | one row per | ~rows |
|---|---|---|
| `final_HH_MICS` | household | 2.8M |
| `final_HL_MICS` | household member | 11.7M |
| `final_WM_MICS` | woman 15–49 | 3.0M |
| `final_CH_MICS` | child under 5 | 1.7M |

Join on `dataset_name + cluster_number + household_number (+ line_number)`.
**Pitfalls**: WM calls the household id `hh_number`; key columns are TEXT in some
tables (cast to float); keys unique only within `dataset_name`.

### Prefer harmonized variables for cross-country work

`*_harmonized` (ISCED education 0–3, media frequency 0–3), `education_years` /
`mother_education_years` (+ `_estimated` flags), `child_age_years`,
`woman_age_group`, `sex_of_household_head`. Raw variables keep country-specific
codes and sentinel values (97/98/99 etc.) — harmonized ones have sentinels nulled.

## Repo layout

- `MICS-{WM,HH,HL,CH}/` — per-module pipeline: `src/` (extract → align → merge →
  upload + patch scripts), `data/<MOD>/raw/` (yaml metadata), `processed_data/*.parquet`
  (source of truth, DB is rebuilt from these)
- `DATA_PATCH_LOG.md` — full history of data corrections (P01–P10); every patch
  keeps DB and parquet in sync. Mirrored in `_data_issues` in the DB.
- `Research/` — analysis projects (reference only, e.g. MJ01b WASH study)
- `src/build_db_documentation.py` — rebuilds `_guide`/`_catalog` + column comments
  (re-run after adding variables; never drops `_data_issues`)

## Conventions for working here

- Python: use `.venv/bin/python` (repo root venv), NOT system/anaconda python.
- Raw SAV files live on the external drive `/Volumes/MikesDataBackup/MICS/raw`
  (path in `.env` as `DATA_RAW_DIR`); check it is mounted before raw-data work.
- Data corrections follow the patch pattern: numbered Pnn, scan script + patch
  script, parquet AND DB both updated, entry appended to `DATA_PATCH_LOG.md`,
  resolution recorded in `_data_issues`.
- DB re-uploads rebuild `ind_que_*` from `alignment_v2.yaml` — snapshot and
  re-insert patch-derived rows (see `sync_p09_to_db.py` for the pattern).
- Before fixing anything reported in `_data_issues`, mark it `confirmed`; after
  fixing, set `status='fixed'`, `resolution`, `patch_id`, `resolved_at`.
