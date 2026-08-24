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
    CP_age_at_first_birth (10-49; CMC-derived, +_estimated flag for year-level),
    CP_woman_age (real age 10-64; raw where real else HL-recovered — raw woman_age
    is the 5-yr GROUP code for 153 datasets), CP_woman_birth_year (Gregorian
    1940-2010; +CP_woman_birth_year_estimated 0 exact /1 age-derived),
    CP_place_of_delivery (1 Home/2 Public/3 Private/4 Other facility/5 Other),
    CP_received_anc (1 received /0 not; +CP_received_anc_derived: 0 self-report
    /1 derived from MN2 provider checklist),
    CP_first_trimester_anc (1 first ANC <=3 months/<=13 weeks /0 later;
    +CP_first_trimester_anc_derived: 0 mapped /1 recovered),
    CP_early_initiation_breastfeeding (1 first breastfed <=1h /0 later),
    CP_breastfed_within_24h, CP_time_to_breastfeed_hours (continuous)
All tables: CP_area_type (1 Urban /2 Rural /3 Refugee-camp) — harmonized area of
    residence; use instead of raw `area` (HH6). Camp = State of Palestine only.
All tables: CP_survey_year / CP_survey_month — Gregorian interview year/month
    (Thailand Buddhist-Era and Nepal Bikram-Sambat converted); use instead of raw
    interview_year / interview_month.
All tables: CP_country / CP_country_code (ISO3) — standardised country; CP_subnational
    / CP_subnational_matched — admin-1 name (state.json-standardised where matched=1,
    else the raw survey label); CP_district / CP_district_matched — admin-2 name (kept
    separate from the admin-1 CP_subnational). See the _geo_dict reference table.
HL: education_years (+_estimated)
CH: child_age_years (0-4), CP_child_age_months (0-59, 248 datasets — rebuilt from
    raw CAGE + interview-minus-birth date; raw child_age_months had only ~42),
    mother_education_harmonized (0-3 as above),
    mother_education_years (+_estimated),
    CP_bmi_for_age_zscore (cleaned |z|<=6 + WHO-2006 derived where missing;
    see CP_bmi_for_age_zscore_derived; WHO prefers WHZ for <5y),
    CP_diarrhea_last_2_weeks / CP_fever_last_2_weeks / CP_cough_last_2_weeks
    (harmonized 1=Yes/0=No; per-dataset label mapping),
    CP_child_sample_weight (normalized to mean 1 per dataset; for pooling),
    CP_ever_breastfed (1=Yes/0=No; 233 datasets, incl. 28 recovered from unmapped
    non-English labels), CP_still_breastfeeding (1=Yes/0=No; 241 datasets),
    CP_fed_milk_yesterday (1=drank formula or animal milk /0 neither; 227 datasets;
    re-derived - do NOT use raw infant_fed_milk_yesterday which conflates cheese/juice),
    CP_breastfeeding_status (3-cat current status: 0 never / 1 stopped / 2 currently;
    241 datasets; derived from ever + still),
    CP_fed_grains_yesterday (ate grains yesterday 1/0; 114 datasets; from raw BD8C
    only - prefer over dd_grains which conflates broth/rice-water/roots/porridge),
    CP_fed_grain_based_fortified_baby_food_yesterday (ate fortified baby food /
    cerelac yesterday 1/0; 114 datasets; from raw BD8B),
    CP_fed_roots_tubers_plantains_yesterday (ate white roots/tubers/plantains
    yesterday 1/0; 113 datasets; from raw BD8E),
    CP_fed_pulses_nuts_seeds_yesterday (ate beans/peas/lentils/nuts yesterday 1/0;
    112 datasets; rebuilt from raw BD8M - dd_legumes_nuts was contaminated),
    CP_fed_yogurt_yesterday (drank/ate yogurt yesterday 1/0; 155 datasets; rebuilt
    from raw BD8A+BD7F - infant_fed_yogurt_yesterday mixed in times-counts/cheese),
    CP_fed_cheese_other_dairy_yesterday (ate cheese/other milk food yesterday 1/0;
    112 datasets; rebuilt from raw BD8N - dd_dairy was contaminated with yogurt),
    CP_fed_organ_meat_yesterday (ate liver/kidney/heart/organ meat yesterday 1/0;
    107 datasets; rebuilt from raw BD8I - excludes Pakistan-KP BD8I=eggs mislabel),
    CP_fed_meat_poultry_yesterday (ate meat/poultry yesterday 1/0; 108 datasets;
    rebuilt from raw BD8J - Pakistan-KP reads BD8H, Vietnam BF9-broth excluded),
    CP_fed_fish_seafood_yesterday (ate fish/seafood yesterday 1/0; 108 datasets;
    rebuilt from raw BD8L - Pakistan-KP reads BD8J, its BD8L is cheese),
    CP_fed_eggs_yesterday (ate eggs yesterday 1/0; 107 datasets; rebuilt from raw
    BD8K - Pakistan-KP reads BD8I, its BD8K is legumes),
    CP_fed_vitamin_a_vegetables_yesterday (ate pumpkin/carrots/squash/orange sweet
    potato yesterday 1/0; 107 datasets; rebuilt from raw BD8D),
    CP_fed_dark_green_leafy_vegetables_yesterday (ate spinach/broccoli/kale etc.
    yesterday 1/0; 107 datasets; rebuilt from raw BD8F),
    CP_fed_vitamin_a_fruits_yesterday (ate ripe mango/papaya/apricot/melon etc.
    yesterday 1/0; 108 datasets; rebuilt from raw BD8G),
    CP_fed_other_fruit_vegetables_yesterday (ate other fruits/vegetables yesterday
    1/0; 116 datasets; from raw BD8H + BD8F1),
    CP_fed_sweets_yesterday (ate sugary/sweet foods yesterday 1/0; only 11 datasets
    - add-on question; from raw BD8O/BD8P/BD8Q by label),
    CP_mother_birth_year (+_estimated) / CP_mother_birth_month (mother's birth
    date, linked from her WM record; 201 datasets)
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
     "CP_child_age_months now covers 248 datasets (0-59, rebuilt from raw CAGE + "
     "date); prefer it over raw child_age_months (~42) and over child_age_years "
     "where a month value exists. Anthropometry z-scores need flag==0 or |z|<=6 filtering."),
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
    ("P60", "final_CH_MICS", "CP_fed_ors_yesterday",
     "The ORS (oral rehydration solution) yes/no feeding item (raw BD5 MICS6, BF11 MICS4/5, BF3D MICS2/3 \u2018Received: ORS\u2019) was mapped for 223 datasets, but ~15 of those took the value from the diarrhoea-care ORS columns (CA/CI series) \u2014 a different question \u2014 because ORS appears in both modules.",
     "Added CP_fed_ors_yesterday (1/0) rebuilt fresh from raw, NAME-anchored to {BD5,BF11,BF3D} (the feeding positions) and label-verified, excluding the diarrhoea-care and count false friends. 190 datasets, 897,820 rows, yes-rate 0.03 (ORS is rare); no all-yes dataset."),
    ("P59", "final_CH_MICS", "CP_fed_juice_yesterday",
     "The juice yes/no feeding item (raw BD7B MICS6, BF8 MICS4/5, BF3C MICS2/3 sweetened water/juice) was mapped for 190 datasets though present in ~224; \u2018juice\u2019 also appears on diarrhoea-care liquids (CA/CI series) with different column names.",
     "Added CP_fed_juice_yesterday (1/0) rebuilt fresh from raw, NAME-anchored to {BD7B,BF8,BF3C} and label-verified, excluding diarrhoea-care and count false friends. 201 datasets, 954,915 rows, yes-rate 0.34, no all-yes/all-no dataset."),
    ("P58", "final_CH_MICS", "CP_fed_plain_water_yesterday",
     "The plain-water yes/no feeding item (raw BD7A MICS6, BF3 MICS4, BF3B MICS5) was mapped for 194 datasets though present in ~230; \u2018water\u2019 is a heavily polluted keyword \u2014 household water-supply (WS4/WS5), diarrhoea-care water (CI3F/CI3G, CA-series), and sweet/tea/broth water (the C-suffix items BF3C/BD7C) all carry a water label.",
     "Added CP_fed_plain_water_yesterday (1/0) rebuilt fresh from raw, NAME-anchored to {BD7A,BF3,BF3B} and label-verified, excluding diarrhoea/water-source/sweet-water false friends. 207 datasets, 979,813 rows, yes-rate 0.87, no all-yes/all-no dataset."),
    ("P57", "final_CH_MICS", "CP_times_solid_semisolid_soft_food_yesterday",
     "The times-ate-solid/semi-solid/soft-food count (IYCF meal frequency; raw BD9 MICS6, BF17 MICS4/5, BD11, BF5 some MICS4/5) was mapped for only 40 datasets though present in ~175; BF5 also denotes formula-times in other rounds, so the column must be picked by label.",
     "Added CP_times_solid_semisolid_soft_food_yesterday (count) rebuilt fresh from raw by LABEL (one column per dataset, strictly disambiguated from formula/milk/yogurt times), with per-dataset sentinel handling from value labels. 163 datasets, 555,894 rows, range 1-22 (mean 3.0)."),
    ("P56", "final_CH_MICS", "CP_times_yogurt_yesterday",
     "The times-drank/ate-yogurt count (raw BD8A1 MICS6, BD8AN MICS5, BF14 MICS4, BD7F1 "
     "MICS6-2023) was mapped for only 67 datasets though present in ~166; MICS6-2023 splits it "
     "into eaten (BD8A1) + drunk (BD7F1), and one CAR column (BD8DUMMY) is a check-flag.",
     "Added CP_times_yogurt_yesterday (count) rebuilt fresh from raw by LABEL, SUMMING the eaten "
     "and drunk yogurt-times columns, with per-dataset sentinel handling from value labels and a "
     "skip for dummy/instruction-flag columns. Count companion of P38 CP_fed_yogurt_yesterday. "
     "156 datasets, 132,676 rows, range 1-22 (mean 1.6); 100% also flagged as having had yogurt."),
    ("P55", "final_CH_MICS", "CP_times_animal_milk_yesterday",
     "No canonical existed for the number of times a child drank animal/tinned/powdered/fresh "
     "milk (raw BD7E1 MICS6, BF7 MICS4/5).",
     "Added CP_times_animal_milk_yesterday (count) rebuilt fresh from raw by LABEL, with "
     "per-dataset sentinel handling from value labels (DK/missing/NR, or >=90, -> NULL). Count "
     "companion of P53 CP_fed_animal_milk_yesterday. 44 datasets, 24,229 rows, range 1-22 (mean "
     "2.6); 100% also flagged as having drunk animal milk."),
    ("P54", "final_CH_MICS", "CP_times_infant_formula_yesterday",
     "The number-of-times-fed-infant-formula count (raw BD7D1/BF5/BD7EN) was mapped for only "
     "7 datasets though present in ~142; sentinel coding differs by round (MICS6 8/9=DK/NR vs "
     "MICS4 8-12 real counts).",
     "Added CP_times_infant_formula_yesterday (count 1..n) rebuilt fresh from raw by LABEL "
     "(times + infant-formula), with per-dataset sentinel handling from value labels (codes "
     "labelled DK/missing/NR, or >=90, -> NULL; real counts kept incl MICS4 8-12). 132 datasets, "
     "77,462 formula-fed children, range 1-22 (mean 3.5); 98.8% also flagged fed-formula."),
    ("P53", "final_CH_MICS", "CP_fed_animal_milk_yesterday",
     "The animal-milk 24h item (drank tinned/powdered/fresh animal milk) had no clean CP: raw "
     "infant_fed_milk_yesterday is contaminated (mis-mapped to BD8N cheese / BD8A yogurt / BF8 "
     "juice for many datasets, see P31), and the animal-milk letter varies by round.",
     "Added CP_fed_animal_milk_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw by LABEL — the "
     "animal/tinned/powdered/fresh milk column (BD7E MICS6; BD7D/BF6/BF3F/BF3E MICS4/5), excluding "
     "infant formula, breast milk, yogurt/cheese, and diarrhoea-care fluids. 84 datasets; global "
     "rate 0.32. Sibling of P31 CP_fed_milk_yesterday (= formula OR animal milk) — this is the "
     "animal-milk component alone."),
    ("P52", "final_CH_MICS", "CP_mother_native_language",
     "The child questionnaire's own respondent-language (UF14) covered only 53 datasets; the "
     "child's mother's language could be filled more widely from the mother's WM record or the "
     "household respondent.",
     "Added CP_mother_native_language (+_source) on each child: the mother's native language "
     "(decoded name) with fallback WM (mother's own woman record) -> CH (own UF14 respondent) -> "
     "HH (household respondent), all from the P51 CP_respondent_native_language. HL carries no "
     "language variable. 477,440 children / 67 datasets (WM 336,543 + CH 49,986 + HH 90,911)."),
    ("P51", "final_WM_MICS", "CP_respondent_native_language",
     "respondent_native_language was a country-specific numeric code (WM14/HH16/UF14, codes "
     "renumber per dataset) mapped for few datasets, so it was not comparable or readable.",
     "Added CP_respondent_native_language (WM/HH/CH) — the respondent's native language DECODED "
     "to the language NAME (text) from the SAV value labels. Per dataset the column is found by "
     "label (mother tongue / native language / langue maternelle …), excluding the household "
     "head's language (HC1B), interview/questionnaire language, and 'école maternelle'. Sentinels "
     "(DK/missing/inconsistent) -> NULL. WM 55 / HH 65 / CH 53 datasets. Full cross-country language "
     "harmonisation (ISO 639) not attempted — the decoded name is kept as-is."),
    ("P50", "final_CH_MICS", "CP_mother_birth_year",
     "Children had no direct mother-birth-date field; the mother's birth year/month lived only "
     "on her WM (woman 15-49) record.",
     "Added CP_mother_birth_year (+_estimated) and CP_mother_birth_month on each child by linking "
     "to the mother's WM record (dataset+cluster+household+mother_caretaker_line_number == WM "
     "woman_line_number/line_number): year from CP_woman_birth_year (P26), month from "
     "woman_birth_month cleaned to 1-12 (else derived from woman_birth_date_cmc). Falls back to "
     "the mother's HL household-listing row (year_of_birth, else survey_year-age; month_of_birth) "
     "when she is not in the WM 15-49 file. 1,453,480 children / 214 datasets (WM 1,283,814 + HL "
     "fallback 169,666; implied mother age avg 30.5, 99.6% in 12-70)."),
    ("P49", "final_WM_MICS", "CP_education_years",
     "The P09 years-of-schooling derivation mis-handled the 'cumulative' grade branch: for HIGHER "
     "education it ignored the real grade and flat-set base+2 (~15, flagged estimated), and for "
     "hybrid systems where UPPER SECONDARY restarts its grade at 1 (e.g. Tunisia: basic education "
     "numbered 1-9 continuously, then upper-secondary and higher restart) it added no base, so "
     "upper-secondary years were ~9 too low. Affected ~22 WM datasets (also HL/CH).",
     "Reworked the cumulative branch to decide PER RECORD: grade<=level_dur+1 -> base+grade "
     "(restarted within-level), else grade (cumulative); higher: grade<=9 -> base+grade, grade>=base "
     "-> grade, in-between -> base+2 estimate. Re-ran P09 for WM/HL/CH; e.g. Tunisia MICS6 upper-sec "
     "now 9-13 and higher 13-22 (was 0-4 and flat-15). DB rebuilt from parquet (TRUNCATE+COPY, "
     "ind_que untouched); CP_ duplicates resynced."),
    ("P48", "final_CH_MICS", "CP_fed_sweets_yesterday",
     "The sugary/sweet-FOODS item (chocolate/candy/pastry/cake) is an unhealthy-foods add-on "
     "asked in only ~11 MICS surveys; its raw letter varies (BD8O/BD8P/BD8Q; MICS4 BF16M/BF19N; "
     "Ghana DD1S) and those letters mean other things elsewhere (BD8O is insects/nuts in some).",
     "Added CP_fed_sweets_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw by LABEL (sugary/"
     "sweet food; excludes sugary drinks, diarrhoea sugar-salt solutions, sweet potato). 11 datasets; "
     "global rate 0.39. Low coverage is inherent to the question."),
    ("P47B", "final_CH_MICS", "CP_fed_grains_yesterday",
     "The dietary-item value classifier dropped Portuguese 'No' answers stored as mojibake "
     "('Não' saved as 'NÃ£o'), leaving only 'Yes' — Sao Tome & Principe MICS5 showed rate=1.0 "
     "for all 13 food groups (P34-P46).",
     "Fixed _classify to strip non-letter chars before matching (so mojibake 'nao' matches) and "
     "to treat 'sabe'/'ne sait' as DK. Re-derived all 13 food-group columns for Sao Tome MICS5 "
     "(now 0/1); audit confirms no remaining rate=1.0 datasets. Propagated to all 13 patch scripts."),
    ("P47", "final_CH_MICS", "CP_fed_other_fruit_vegetables_yesterday",
     "dd_other_fruit_veg (catch-all other-fruit/veg group, raw BD8H) covered 89 of 115 BD8H "
     "datasets and was multi-source for Fiji/Georgia MICS6; letter-shifted Pakistan-KP MICS5 BD8H "
     "is 'meat' (its other-fruit/veg is BD8G).",
     "Added CP_fed_other_fruit_vegetables_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8H "
     "(multilingual other-fruit/veg label; rejects Pakistan-KP meat) OR-combined with BD8F1 'any "
     "other vegetables' where present (MICS6-2023 Azerbaijan/Kyrgyzstan/Lao). Shifted datasets read "
     "Pakistan-KP BD8G, Madagascar BF15GX. 89 -> 116 datasets; global rate 0.27."),
    ("P46", "final_CH_MICS", "CP_fed_vitamin_a_fruits_yesterday",
     "dd_vitamin_a_fruit (vit-A fruit group, raw BD8G) covered only 65 of 115 BD8G datasets. "
     "Letter-shift: Pakistan-KP MICS5 BD8G is 'any other fruits or vegetables' (its vit-A fruit "
     "is BD8F).",
     "Added CP_fed_vitamin_a_fruits_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8G with "
     "a vit-A-fruit label guard (multilingual, locally-adapted fruits: mango/papaya/apricot/melon/"
     "persimmon/'riches en Vitamine A'). Shifted-letter datasets read Pakistan-KP BD8F, Madagascar "
     "BF15FX. 65 -> 108 datasets; global rate 0.15. 7 skipped (household guard)."),
    ("P45", "final_CH_MICS", "CP_fed_dark_green_leafy_vegetables_yesterday",
     "dd_green_leafy_veg (dark-green-leafy group, raw BD8F) covered 92 datasets; the food-group "
     "letters differ by questionnaire — standard MICS6 BD8F = green leafy, but letter-shifted "
     "Pakistan-KP MICS5 has NO green-leafy item and its BD8F is vitamin-A FRUIT (mango).",
     "Added CP_fed_dark_green_leafy_vegetables_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw "
     "BD8F with a green-leafy label guard (multilingual: green leafy/feuilles vertes/hoja verde/"
     "couve/folhas; excludes Pakistan-KP mango). Madagascar-South reads BF15EX. 92 -> 107 datasets; "
     "global rate 0.26. 8 skipped (household guard) + Pakistan-KP (no green-leafy item)."),
    ("P44", "final_CH_MICS", "CP_fed_vitamin_a_vegetables_yesterday",
     "dd_vitamin_a_veg (vitamin-A veg group, raw BD8D) is multi-source for Fiji/Georgia MICS6 "
     "(BD7B1/BD7B2 liquids mixed with BD8D) and covered 100 of 115 BD8D datasets.",
     "Added CP_fed_vitamin_a_vegetables_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8D "
     "with a vit-A-veg label + household guard. No letter-shift (BD8D correct even for Pakistan-KP). "
     "100 -> 107 datasets; global rate 0.19. 8 skipped (household guard)."),
    ("P43", "final_CH_MICS", "CP_fed_eggs_yesterday",
     "dd_eggs (eggs group, raw BD8K) is mis-sourced for a few: Pakistan-KP MICS5 BD8K is "
     "actually 'beans/legumes' (letters shifted; its eggs are BD8I), and Azerbaijan MICS6-2023 "
     "is multi-source (BD8F1 + BD8K). BD8K present in 115 raw SAVs vs 101 mapped.",
     "Added CP_fed_eggs_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8K with an egg-label "
     "+ household guard. Shifted-letter datasets read their real eggs column (Pakistan-KP BD8I, "
     "Madagascar-South BF15JX). 101 -> 107 datasets; global rate 0.22. 8 skipped (household guard)."),
    ("P42", "final_CH_MICS", "CP_fed_fish_seafood_yesterday",
     "dd_fish_seafood (fish/seafood group, raw BD8L) is mis-sourced for a few: Pakistan-KP "
     "MICS5 BD8L is actually 'cheese' (letters shifted; its fish is BD8J), and Guyana MICS6 is "
     "multi-source (BD7C broth + BD8L). BD8L present in 115 raw SAVs vs 100 mapped.",
     "Added CP_fed_fish_seafood_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8L with a "
     "fish-label + household guard. Shifted-letter datasets read their real fish column (Pakistan-"
     "KP BD8J, Madagascar-South BF15KX). 100 -> 108 datasets; global rate 0.18. 8 skipped (household guard)."),
    ("P41", "final_CH_MICS", "CP_fed_meat_poultry_yesterday",
     "dd_meat_poultry (flesh-meat/poultry group, raw BD8J) is mis-sourced for a few: "
     "Pakistan-KP MICS5 BD8J is actually 'fish' (letters shifted; its meat is BD8H), and "
     "Vietnam MICS4 came from BF9 'meat SOUP/broth' (a liquid, not meat-eating). BD8J present "
     "in 115 raw SAVs vs 102 mapped.",
     "Added CP_fed_meat_poultry_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8J with a "
     "meat-label (excl soup/broth) + household guard. Shifted-letter datasets read their real "
     "meat column (Pakistan-KP BD8H, Madagascar-South BF15IX). 102 -> 108 datasets; global rate "
     "0.26. 8 skipped (household guard)."),
    ("P40", "final_CH_MICS", "CP_fed_organ_meat_yesterday",
     "dd_organ_meat (organ-meat food group, raw BD8I) is single-source but one dataset's "
     "BD8I is mislabelled: Pakistan-KP MICS5 BD8I is actually 'Child ate eggs' (its food-group "
     "letters are shifted; it has no separate organ-meat item), so its dd_organ_meat value was "
     "eggs. BD8I present in 115 raw SAVs vs 100 mapped.",
     "Added CP_fed_organ_meat_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw BD8I with an "
     "organ-meat-label + household guard (rejects Pakistan-KP eggs). Madagascar-South reads its "
     "shifted column BF15HX. 100 -> 107 datasets; global rate 0.06. 9 skipped (Pakistan-KP eggs "
     "+ 8 household guard fails)."),
    ("P39", "final_CH_MICS", "CP_fed_cheese_other_dairy_yesterday",
     "dd_dairy (cheese/other-milk-food group, raw BD8N) covered only 54 datasets though "
     "BD8N is present in 114; and it was contaminated for multi-source datasets (Cameroon/"
     "CAR == BD8A yogurt, Georgia == BD7P/BD7Q1).",
     "Added CP_fed_cheese_other_dairy_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw "
     "BD8N with a cheese/dairy-label + household guard (never trusting the contaminated "
     "merged column). Shifted-letter cheese items read from their real column (Pakistan-KP "
     "BD8L, Madagascar-South BF15MX); single-BD8N id-recoded datasets kept from merged value. "
     "54 -> 112 datasets; global rate 0.12. 4 skipped (unmapped + household guard fail)."),
    ("P38", "final_CH_MICS", "CP_fed_yogurt_yesterday",
     "infant_fed_yogurt_yesterday (148 datasets) was contaminated: it mixed the yes/no "
     "yogurt item (BD8A/BF13) with its TIMES-count companion (BD8A1/BD8AN/BF14 'Times "
     "drank or ate yogurt' — values 3/4/7 appeared) and, for a few datasets, cheese / "
     "mixed-dairy / diarrhoea-liquid columns.",
     "Added CP_fed_yogurt_yesterday (1=Yes/0=No/NULL), rebuilt fresh from raw: per dataset "
     "select every yogurt YES/NO column (BD8A 'drank or ate yogurt', BD7F/BD7F2 yogurt "
     "drinks, BF13 MICS4, BF3I 'received yogurt') and OR-combine; times-counts, cheese, "
     "mixed-dairy and diarrhoea catch-all liquids excluded by label. 148 -> 155 datasets; "
     "global rate 0.19. 9 skipped (household guard — id-recoded MICS6 + Moldova MICS4)."),
    ("P37", "final_CH_MICS", "CP_fed_pulses_nuts_seeds_yesterday",
     "dd_legumes_nuts (the legumes/nuts food group, raw BD8M) was silently contaminated: "
     "for several multi-source datasets the merge took the WRONG raw column — Algeria MICS6 "
     "== BD8G ('figues, pommes, poires' vitamin-A fruit), others carried BD7D infant formula "
     "or IM8/IM12 immunization columns; Pakistan-KP's BD8M is actually 'other solid food'.",
     "Added CP_fed_pulses_nuts_seeds_yesterday (1=Yes/0=No/NULL), REBUILT fresh from raw "
     "BD8M with a legumes-label + household-alignment guard (never trusting the contaminated "
     "merged column). 2 shifted-letter datasets read from their real column (Pakistan-KP "
     "BD8K, Madagascar-South BF15LX); 4 id-recoded single-BD8M datasets kept from the merged "
     "value. 112 datasets; global rate 0.19. 4 skipped (multi-source + household guard fail)."),
    ("P36", "final_CH_MICS", "CP_fed_roots_tubers_plantains_yesterday",
     "The white-roots-and-tubers food-group item (BD8E, 'ate white potatoes, yams, "
     "manioc, cassava or other foods made from roots') existed only as dd_white_roots_"
     "tubers, mapped for 94 datasets though BD8E is present in 115.",
     "Added CP_fed_roots_tubers_plantains_yesterday (1=Yes/0=No/NULL) from BD8E: "
     "harmonized the 94 mapped (93 BD8E + 1 Madagascar BF15DX 'à base de racines') + "
     "recovered 19 more. 94 -> 113 datasets; global rate 0.30. 3 skipped (Guinea Bissau "
     "MICS6 & Sao Tome MICS6 x2, household guard). BD8E-only scope; MICS4 roots items "
     "under other codes (Ghana DD1H, CAR BF19C, Mali BF16C) left out."),
    ("P35", "final_CH_MICS", "CP_fed_grain_based_fortified_baby_food_yesterday",
     "The commercial fortified baby-food item (BD8B, 'ate fortified baby food such as "
     "cerelac/gerber/nestum yesterday') was mapped for only 107 datasets though BD8B is "
     "present in 115 raw SAVs.",
     "Added CP_fed_grain_based_fortified_baby_food_yesterday (1=Yes/0=No/NULL) from BD8B "
     "only: harmonized the 107 mapped + recovered 7 more whose BD8B was unmapped. 107 -> "
     "114 datasets; global rate 0.12. 1 skipped (Kosovo-Roma MICS5, household guard 98.2%). "
     "A broad sweep found no fortified-baby-food question outside BD8B (MICS5/6-only item)."),
    ("P34", "final_CH_MICS", "CP_fed_grains_yesterday",
     "The 24h grains food-group item (BD8C, 'ate bread/rice/noodles/porridge or other "
     "foods made from grains') was mapped for only 55 datasets, though BD8C is present in "
     "115. dd_grains conflated BD8C with mis-aligned raw columns (BD7C broth, BD7O rice "
     "water, BD8E roots, BD8P sweets, CI3B diarrhoea gruel, BF15 thin porridge).",
     "Added CP_fed_grains_yesterday (1=Yes/0=No/NULL) from BD8C only: harmonized the 55 "
     "mapped + recovered 59 more whose BD8C was unmapped due to non-English labels "
     "(French/Spanish/Portuguese). 55 -> 114 datasets; global rate 0.64. 1 skipped "
     "(Kosovo-Roma MICS5, household guard 98.2%). BD8C-only scope keeps the construct "
     "identical across datasets; dd_grains left untouched."),
    ("P33", "final_CH_MICS", "CP_child_age_months",
     "CP_child_age_months carried the merged child_age_months, populated for only "
     "~42 datasets — the alignment had mapped it to a grab-bag of raw columns (age "
     "BANDS, DOB CMC, line numbers) and produced a valid month value for almost none, "
     "even though the raw SAVs nearly all carry CAGE='Age (months)'.",
     "Rebuilt CP_child_age_months from raw: CAGE (completed months 0-59) first, else "
     "interview-minus-birth CMC (MICS4/5 UF8M/Y-AG1M/Y, MICS6 UF7M/Y-UB1M/Y). Guarded "
     "positional backfill: row-count match + real 0-59 scale (max>=48, excludes Cuba's "
     "cage capped at 23 and Indonesia-2000's constant 1) + rows aligned by household id "
     ">=99.9% OR age//12 vs child_age_years >=90%. 42 -> 248 datasets, 1,625,468 rows. "
     "Also surfaced that child_age_years is broken (all-zero / partial) for ~12 datasets "
     "(e.g. Malawi/Sierra Leone/Uzbekistan MICS6, Guinea MICS5) — CP_child_age_months is "
     "the reliable age source there. 7 skipped: Cuba/Indonesia (miscoded cage), Kyrgyzstan "
     "(misaligned SAV), Myanmar-2000 (no anchor), CAR-2000 + Guyana/Iraq-2000 (no source)."),
    ("P32", "final_CH_MICS", "CP_breastfeeding_status",
     "There was no single variable for current breastfeeding status; ever-breastfed "
     "(lifetime) and still-breastfeeding (current) lived in two separate columns.",
     "Derived CP_breastfeeding_status (0=never / 1=ever but stopped/weaned / "
     "2=currently breastfeeding) from CP_ever_breastfed + CP_still_breastfeeding. "
     "still=1 wins (implies ever); ever=0 -> never; ever=1 & still=0 -> weaned; "
     "indeterminate combos -> NULL. 241 datasets, 1,217,377 rows."),
    ("P31", "final_CH_MICS", "CP_fed_milk_yesterday",
     "infant_fed_milk_yesterday was semantically inconsistent and mis-aligned: for ~52 "
     "MICS6 datasets it was mapped to BD8N='child ate CHEESE/other food made from milk' "
     "(a solid dairy food, not milk drinking); Cuba MICS4->juice, Sao Tome MICS5->fish; "
     "and the correctly-mapped ones mixed formula / animal-milk / combined.",
     "Re-derived CP_fed_milk_yesterday = drank infant formula (infant_fed_formula_"
     "yesterday) OR animal/other milk (infant_fed_milk_yesterday where valid, else the "
     "real BD7E recovered from the raw SAV for 50 mis-aligned MICS6 datasets); cheese/"
     "juice/fish excluded. 227 datasets; rate 0.39. 4 datasets skipped BD7E (guard) -> "
     "formula only."),
    ("P30", "final_CH_MICS", "CP_still_breastfeeding",
     "still_breastfeeding aligned for 240 datasets; 2 more (DR Congo 2001, "
     "Kyrgyzstan) had it unmapped in the raw SAV (BF2).",
     "Added CP_still_breastfeeding (1=Yes/0=No/NULL): harmonized 240 + recovered 1 "
     "(DR Congo 2001; Kyrgyzstan skipped - broken key). 240->241 datasets; still rate "
     "0.44. Near ceiling - the other missing datasets never asked it. Consistency "
     "checked: still=1&ever=0 stays 57 rows (pre-existing raw noise, no new)."),
    ("P29", "final_CH_MICS", "CP_ever_breastfed",
     "ever_breastfed was aligned for 205 datasets; 31 more had the question UNMAPPED "
     "in their raw SAV under a non-English label (French 'L'enfant a été allaité', "
     "Spanish 'El niño fue amamantado', Portuguese 'Alimentado com leite materno').",
     "Added CP_ever_breastfed (1=Yes/0=No/NULL): harmonized the 205 mapped (1->1,2->0, "
     "sentinels null) and recovered 28 of the 31 unmapped datasets by guarded "
     "positional backfill, value classified from each column's SAV labels (excluding "
     "diarrhoea/still/yesterday look-alikes). 205->233 datasets; ever-breastfed 0.95. "
     "3 skipped (no SAV / no guard key on 2000-era)."),
    ("P28", "final_WM_MICS", "CP_early_initiation_breastfeeding",
     "No early-initiation-of-breastfeeding indicator existed; the 'time to first "
     "breastfeed' question (number+unit) was aligned for 154 datasets but 39 more had "
     "it UNMAPPED under a non-English label (translation gap).",
     "Derived CP_time_to_breastfeed_hours (unit interpreted by label: immediately/"
     "minutes/hours/days), CP_early_initiation_breastfeeding (<=1h) and "
     "CP_breastfed_within_24h. Recovered 36 unmapped datasets (guarded), excluding "
     "look-alikes (time bathed / facility stay / postnatal / BF duration). "
     "154->190 datasets; early-init rate 0.56."),
    ("P27", "final_HH_MICS", "CP_country",
     "No standardised geography existed: country was only implicit in dataset_name "
     "(many spellings/subnational surveys) and the subnational unit was an unlabeled "
     "numeric `region` code.",
     "Added CP_country / CP_country_code (ISO3) — dataset_name matched to "
     "data/geolocation/country.json (255/255) — and CP_subnational / "
     "CP_subnational_matched — the admin-1 code's SAV label (from `region`, else the "
     "`province` column — some surveys' HH7 landed there) canonicalised to state.json "
     "admin-1 names (exact/fold/fuzzy≤2), else the raw label kept (matched=0). All 4 "
     "tables; subnational HH 191 / WM 171 / CH 176 / HL 164 datasets; plus CP_district / CP_district_matched (admin-2, HH 34 ds) kept separate; dictionary in _geo_dict."),
    ("P26", "final_WM_MICS", "CP_woman_birth_year",
     "woman_age (and its P11 copy CP_woman_age) was contaminated: 153 datasets "
     "stored the 5-year age-GROUP code (1-7), not the real age (identical to "
     "woman_age_group); only 86 held the real 15-49 age. And no woman birth year "
     "existed.",
     "Recovered the real age from the household listing (HL join on dataset/cluster/"
     "household/line) and rebuilt CP_woman_age = real age (raw where real, else HL); "
     "216 datasets (31 group-code datasets have no WM line number so stay NULL). "
     "Derived CP_woman_birth_year (Gregorian 1940-2010): exact from woman_birth_date_"
     "cmc / woman_birth_year for Gregorian datasets (est=0), else CP_survey_year - "
     "CP_woman_age (est=1, ±1yr) for Nepal/Thailand/gaps; a plausibility guard "
     "(implied age 12-60) drops contaminated birth-year fields. 245 datasets; "
     "CP_woman_birth_year_estimated flags the source."),
    ("P25", "final_WM_MICS", "CP_survey_year",
     "No harmonized interview year/month existed: `interview_year`/`interview_month` "
     "carry sentinels (9999/99/0) and two non-Gregorian calendars — Thailand "
     "(Buddhist Era, year+543) and Nepal (Bikram Sambat, different year AND month).",
     "Added CP_survey_year + CP_survey_month (Gregorian) in all 4 tables. Normal "
     "datasets use interview_year/month (verified == cmc-derived: year 100%, month "
     "99.9%); Thailand = year-543 (month unchanged); Nepal converted BS->Gregorian "
     "via an embedded BS calendar (month lengths + per-year anchor). WM fills 7 "
     "cmc-only datasets from interview_date_cmc. Clean range year 1998-2025, month "
     "1-12. HH 242 / WM 244 / CH 243 / HL 210 datasets, out-of-range 0."),
    ("P24", "final_HH_MICS", "CP_area_type",
     "The raw `area` (HH6 area of residence) is not comparable across surveys: "
     "codes/labels differ (usually 1=urban/2=rural, Zambia reversed), many surveys "
     "use >2 categories needing collapse (Mongolia capital/aimag/soum centre, Lao "
     "rural-with/without-road, city-name strata, peri-urban, slum), and `area` was "
     "mis-aligned to a region/cluster column in ~26 datasets.",
     "Added CP_area_type (1 Urban / 2 Rural / 3 Refugee-camp / NULL) in all four "
     "tables via per-dataset value-label classification: urban incl. city/capital/"
     "centre/metro/municipal/slum; rural incl. village/interior/coastal/tribal/"
     "peri-urban; camp = the 3 State-of-Palestine surveys (HH6=Camp). Region-only "
     "codings (Egypt sub-national) -> NULL. Contaminated/unaligned datasets "
     "recovered from HH6 in the HH SAV (guarded); member tables filled from HH via "
     "the household join. HH 241 / WM 225 / CH 229 / HL 213 datasets."),
    ("P23", "final_WM_MICS", "CP_first_trimester_anc",
     "No first-trimester-ANC indicator existed; the 'weeks/months pregnant at first "
     "ANC visit' timing was mapped for only 74 datasets, and ~44 more had the raw "
     "timing question (MN2AN/MN2AU, MN2AAN/MN2AAU, MN4AN/MN4AU, single month/week "
     "columns) unmapped.",
     "Derived CP_first_trimester_anc (1 = first ANC <=3 months / <=13 weeks, 0 = "
     "later, NULL): from the mapped timing number+unit for 74 datasets, plus 41 "
     "recovered from unmapped raw timing columns (guarded positional backfill). "
     "CP_first_trimester_anc_derived flags mapped(0) vs recovered(1). 277,613 rows "
     "/ 115 datasets; overall first-trimester rate 0.59. 3 skipped (no SAV / "
     "unverifiable key)."),
    ("P22", "final_WM_MICS", "CP_received_anc",
     "received_anc was aligned to BOTH the yes/no ANC question (MN1/MN2) AND the "
     "visit-count (MN3/MN5), contaminating the binary with counts; 5 datasets had "
     "only a count/timing column mapped; and 88 datasets (mostly MICS2/MICS3-era) "
     "looked 'missing' but had asked ANC via a provider checklist, not a single "
     "yes/no question.",
     "Added CP_received_anc (1 received / 0 not / NULL): harmonized 153 clean "
     "yes/no datasets; recovered 10 with an unmapped MN1/MN2 question; DERIVED 58 "
     "MICS2/MICS3-era datasets from the MN2 provider checklist (any provider=1, "
     "no one=0 — validated to reproduce the yes/no answer at median 100%/mean "
     "99.5% on 150 overlap datasets); CP_received_anc_derived flags the source. "
     "Coverage 158 -> 221 datasets / 557,131 rows. 19 skipped (no SAV or "
     "unverifiable household key); 11 genuinely never collected ANC in WM."),
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
    ("P21", "final_CH_MICS", "CP_child_sample_weight",
     "child_sample_weight had a scale inconsistency (a few datasets store "
     "un-normalised expansion weights, mean 60-5000, vs mean~1 elsewhere) and was "
     "unmapped for 51 datasets that have a raw chweight column.",
     "Added CP_child_sample_weight normalised to mean 1 within each dataset (only "
     "the un-normalised outlier datasets, mean>5, divided by their mean; others "
     "unchanged; weight 0 kept). Recovered 30 datasets from raw chweight (guarded); "
     "21 skipped (no usable household key). 1,104,528 rows / 164 datasets."),
    ("P20", "final_WM_MICS", "CP_place_of_delivery",
     "place_of_delivery uses country-specific numeric codes and was mapped for "
     "only 176 datasets; Philippines 1999 was mis-mapped to 'who decided the "
     "place'; ~33 datasets had an unmapped place column (MN18/MN20/MN8/NN3).",
     "Added CP_place_of_delivery, harmonized 5-category (1 Home / 2 Public / "
     "3 Private / 4 Other facility / 5 Other-en route) via per-dataset value-"
     "label mapping; recovered 34 unmapped datasets by guarded backfill. "
     "543,011 rows / 209 datasets. Philippines 1999 left NULL (mis-map)."),
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
    ("final_WM_MICS", "CP_first_trimester_anc"): "First-trimester ANC: 1 = first antenatal-care visit in the first trimester (<=3 months / <=13 weeks pregnant), 0 = later, NULL = no timing / missing. Derived from the 'weeks or months pregnant at first ANC visit' question (anc_first_visit_timing_number + _unit). 115 datasets (74 mapped + 41 recovered from unmapped MN2AN/MN4AN/... via CP_first_trimester_anc_derived). (P23)",
    ("final_HH_MICS", "CP_country"): "Country (canonical name, from data/geolocation/country.json), matched from dataset_name. Subnational surveys map to the mother country (e.g. Pakistan (Punjab)→Pakistan); Palestinians-in-Lebanon→Lebanon. (P27)",
    ("final_HH_MICS", "CP_country_code"): "ISO3 country code for CP_country. (P27)",
    ("final_HH_MICS", "CP_subnational"): "Admin-1 unit (state/province/region/governorate) NAME. The raw `region` code's SAV label canonicalised to state.json where it matches (CP_subnational_matched=1), else the cleaned raw label (=0). NULL where `region` is unpopulated or unlabeled. Meaningful only within a country; granularity varies by survey. (P27)",
    ("final_HH_MICS", "CP_subnational_matched"): "1 = CP_subnational matched a state.json admin-1 name (standardised); 0 = raw survey label kept (macro-region / transliteration / re-districting differs); NULL where CP_subnational is NULL. (P27)",
    ("final_HH_MICS", "CP_district"): "Admin-2 unit (district/arrondissement) NAME, from the `district` code's SAV label; standardised to state.json where it happens to align (small countries whose 'district' IS admin-1, e.g. Lesotho — CP_district_matched=1), else the cleaned raw label (=0). Finer than CP_subnational; kept separate to keep CP_subnational a single admin-1 level. (P27)",
    ("final_HH_MICS", "CP_district_matched"): "1 = CP_district matched a state.json name; 0 = raw label; NULL where CP_district is NULL. (P27)",
    ("final_WM_MICS", "CP_district"): "Admin-2 unit name (see final_HH_MICS.CP_district). (P27)",
    ("final_WM_MICS", "CP_district_matched"): "1 matched / 0 raw label. (P27)",
    ("final_CH_MICS", "CP_district"): "Admin-2 unit name (see final_HH_MICS.CP_district). (P27)",
    ("final_CH_MICS", "CP_district_matched"): "1 matched / 0 raw label. (P27)",
    ("final_HL_MICS", "CP_district"): "Admin-2 unit name (see final_HH_MICS.CP_district). (P27)",
    ("final_HL_MICS", "CP_district_matched"): "1 matched / 0 raw label. (P27)",
    ("final_WM_MICS", "CP_country"): "Country canonical name (see final_HH_MICS.CP_country). (P27)",
    ("final_WM_MICS", "CP_country_code"): "ISO3 country code. (P27)",
    ("final_WM_MICS", "CP_subnational"): "Admin-1 unit name (see final_HH_MICS.CP_subnational). (P27)",
    ("final_WM_MICS", "CP_subnational_matched"): "1 matched state.json / 0 raw label (see final_HH_MICS). (P27)",
    ("final_CH_MICS", "CP_country"): "Country canonical name (see final_HH_MICS.CP_country). (P27)",
    ("final_CH_MICS", "CP_country_code"): "ISO3 country code. (P27)",
    ("final_CH_MICS", "CP_subnational"): "Admin-1 unit name (see final_HH_MICS.CP_subnational). (P27)",
    ("final_CH_MICS", "CP_subnational_matched"): "1 matched / 0 raw label. (P27)",
    ("final_HL_MICS", "CP_country"): "Country canonical name (see final_HH_MICS.CP_country). (P27)",
    ("final_HL_MICS", "CP_country_code"): "ISO3 country code. (P27)",
    ("final_HL_MICS", "CP_subnational"): "Admin-1 unit name (see final_HH_MICS.CP_subnational). (P27)",
    ("final_HL_MICS", "CP_subnational_matched"): "1 matched / 0 raw label. (P27)",
    ("final_WM_MICS", "CP_time_to_breastfeed_hours"): "Hours after birth the child was first put to the breast (harmonized): unit read by LABEL (immediately=0 / minutes/60 / hours / days*24). Sentinels & implausible -> NULL. WM, last birth. (P28)",
    ("final_WM_MICS", "CP_early_initiation_breastfeeding"): "Early initiation of breastfeeding: 1 = first breastfed within 1 hour of birth, 0 = later, NULL = missing. Standard WHO/MICS indicator, from CP_time_to_breastfeed_hours. 190 datasets. (P28)",
    ("final_WM_MICS", "CP_breastfed_within_24h"): "1 = first breastfed within 24 hours of birth, 0 = later, NULL = missing. (P28)",
    ("final_WM_MICS", "woman_age"): "Woman's age, RAW: for 153 datasets this holds the 5-YEAR AGE-GROUP code (1-7), NOT the real age (identical to woman_age_group); only 86 hold real 15-49. Use CP_woman_age. (P26)",
    ("final_WM_MICS", "CP_woman_age"): "Woman's real age in years (10-64): raw woman_age where it is genuinely 15-49, else recovered from the household-listing age (HL join). NULL for 31 group-code datasets with no WM line number to join on (their age band is in CP_woman_age_group). (P26)",
    ("final_WM_MICS", "CP_woman_birth_year"): "Woman's birth year, Gregorian (1940-2010). Exact from woman_birth_date_cmc / woman_birth_year where those are Gregorian (CP_woman_birth_year_estimated=0); else CP_survey_year - CP_woman_age (=1, ±1yr) for Nepal (Bikram Sambat), Thailand (Buddhist Era) and datasets lacking a Gregorian birth field. A plausibility guard drops birth years implying age <12 or >60. (P26)",
    ("final_WM_MICS", "CP_woman_birth_year_estimated"): "Provenance/precision flag for CP_woman_birth_year: 0 = exact (from a birth-date field), 1 = age-derived (survey_year - age, ±1 year); NULL where CP_woman_birth_year is NULL. (P26)",
    ("final_HH_MICS", "CP_survey_year"): "Interview (survey) year, Gregorian: cleaned interview_year with Thailand Buddhist-Era (−543) and Nepal Bikram-Sambat converted to Gregorian; sentinels 9999/0 → NULL; valid 1998–2025. Each table uses its own interview date. (P25)",
    ("final_HH_MICS", "CP_survey_month"): "Interview (survey) month 1–12, Gregorian (Thailand month unchanged; Nepal BS→Gregorian); sentinel 99 → NULL. (P25)",
    ("final_WM_MICS", "CP_survey_year"): "Interview (survey) year, Gregorian: cleaned interview_year / interview_date_cmc with Thailand (−543) and Nepal (BS→Gregorian) conversion; valid 1998–2025. (P25)",
    ("final_WM_MICS", "CP_survey_month"): "Interview (survey) month 1–12, Gregorian. (P25)",
    ("final_CH_MICS", "CP_survey_year"): "Interview (survey) year, Gregorian (see final_HH_MICS.CP_survey_year). (P25)",
    ("final_CH_MICS", "CP_survey_month"): "Interview (survey) month 1–12, Gregorian. (P25)",
    ("final_HL_MICS", "CP_survey_year"): "Interview (survey) year, Gregorian (see final_HH_MICS.CP_survey_year). (P25)",
    ("final_HL_MICS", "CP_survey_month"): "Interview (survey) month 1–12, Gregorian. (P25)",
    ("final_HH_MICS", "CP_area_type"): "Harmonized area of residence: 1=Urban, 2=Rural, 3=Refugee-camp, NULL. Cross-survey comparable (raw `area`/HH6 is not — codes/labels differ, some surveys use >2 collapsed categories, some were mis-aligned to a region column). Urban incl. city/capital/centre/metro/municipal/slum; rural incl. village/interior/coastal/tribal/peri-urban; camp = State-of-Palestine surveys only. (P24)",
    ("final_WM_MICS", "CP_area_type"): "Harmonized area of residence: 1=Urban, 2=Rural, 3=Refugee-camp, NULL (household's value, from final_HH_MICS). Use instead of raw `area`. (P24)",
    ("final_CH_MICS", "CP_area_type"): "Harmonized area of residence: 1=Urban, 2=Rural, 3=Refugee-camp, NULL (household's value, from final_HH_MICS). Use instead of raw `area`. (P24)",
    ("final_HL_MICS", "CP_area_type"): "Harmonized area of residence: 1=Urban, 2=Rural, 3=Refugee-camp, NULL (household's value, from final_HH_MICS). Use instead of raw `area`. (P24)",
    ("final_HH_MICS", "area"): "Area of residence, RAW (HH6): country-specific codes/labels, not cross-survey comparable (some >2 categories, some mis-aligned to region). Use CP_area_type. (P24)",
    ("final_WM_MICS", "area"): "Area of residence, RAW (HH6): not cross-survey comparable. Use CP_area_type. (P24)",
    ("final_CH_MICS", "area"): "Area of residence, RAW (HH6): not cross-survey comparable. Use CP_area_type. (P24)",
    ("final_HL_MICS", "area"): "Area of residence, RAW (HH6): not cross-survey comparable. Use CP_area_type. (P24)",
    ("final_WM_MICS", "CP_first_trimester_anc_derived"): "Provenance flag for CP_first_trimester_anc: 0 = from the already-mapped anc_first_visit_timing_number/_unit; 1 = recovered from an unmapped raw first-visit timing column; NULL where CP_first_trimester_anc is NULL. (P23)",
    ("final_WM_MICS", "received_anc"): "Received antenatal care, RAW: aligned to BOTH the yes/no question (MN1/MN2) AND the visit-count (MN3/MN5) in most datasets, so values are contaminated by counts; some datasets hold a count/timing column instead. Use CP_received_anc. (P22)",
    ("final_WM_MICS", "CP_received_anc"): "Received antenatal care during last pregnancy, harmonized binary: 1=received / 0=not received / NULL=missing. 163 datasets from the direct yes/no question (MN1/MN2); 58 MICS2/MICS3-era datasets DERIVED from the provider checklist ('whom did you see for ANC': any provider=1, no one=0) — matches UNICEF's ANC-coverage definition. See CP_received_anc_derived. (P22)",
    ("final_WM_MICS", "CP_received_anc_derived"): "Provenance flag for CP_received_anc: 0 = self-reported yes/no question; 1 = derived from the MN2 provider checklist (MICS2/MICS3-era datasets that never asked a single yes/no ANC question); NULL where CP_received_anc is NULL. (P22)",
    ("final_WM_MICS", "CP_place_of_delivery"): "Place of delivery, harmonized 5-category (per-dataset value-label mapping): 1=Home, 2=Public facility, 3=Private facility, 4=Other facility (NGO/faith/UNRWA/sector-unknown), 5=Other/en route; NULL=DK/missing. (P20)",
    # HL
    ("final_HL_MICS", "relationship_to_head"): "Relationship to household head; 1 = head. Head is roster line 1 by MICS design.",
    ("final_HL_MICS", "sex"): "1 = male, 2 = female.",
    ("final_HL_MICS", "highest_grade_completed"): "Attainment grade, RAW: mixed codings across datasets — use education_years for comparisons. (P08 backfilled)",
    ("final_HL_MICS", "ever_completed_grade"): "Completed that grade? 1 yes, 2 no. (P08)",
    ("final_HL_MICS", "education_years"): "Years of schooling, 0-25, cross-dataset comparable. (P09)",
    ("final_HL_MICS", "education_years_estimated"): "1 = midpoint estimate, 0 = exact. (P09)",
    # CH
    ("final_CH_MICS", "child_age_years"): "Child age in completed years 0-4, ALL datasets. (P07)",
    ("final_CH_MICS", "child_age_months"): "Child age in months 0-59, RAW: only ~42 month-coded datasets, NULL elsewhere. Use CP_child_age_months (248 datasets). (P07/P33)",
    ("final_CH_MICS", "CP_child_age_months"): "Child age in completed months 0-59, 248 datasets. Rebuilt from raw: CAGE ('Age (months)') where present, else interview-minus-birth date (CMC: MICS4/5 UF8M/Y-AG1M/Y, MICS6 UF7M/Y-UB1M/Y). Guarded (0-59 scale + household or age-year row alignment). Prefer over raw child_age_months (~42) and over child_age_years where a month value exists. NULL for 7 datasets with no valid/aligned source (Cuba, Indonesia-2000, Kyrgyzstan-05, Myanmar-2000, CAR-2000, Guyana/Iraq-2000). (P33)",
    ("final_CH_MICS", "mother_education_harmonized"): "Mother's education, ISCED 4-level 0-3. NULL=sentinel/unmapped. (P03)",
    ("final_CH_MICS", "mother_education_years"): "Mother's years of schooling 0-25: WM-linked, HL fallback, coarse midpoint last resort. (P09)",
    ("final_CH_MICS", "mother_education_years_estimated"): "1 = estimated (midpoint/coarse fallback), 0 = exact. (P09)",
    ("final_CH_MICS", "bmi_for_age_zscore"): "BMI-for-age z-score (WHO), RAW/MICS-provided: keeps sentinel 999.99 and implausible values. Use CP_bmi_for_age_zscore. NB WHO prefers weight_for_height_zscore for under-5. (P14)",
    ("final_CH_MICS", "CP_bmi_for_age_zscore"): "BMI-for-age z-score, cleaned to |z|<=6, PLUS derived (WHO 2006 from weight/height/age/sex) for 33 fully-missing datasets that passed a data-quality gate. ~1.17M rows / 178 datasets. See CP_bmi_for_age_zscore_derived. (P14)",
    ("final_CH_MICS", "CP_bmi_for_age_zscore_derived"): "1 = CP_bmi_for_age_zscore was derived here (WHO 2006), 0 = MICS-provided, NULL = CP_ is NULL. ~187k derived. (P14)",
    ("final_CH_MICS", "child_sample_weight"): "Child sample weight, RAW: 131 datasets normalised (mean~1) but Thailand/Costa Rica/Panama store un-normalised expansion weights. Use CP_child_sample_weight for pooling. (P21 recovered 51 datasets)",
    ("final_CH_MICS", "CP_child_sample_weight"): "Child sample weight, scale-harmonised for pooling: normalised to mean 1 within each dataset (only the un-normalised outlier datasets divided by their mean; others unchanged). 0 = excluded case. (P21)",
    ("final_CH_MICS", "diarrhea_last_2_weeks"): "Had diarrhoea in last 2 weeks, RAW: coding varies across datasets (1/2, 0/1, 0/100, Iraq/Yemen 2=yes-without-blood). Use CP_diarrhea_last_2_weeks. (P15 fixed Congo_MICS5 source CA2->CA1)",
    ("final_CH_MICS", "CP_diarrhea_last_2_weeks"): "Diarrhoea in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label-driven mapping (handles 2=yes-without-blood, 0/100). (P15)",
    ("final_CH_MICS", "fever_last_2_weeks"): "Had fever in last 2 weeks, RAW: coding varies across datasets (1/2, 0/100, sentinels). Use CP_fever_last_2_weeks. (P16)",
    ("final_CH_MICS", "CP_fever_last_2_weeks"): "Fever in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label mapping; 9 datasets recovered from unmapped/mis-mapped raw cols (malaria-module ML1/CA6AA/PCA6) the alignment had missed. 167 datasets. (P16)",
    ("final_CH_MICS", "cough_last_2_weeks"): "Had cough in last 2 weeks, RAW: coding varies across datasets (1/2, 0/1, sentinels). Use CP_cough_last_2_weeks. (P17)",
    ("final_CH_MICS", "CP_cough_last_2_weeks"): "Cough in last 2 weeks, harmonized: 1=Yes, 0=No, NULL=DK/missing/unknown. Per-dataset label mapping; 5 datasets recovered from unmapped raw CI6/CA7/CA5 the alignment had missed. (P17)",
    ("final_CH_MICS", "ever_breastfed"): "Child ever breastfed, RAW (1=Yes/2=No + sentinels). Use CP_ever_breastfed. (P29)",
    ("final_CH_MICS", "CP_ever_breastfed"): "Was the child ever breastfed: 1=Yes, 0=No, NULL=DK/missing. 233 datasets — 205 harmonized + 28 recovered from raw SAV columns (BF1/BD2) the alignment had missed because of non-English labels (French/Spanish/Portuguese). (P29)",
    ("final_CH_MICS", "still_breastfeeding"): "Child still being breastfed, RAW (1=Yes/2=No + sentinels). Use CP_still_breastfeeding. (P30)",
    ("final_CH_MICS", "infant_fed_milk_yesterday"): "RAW and INCONSISTENT: for ~52 MICS6 datasets this is BD8N='ate cheese/food made from milk' (NOT milk drinking), plus juice/fish in a couple; elsewhere it mixes formula/animal/combined milk. Do NOT use directly — use CP_fed_milk_yesterday. (P31)",
    ("final_CH_MICS", "CP_fed_ors_yesterday"): "Whether the child drank ORS (oral rehydration solution) yesterday (1=yes, 0=no). Rebuilt fresh from raw, NAME-anchored to the ORS feeding item (BD5 MICS6; BF11 MICS4/5; BF3D MICS2/3 \u2018Received: ORS\u2019) then label-verified, because ORS also appears in the diarrhoea-care module (CA/CI series) which is a DIFFERENT question and had contaminated the base column for ~15 datasets. Sentinels nulled. 190 datasets; yes-rate ~3% (ORS is rare). (P60)",
    ("final_CH_MICS", "CP_fed_juice_yesterday"): "Whether the child drank juice or juice drinks yesterday (1=yes, 0=no). Rebuilt fresh from raw, NAME-anchored to the juice feeding item (BD7B MICS6; BF8 MICS4/5; BF3C MICS2/3 \u2018Received: sweetened water / juice\u2019) then label-verified, because \u2018juice\u2019 also appears on diarrhoea-care liquids (CA/CI series) whose column names differ. Sentinels nulled. 201 datasets. (P59)",
    ("final_CH_MICS", "CP_fed_plain_water_yesterday"): "Whether the child drank plain water yesterday (1=yes, 0=no). Rebuilt fresh from raw, NAME-anchored to the plain-water feeding item (BD7A MICS6; BF3 MICS4; BF3B MICS5 \u2018Received: plain water\u2019) then label-verified, because \u2018water\u2019 is a polluted keyword \u2014 household water-supply (WS), diarrhoea-care water (CI3/CA), and sweet/tea/broth water (the C-suffix items) all carry a water label and are excluded. Sentinels nulled. 207 datasets. (P58)",
    ("final_CH_MICS", "CP_times_solid_semisolid_soft_food_yesterday"): "Number of times the child ate solid, semi-solid or soft foods yesterday (IYCF meal-frequency count; MICS6 caps at '7 or more'). Rebuilt fresh from raw by label (BD9 MICS6; BF17 MICS4/5; BD11; BF5 some MICS4/5 \u2014 picked strictly by label since BF5 also means formula-times elsewhere); per-dataset sentinels (DK/missing/NR, >=90) nulled, one count per dataset. 163 datasets. (P57)",
    ("final_CH_MICS", "CP_times_yogurt_yesterday"): "Number of times the child drank or ate yogurt yesterday (count; MICS6 caps at '7 or more'). Rebuilt fresh from raw by label (BD8A1 MICS6; BD8AN MICS5; BF14 MICS4; BD7F1 MICS6-2023 yogurt-drink), summing eaten+drunk where split; per-dataset sentinels (DK/missing/NR, >=90) nulled, dummy/flag columns skipped. Non-null only for children who had yogurt. Count companion of CP_fed_yogurt_yesterday. 156 datasets. (P56)",
    ("final_CH_MICS", "CP_times_animal_milk_yesterday"): "Number of times the child drank animal / tinned / powdered / fresh milk yesterday (count; MICS6 caps at '7 or more', MICS4 up to ~22). Rebuilt fresh from raw by label (BD7E1 MICS6; BF7 MICS4/5); per-dataset sentinels (DK/missing/NR, >=90) nulled. Non-null only for children who drank animal milk. Count companion of CP_fed_animal_milk_yesterday. 44 datasets. (P55)",
    ("final_CH_MICS", "CP_times_infant_formula_yesterday"): "Number of times the child was fed infant formula yesterday (count; 7 = '7 or more' in MICS6, actual counts up to ~22 in MICS4). Rebuilt fresh from raw by label (BD7D1 MICS6; BF5/BD7EN MICS4/5); per-dataset sentinels (DK/missing/NR, >=90) nulled. Non-null only for formula-fed children. 132 datasets. (P54)",
    ("final_CH_MICS", "CP_fed_animal_milk_yesterday"): "Child drank animal / tinned / powdered / fresh milk yesterday (NOT infant formula, NOT breast milk, NOT yogurt): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw by label (BD7E MICS6; BD7D/BF6/BF3F/BF3E MICS4/5), excluding formula/breast/yogurt/cheese and diarrhoea-care fluids. 84 datasets. Animal-milk component of CP_fed_milk_yesterday (P31, formula OR animal milk). (P53)",
    ("final_CH_MICS", "CP_fed_milk_yesterday"): "Child drank milk yesterday: 1 = drank infant formula OR animal/other milk, 0 = neither, NULL = missing. Re-derived to fix the mis-aligned raw variable (which conflated cheese/juice/fish); animal-milk BD7E recovered from the SAV for 50 MICS6 datasets. 227 datasets. (P31)",
    ("final_CH_MICS", "CP_still_breastfeeding"): "Is the child still being breastfed: 1=Yes, 0=No, NULL=DK/missing. 241 datasets (240 harmonized + 1 recovered). By definition applies to children ever breastfed. (P30)",
    ("final_WM_MICS", "CP_respondent_native_language"): "Respondent's (woman's) native language / mother tongue, DECODED to the language name (text) from the SAV value labels; raw code renumbers per dataset. Excludes household-head language and interview/questionnaire language. Sentinels->NULL. 55 datasets. (P51)",
    ("final_HH_MICS", "CP_respondent_native_language"): "Household respondent's native language / mother tongue, decoded to the language name (text). 65 datasets. Distinct from mother_tongue_of_household_head. (P51)",
    ("final_CH_MICS", "CP_mother_native_language"): "Child's mother's native language (decoded language name), filled with priority WM (mother's own woman-record language) -> CH (this child's UF14 respondent) -> HH (household respondent). 477,440 children / 67 datasets. Note: names are not harmonised across countries (e.g. 'Arabe' vs 'Arabic'). (P52)",
    ("final_CH_MICS", "CP_mother_native_language_source"): "Which source filled CP_mother_native_language: 'WM' (mother's woman record), 'CH' (child questionnaire respondent), or 'HH' (household respondent). (P52)",
    ("final_CH_MICS", "CP_respondent_native_language"): "Child questionnaire respondent's (mother/caretaker) native language / mother tongue, decoded to the language name (text). 53 datasets. (P51)",
    ("final_CH_MICS", "CP_mother_birth_year"): "Mother's birth year (Gregorian), linked from her WM record's CP_woman_birth_year (P26), with an HL household-listing fallback (year_of_birth, else survey_year-age) for mothers not in the WM 15-49 file. 214 datasets. (P50)",
    ("final_CH_MICS", "CP_mother_birth_year_estimated"): "1 = the mother's CP_mother_birth_year is an estimate (from her WM CP_woman_birth_year_estimated). (P50)",
    ("final_CH_MICS", "CP_mother_birth_month"): "Mother's birth month 1-12, linked from her WM record (woman_birth_month cleaned, else derived from woman_birth_date_cmc; HL month_of_birth fallback). 206 datasets. (P50)",
    ("final_CH_MICS", "CP_fed_sweets_yesterday"): "Child ate sugary/sweet FOODS yesterday (chocolate, sweets, candies, pastries, cakes): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw by label (letter varies BD8O/BD8P/BD8Q/BF16M/BF19N/DD1S); excludes sugary drinks and sugar-salt solutions. Only 11 datasets asked this unhealthy-foods add-on. (P48)",
    ("final_CH_MICS", "dd_sweets"): "Dietary sugary-foods flag, RAW; only 12 datasets. Use CP_fed_sweets_yesterday (11, label-driven). (P48)",
    ("final_CH_MICS", "CP_fed_other_fruit_vegetables_yesterday"): "Child ate other fruits or vegetables yesterday (catch-all not in a specific group): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8H, OR-combined with BD8F1 'other vegetables' in MICS6-2023 surveys. Pakistan-KP reads BD8G (its BD8H is meat). 116 datasets. (P47)",
    ("final_CH_MICS", "dd_other_fruit_veg"): "Dietary-diversity other-fruit/veg flag, RAW (BD8H). Use CP_fed_other_fruit_vegetables_yesterday (116). (P47)",
    ("final_CH_MICS", "CP_fed_vitamin_a_fruits_yesterday"): "Child ate vitamin-A-rich fruits yesterday (ripe mangoes, papayas, apricots, ripe melon, persimmon etc. - locally adapted): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8G (vit-A-fruit label + household guard). Pakistan-KP reads its real vit-A fruit BD8F (its BD8G is other fruit/veg). 108 datasets. (P46)",
    ("final_CH_MICS", "dd_vitamin_a_fruit"): "Dietary-diversity vit-A fruit flag, RAW (BD8G); only 65 datasets. Use CP_fed_vitamin_a_fruits_yesterday (108). (P46)",
    ("final_CH_MICS", "CP_fed_dark_green_leafy_vegetables_yesterday"): "Child ate dark green leafy vegetables yesterday (spinach, broccoli, Swiss chard, kale, collard etc.): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8F (green-leafy label + household guard). Pakistan-KP has no green-leafy item (its BD8F is vitamin-A fruit) and is excluded. 107 datasets. (P45)",
    ("final_CH_MICS", "dd_green_leafy_veg"): "Dietary-diversity dark-green-leafy flag, RAW (BD8F). Use CP_fed_dark_green_leafy_vegetables_yesterday (107, recovers Spanish/Portuguese-labelled datasets). (P45)",
    ("final_CH_MICS", "CP_fed_vitamin_a_vegetables_yesterday"): "Child ate vitamin-A-rich vegetables yesterday (pumpkin, carrots, squash, orange sweet potato that are yellow/orange inside): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8D (vit-A-veg label + household guard). 107 datasets. (P44)",
    ("final_CH_MICS", "dd_vitamin_a_veg"): "Dietary-diversity vitamin-A vegetable flag, RAW (BD8D). Multi-source (BD7B1/BD7B2 liquids) for Fiji/Georgia MICS6. Use CP_fed_vitamin_a_vegetables_yesterday. (P44)",
    ("final_CH_MICS", "CP_fed_eggs_yesterday"): "Child ate eggs yesterday: 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8K (egg-label + household guard). Pakistan-KP reads its real eggs BD8I (its BD8K is legumes). 107 datasets. (P43)",
    ("final_CH_MICS", "dd_eggs"): "Dietary-diversity eggs flag, RAW (BD8K). Mis-sourced for a few: Pakistan-KP MICS5 value is legumes (BD8K shifted), Azerbaijan MICS6-2023 multi-source. Use CP_fed_eggs_yesterday. (P43)",
    ("final_CH_MICS", "CP_fed_fish_seafood_yesterday"): "Child ate fresh or dried fish or shellfish yesterday: 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8L (fish-label + household guard). Pakistan-KP reads its real fish BD8J (its BD8L is cheese); Guyana reads BD8L not BD7C broth. 108 datasets. (P42)",
    ("final_CH_MICS", "dd_fish_seafood"): "Dietary-diversity fish/seafood flag, RAW (BD8L). Mis-sourced for a few: Pakistan-KP MICS5 value is cheese (BD8L shifted), Guyana MICS6 multi-source with BD7C broth. Use CP_fed_fish_seafood_yesterday. (P42)",
    ("final_CH_MICS", "CP_fed_meat_poultry_yesterday"): "Child ate meat/poultry yesterday (beef, pork, lamb, goat, chicken, duck): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8J (meat-label excl soup/broth + household guard). Pakistan-KP reads its real meat BD8H (its BD8J is fish); Vietnam MICS4 (BF9 meat broth) excluded. 108 datasets. (P41)",
    ("final_CH_MICS", "dd_meat_poultry"): "Dietary-diversity meat/poultry flag, RAW (BD8J). Mis-sourced for a few: Pakistan-KP MICS5 value is fish (BD8J shifted), Vietnam MICS4 is meat broth (BF9). Use CP_fed_meat_poultry_yesterday. (P41)",
    ("final_CH_MICS", "CP_fed_organ_meat_yesterday"): "Child ate liver, kidney, heart or other organ meat yesterday: 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8I (organ-meat-label + household guard). Excludes Pakistan-KP MICS5 whose BD8I is mislabelled 'eggs' (shifted letters). 107 datasets. (P40)",
    ("final_CH_MICS", "dd_organ_meat"): "Dietary-diversity organ-meat flag, RAW (BD8I). Mostly correct but Pakistan-KP MICS5's value is actually eggs (its BD8I is mislabelled). Use CP_fed_organ_meat_yesterday. (P40)",
    ("final_CH_MICS", "CP_fed_cheese_other_dairy_yesterday"): "Child ate cheese or other food made from milk yesterday (cheese/curd/cottage cheese etc.; excludes yogurt=CP_fed_yogurt and milk-drinking): 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8N (cheese-label + household guard), NOT from dd_dairy which was contaminated (took BD8A yogurt / BD7P-Q for some datasets). 112 datasets. (P39)",
    ("final_CH_MICS", "dd_dairy"): "Dietary-diversity dairy flag, RAW and CONTAMINATED: covered only 54 datasets and for multi-source ones the merge took the wrong column (Cameroon/CAR = BD8A yogurt, Georgia = BD7P/BD7Q1). Do NOT use - use CP_fed_cheese_other_dairy_yesterday. (P39)",
    ("final_CH_MICS", "CP_fed_yogurt_yesterday"): "Child drank or ate yogurt yesterday: 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw (OR of every yogurt yes/no column: BD8A drank/ate, BD7F/BD7F2 yogurt drinks, BF13 MICS4, BF3I received). NOT from infant_fed_yogurt_yesterday which was contaminated with times-counts (values 3/4/7) and cheese/mixed-dairy. 155 datasets. (P38)",
    ("final_CH_MICS", "infant_fed_yogurt_yesterday"): "Child ate/drank yogurt yesterday, RAW and CONTAMINATED: mixed the yes/no item (BD8A/BF13) with its times-count companion (BD8A1/BD8AN/BF14, values 3/4/7) plus some cheese/mixed-dairy columns. Do NOT use — use CP_fed_yogurt_yesterday. (P38)",
    ("final_CH_MICS", "CP_fed_pulses_nuts_seeds_yesterday"): "Child ate beans, peas, lentils, nuts or seeds yesterday: 1=Yes, 0=No, NULL=DK/missing. Rebuilt fresh from raw BD8M (legumes-label + household guard), NOT from dd_legumes_nuts which was contaminated (took BD8G fruit / BD7D formula / IM8-IM12 immunization for some datasets). 112 datasets. (P37)",
    ("final_CH_MICS", "dd_legumes_nuts"): "Dietary-diversity legumes/nuts flag, RAW and CONTAMINATED: for several multi-source datasets the merge took the wrong raw column (Algeria MICS6 = BD8G vitamin-A fruit; others BD7D formula or IM8/IM12 immunization). Do NOT use — use CP_fed_pulses_nuts_seeds_yesterday. (P37)",
    ("final_CH_MICS", "CP_fed_roots_tubers_plantains_yesterday"): "Child ate white roots, tubers or plantains yesterday (white potatoes/yams/manioc/cassava etc.): 1=Yes, 0=No, NULL=DK/missing. From raw BD8E. 113 datasets (94 mapped + 19 recovered). (P36)",
    ("final_CH_MICS", "dd_white_roots_tubers"): "Dietary-diversity white-roots/tubers flag, RAW (BD8E, 1=Yes/2=No + sentinels); 94 datasets. Use CP_fed_roots_tubers_plantains_yesterday (113). (P36)",
    ("final_CH_MICS", "CP_fed_grain_based_fortified_baby_food_yesterday"): "Child ate commercially fortified (grain-based) baby food yesterday, e.g. Cerelac/Gerber/Nestum: 1=Yes, 0=No, NULL=DK/missing. From raw BD8B only. 114 datasets (107 mapped + 7 recovered). MICS5/6-only item. (P35)",
    ("final_CH_MICS", "infant_fed_fortified_baby_food"): "Child ate fortified baby food yesterday, RAW (BD8B/BD8B1, 1=Yes/2=No + sentinels); 107 datasets. Use CP_fed_grain_based_fortified_baby_food_yesterday (114). (P35)",
    ("final_CH_MICS", "CP_fed_grains_yesterday"): "Child ate foods made from grains yesterday (bread/rice/noodles/porridge/pasta etc.): 1=Yes, 0=No, NULL=DK/missing. From raw BD8C only. 114 datasets (55 mapped + 59 recovered from unmapped non-English BD8C). Prefer over dd_grains, which conflated BD8C with broth/rice-water/roots/sweets/thin-porridge. (P34)",
    ("final_CH_MICS", "infant_fed_grains_yesterday"): "Child ate foods made from grains yesterday, RAW (BD8C, 1=Yes/2=No + sentinels); only 55 datasets. Use CP_fed_grains_yesterday (114). (P34)",
    ("final_CH_MICS", "dd_grains"): "Dietary-diversity grains flag, RAW and PARTLY MIS-ALIGNED: mostly BD8C (grains) but for ~16 datasets mapped to broth/rice-water/roots/sweets/diarrhoea-gruel/thin-porridge. Do NOT use for a clean grains indicator — use CP_fed_grains_yesterday. (P34)",
    ("final_CH_MICS", "CP_breastfeeding_status"): "Current breastfeeding status (3-category): 0 = never breastfed, 1 = ever breastfed but stopped/weaned, 2 = currently breastfeeding, NULL = indeterminate. Derived from CP_ever_breastfed (lifetime) + CP_still_breastfeeding (current): still=1 -> 2 (wins, implies ever); ever=0 -> 0; ever=1 & still=0 -> 1. 241 datasets, 1,217,377 rows. (P32)",
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
        "place_of_delivery", "received_anc", "woman_birth_year",
    ],
    "final_HL_MICS": [
        "highest_grade_completed", "ever_completed_grade",
        "education_years", "education_years_estimated",
    ],
    "final_CH_MICS": [
        "mother_education_harmonized", "child_age_months", "child_age_years",
        "mother_education_years", "mother_education_years_estimated",
        "bmi_for_age_zscore", "diarrhea_last_2_weeks", "fever_last_2_weeks",
        "cough_last_2_weeks", "child_sample_weight",
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
