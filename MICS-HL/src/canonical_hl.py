"""Rule-based canonicalization helpers for MICS HL (household listing) columns.

Key differences from the HH rule engine:
- "age" and "sex" refer to each listed household member, not the household head.
- Education (ED) and child labour (CL) module variables are the primary content.
- Eligibility line-number pointers link the listing to other questionnaires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_SPACE_RE = re.compile(r"\s+")
_VAR_PREFIX_RE = re.compile(r"^[a-z]{1,5}\d+[a-z0-9_]*[.)]\s*", re.IGNORECASE)


@dataclass(frozen=True)
class CanonicalEntry:
    canonical_varname: str
    canonical_text: str
    measure_type: str
    relation: str | None = None
    response_type: str | None = None
    event: str | None = None
    component: str | None = None
    entities: tuple[str, ...] = ()
    entity_operator: str | None = None
    is_compound: bool = False
    source_kind: str = "explicit"
    derivation: str | None = None
    confidence: str = "medium"
    needs_review: bool = False

    def to_dict(self) -> dict:
        data = {
            "canonical_varname": self.canonical_varname,
            "canonical_text": self.canonical_text,
            "measure_type": self.measure_type,
            "source_kind": self.source_kind,
            "confidence": self.confidence,
        }
        optional = {
            "relation": self.relation,
            "response_type": self.response_type,
            "event": self.event,
            "component": self.component,
            "entities": list(self.entities) if self.entities else None,
            "entity_operator": self.entity_operator,
            "is_compound": self.is_compound if self.is_compound else None,
            "derivation": self.derivation,
            "needs_review": self.needs_review if self.needs_review else None,
        }
        for key, value in optional.items():
            if value is not None:
                data[key] = value
        return data


def canonicalize_label(label: str) -> list[CanonicalEntry]:
    text = _clean_label(label)
    if not text:
        return [_fallback(label)]

    for fn in (
        _date_or_time,
        _identifiers,
        _demographics,
        _family_links,
        _eligibility_pointers,
        _education,
        _child_labour,
        _mosquito_net,
        _survey_metadata,
        _derived_background,
        _response_options,
    ):
        result = fn(text)
        if result is not None:
            return result if isinstance(result, list) else [result]

    return [_fallback(label)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_label(label: str) -> str:
    text = str(label or "").strip()
    text = _VAR_PREFIX_RE.sub("", text)
    text = text.replace("_", " ")
    text = text.replace("?", "")
    text = text.replace("'", "'")
    text = text.replace("&", " and ")
    text = text.replace(" / ", "/")
    text = text.replace(" - ", " ")
    text = text.lower()
    text = _SPACE_RE.sub(" ", text).strip(" :;,.")
    return text


def _has(text: str, *phrases: str) -> bool:
    return any(p in text for p in phrases)


def _exact(text: str, *phrases: str) -> bool:
    return text in phrases


def _fallback(label: str) -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname="unknown",
        canonical_text=str(label or "").strip(),
        measure_type="unknown",
        confidence="low",
        needs_review=True,
    )


def _explicit(varname: str, text: str, measure: str,
               response: str | None = None, confidence: str = "high") -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=text,
        measure_type=measure,
        source_kind="explicit",
        response_type=response,
        confidence=confidence,
    )


def _date_component(event: str, component: str, source_kind: str,
                    derivation: str | None, canonical_text: str) -> CanonicalEntry:
    varname = f"interview_{component}" if event == "interview" else f"{event}_{component}"
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=canonical_text,
        measure_type="interview_date_component",
        event=event,
        component=component,
        source_kind=source_kind,
        derivation=derivation,
        response_type="date_component",
        confidence="high",
    )


# ---------------------------------------------------------------------------
# Pattern matchers
# ---------------------------------------------------------------------------

def _date_or_time(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "date of interview", "interview date") and not _has(text, "birth"):
        return [
            _date_component("interview", "year",  "derived", "extract_year",  "Interview year"),
            _date_component("interview", "month", "derived", "extract_month", "Interview month"),
            _date_component("interview", "day",   "derived", "extract_day",   "Interview day"),
        ]
    if _has(text, "year of interview", "interview year"):
        return [_date_component("interview", "year", "explicit", None, "Interview year")]
    if _has(text, "month of interview", "interview month"):
        return [_date_component("interview", "month", "explicit", None, "Interview month")]
    if _has(text, "day of interview", "interview day"):
        return [_date_component("interview", "day", "explicit", None, "Interview day")]
    if _exact(text, "year of birth", "birth year"):
        return [_explicit("year_of_birth", "Year of birth", "demographics", "date_component")]
    if _exact(text, "month of birth", "birth month"):
        return [_explicit("month_of_birth", "Month of birth", "demographics", "date_component")]
    if _exact(text, "day of birth", "birth day"):
        return [_explicit("day_of_birth", "Day of birth", "demographics", "date_component")]
    return None


def _identifiers(text: str) -> CanonicalEntry | None:
    if _exact(text, "cluster number", "psu", "primary sampling unit"):
        varname = "primary_sampling_unit" if _has(text, "primary sampling unit", "psu") else "cluster_number"
        return _explicit(varname, varname.replace("_", " ").title(), "household_identifier", "identifier")
    if _exact(text, "household number"):
        return _explicit("household_number", "Household number", "household_identifier", "identifier")
    if _exact(text, "line number"):
        return _explicit("line_number", "Line number", "household_identifier", "identifier")
    if _exact(text, "stratum"):
        return _explicit("stratum", "Stratum", "survey_design", "identifier")
    return None


def _demographics(text: str) -> CanonicalEntry | None:
    if _exact(text, "sex"):
        return _explicit("sex", "Sex", "demographics", "categorical")
    if _exact(text, "age"):
        return _explicit("age", "Age", "demographics", "continuous")
    if _exact(text, "age above 3", "age 3-24", "member age 0-17", "age at beginning of school year"):
        return _explicit("age_at_start_of_school_year", "Age at beginning of school year",
                         "demographics", "continuous", confidence="medium")
    if _has(text, "relationship to the head", "relationship to head"):
        return _explicit("relationship_to_head", "Relationship to the head",
                         "household_head_demographics", "categorical")
    if _has(text, "marital status"):
        return _explicit("marital_status", "Marital status", "demographics", "categorical")
    return None


def _family_links(text: str) -> CanonicalEntry | None:
    if _has(text, "is natural mother alive", "natural mother alive") or _exact(text, "mother alive"):
        return _explicit("is_natural_mother_alive", "Is natural mother alive",
                         "household_member_background", "binary")
    if _has(text, "is natural father alive", "natural father alive") or _exact(text, "father alive"):
        return _explicit("is_natural_father_alive", "Is natural father alive",
                         "household_member_background", "binary")
    if _has(text, "natural mother's line number", "mother's line number in hh"):
        return _explicit("natural_mother_line_number", "Natural mother's line number",
                         "household_member_background", "identifier")
    if _has(text, "natural father's line number", "father's line number in hh"):
        return _explicit("natural_father_line_number", "Natural father's line number",
                         "household_member_background", "identifier")
    if _exact(text, "mother's line number"):
        return _explicit("natural_mother_line_number", "Natural mother's line number",
                         "household_member_background", "identifier")
    if _exact(text, "father's line number"):
        return _explicit("natural_father_line_number", "Natural father's line number",
                         "household_member_background", "identifier")
    if _has(text, "where does natural mother live"):
        return _explicit("natural_mother_location", "Where does natural mother live",
                         "household_member_background", "categorical")
    if _has(text, "where does natural father live"):
        return _explicit("natural_father_location", "Where does natural father live",
                         "household_member_background", "categorical")
    if _has(text, "does natural mother live in hh"):
        return _explicit("natural_mother_lives_in_hh", "Does natural mother live in household",
                         "household_member_background", "binary")
    if _has(text, "does natural father live in hh"):
        return _explicit("natural_father_lives_in_hh", "Does natural father live in household",
                         "household_member_background", "binary")
    if _has(text, "member stayed in the house last night", "stayed last night"):
        return _explicit("stayed_last_night", "Member stayed in the house last night",
                         "household_member_background", "binary")
    return None


def _eligibility_pointers(text: str) -> CanonicalEntry | None:
    if _has(text, "line number of woman age 15"):
        return _explicit("line_number_eligible_woman",
                         "Line number of eligible woman (15-49)",
                         "household_identifier", "identifier")
    if _has(text, "line number of mother", "line number of mother or primary caretaker") and _has(text, "0-17", "0 17"):
        return _explicit("line_number_mother_caretaker_child_0_17",
                         "Line number of mother/caretaker for children 0-17",
                         "household_identifier", "identifier")
    if _has(text, "line number", "number for children") and _has(text, "0-4", "0 4", "under 5", "age 5"):
        return _explicit("line_number_mother_caretaker_child_0_4",
                         "Line number of mother/caretaker for children 0-4",
                         "household_identifier", "identifier")
    if _has(text, "line number") and _has(text, "5-14", "5 14"):
        return _explicit("line_number_mother_caretaker_child_5_14",
                         "Line number of mother/caretaker for children 5-14",
                         "household_identifier", "identifier")
    return None


def _education(text: str) -> CanonicalEntry | None:
    if _has(text, "ever attended school"):
        return _explicit("ever_attended_school", "Ever attended school",
                         "education", "binary")
    if _has(text, "highest level of education", "highest education level"):
        return _explicit("highest_education_level", "Highest level of education attended",
                         "education", "categorical")
    if _has(text, "highest grade completed", "highest grade attended"):
        return _explicit("highest_grade_completed", "Highest grade completed",
                         "education", "ordinal")
    if _has(text, "attended school during current school year") or _exact(text, "attended school current year"):
        return _explicit("attended_school_current_year", "Attended school during current school year",
                         "education", "binary")
    if _has(text, "level of education attended current school year", "level during current"):
        return _explicit("education_level_current_year", "Level of education attended current school year",
                         "education", "categorical")
    if _has(text, "grade of education attended current school year", "grade during current"):
        return _explicit("education_grade_current_year", "Grade attended current school year",
                         "education", "ordinal")
    if _has(text, "attended school during previous school year",
                  "attended school previous year",
                  "attended school previous school year"):
        return _explicit("attended_school_previous_year", "Attended school during previous school year",
                         "education", "binary")
    if _has(text, "level of education attended previous school year",
                  "level of education attended last year",
                  "level during previous"):
        return _explicit("education_level_previous_year", "Level of education attended previous school year",
                         "education", "categorical")
    if _has(text, "grade of education attended previous school year",
                  "grade of education attended last year",
                  "grade during previous"):
        return _explicit("education_grade_previous_year", "Grade attended previous school year",
                         "education", "ordinal")
    if _has(text, "days attended") and _has(text, "past week", "since last"):
        return _explicit("school_days_attended_past_week", "Days attended school past week",
                         "education", "continuous")
    if _has(text, "highest level of school attended", "highest level of education attended"):
        return _explicit("highest_education_level", "Highest level of education attended",
                         "education", "categorical")
    if _exact(text, "level of education attended"):
        return _explicit("education_level_current_year", "Level of education attended",
                         "education", "categorical", confidence="medium")
    if _exact(text, "grade of education attended", "grade of education attended current year",
              "highest grade at level"):
        return _explicit("highest_grade_completed", "Highest grade completed",
                         "education", "ordinal", confidence="medium")
    if _has(text, "school tuition") or (_has(text, "tuition") and _has(text, "current school year")):
        return _explicit("school_tuition_current_year", "School tuition in the current school year",
                         "education", "categorical")
    if _has(text, "material support") and _has(text, "school year"):
        return _explicit("material_support_current_year", "Material support in the current school year",
                         "education", "categorical")
    if _has(text, "attended public school") and _has(text, "current"):
        return _explicit("attended_public_school_current_year", "Attended public school current school year",
                         "education", "binary")
    if _has(text, "ever completed that grade"):
        return _explicit("ever_completed_grade", "Ever completed that grade",
                         "education", "binary")
    if _has(text, "functional difficulties") and _has(text, "18-49", "18 49"):
        return _explicit("functional_difficulties_adult", "Functional difficulties (age 18-49)",
                         "health", "categorical")
    return None


def _child_labour(text: str) -> CanonicalEntry | None:
    if _has(text, "worked in past week for someone") or (
            _has(text, "worked") and _has(text, "past week") and _has(text, "not a hh", "outside")):
        return _explicit("worked_for_pay_past_week",
                         "Worked in past week for someone outside the household",
                         "child_labour", "binary")
    if _has(text, "hours worked in past week for someone") or (
            _has(text, "hours worked") and _has(text, "past week") and _has(text, "not a hh", "outside")):
        return _explicit("hours_worked_for_pay_past_week",
                         "Hours worked in past week for someone outside the household",
                         "child_labour", "continuous")
    if _has(text, "fetch water", "collect firewood") and _has(text, "worked", "past week"):
        return _explicit("worked_fetching_water_firewood",
                         "Worked in past week to fetch water or collect firewood",
                         "child_labour", "binary")
    if _has(text, "fetch water", "collect firewood") and _has(text, "hours"):
        return _explicit("hours_fetching_water_firewood",
                         "Hours spent fetching water or collecting firewood",
                         "child_labour", "continuous")
    if _has(text, "other paid or unpaid family work") or (
            _has(text, "other") and _has(text, "family work") and _has(text, "past week")):
        return _explicit("other_family_work_past_week",
                         "Other paid or unpaid family work in past week",
                         "child_labour", "binary")
    if _has(text, "hours worked on other family work", "hours on other family work"):
        return _explicit("hours_other_family_work",
                         "Hours worked on other family work",
                         "child_labour", "continuous")
    if _has(text, "helped with household chores") or (
            _has(text, "household chores") and _has(text, "past week")):
        return _explicit("household_chores_past_week",
                         "Helped with household chores in past week",
                         "child_labour", "binary")
    if _has(text, "hours spent on chores", "hours on chores", "hours doing chores"):
        return _explicit("hours_household_chores",
                         "Hours spent on household chores",
                         "child_labour", "continuous")
    return None


def _mosquito_net(text: str) -> CanonicalEntry | None:
    if _has(text, "mosquito net observed"):
        return _explicit("mosquito_net_observed", "Mosquito net observed",
                         "health_prevention", "binary")
    if _has(text, "months ago net obtained", "months ago obtained"):
        return _explicit("months_ago_mosquito_net_obtained", "Months ago mosquito net obtained",
                         "health_prevention", "continuous")
    if _exact(text, "net number"):
        return _explicit("mosquito_net_number", "Net number",
                         "health_prevention", "identifier")
    if _has(text, "persons slept under mosquito net"):
        return _explicit("persons_slept_under_net", "Persons slept under mosquito net last night",
                         "health_prevention", "count")
    if _has(text, "person 1 who slept under net") or _exact(text, "person 1 who slept under net"):
        return _explicit("person_1_slept_under_net", "Person 1 who slept under net",
                         "health_prevention", "identifier")
    if _has(text, "person 2 who slept under net"):
        return _explicit("person_2_slept_under_net", "Person 2 who slept under net",
                         "health_prevention", "identifier")
    if _has(text, "person 3 who slept under net"):
        return _explicit("person_3_slept_under_net", "Person 3 who slept under net",
                         "health_prevention", "identifier")
    if _has(text, "person 4 who slept under net"):
        return _explicit("person_4_slept_under_net", "Person 4 who slept under net",
                         "health_prevention", "identifier")
    return None


def _survey_metadata(text: str) -> CanonicalEntry | None:
    if _exact(text, "area"):
        return _explicit("area", "Area", "geography", "categorical")
    if _exact(text, "region"):
        return _explicit("region", "Region", "geography", "categorical")
    if _has(text, "interviewer number"):
        return _explicit("interviewer_number", "Interviewer number",
                         "survey_administration", "identifier")
    if _has(text, "supervisor number"):
        return _explicit("supervisor_number", "Supervisor number",
                         "survey_administration", "identifier")
    if _has(text, "data entry") and _has(text, "clerk", "number", "operator"):
        return _explicit("data_entry_clerk", "Data entry clerk number",
                         "survey_administration", "identifier")
    if _has(text, "field editor"):
        return _explicit("field_editor", "Field editor",
                         "survey_administration", "identifier")
    if _has(text, "result") and _has(text, "interview", "household"):
        return _explicit("household_interview_result", "Result of household interview",
                         "survey_administration", "categorical")
    if _has(text, "total eligible women", "number of eligible women"):
        return _explicit("total_eligible_women", "Total eligible women",
                         "survey_administration", "count")
    if _has(text, "number of household members"):
        return _explicit("number_of_household_members", "Number of household members",
                         "household_composition", "count")
    if _has(text, "province"):
        return _explicit("province", "Province", "geography", "categorical")
    if _exact(text, "district"):
        return _explicit("district", "District", "geography", "categorical")
    if _has(text, "respondent") and _has(text, "hh questionnaire", "household questionnaire"):
        return _explicit("respondent_to_household_questionnaire",
                         "Respondent to household questionnaire",
                         "survey_administration", "identifier")
    if _has(text, "women interviews completed", "women questionnaires completed"):
        return _explicit("number_of_women_questionnaires_completed",
                         "Number of women questionnaires completed",
                         "survey_administration", "count")
    if _has(text, "total children under 5", "children under 5"):
        return _explicit("number_of_children_under_5", "Number of children under 5",
                         "household_composition", "count")
    if _has(text, "child interviews completed", "child questionnaires completed"):
        return _explicit("number_of_child_questionnaires_completed",
                         "Number of child questionnaires completed",
                         "survey_administration", "count")
    return None


def _derived_background(text: str) -> CanonicalEntry | None:
    if _has(text, "household sample weight", "relative household weight", "household weight"):
        return _explicit("household_sample_weight", "Household sample weight",
                         "survey_design", "weight")
    if _exact(text, "wealth index score") or _has(text, "combined wealth score"):
        return _explicit("wealth_score", "Wealth index score",
                         "household_ses", "continuous")
    if _has(text, "urban wealth score"):
        return _explicit("urban_wealth_score", "Urban wealth score",
                         "household_ses", "continuous")
    if _has(text, "rural wealth score"):
        return _explicit("rural_wealth_score", "Rural wealth score",
                         "household_ses", "continuous")
    if _has(text, "wealth index quintile") and not _has(text, "urban", "rural"):
        return _explicit("wealth_index_quintile", "Wealth index quintile",
                         "household_ses", "ordinal")
    if _has(text, "urban wealth index quintile"):
        return _explicit("urban_wealth_index_quintile", "Urban wealth index quintile",
                         "household_ses", "ordinal")
    if _has(text, "rural wealth index quintile"):
        return _explicit("rural_wealth_index_quintile", "Rural wealth index quintile",
                         "household_ses", "ordinal")
    if _has(text, "education of household head"):
        return _explicit("education_of_household_head", "Education of household head",
                         "household_head_demographics", "categorical")
    if _exact(text, "mother's education") or _has(text, "mother education", "education of the mother"):
        return _explicit("mother_education", "Mother's education",
                         "household_member_background", "categorical")
    if _exact(text, "father's education") or _has(text, "father education", "education of the father"):
        return _explicit("father_education", "Father's education",
                         "household_member_background", "categorical")
    if _has(text, "ethnicity of household head"):
        return _explicit("ethnicity_of_household_head", "Ethnicity of household head",
                         "household_head_demographics", "categorical")
    if _has(text, "age at beginning of school year"):
        return _explicit("age_at_start_of_school_year", "Age at beginning of school year",
                         "education", "continuous")
    # Household assets that appear as background/derived in some HL files
    if _exact(text, "electricity"):
        return _explicit("household_has_electricity", "Household has electricity",
                         "household_asset", "binary")
    if _exact(text, "radio"):
        return _explicit("household_has_radio", "Household has radio", "household_asset", "binary")
    if _exact(text, "television"):
        return _explicit("household_has_television", "Household has television",
                         "household_asset", "binary")
    if _exact(text, "refrigerator"):
        return _explicit("household_has_refrigerator", "Household has refrigerator",
                         "household_asset", "binary")
    if _exact(text, "bicycle"):
        return _explicit("household_has_bicycle", "Household has bicycle",
                         "household_asset", "binary")
    if _exact(text, "mobile phone") or _has(text, "mobile telephone"):
        return _explicit("household_has_mobile_phone", "Household has mobile phone",
                         "household_asset", "binary")
    return None


def _response_options(text: str) -> CanonicalEntry | None:
    """Labels that are response options or context-free — do not assign canonical."""
    _skip = {
        "none", "other", "dk", "others", "no response", "missing",
        "yes", "no", "don't know", "do not know",
        "add bleach/chlorine", "boil", "solar disinfection",
        "strain it through a cloth", "let it stand and settle",
        "use water filter", "other (specify)",
        "tuition provided: other", "tuition provided: dk",
        "tuition provided: govt./public", "tuition provided: private",
        "tuition provided: no response", "tuition provided: ngo",
    }
    if text in _skip:
        return CanonicalEntry(
            canonical_varname="unknown",
            canonical_text=text,
            measure_type="response_option",
            confidence="low",
            needs_review=True,
        )
    return None
