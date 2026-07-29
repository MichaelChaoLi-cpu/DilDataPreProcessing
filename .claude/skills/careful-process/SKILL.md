---
name: careful-process
description: >
  Carefully process a MICS canonical variable into a CP_ ("carefully processed")
  column — clean sentinels/implausible values, optionally backfill/derive missing
  coverage, and keep parquet + PostgreSQL + docs in sync as a numbered patch (Pnn).
  Use whenever the user asks to "carefully process", "careful-process", "clean up",
  "increase alignment/coverage of", or build a CP_ version of a variable in this
  DilDataPreProcessing repo (e.g. "carefully process diarrhea_last_2_weeks").
  Encodes the investigate → review → validate → patch → verify → commit workflow
  refined across patches P11–P14.
---

# Careful-process a variable (CP_ patch)

Goal: turn a raw canonical variable into a trustworthy `CP_<name>` column, and
raise its coverage where that can be done **without introducing serious error**.
The original column is NEVER changed except by purely-additive backfill; all
cleaning lives in the CP_ copy (so prior projects still reproduce).

This is a **numbered data patch (Pnn)** — follow the repo's patch pattern:
parquet AND DB both updated, `ind_que_*` kept in sync, `DATA_PATCH_LOG.md` +
`_data_issues` + column comments updated, changes committed only on request.

## Conventions (don't relearn these each time)

- Python: `.venv/bin/python` (repo root venv). It has **no pip**; `numpy` yes,
  `scipy`/`pandas`/`psycopg2`/`pyreadstat`/`pyyaml` yes. Network works — fetch
  reference data via `urllib` and **embed it in the patch script** (the `data/`
  tree is gitignored, so external CSVs won't commit).
- DB: `psycopg2.connect(host="localhost",port=5432,dbname="mda",user="lichao")`.
  Identifiers are **case-sensitive → always double-quote** (`"final_WM_MICS"`).
- Tables: `final_{WM,HH,HL,CH}_MICS` (+ `ind_que_*`, `_guide`, `_catalog`,
  `_data_issues`). Keys unique only **within `dataset_name`**; some key columns
  are TEXT (cast to float); WM calls the hh id `hh_number`.
- Parquet is source of truth: `MICS-<MOD>/data/<MOD>/processed_data/<mod>_merged.parquet`.
- `CP_` = carefully processed (P11). New/altered vars get a `CP_` name and go in
  `CP_COLUMNS` in `src/build_db_documentation.py`.
- Raw SAVs: `$DATA_RAW_DIR` (`/Volumes/MikesDataBackup/MICS/raw/<dataset>/<mod>.sav`)
  — check mounted before raw work. Per-dataset column metadata: `data/<MOD>/raw/<ds>/<mod>.yaml`.

## Workflow

### 1. Investigate (read-only)
Find the column's table (search `information_schema.columns`). Report:
- coverage: non-null rows, **# datasets, and # countries** (extract country from
  `dataset_name` before "MICS"/year);
- value range + distribution (min/max/median/p99), sentinels (97/98/99, 999.99,
  9999…), negatives, zeros, implausible extremes;
- cross-variable consistency (e.g. CEB ≥ children_dead; age ≤ woman_age).
- **Beware artifacts**: a "violation" may come from the *other* variable's coding
  (e.g. `woman_age` stored as 5-yr group codes 1–7 made age_at_first_union look
  70% impossible). Recompute against a clean comparator before concluding.

Heavy `COUNT(DISTINCT)`/full-scan queries: run in background + Monitor; reading
the parquet columns is often faster than the DB.

### 2. Assess backfill / alignment options
For missing coverage, in order of trust:
- **Cross-module** (HL/HH/CH/WM): usually impossible — confirm which module
  *owns* the concept (grep each `alignment_v2.yaml`). Marriage/fertility/anthro
  are women/child-only.
- **Within-DB derivation** (e.g. sum of components, WHO z from weight/height):
  only if it **validates** (step 4). Components often don't reconstruct totals
  (CEB sons/daughters ≈16% exact → rejected).
- **Raw-SAV rescan** for an unmapped column: write a `scan_<var>.py` that
  label-matches (names are reused across rounds, so match on labels, multilingual
  EN/FR/ES/PT), reports candidates **without changing data**, and validate the
  candidate's distribution by reading the SAV.

### 3. Review checkpoint (ask before changing data)
Present findings and use `AskUserQuestion` for the real decisions:
- **clean range** (e.g. keep [8,49] / [0,20] / |z|≤6; whether to null cross-var
  inconsistencies);
- **backfill scope** ("scan only, don't modify" vs "scan + backfill");
- **inclusion threshold** when deriving.
Recommend an option; don't over-ask settled points. Wait for the answer.

### 4. Validate — the serious-error gate (for any derivation/backfill)
NEVER ship derived/backfilled values without a gate:
- **Method check**: recompute on rows that ALREADY have the value; report median
  |diff| / % within tolerance / correlation. Ship only if it reproduces them.
- **Per-dataset QC**: derived distributions can be garbage even when the method
  is sound (uncleaned input sentinels). Clean inputs first, then per NEW dataset
  check n / drop-rate / mean / SD; **derive only datasets that pass** (e.g. SD
  0.7–1.8, drop ≤5%, |mean|≤1.5). Exclude the rest, keep them NULL, and REPORT
  which and why. Put the gate logic in-code so it's reproducible.
- **Positional backfill guard**: when aligning SAV rows to parquet by order
  (broken keys), require `hh_number == HH2` (or equivalent) 100% before writing;
  skip + report the dataset otherwise (Kyrgyzstan/Mozambique had broken keys).

### 5. Build the patch `MICS-<MOD>/src/patch_<var>.py`
- `CP_<var>` = cleaned copy; original unchanged (backfill is additive only).
- Add companion flags where useful: `_derived` / `_estimated` (1/0/NULL).
- Embed any reference table (e.g. WHO LMS) as a constant in the script.
- Idempotent; include a `--verify` mode.
- **parquet**: back up to `.bak_pNN` (only if absent), add columns, write.
- **DB**: `ALTER … ADD COLUMN`; in-place `UPDATE` for pure per-row transforms;
  for backfilled datasets with broken keys, **DELETE + re-insert from patched
  parquet** (coerce dtypes to the DB column types so COPY won't fail on "36.0"→
  BIGINT). Autocommit off, commit at end.
- **ind_que**: mirror base rows to `CP_<var>` (+ add provenance rows for
  backfilled datasets). Update `alignment_v2.yaml` (backup `.bak_pNN`) for new
  raw-column mappings so a full rebuild reproduces them.

### 6. Documentation (`src/build_db_documentation.py`)
- add `<var>` to `CP_COLUMNS[<table>]`;
- add CURATED comments for `<var>`, `CP_<var>`, and any flag column;
- add a `HISTORY` entry `("Pnn", table, "CP_<var>", problem, resolution)`;
- mention it in the `harmonized_variables` guide section.
Then rebuild docs (see step 8).

### 7. `DATA_PATCH_LOG.md`
Add the index row and a full `## Pnn — …` section: problem, investigation
(incl. what was rejected and why), fix, guard/exclusions, result
(rows/datasets/countries), DB/parquet status, code. Also upsert `_data_issues`
(patch_id=Pnn, status='fixed', resolution).

### 8. VACUUM + rebuild docs
A mass `UPDATE` bloats the table and triggers *throttled* autovacuum that can
starve later queries for a long time. So, after the patch: cancel any throttled
autovacuum and run a **manual `VACUUM (ANALYZE) "final_<MOD>_MICS"`** (full
speed), then run `.venv/bin/python src/build_db_documentation.py`. Chain these in
one background job.

### 9. Verify
Run `patch_<var>.py --verify`: CP_ present & equals the cleaned recompute in
parquet, DB non-null / #datasets / **out-of-range = 0**, `ind_que` CP_ rows,
parquet == DB. Report the numbers.

### 10. Confirm & commit
Summarize results (before/after coverage, countries, what was excluded and why).
**Commit only when the user asks.** This user commits per-patch and wants **no
`Co-Authored-By` line**. Parquet + `.bak_*` + `data/` CSVs are gitignored — only
scripts + `DATA_PATCH_LOG.md` + `build_db_documentation.py` get committed.

## Long-running work
parquet rewrites (100–190 MB) and full-table `UPDATE`s take minutes and buffer
stdout. Run them with `run_in_background` and watch with `Monitor` (grep the
progress lines). Don't fabricate results — wait for the completion notification.

## Reference patches
P12 `age_at_first_union` (positional backfill, 1 dataset), P13
`children_ever_born` (9-dataset recovery, guard skipped Kyrgyzstan), P14
`bmi_for_age_zscore` (WHO-2006 derivation with per-dataset QC gate, 33 in / 11
excluded). Read their `MICS-*/src/patch_*.py` + `DATA_PATCH_LOG.md` entries for
concrete templates.
