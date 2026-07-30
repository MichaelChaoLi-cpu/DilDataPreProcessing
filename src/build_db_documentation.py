"""
Build the in-database documentation layer, so that any agent connecting to
PostgreSQL can understand the data WITHOUT access to this repository.

Creates / refreshes:
  _guide        -- ordered markdown sections: start here (SELECT * ORDER BY position)
  _catalog      -- one row per data table: grain, keys, caveats
  _data_issues  -- issue tracker: external agents INSERT reports here;
                   this repo records resolutions (linked to DATA_PATCH_LOG ids).
                   Never dropped; seeded once with the P01-P10 history.
  COMMENT ON    -- every table and every column of the final_* tables
                   (auto-generated from ind_que_* labels + curated overrides)

Re-runnable: _guide/_catalog are rebuilt, comments overwritten; _data_issues
is only appended to.

Usage:
  python src/build_db_documentation.py
"""
from __future__ import annotations

from datetime import date

import psycopg2

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
TODAY = date.today().isoformat()

FINAL_TABLES = {
    "final_WM_MICS": "ind_que_WM_MICS",
    "final_HH_MICS": "ind_que_HH_MICS",
    "final_HL_MICS": "ind_que_HL_MICS",
    "final_CH_MICS": "ind_que_CH_MICS",
}

# ---------------------------------------------------------------------------
# _guide sections (markdown, English — written for consuming agents)
# ---------------------------------------------------------------------------

GUIDE_SECTIONS = [
    ("overview", """\
# MICS harmonized database (mda)

Pooled microdata from UNICEF MICS surveys (rounds MICS2-MICS6, 1999-2023,
~110 countries, 252 datasets). Each `final_*` table stacks all datasets;
`dataset_name` identifies the survey. Data are cross-sectional repeated
surveys, NOT a panel.

START HERE:
  SELECT * FROM "_catalog";                          -- what tables exist
  SELECT * FROM "_guide" ORDER BY position;          -- this guide
  SELECT * FROM "_data_issues" WHERE status='open';  -- known open problems

Column-level docs: every column of every final_* table carries a COMMENT
(visible via \\d+ in psql or information_schema/pg_description). Per-dataset
variable provenance lives in the ind_que_* tables (one row per dataset x
variable: raw SAV column name + English label)."""),

    ("tables_and_grain", """\
# Tables and grain

| table | one row per | typical use |
|---|---|---|
| final_HH_MICS | household | WASH, assets, household composition |
| final_HL_MICS | household member (roster) | education/demographics of ALL members |
| final_WM_MICS | woman 15-49 (interviewed) | fertility, health, media, education |
| final_CH_MICS | child under 5 | anthropometry, illness, care |
| final_NepalLivingStandardardSurvey2022 | separate survey (Nepal LSS 2022), not MICS-harmonized |

Row counts are in _catalog (refreshed on rebuild)."""),

    ("join_conventions", """\
# Join conventions

Within one dataset, tables link on cluster + household (+ line number):

  HH <-> HL/WM/CH:  (dataset_name, cluster_number, household_number)
  HL member <-> WM: (... , line_number)  -- WM also has woman_line_number
  CH -> mother:     CH.mother_caretaker_line_number = WM.line_number
                    (or HL.line_number for roster fallback)

PITFALLS:
- final_WM_MICS uses hh_number (NOT household_number) for the household id.
- Key columns are TEXT in some tables, DOUBLE PRECISION in others -> cast
  (e.g. cluster_number::float) before joining across tables.
- Keys are unique only WITHIN dataset_name; always join on dataset_name too.
- A few datasets have non-unique (cluster, household) keys (e.g.
  'Niger 2000 MICS_Datasets' in HH) -- deduplicate or skip them."""),

    ("coding_conventions", """\
# Coding conventions

- Sentinel/missing codes in RAW variables: 7/9, 97/98/99, 9997-9999 mean
  DK/refused/missing. Harmonized (*_harmonized, *_years) variables already
  have sentinels set to NULL; raw variables generally DO NOT.
- Sex variables: 1 = male, 2 = female (verified across all datasets, P10).
- Yes/no variables: usually 1 = yes, 2 = no. EXCEPTION: MICS2-era datasets
  (1999-2001) often use 0 = no, 1 = yes. Check per dataset before pooling.
- education_grade / highest_grade_completed mix two codings across datasets:
  grade-within-level (standard) vs cumulative class count (ex-Soviet and
  some francophone datasets). Use education_years instead for comparisons.
- *_estimated companion columns: 1 = value is a midpoint estimate, 0 = exact.
  Exclude or dummy them in measurement-sensitive analyses."""),

    ("harmonized_variables", """\
# Cross-dataset comparable (harmonized/derived) variables

These are safe to compare across countries; raw variables often are not.

WM: woman_age (15-49), woman_age_group (1-7 = 5yr bands),
    education_level_harmonized (0 none /1 primary /2 secondary /3 higher),
    media_tv/radio/newspaper_frequency_harmonized (0 never /1 <weekly
    /2 >=weekly /3 ~daily), education_years (+_estimated),
    CP_age_at_first_union (cleaned, valid 8-49; NULL=never-married),
    CP_children_ever_born (cleaned, valid 0-20),
    CP_first_birth_year (Gregorian CE 1950-2024; CMC-derived + calendar-harmonised),
    CP_age_at_first_birth (10-49; CMC-derived, +_estimated flag for year-level)
HL: education_years (+_estimated)
CH: child_age_years (0-4), child_age_months (0-59, only ~42 month-coded
    datasets), mother_education_harmonized (0-3 as above),
    mother_education_years (+_estimated),
    CP_bmi_for_age_zscore (cleaned |z|<=6 + WHO-2006 derived where missing;
    see CP_bmi_for_age_zscore_derived; WHO prefers WHZ for <5y),
    CP_diarrhea_last_2_weeks / CP_fever_last_2_weeks / CP_cough_last_2_weeks
    (harmonized 1=Yes/0=No; per-dataset label mapping)
HH: sex_of_household_head (1/2, cleaned)

Full change history: _data_issues (status='fixed', patch_id P01-P10) and
DATA_PATCH_LOG.md in the DilDataPreProcessing repository."""),

    ("cp_prefix", """\
# CP_ = carefully processed (naming convention, P11)

Any column whose NAME starts with CP_ is the "carefully processed" version of
a variable: its values are the deliberate product of a post-hoc patch
(cleaning, splitting, harmonization, derivation, or backfill) rather than a
coarse rename of the raw SPSS column. For cross-dataset analysis, PREFER the
CP_ columns.

Each CP_ column is a duplicate: the original un-prefixed column is retained
unchanged so earlier projects remain reproducible. The two hold identical
values today; they diverge only if a future patch revises the CP_ version.

Retrofitted (P11) for every column touched by P01-P10, e.g.
CP_woman_age, CP_education_level_harmonized, CP_education_years,
CP_mother_education_harmonized, CP_child_age_years, CP_sex_of_household_head.
Provenance rows in ind_que_* are mirrored under the CP_ name.

Rule going forward: a variable created or altered by a patch gets a CP_ name."""),

    ("issue_reporting", """\
# Reporting data problems

If you (an agent or analyst in ANY repository) find a suspected data problem
in this database, INSERT a row into _data_issues:

  INSERT INTO "_data_issues"
    (reported_by, table_name, variable, severity, description)
  VALUES
    ('<repo or agent name>', 'final_CH_MICS', '<column>',
     'warning',  -- 'info' | 'warning' | 'error'
     'What you observed, which dataset_name(s), and how to reproduce.');

The maintaining repository (DilDataPreProcessing) reviews open issues,
fixes them via numbered patches, and records the resolution in the same row
(status -> 'fixed', resolution, patch_id). Check your issue's status later:

  SELECT * FROM "_data_issues" WHERE reported_by = '<your name>';"""),
]

# ---------------------------------------------------------------------------
# _catalog rows
# ---------------------------------------------------------------------------

CATALOG = [
    ("final_HH_MICS", "HH", "one row per household",
     "dataset_name + cluster_number + household_number",
     "ind_que_HH_MICS",
     "Household questionnaire: WASH (water source, toilet, handwashing), assets, "
     "wealth index, household head attributes, survey design (weights, area, region).",
     "Water/toilet type codes are country-specific two-digit JMP-style codes; "
     "sex_of_household_head cleaned in P10 (domain {1,2,NULL})."),
    ("final_HL_MICS", "HL", "one row per household member (roster)",
     "dataset_name + cluster_number + household_number + line_number",
     "ind_que_HL_MICS",
     "Household listing: age, sex, relationship to head (1=head), education of every "
     "member, orphanhood, parental survival/residence.",
     "relationship_to_head unmapped in a few datasets; education_years available (P09)."),
    ("final_WM_MICS", "WM", "one row per interviewed woman age 15-49",
     "dataset_name + cluster_number + hh_number + line_number (NB: hh_number!)",
     "ind_que_WM_MICS",
     "Women's questionnaire: fertility/birth history, maternal health, marriage, "
     "media exposure, HIV knowledge, education (level/grade/years).",
     "Household id column is hh_number, not household_number."),
    ("final_CH_MICS", "CH", "one row per child under 5",
     "dataset_name + cluster_number + household_number + child_line_number; "
     "mother via mother_caretaker_line_number",
     "ind_que_CH_MICS",
     "Under-5 questionnaire: anthropometry (HAZ/WAZ/WHZ + flags), illness "
     "(diarrhea/fever/cough), vaccination, breastfeeding, early development, "
     "mother's education (harmonized + years).",
     "child_age_months only in ~42 month-coded datasets; use child_age_years for "
     "all-dataset work. Anthropometry z-scores need flag==0 or |z|<=6 filtering."),
    ("final_NepalLivingStandardardSurvey2022", "NLSS", "Nepal LSS 2022 (separate survey)",
     "not harmonized with MICS tables",
     "ind_que_NepalLivingStandardardSurvey2022",
     "Standalone Nepal Living Standards Survey 2022 extract; independent of the "
     "MICS harmonization.", None),
]

# ---------------------------------------------------------------------------
# Historical issues (seed for _data_issues; matches DATA_PATCH_LOG.md)
# ---------------------------------------------------------------------------

HISTORY = [
    ("P01", "final_WM_MICS", "woman_age",
     "woman_age mixed actual age (15-49) with 5-year age-group codes (1-7) across datasets.",
     "Split into woman_age (actual) + woman_age_group (1-7); groups derived from age where absent."),
    ("P02", "final_WM_MICS", "education_level_harmonized",
     "education_level uses incompatible country-specific codings; cross-country comparison invalid.",
     "Added education_level_harmonized (ISCED 4-level 0-3) via multilingual label mapping."),
    ("P03", "final_CH_MICS", "mother_education_harmonized",
     "mother_education same cross-country coding problem as P02.",
     "Added mother_education_harmonized (ISCED 4-level 0-3)."),
    ("P04", "final_WM_MICS", "media_tv_frequency_harmonized",
     "media_tv_frequency scale direction flips between rounds (MICS6 ascending, MICS4/5 descending).",
     "Added harmonized 4-level scale: 0 never / 1 <weekly / 2 >=weekly / 3 ~daily."),
    ("P05", "final_WM_MICS", "media_radio_frequency_harmonized",
     "Same scale-direction problem as P04 for radio.", "Same 4-level harmonization."),
    ("P06", "final_WM_MICS", "media_newspaper_frequency_harmonized",
     "Same scale-direction problem as P04 for newspapers.", "Same 4-level harmonization."),
    ("P07", "final_CH_MICS", "child_age_months",
     "child_age_months mixed age-in-years (209 datasets, values 0-4) with age-in-months coding.",
     "Added child_age_years (all datasets); child_age_months kept only for month-coded datasets, "
     "out-of-range values nulled."),
    ("P08", "final_WM_MICS", "education_grade",
     "Attainment grade variables existed in raw SAVs but were unmapped for 73+ datasets "
     "(WM education_grade 150->244 datasets, HL highest_grade_completed 155->225).",
     "Backfilled from raw SAVs with row-alignment verification; alignment yaml updated."),
    ("P09", "final_CH_MICS", "mother_education_years",
     "Only 4-level education available; years of schooling not constructed.",
     "Built education_years (WM/HL) and mother_education_years (CH) from level+grade+WB "
     "school-system durations; compound/cumulative grade codings auto-detected; "
     "_estimated flags mark midpoint imputations."),
    ("P10", "final_HH_MICS", "sex_of_household_head",
     "Mozambique 2008 mapped from wrong source (orphanhood module); 11 datasets unmapped; "
     "sentinel codes 3/7/9 present.",
     "Coding verified 1=male/2=female across all 247 datasets; wrong source nulled; "
     "38,236 rows backfilled from HL roster with strict key matching; domain now {1,2,NULL}."),
    ("P12", "final_WM_MICS", "CP_age_at_first_union",
     "age_at_first_union carried sentinels (97/98/99), zeros, negatives and "
     "implausible ages; 41 datasets had zero coverage.",
     "Added CP_age_at_first_union (valid 8-49 only); recovered Mozambique 2008 "
     "from unmapped raw AGEM via positional alignment (guarded). Cross-module "
     "backfill impossible (marriage data is WM-only); other 40 datasets never "
     "collected it. ~1.78M valid values across 211 datasets."),
    ("P13", "final_WM_MICS", "CP_children_ever_born",
     "children_ever_born carried sentinel 99 and rare implausibly-high values; "
     "39 datasets had zero coverage.",
     "Added CP_children_ever_born (valid 0-20 only). Recovered 9 datasets from "
     "unmapped raw CEB columns via guarded positional alignment (Kyrgyzstan "
     "2005-06 skipped: hh_number!=HH2). Component derivation rejected (~16% "
     "exact). ~2.43M valid values across 221 datasets."),
    ("P14", "final_CH_MICS", "CP_bmi_for_age_zscore",
     "bmi_for_age_zscore carried sentinel 999.99 and implausible extremes; 61% "
     "coverage / 94 countries (below the sibling WHO z-scores).",
     "Added CP_bmi_for_age_zscore: cleaned to |z|<=6, PLUS derived (WHO 2006 "
     "BMI-for-age from weight/height/age/sex) for 33 fully-missing datasets that "
     "passed a data-quality gate (drop<=5%, SD 0.7-1.8, |mean|<=1.5); 11 "
     "error-prone datasets excluded (SD>1.8). CP_bmi_for_age_zscore_derived "
     "flags derived rows. ~1.17M rows / 178 datasets / 106 countries "
     "(+187k derived / +12 countries)."),
    ("P15", "final_CH_MICS", "CP_diarrhea_last_2_weeks",
     "diarrhea_last_2_weeks coding varies across datasets (1/2, 0/1, 0/100; "
     "Iraq/Yemen 2=yes-without-blood); Congo_MICS5 mis-mapped to CA2 (fluid "
     "intake) not CA1.",
     "Added CP_diarrhea_last_2_weeks (1=Yes/0=No/NULL) via per-dataset "
     "label-driven mapping; {0,100} decoded 100=Yes (prevalence+downstream "
     "evidence); Congo_MICS5 source fixed CA2->CA1 and recovered (guarded)."),
    ("P16", "final_CH_MICS", "CP_fever_last_2_weeks",
     "fever_last_2_weeks coding varies across datasets (1/2, 0/100, sentinels); "
     "and 9 datasets were wrongly missing (reviewed all 93 uncovered datasets' "
     "raw metadata): the fever question sits in the malaria module ML1 / Spanish "
     "CA6AA, or (Palestine MICS4 PCA6) was mis-mapped to respondent_name.",
     "Added CP_fever_last_2_weeks (1=Yes/0=No/NULL) via per-dataset value-label "
     "mapping (sentinels 7/8/9 -> NULL; {0,100} decoded 100=Yes). Recovered 9 "
     "datasets from raw ML1/CA6AA/PCA6 (guarded) -> 167 datasets. Remaining "
     "uncovered genuinely lack a fever-occurrence question. Coverage-aware map "
     "selection avoids silently NULLing multi-source data."),
    ("P19", "final_WM_MICS", "CP_age_at_first_birth",
     "No clean age-at-first-birth variable existed (only ~5 datasets surveyed it "
     "directly); needed for fertility analysis.",
     "Derived CP_age_at_first_birth (10-49): primarily floor((first_child_"
     "birth_date_cmc - woman_birth_date_cmc)/12) (calendar-agnostic, month-"
     "precise), else CP_first_birth_year-(interview_year-woman_age); "
     "CP_age_at_first_birth_estimated flags the year-level fallback. "
     "1,221,378 rows / 167 datasets."),
    ("P18", "final_WM_MICS", "CP_first_birth_year",
     "first_birth_year covered only 116 datasets, with sentinels (9997/8/9) and "
     "NON-Gregorian calendars (Thailand Buddhist Era +543, Nepal Bikram Sambat "
     "+57) and a 2-digit-year dataset.",
     "Added CP_first_birth_year (Gregorian CE, 1950-2024): derived from "
     "first_child_birth_date_cmc where valid (Gregorian, matches year field 100% "
     "and is calendar-agnostic), else the year field converted (Thai -543 / Nepal "
     "-57 / 2-digit pivot). Coverage 116 -> 190 datasets."),
    ("P17", "final_CH_MICS", "CP_cough_last_2_weeks",
     "cough_last_2_weeks coding varies (1/2, 0/1, sentinels); and 5 datasets were "
     "wrongly missing because their cough-occurrence column (CI6/CA7/CA5) was "
     "never mapped.",
     "Added CP_cough_last_2_weeks (1=Yes/0=No/NULL) via per-dataset value-label "
     "mapping. Reviewed all 29 uncovered datasets' raw metadata: recovered 5 "
     "(Cameroon 2000, Indonesia MICS2, Dominican Rep MICS5, Paraguay MICS5, "
     "Palestinians in Lebanon); CA8/ca6 'faster breathing while ill with cough' "
     "correctly excluded (pneumonia sign). 227 datasets."),
]

# ---------------------------------------------------------------------------
# Curated column comments (override the auto-generated ones)
# ---------------------------------------------------------------------------

CURATED: dict[tuple[str, str], str] = {
    # WM
    ("final_WM_MICS", "hh_number"): "Household number (join key; NB other tables call this household_number).",
    ("final_WM_MICS", "woman_age"): "Woman's age in years, 15-49. P01: age-group codes removed.",
    ("final_WM_MICS", "woman_age_group"): "5-year age group 1-7 (1=15-19 ... 7=45-49). P01 derived where needed.",
    ("final_WM_MICS", "education_level_harmonized"): "ISCED 4-level: 0 none/pre-primary, 1 primary, 2 secondary, 3 higher. NULL=sentinel/unmapped. (P02)",
    ("final_WM_MICS", "media_tv_frequency_harmonized"): "0 never, 1 <weekly, 2 >=weekly, 3 ~daily. Direction-corrected across rounds. (P04)",
    ("final_WM_MICS", "media_radio_frequency_harmonized"): "0 never, 1 <weekly, 2 >=weekly, 3 ~daily. (P05)",
    ("final_WM_MICS", "media_newspaper_frequency_harmonized"): "0 never, 1 <weekly, 2 >=weekly, 3 ~daily. (P06)",
    ("final_WM_MICS", "education_grade"): "Attainment grade, RAW: mixes grade-within-level and cumulative codings across datasets — use education_years for comparisons. (P08 backfilled)",
    ("final_WM_MICS", "education_grade_completed"): "Completed that grade? 1 yes, 2 no. (P08)",
    ("final_WM_MICS", "education_years"): "Years of schooling, 0-25, cross-dataset comparable. Built from level+grade+WB durations. (P09)",
    ("final_WM_MICS", "education_years_estimated"): "1 = education_years is a level-midpoint estimate (grade missing); 0 = exact. (P09)",
    ("final_WM_MICS", "age_at_first_union"): "Woman's age at first marriage/union, RAW: keeps sentinels (97/98/99), 0 and implausible values. Use CP_age_at_first_union. NULL for never-married women. (P12 added Mozambique 2008)",
    ("final_WM_MICS", "CP_age_at_first_union"): "Age at first marriage/union, cleaned: valid range 8-49 only (sentinels/0/neg/<8/>49 nulled). NULL also = never-married. 211 datasets. (P12)",
    ("final_WM_MICS", "children_ever_born"): "Total children ever born to the woman, RAW: keeps sentinel 99 and rare implausibly-high values; some cross-var inconsistencies (vs children_dead/ever_given_birth) untouched. Use CP_children_ever_born. (P13 backfilled 10 datasets)",
    ("final_WM_MICS", "CP_children_ever_born"): "Children ever born, cleaned: valid 0-20 only (99/>20 nulled). ~223 datasets. Cross-variable inconsistencies intentionally kept. (P13)",
    ("final_WM_MICS", "first_birth_year"): "Year of woman's first birth, RAW: only ~116 datasets; sentinels 9997/8/9; NON-Gregorian calendars (Thailand Buddhist Era +543, Nepal Bikram Sambat +57) and a 2-digit dataset. Use CP_first_birth_year. (P18)",
    ("final_WM_MICS", "CP_first_birth_year"): "Year of first birth, Gregorian CE, cleaned & calendar-harmonised: derived from first_child_birth_date_cmc where valid (calendar-agnostic), else the year field converted (Thai -543 / Nepal -57 / 2-digit pivot); valid 1950-2024. ~191 datasets. (P18)",
    ("final_WM_MICS", "CP_age_at_first_birth"): "Woman's age (completed years) at first live birth, DERIVED, valid 10-49: primarily floor((first_child_birth_date_cmc - woman_birth_date_cmc)/12) (calendar-agnostic, month-precise), else CP_first_birth_year-(interview_year-woman_age). ~167 datasets. See CP_age_at_first_birth_estimated. (P19)",
    ("final_WM_MICS", "CP_age_at_first_birth_estimated"): "0 = CP_age_at_first_birth is CMC-exact, 1 = year-level approximation (fallback), NULL = value is NULL. (P19)",
    # HL
    ("final_HL_MICS", "relationship_to_head"): "Relationship to household head; 1 = head. Head is roster line 1 by MICS design.",
    ("final_HL_MICS", "sex"): "1 = male, 2 = female.",
    ("final_HL_MICS", "highest_grade_completed"): "Attainment grade, RAW: mixed codings across datasets — use education_years for comparisons. (P08 backfilled)",
    ("final_HL_MICS", "ever_completed_grade"): "Completed that grade? 1 yes, 2 no. (P08)",
    ("final_HL_MICS", "education_years"): "Years of schooling, 0-25, cross-dataset comparable. (P09)",
    ("final_HL_MICS", "education_years_estimated"): "1 = midpoint estimate, 0 = exact. (P09)",
    # CH
    ("final_CH_MICS", "child_age_years"): "Child age in completed years 0-4, ALL datasets. (P07)",
    ("final_CH_MICS", "child_age_months"): "Child age in months 0-59; only ~42 month-coded datasets, NULL elsewhere. (P07)",
    ("final_CH_MICS", "mother_education_harmonized"): "Mother's education, ISCED 4-level 0-3. NULL=sentinel/unmapped. (P03)",
    ("final_CH_MICS", "mother_education_years"): "Mother's years of schooling 0-25: WM-linked, HL fallback, coarse midpoint last resort. (P09)",
    ("final_CH_MICS", "mother_education_years_estimated"): "1 = estimated (midpoint/coarse fallback), 0 = exact. (P09)",
    ("final_CH_MICS", "bmi_for_age_zscore"): "BMI-for-age z-score (WHO), RAW/MICS-provided: keeps sentinel 999.99 and implausible values. Use CP_bmi_for_age_zscore. NB WHO prefers weight_for_height_zscore for under-5. (P14)",
    ("final_CH_MICS", "CP_bmi_for_age_zscore"): "BMI-for-age z-score, cleaned to |z|<=6, PLUS derived (WHO 2006 from weight/height/age/sex) for 33 fully-missing datasets that passed a data-quality gate. ~1.17M rows / 178 datasets. See CP_bmi_for_age_zscore_derived. (P14)",
    ("final_CH_MICS", "CP_bmi_for_age_zscore_derived"): "1 = CP_bmi_for_age_zscore was derived here (WHO 2006), 0 = MICS-provided, NULL = CP_ is NULL. ~187k derived. (P14)",
    ("final_CH_MICS", "diarrhea_last_2_weeks"): "Had diarrhoea in last 2 weeks, RAW: coding varies across datasets (1/2, 0/1, 0/100, Iraq/Yemen 2=yes-without-blood). Use CP_diarrhea_last_2_weeks. (P15 fixed Congo_MICS5 source CA2->CA1)",
    ("final_CH_MICS", "CP_diarrhea_last_2_weeks"): "Diarrhoea in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label-driven mapping (handles 2=yes-without-blood, 0/100). (P15)",
    ("final_CH_MICS", "fever_last_2_weeks"): "Had fever in last 2 weeks, RAW: coding varies across datasets (1/2, 0/100, sentinels). Use CP_fever_last_2_weeks. (P16)",
    ("final_CH_MICS", "CP_fever_last_2_weeks"): "Fever in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label mapping; 9 datasets recovered from unmapped/mis-mapped raw cols (malaria-module ML1/CA6AA/PCA6) the alignment had missed. 167 datasets. (P16)",
    ("final_CH_MICS", "cough_last_2_weeks"): "Had cough in last 2 weeks, RAW: coding varies across datasets (1/2, 0/1, sentinels). Use CP_cough_last_2_weeks. (P17)",
    ("final_CH_MICS", "CP_cough_last_2_weeks"): "Cough in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label mapping; 5 datasets recovered from unmapped raw CI6/CA7/CA5 the alignment had missed. (P17)",
    ("final_CH_MICS", "mother_caretaker_line_number"): "Roster line of mother/caretaker; join to WM.line_number or HL.line_number.",
    # HH
    ("final_HH_MICS", "sex_of_household_head"): "1 = male, 2 = female, NULL = unknown. Verified & cleaned across all datasets. (P10)",
}

# ---------------------------------------------------------------------------
# CP_ ("carefully processed") columns — P11.
# Every variable a patch (P01-P10) cleaned/split/harmonized/derived/backfilled
# has a CP_<name> duplicate; the original is retained for backward compat.
# Comments for CP_ columns are auto-generated from the base column's comment so
# the two stay in sync. Going forward, new post-processed variables should be
# created with a CP_ prefix directly and listed here.
# ---------------------------------------------------------------------------

CP_COLUMNS: dict[str, list[str]] = {
    "final_WM_MICS": [
        "woman_age", "woman_age_group", "education_level_harmonized",
        "media_tv_frequency_harmonized", "media_radio_frequency_harmonized",
        "media_newspaper_frequency_harmonized", "education_grade",
        "education_grade_completed", "education_years", "education_years_estimated",
        "age_at_first_union", "children_ever_born", "first_birth_year",
    ],
    "final_HL_MICS": [
        "highest_grade_completed", "ever_completed_grade",
        "education_years", "education_years_estimated",
    ],
    "final_CH_MICS": [
        "mother_education_harmonized", "child_age_months", "child_age_years",
        "mother_education_years", "mother_education_years_estimated",
        "bmi_for_age_zscore", "diarrhea_last_2_weeks", "fever_last_2_weeks",
        "cough_last_2_weeks",
    ],
    "final_HH_MICS": ["sex_of_household_head"],
}

# Auto-generate a CP_ comment from each base column's comment, UNLESS an explicit
# CP_ entry already exists in CURATED (e.g. CP_age_at_first_union, curated for P12).
for _tbl, _cols in CP_COLUMNS.items():
    for _c in _cols:
        _base = CURATED.get((_tbl, _c), "")
        CURATED.setdefault((_tbl, "CP_" + _c), (
            f"CP (carefully processed) copy of {_c}"
            + (f" — {_base}" if _base else "") + " (P11)"
        ))

TABLE_COMMENTS = {
    "final_WM_MICS": "MICS women 15-49, all datasets pooled. Keys: dataset_name+cluster_number+hh_number(+line_number). See _catalog/_guide.",
    "final_HH_MICS": "MICS households, all datasets pooled. Keys: dataset_name+cluster_number+household_number. See _catalog/_guide.",
    "final_HL_MICS": "MICS household-member roster, all datasets pooled. Keys: dataset_name+cluster_number+household_number+line_number. See _catalog/_guide.",
    "final_CH_MICS": "MICS children under 5, all datasets pooled. Keys: dataset_name+cluster_number+household_number+child_line_number. See _catalog/_guide.",
}


def esc(s: str) -> str:
    return s.replace("'", "''")


def main() -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()

    # --- _guide ------------------------------------------------------------
    cur.execute('DROP TABLE IF EXISTS "_guide"')
    cur.execute('''CREATE TABLE "_guide" (
        position INT, section TEXT, content TEXT, updated_at DATE)''')
    for i, (sec, content) in enumerate(GUIDE_SECTIONS, 1):
        cur.execute('INSERT INTO "_guide" VALUES (%s, %s, %s, %s)',
                    (i, sec, content, TODAY))
    cur.execute('''COMMENT ON TABLE "_guide" IS
        'Database usage guide for agents. Read with: SELECT * FROM "_guide" ORDER BY position' ''')
    print(f"_guide: {len(GUIDE_SECTIONS)} sections")

    # --- _catalog ----------------------------------------------------------
    cur.execute('DROP TABLE IF EXISTS "_catalog"')
    cur.execute('''CREATE TABLE "_catalog" (
        table_name TEXT, module TEXT, grain TEXT, join_keys TEXT,
        ind_que_table TEXT, description TEXT, caveats TEXT,
        row_count BIGINT, n_datasets INT, updated_at DATE)''')
    for tbl, module, grain, keys, ind, desc, cav in CATALOG:
        cur.execute('''SELECT 1 FROM information_schema.columns
                       WHERE table_name = %s AND column_name = 'dataset_name' ''', (tbl,))
        if cur.fetchone():
            cur.execute(f'SELECT COUNT(*), COUNT(DISTINCT dataset_name) FROM "{tbl}"')
            n, nds = cur.fetchone()
        else:
            cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
            n, nds = cur.fetchone()[0], None
        cur.execute('INSERT INTO "_catalog" VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (tbl, module, grain, keys, ind, desc, cav, n, nds, TODAY))
    cur.execute('''COMMENT ON TABLE "_catalog" IS
        'One row per data table: grain, join keys, caveats. Start here.' ''')
    print(f"_catalog: {len(CATALOG)} tables")

    # --- _data_issues (append-only; create + seed once) ---------------------
    cur.execute('''CREATE TABLE IF NOT EXISTS "_data_issues" (
        issue_id SERIAL PRIMARY KEY,
        reported_at TIMESTAMP DEFAULT now(),
        reported_by TEXT NOT NULL,
        table_name TEXT,
        variable TEXT,
        severity TEXT CHECK (severity IN ('info','warning','error')),
        description TEXT NOT NULL,
        status TEXT DEFAULT 'open'
            CHECK (status IN ('open','confirmed','fixed','wontfix','duplicate')),
        resolution TEXT,
        patch_id TEXT,
        resolved_at DATE)''')
    cur.execute('''COMMENT ON TABLE "_data_issues" IS
        'Data problem tracker. External agents: INSERT reports here (see _guide section issue_reporting). Maintainer records fixes with patch ids matching DATA_PATCH_LOG.md.' ''')
    cur.execute('SELECT COUNT(*) FROM "_data_issues"')
    if cur.fetchone()[0] == 0:
        for pid, tbl, var, desc, res in HISTORY:
            cur.execute('''INSERT INTO "_data_issues"
                (reported_by, table_name, variable, severity, description,
                 status, resolution, patch_id, resolved_at)
                VALUES ('DilDataPreProcessing (internal)', %s, %s, 'warning',
                        %s, 'fixed', %s, %s, %s)''',
                        (tbl, var, desc, res, pid, TODAY))
        print(f"_data_issues: seeded {len(HISTORY)} historical patches")
    else:
        print("_data_issues: exists, left untouched")

    # --- column comments -----------------------------------------------------
    for tbl, ind in FINAL_TABLES.items():
        cur.execute(f'COMMENT ON TABLE "{tbl}" IS \'{esc(TABLE_COMMENTS[tbl])}\'')
        # auto: most common English label per canonical + dataset coverage
        cur.execute(f'''
            SELECT DISTINCT ON (canonical_varname)
                   canonical_varname, label, n_ds
            FROM (
                SELECT canonical_varname,
                       column_label_in_english AS label,
                       COUNT(*) AS n_lbl,
                       SUM(COUNT(*)) OVER (PARTITION BY canonical_varname) AS n_ds
                FROM "{ind}"
                WHERE column_label_in_english IS NOT NULL
                  AND column_label_in_english != ''
                GROUP BY canonical_varname, column_label_in_english
            ) t
            ORDER BY canonical_varname, n_lbl DESC''')
        labels = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        cur.execute('''SELECT column_name FROM information_schema.columns
                       WHERE table_name = %s''', (tbl,))
        cols = [r[0] for r in cur.fetchall()]
        n_commented = 0
        for col in cols:
            if (tbl, col) in CURATED:
                text = CURATED[(tbl, col)]
            elif col in labels:
                lbl, nds = labels[col]
                text = f"{lbl[:180]} [in {nds} datasets; per-dataset source: {ind}]"
            elif col == "dataset_name":
                text = "Survey dataset identifier (country + MICS round). All joins must include it."
            else:
                continue
            cur.execute(f'COMMENT ON COLUMN "{tbl}"."{col}" IS \'{esc(text)}\'')
            n_commented += 1
        print(f"{tbl}: {n_commented}/{len(cols)} columns commented")

    conn.commit()
    conn.close()
    print("\nDone. Verify with: SELECT * FROM \"_guide\" ORDER BY position;")


if __name__ == "__main__":
    main()
