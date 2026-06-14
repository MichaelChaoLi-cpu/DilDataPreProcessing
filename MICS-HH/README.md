# MICS-HH Variable Canonicalization Plan

This project aligns MICS household questionnaire variables so one canonical
variable name corresponds to one consistent question.

## Goal

The main problem is that MICS HH files reuse similar or identical column names
for different questions, and the same question may appear in different
languages or with different wording. The target output is a canonical HH
variable layer where comparable questions share a stable canonical name.

## Current Pipeline

1. Extract HH column metadata from `.sav` files.
   - Script: `src/extract_hh_columns.py`
   - Output: `data/HH/raw/.../hh.yaml`
   - Extracts column names, labels, value labels, and variable metadata.

2. Translate non-English labels to English.
   - Script: `src/translate_hh_yaml.py`
   - Output: `data/HH/translate/.../hh.yaml`
   - This is the LLM step when translation is needed.

3. Canonicalize translated labels with deterministic rules.
   - Script: `src/canonicalize_hh_columns.py`
   - Rule engine: `src/canonical_hh.py`
   - Output: `data/HH/canonical/.../hh.yaml`

4. Deduplicate within each questionnaire.
   - Script: `src/dedup_hh_columns_v2.py`
   - Output: `data/HH/questionnaire_dedup_v2/.../dup.yaml`
   - The dedup step marks duplicate or derived-overlap candidates but does not
     drop original columns.

5. Align canonical variables across datasets.
   - Script: `src/align_hh_columns_v2.py`
   - Outputs:
     - `data/HH/alignment_v2.yaml`
     - `data/HH/alignment_summary_v2.csv`

6. Inspect unmapped variables and expand rules gradually.
   - Script: `src/analyze_unmapped_hh_columns.py`
   - Output:
     - `data/HH/unmapped_clusters.csv`
     - `data/HH/unmapped_cluster_examples.yaml`
   - This step is rule/embedding analysis only and does not call LLM.

## Current Rules

Important canonicalization decisions:

- `automatic washing machine`, `semi-automatic washing machine`, and
  `washing machine` are treated as the same asset.
- Compound asset questions remain compound. For example,
  `washing machine / dryer` should not be merged into standalone
  `washing machine`.
- Full date variables may be split into derived year, month, and day variables.
- In HH questionnaires, standalone `Age` and `Sex` are treated as household
  head variables: `age_of_household_head` and `sex_of_household_head`.
- Context-free response options such as `other`, `none`, `dk`, `missing`, and
  `no response` should not become global canonical variables.

## Latest Status

Latest verified run:

- Total entries: 35,861
- Recognized/aligned entries: 25,748
- `needs_review`: 10,113
- Derived entries: 46
- Compound entries: 92
- Canonical alignment variables: 298

Remaining exact-label unmapped items appearing at least 20 times:

- `none`
- `other`
- `dk`
- `others`
- `no response`
- `missing`
- `private company`
- `non-governmental organization`

These are likely response options or context-dependent items, so they should not
be globally mapped without parent-question context.

## Run Commands

From the repository root:

```bash
.venv/bin/python MICS-HH/src/canonicalize_hh_columns.py --rerun
.venv/bin/python MICS-HH/src/dedup_hh_columns_v2.py --rerun
.venv/bin/python MICS-HH/src/align_hh_columns_v2.py
```

To inspect remaining unmapped variables:

```bash
.venv/bin/python MICS-HH/src/analyze_unmapped_hh_columns.py
```

## Next Plan

The rule expansion should continue in controlled rounds:

1. Recompute unmapped frequency after each canonicalization run.
2. Review high-frequency unmapped labels first.
3. Promote only safe question-level labels to deterministic rules.
4. Avoid global rules for response-only labels.
5. Add parent-question context for option-like columns, using neighboring
   columns, variable prefixes, or value-label metadata.
6. Re-run canonicalization, deduplication, and alignment after each rule batch.
7. Track recognized count, `needs_review` count, and canonical variable count
   after every round.

The next useful improvement is parent-child/context handling for labels such as
`private company` and `non-governmental organization`, which are not meaningful
as standalone HH variables without their parent question.
