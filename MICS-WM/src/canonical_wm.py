"""
Rule engine for MICS Women's Questionnaire (WM) canonicalisation.

Call canonicalise(column_label_in_english) -> list[CanonicalEntry].
Returns an empty list for labels that cannot be matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalEntry:
    canonical_varname: str
    canonical_text: str
    measure_type: str
    response_type: str | None = None
    relation: str | None = None
    event: str | None = None
    component: str | None = None
    entities: tuple[str, ...] = field(default_factory=tuple)
    entity_operator: str | None = None
    is_compound: bool = False
    source_kind: str = "explicit"
    derivation: str | None = None
    confidence: str = "high"
    needs_review: bool = False

    def to_dict(self) -> dict:
        d: dict = {
            "canonical_varname": self.canonical_varname,
            "canonical_text":    self.canonical_text,
            "measure_type":      self.measure_type,
            "source_kind":       self.source_kind,
            "confidence":        self.confidence,
            "needs_review":      self.needs_review,
        }
        for k in ("response_type", "relation", "event", "component",
                  "entity_operator", "derivation"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.entities:
            d["entities"] = list(self.entities)
        if self.is_compound:
            d["is_compound"] = True
        return d


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

_PREFIX_RE = re.compile(r"^[a-z]{1,5}\d+[a-z0-9_]*[.)]\s*")


_APOS = ('’', '‘', 'ʼ', "'")  # right-quote, left-quote, modifier-apos, ASCII-apos


def _clean_label(text: str) -> str:
    t = text.lower().strip()
    # Normalize all apostrophe variants before replacement
    for a in _APOS:
        t = t.replace(a + "s", "s")
    t = t.replace(" - ", " ")
    t = t.replace("&", " and ")
    t = _PREFIX_RE.sub("", t)
    t = t.rstrip(":? ")
    return t


def _has(text: str, *phrases: str) -> bool:
    return any(p in text for p in phrases)


def _exact(text: str, *phrases: str) -> bool:
    return text in phrases


def _startswith(text: str, *phrases: str) -> bool:
    return any(text.startswith(p) for p in phrases)


# ---------------------------------------------------------------------------
# Entry constructors
# ---------------------------------------------------------------------------

def _explicit(
    varname: str,
    text: str,
    measure_type: str,
    response_type: str | None = None,
    *,
    relation: str | None = None,
    event: str | None = None,
    component: str | None = None,
    entities: tuple[str, ...] = (),
    entity_operator: str | None = None,
    is_compound: bool = False,
    confidence: str = "high",
    needs_review: bool = False,
) -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=text,
        measure_type=measure_type,
        response_type=response_type,
        relation=relation,
        event=event,
        component=component,
        entities=entities,
        entity_operator=entity_operator,
        is_compound=is_compound,
        source_kind="explicit",
        confidence=confidence,
        needs_review=needs_review,
    )


def _derived(
    varname: str,
    text: str,
    measure_type: str,
    derivation: str,
    confidence: str = "high",
) -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=text,
        measure_type=measure_type,
        source_kind="derived",
        derivation=derivation,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Response-option skip set
# ---------------------------------------------------------------------------

_SKIP_LABELS = {
    "other", "other specify", "other (specify)", "other:",
    "others", "other (specify):",
    "dk", "don't know", "dont know", "do not know",
    "no", "yes", "none", "not applicable", "n/a", "na",
    "ns", "nr", "no answer", "not stated", "no response",
    "missing", "end", "finish",
    "none of the above", "none of the above codes",
    "not applicable (n/a)",
    "unit", "number",
}


def _response_options(text: str) -> list[CanonicalEntry] | None:
    if text in _SKIP_LABELS:
        return []
    if len(text) <= 2 and text.isalpha():
        return []
    return None


# ---------------------------------------------------------------------------
# Module functions
# ---------------------------------------------------------------------------

def _identifiers(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "cluster number", "cluster no"):
        return [_explicit("cluster_number", "Cluster number", "identifier")]
    if _has(text, "household number", "hh number", "household no"):
        return [_explicit("hh_number", "Household number", "identifier")]
    if _has(text, "womans line number", "woman line number", "woman's line no"):
        return [_explicit("woman_line_number", "Woman's line number", "identifier")]
    if _exact(text, "line number", "line no"):
        return [_explicit("line_number", "Line number", "identifier")]
    if _exact(text, "primary sampling unit", "psu"):
        return [_explicit("psu", "Primary sampling unit", "identifier")]
    if _exact(text, "stratum", "strata"):
        return [_explicit("stratum", "Stratum", "identifier")]
    if _has(text, "total eligible women", "number of eligible women"):
        return [_explicit("total_eligible_women", "Total eligible women", "identifier")]
    return None


def _survey_metadata(text: str) -> list[CanonicalEntry] | None:
    # Interview date
    if _exact(text, "day of interview"):
        return [_explicit("interview_day", "Interview day", "interview_date_component")]
    if _exact(text, "month of interview"):
        return [_explicit("interview_month", "Interview month", "interview_date_component")]
    if _exact(text, "year of interview"):
        return [_explicit("interview_year", "Interview year", "interview_date_component")]
    if _has(text, "date of interview women (cmc)", "date of interview (cmc)",
            "date of interview women"):
        return [_explicit("interview_date_cmc", "Date of interview (CMC)", "interview_date_cmc")]

    # Interview time
    if _has(text, "start of interview", "interview start") and _has(text, "hour"):
        return [_explicit("interview_start_hour", "Start of interview – hour",
                          "interview_time_component")]
    if _has(text, "start of interview", "interview start") and _has(text, "minute"):
        return [_explicit("interview_start_minute", "Start of interview – minutes",
                          "interview_time_component")]
    if (_has(text, "end of interview", "interview end") or
            _has(text, "interview end")) and _has(text, "hour"):
        return [_explicit("interview_end_hour", "End of interview – hour",
                          "interview_time_component")]
    if (_has(text, "end of interview", "interview end") or
            _has(text, "interview end")) and _has(text, "minute"):
        return [_explicit("interview_end_minute", "End of interview – minutes",
                          "interview_time_component")]
    # "Interview end - Hour" → after cleaning becomes "interview end hour"
    if _exact(text, "interview end hour", "interview end minutes",
              "interview end minute"):
        if "hour" in text:
            return [_explicit("interview_end_hour", "End of interview – hour",
                              "interview_time_component")]
        return [_explicit("interview_end_minute", "End of interview – minutes",
                          "interview_time_component")]
    if _exact(text, "interview year"):
        return [_explicit("interview_year", "Interview year", "interview_date_component")]
    if _exact(text, "interview month"):
        return [_explicit("interview_month", "Interview month", "interview_date_component")]
    if _exact(text, "interview day"):
        return [_explicit("interview_day", "Interview day", "interview_date_component")]

    # Interview result & admin
    if _has(text, "result of womans interview", "result of womens interview",
            "womans interview outcome", "womens interview outcome",
            "result of women s interview"):
        return [_explicit("interview_result", "Result of woman's interview", "interview_admin")]
    if _has(text, "result of hh interview", "result of household interview"):
        return [_explicit("hh_interview_result", "Result of HH interview", "interview_admin")]
    if _has(text, "women interviews completed"):
        return [_explicit("wm_interviews_completed",
                          "Women interviews completed", "interview_admin")]
    if _has(text, "child interviews completed"):
        return [_explicit("ch_interviews_completed",
                          "Child interviews completed", "interview_admin")]
    if _has(text, "total children under 5"):
        return [_explicit("total_children_under5",
                          "Total children under 5", "interview_admin")]
    if _has(text, "respondent hh questionnaire", "respondent to hh questionnaire"):
        return [_explicit("respondent_hh_questionnaire",
                          "Respondent to HH questionnaire", "interview_admin")]
    if _exact(text, "consent"):
        return [_explicit("consent", "Consent", "interview_admin")]
    if _has(text, "interview completed in private"):
        return [_explicit("interview_private", "Interview completed in private", "interview_admin")]
    if _has(text, "respondent to another questionnaire"):
        return [_explicit("respondent_other_questionnaire",
                          "Respondent to another questionnaire", "interview_admin")]
    if _has(text, "household interviewer"):
        return [_explicit("hh_interviewer_number", "Household interviewer number",
                          "interview_admin")]
    if _has(text, "mother alive", "is mother alive"):
        return [_explicit("mother_alive", "Mother alive", "demographic", "yes_no")]
    if _has(text, "father alive", "is father alive"):
        return [_explicit("father_alive", "Father alive", "demographic", "yes_no")]
    if _has(text, "household identification", "household id"):
        return [_explicit("hh_number", "Household number", "identifier")]

    # Personnel
    if _exact(text, "interviewer number", "interviewer no", "interviewer code"):
        return [_explicit("interviewer_number", "Interviewer number", "interview_admin")]
    if _exact(text, "supervisor number", "supervisor no"):
        return [_explicit("supervisor_number", "Supervisor number", "interview_admin")]
    if _exact(text, "field editor"):
        return [_explicit("field_editor", "Field editor", "interview_admin")]
    if _exact(text, "data entry clerk"):
        return [_explicit("data_entry_clerk", "Data entry clerk", "interview_admin")]

    # Language
    if _has(text, "language of the questionnaire"):
        return [_explicit("questionnaire_language", "Language of the questionnaire",
                          "interview_admin")]
    if _has(text, "language of the interview"):
        return [_explicit("interview_language", "Language of the interview", "interview_admin")]
    if _has(text, "native language of the respondent"):
        return [_explicit("respondent_native_language", "Native language of the respondent",
                          "interview_admin")]
    if _has(text, "translator used"):
        return [_explicit("translator_used", "Translator used", "interview_admin")]

    # Women's sample weight  (after _clean_label: "woman's" → "womans")
    if _has(text, "womens sample weight", "womans sample weight"):
        return [_explicit("women_sample_weight", "Women's sample weight", "survey_weight")]

    return None


def _geographic(text: str) -> list[CanonicalEntry] | None:
    if _exact(text, "region"):
        return [_explicit("region", "Region", "geographic")]
    if _exact(text, "area"):
        return [_explicit("area", "Area (urban/rural)", "geographic")]
    if _exact(text, "district"):
        return [_explicit("district", "District", "geographic")]
    if _exact(text, "province", "province/city"):
        return [_explicit("province", "Province", "geographic")]
    if _exact(text, "commune", "commune/ward"):
        return [_explicit("commune", "Commune/ward", "geographic")]
    return None


def _woman_background(text: str) -> list[CanonicalEntry] | None:
    # Age and date of birth
    if _exact(text, "age of woman", "womans age", "age", "how old are you"):
        return [_explicit("woman_age", "Age of woman", "woman_background", "continuous")]
    if _exact(text, "month of birth of woman", "month of birth",
              "womans month of birth", "womans birth month"):
        return [_explicit("woman_birth_month", "Month of birth of woman",
                          "woman_background")]
    if _exact(text, "year of birth of woman", "year of birth",
              "womans year of birth", "womans birth year"):
        return [_explicit("woman_birth_year", "Year of birth of woman",
                          "woman_background")]
    if _exact(text, "day of birth"):
        return [_explicit("woman_birth_day", "Day of birth of woman", "woman_background")]
    if _has(text, "date of birth of woman (cmc)", "date of birth (cmc)"):
        return [_explicit("woman_birth_date_cmc", "Date of birth of woman (CMC)",
                          "woman_background")]

    # Education
    if _exact(text, "education"):
        return [_explicit("education_level", "Highest level of school attended",
                          "woman_background", "categorical", confidence="medium")]
    if _has(text, "ever attended school", "ever attended an educational institution",
            "have you ever attended"):
        return [_explicit("ever_attended_school", "Ever attended school",
                          "woman_background", "yes_no")]
    if _has(text, "highest level of school attended", "highest level of school you attended",
            "what is the highest level of school", "highest level you have attended in school",
            "woman's education level", "womans education level"):
        return [_explicit("education_level", "Highest level of school attended",
                          "woman_background", "categorical")]
    if _has(text, "highest grade completed at that level", "highest grade attended at that level",
            "highest grade you completed at that level", "highest grade at that level"):
        return [_explicit("education_grade", "Highest grade completed",
                          "woman_background", "continuous")]
    if _has(text, "can read part of the sentence", "read part of the sentence",
            "read parts of a sentence", "can read parts of", "can you write part of"):
        return [_explicit("literacy", "Literacy (can read part of sentence)",
                          "woman_background", "yes_no")]
    if _has(text, "attended school during current school year",
            "school attendance during the current school year"):
        return [_explicit("currently_attending_school", "Currently attending school",
                          "woman_background", "yes_no")]
    if _has(text, "attended school previous school year", "attended school last year",
            "attend school during last year"):
        return [_explicit("attended_school_prev_year", "Attended school previous year",
                          "woman_background", "yes_no")]
    if _has(text, "level of education attended current school year",
            "school level attended this year"):
        return [_explicit("current_school_education_level",
                          "Level of education attended current school year",
                          "woman_background", "categorical")]
    if _has(text, "level of education attended previous school year"):
        return [_explicit("prev_school_education_level",
                          "Level of education attended previous school year",
                          "woman_background", "categorical")]

    # Sex (from HL listing)
    if _exact(text, "sex"):
        return [_explicit("sex", "Sex", "woman_background", "categorical")]

    return None


def _marriage(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "marital/union status of woman", "marital/union status",
            "marital status"):
        return [_explicit("marital_status", "Marital status", "marriage", "categorical")]
    if _has(text, "currently married or living with a man"):
        return [_explicit("currently_married_or_cohabiting",
                          "Currently married or living with a man", "marriage", "yes_no")]
    if _has(text, "ever married or lived with a man"):
        return [_explicit("ever_married_or_cohabiting",
                          "Ever married or lived with a man", "marriage", "yes_no")]
    if _has(text, "married or lived with a man once or more than once"):
        return [_explicit("times_married", "Married once or more than once",
                          "marriage", "categorical")]
    if _has(text, "age at first marriage/union of woman", "age at first marriage/union",
            "age at first marriage", "age at first union"):
        return [_explicit("age_at_first_union", "Age at first marriage/union",
                          "marriage", "continuous")]
    if _has(text, "month of first union", "month of first marriage"):
        return [_explicit("first_union_month", "Month of first union", "marriage")]
    if _has(text, "year of first union", "year of first marriage"):
        return [_explicit("first_union_year", "Year of first union", "marriage")]
    if _has(text, "date of marriage of woman (cmc)", "date of marriage (cmc)"):
        return [_explicit("date_marriage_cmc", "Date of marriage (CMC)", "marriage")]
    if _has(text, "husband/partner has other wives", "number of other wives",
            "husband/partner has more wives", "partner has more wives or partners"):
        return [_explicit("polygyny", "Husband/partner has other wives", "marriage")]
    if _exact(text, "currently married"):
        return [_explicit("currently_married_or_cohabiting",
                          "Currently married or in union", "marriage", "yes_no")]
    if _has(text, "age of husband/partner"):
        return [_explicit("partner_age", "Age of husband/partner", "marriage", "continuous")]
    return None


def _birth_history(text: str) -> list[CanonicalEntry] | None:
    if _exact(text, "ever given birth") or \
       _has(text, "ever had a birth with a live-born child", "ever had children",
            "have you ever given birth"):
        return [_explicit("ever_given_birth", "Ever given birth", "birth_history", "yes_no")]
    if _has(text, "children ever born", "check total number of children ever born",
            "confirm total number of children ever born",
            "number of total birth", "total number of births", "live births"):
        return [_explicit("children_ever_born", "Children ever born",
                          "birth_history", "continuous")]
    if _has(text, "sons living with you", "sons at home", "sons are living with you",
            "sons live with you", "how many sons live with you"):
        return [_explicit("sons_living_with", "Sons living with respondent",
                          "birth_history", "continuous")]
    if _has(text, "daughters living with you", "daughters at home",
            "daughters are living with you", "daughters live with you",
            "how many daughters live with you"):
        return [_explicit("daughters_living_with", "Daughters living with respondent",
                          "birth_history", "continuous")]
    if _has(text, "sons living elsewhere", "sons living not with you", "sons elsewhere",
            "sons are alive but not living with you", "sons alive but not living with you",
            "sons alive but do not live with you"):
        return [_explicit("sons_living_elsewhere", "Sons living elsewhere",
                          "birth_history", "continuous")]
    if _has(text, "daughters living elsewhere", "daughters not living with you",
            "daughters elsewhere", "daughters are alive but not living with you",
            "daughters alive but not living with you",
            "daughters alive but do not live with you"):
        return [_explicit("daughters_living_elsewhere", "Daughters living elsewhere",
                          "birth_history", "continuous")]
    if _has(text, "boys dead", "dead children", "deceased sons", "how many boys have died") \
       and _has(text, "boys", "sons"):
        return [_explicit("sons_dead", "Sons who died", "birth_history", "continuous")]
    if (_has(text, "girls dead", "deceased daughters", "how many girls have died") and
            _has(text, "girls", "daughters")):
        return [_explicit("daughters_dead", "Daughters who died", "birth_history", "continuous")]
    if _exact(text, "boys dead", "deceased sons"):
        return [_explicit("sons_dead", "Sons who died", "birth_history", "continuous")]
    if _exact(text, "girls dead", "deceased daughters"):
        return [_explicit("daughters_dead", "Daughters who died", "birth_history", "continuous")]
    if _exact(text, "children dead", "dead children", "children surviving",
              "surviving children", "children who have since died", "deceased children",
              "number of children surviving"):
        return [_explicit("children_dead", "Children who died", "birth_history", "continuous")]
    if _has(text, "any sons or daughters living with you"):
        return [_explicit("any_children_living_with",
                          "Any sons or daughters living with respondent",
                          "birth_history", "yes_no")]
    if _has(text, "any sons or daughters not living with you"):
        return [_explicit("any_children_living_elsewhere",
                          "Any sons or daughters not living with respondent",
                          "birth_history", "yes_no")]
    if _has(text, "ever had child who later died"):
        return [_explicit("ever_child_died", "Ever had a child who later died",
                          "birth_history", "yes_no")]
    if _has(text, "any other live births"):
        return [_explicit("other_live_births", "Any other live births",
                          "birth_history", "yes_no")]
    if _has(text, "live births in last two years", "live birth in last 2 years",
            "live births in last 2 years", "live birth in last year",
            "live births in last year"):
        return [_explicit("live_births_last_2yr", "Live births in last two years",
                          "birth_history", "continuous")]
    if _has(text, "last birth in last two years"):
        return [_explicit("last_birth_in_last_2yr", "Last birth in last two years",
                          "birth_history", "yes_no")]

    # Birth dates
    if _has(text, "month of first birth"):
        return [_explicit("first_birth_month", "Month of first birth", "birth_history")]
    if _has(text, "year of first birth"):
        return [_explicit("first_birth_year", "Year of first birth", "birth_history")]
    if _has(text, "day of first birth"):
        return [_explicit("first_birth_day", "Day of first birth", "birth_history")]
    if _has(text, "month of last birth"):
        return [_explicit("last_birth_month", "Month of last birth", "birth_history")]
    if _has(text, "year of last birth"):
        return [_explicit("last_birth_year", "Year of last birth", "birth_history")]
    if _has(text, "day of last birth"):
        return [_explicit("last_birth_day", "Day of last birth", "birth_history")]
    if _has(text, "years since first birth"):
        return [_explicit("years_since_first_birth", "Years since first birth",
                          "birth_history", "continuous")]
    if _has(text, "date of birth of first child (cmc)"):
        return [_explicit("first_child_birth_date_cmc",
                          "Date of birth of first child (CMC)", "birth_history")]
    if _has(text, "date of birth of last child (cmc)"):
        return [_explicit("last_child_birth_date_cmc",
                          "Date of birth of last child (CMC)", "birth_history")]
    if _has(text, "year of first birth"):
        return [_explicit("first_birth_year", "Year of first birth", "birth_history")]

    return None


def _fertility_preferences(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "currently pregnant"):
        return [_explicit("currently_pregnant", "Currently pregnant",
                          "fertility_preference", "yes_no")]
    if _has(text, "able to get pregnant"):
        return [_explicit("able_to_get_pregnant", "Able to get pregnant",
                          "fertility_preference", "yes_no")]
    if _has(text, "would like to have another child (currently pregnant)",
            "would like to have another child (not currently pregnant)",
            "would like to have another child",
            "prefer to have or not to have any more children",
            "prefer to have any more children"):
        return [_explicit("want_another_child", "Would like to have another child",
                          "fertility_preference", "categorical")]
    if _has(text, "desired waiting time (number)", "desired waiting time (unit)",
            "desired waiting time (units)",
            "time would have wished to wait"):
        if _has(text, "number"):
            return [_explicit("desired_waiting_time_number",
                              "Desired waiting time (number)", "fertility_preference")]
        return [_explicit("desired_waiting_time_unit",
                          "Desired waiting time (unit)", "fertility_preference")]

    # Reasons for not wanting more
    _reason_map = [
        ("reason_breastfeeding",       ("breastfeeding",)),
        ("reason_too_old",             ("too old",)),
        ("reason_fatalistic",          ("fatalistic",)),
        ("reason_never_menstruated",   ("never menstruated",)),
        ("reason_hysterectomy",        ("hysterectomy",)),
        ("reason_menopausal",          ("menopausal",)),
        ("reason_postpartum",          ("postpartum amenorrheic", "postpartum")),
        ("reason_infrequent_sex",      ("infrequent sex", "no sex")),
        ("reason_subfecund",           ("trying to get pregnant for 2 year",)),
        ("reason_dk",                  ("reason: dk", "reason: don't know")),
        ("reason_no_response",         ("reason: no response",)),
    ]
    if _startswith(text, "reason:"):
        for varname, terms in _reason_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "fertility_preference")]
        return [_explicit("reason_other", "Reason (other)", "fertility_preference",
                          confidence="medium")]
    return None


def _family_planning(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "currently using a method to avoid pregnancy",
            "currently using method"):
        return [_explicit("currently_using_contraception",
                          "Currently using a method to avoid pregnancy",
                          "family_planning", "yes_no")]
    if _has(text, "ever used a method to avoid pregnancy"):
        return [_explicit("ever_used_contraception",
                          "Ever used a method to avoid pregnancy",
                          "family_planning", "yes_no")]

    # Method type map
    _method_map = [
        ("cp_pill",                  ("current method: pill",)),
        ("cp_iud",                   ("current method: iud",)),
        ("cp_injectables",           ("current method: injectables",
                                      "current method: injections")),
        ("cp_implants",              ("current method: implants",)),
        ("cp_male_condom",           ("current method: male condom", "current method: condom")),
        ("cp_female_condom",         ("current method: female condom",)),
        ("cp_female_sterilization",  ("current method: female sterilization",)),
        ("cp_male_sterilization",    ("current method: male sterilization",)),
        ("cp_periodic_abstinence",   ("current method: periodic abstinence",
                                      "current method: periodic abstinence / rhythm")),
        ("cp_withdrawal",            ("current method: withdrawal", "withdrawal")),
        ("cp_lam",                   ("current method: lactational amenorrh",)),
        ("cp_foam_jelly",            ("current method: foam / jelly", "current method: foam/jelly")),
        ("cp_diaphragm",             ("current method: diaphragm",)),
        ("cp_other",                 ("current method: other",)),
        ("cp_no_response",           ("current method: no response",)),
    ]
    for varname, terms in _method_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "family_planning", "yes_no")]

    if _startswith(text, "what methods are you using") or \
       _startswith(text, "what methods that helps to delay"):
        return [_explicit("current_method_other_text",
                          "Current contraceptive method (text)", "family_planning",
                          confidence="medium")]

    if _has(text, "menstrual period returned since the birth"):
        return [_explicit("menstrual_period_returned",
                          "Menstrual period returned since birth", "family_planning", "yes_no")]
    if _has(text, "start of last menstrual period") and _has(text, "number"):
        return [_explicit("last_menstrual_period_number",
                          "Start of last menstrual period (number)", "family_planning")]
    if _has(text, "start of last menstrual period") and _has(text, "unit"):
        return [_explicit("last_menstrual_period_unit",
                          "Start of last menstrual period (unit)", "family_planning")]

    return None


def _antenatal_care(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "received antenatal care", "received prenatal care",
            "see anyone for antenatal care", "see anyone for prenatal care",
            "did you see anyone for antenatal", "consult anyone for prenatal"):
        return [_explicit("received_anc", "Received antenatal care",
                          "antenatal_care", "yes_no")]
    if _has(text, "times received antenatal care", "times received prenatal care",
            "number of times baby was checked"):
        return [_explicit("anc_visits", "Number of antenatal care visits",
                          "antenatal_care", "continuous")]
    if _has(text, "weeks or months pregnant at first prenatal care",
            "weeks or months pregnent at first prenatal care",
            "weeks or months pregnant at first anc"):
        if _has(text, "number"):
            return [_explicit("anc_first_visit_timing_number",
                              "Weeks/months pregnant at first ANC visit (number)",
                              "antenatal_care")]
        return [_explicit("anc_first_visit_timing_unit",
                          "Weeks/months pregnant at first ANC visit (unit)",
                          "antenatal_care")]

    # ANC provider
    _anc_provider_map = [
        ("anc_provider_doctor",      ("antenatal care: doctor",
                                      "prenatal care: doctor", "gynaecologist")),
        ("anc_provider_nurse",       ("antenatal care: nurse / midwife",
                                      "antenatal care: nurse/midwife",
                                      "prenatal care: nurse", "prenatal care: midwife")),
        ("anc_provider_midwife",     ("antenatal care: auxiliary midwife",
                                      "antenatal care: auxilary midwife",
                                      "antenatal care: auxillary midwife",
                                      "prenatal care: auxiliary midwife")),
        ("anc_provider_tba",         ("antenatal care: traditional birth attendant",
                                      "prenatal care: traditional birth attendant")),
        ("anc_provider_chw",         ("antenatal care: community health worker",
                                      "prenatal care: community health worker")),
        ("anc_provider_relative",    ("antenatal care: relative/friend",
                                      "antenatal care: relative / friend",
                                      "prenatal care: relative/friend")),
        ("anc_provider_none",        ("antenatal care: no one", "prenatal care: no one")),
        ("anc_provider_other",       ("antenatal care: other", "prenatal care: other")),
    ]
    for varname, terms in _anc_provider_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "antenatal_care", "yes_no")]

    # Tetanus toxoid
    if _has(text, "any tetanus toxoid injection during last pregnancy",
            "tetanus injection during last pregnancy",
            "tetanus toxoid during last pregnancy"):
        return [_explicit("tetanus_during_last_pregnancy",
                          "Any tetanus toxoid injection during last pregnancy",
                          "antenatal_care", "yes_no")]
    if _has(text, "any tetanus toxoid injection before last pregnancy",
            "tetanus injection before last pregnancy"):
        return [_explicit("tetanus_before_last_pregnancy",
                          "Any tetanus toxoid injection before last pregnancy",
                          "antenatal_care", "yes_no")]
    if _has(text, "doses of tetanus toxoid during last pregnancy"):
        return [_explicit("tetanus_doses_during_pregnancy",
                          "Doses of tetanus toxoid during last pregnancy",
                          "antenatal_care", "continuous")]
    if _has(text, "doses of tetanus toxoid before last pregnancy"):
        return [_explicit("tetanus_doses_before_pregnancy",
                          "Doses of tetanus toxoid before last pregnancy",
                          "antenatal_care", "continuous")]
    if _has(text, "years ago last tetanus toxoid received before last pregnancy"):
        return [_explicit("tetanus_years_ago_before_pregnancy",
                          "Years since last tetanus toxoid before last pregnancy",
                          "antenatal_care", "continuous")]
    if _has(text, "years ago last tetanus toxoid received", "year last tetanus toxoid received"):
        return [_explicit("tetanus_years_ago",
                          "Years since last tetanus toxoid received",
                          "antenatal_care", "continuous")]
    if _has(text, "month last tetanus toxoid received", "months since last tetanus"):
        return [_explicit("tetanus_months_ago",
                          "Months since last tetanus toxoid received",
                          "antenatal_care", "continuous")]

    # HIV info at ANC
    if _has(text, "given information about hiv during antenatal care",
            "given information about aids virus during antenatal care"):
        if _has(text, "from mother", "mother to child"):
            return [_explicit("anc_hiv_info_mtct",
                              "Given HIV MTCT info at ANC", "antenatal_care", "yes_no")]
        if _has(text, "tested for hiv", "tested for aids"):
            return [_explicit("anc_hiv_info_testing",
                              "Given HIV testing info at ANC", "antenatal_care", "yes_no")]
        if _has(text, "offered a test"):
            return [_explicit("anc_hiv_offered_test",
                              "Offered HIV test at ANC", "antenatal_care", "yes_no")]
        if _has(text, "things to do"):
            return [_explicit("anc_hiv_info_actions",
                              "Given HIV action info at ANC", "antenatal_care", "yes_no")]
        return [_explicit("anc_hiv_info_any",
                          "Given HIV/AIDS info at ANC", "antenatal_care", "yes_no")]
    if _has(text, "tested for hiv as part of antenatal care",
            "tested for aids virus as part of antenatal care"):
        return [_explicit("tested_hiv_anc", "Tested for HIV as part of ANC",
                          "antenatal_care", "yes_no")]
    if _has(text, "received results from test during antenatal care"):
        return [_explicit("anc_hiv_results_received",
                          "Received HIV test results during ANC",
                          "antenatal_care", "yes_no")]
    if _has(text, "received consultation after testing during antenatal care"):
        return [_explicit("anc_hiv_consultation",
                          "Received consultation after HIV testing at ANC",
                          "antenatal_care", "yes_no")]

    # Urine/blood sample at ANC
    if _exact(text, "urine sample"):
        return [_explicit("anc_urine_sample", "Urine sample taken", "antenatal_care", "yes_no")]
    if _exact(text, "blood sample"):
        return [_explicit("anc_blood_sample", "Blood sample taken", "antenatal_care", "yes_no")]

    return None


def _delivery(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "place of delivery"):
        return [_explicit("place_of_delivery", "Place of delivery",
                          "delivery", "categorical")]
    if _has(text, "delivery by caesarean section", "delivery by cesarean section"):
        return [_explicit("caesarean_section", "Delivery by caesarean section",
                          "delivery", "yes_no")]
    if _has(text, "decision made to have caesarean section",
            "decision for caesarean made before the onset of labour",
            "decision for caesarean made before onset of labour"):
        return [_explicit("caesarean_decision",
                          "Decision made to have caesarean section",
                          "delivery", "categorical")]
    if _has(text, "sex of newborns", "sex of the newborn"):
        return [_explicit("child_sex", "Sex of newborn", "delivery", "categorical")]
    if _has(text, "duration of staying in the health facility") and _has(text, "number"):
        return [_explicit("facility_stay_number",
                          "Duration of staying in health facility (number)",
                          "delivery")]
    if _has(text, "duration of staying in the health facility") and _has(text, "unit"):
        return [_explicit("facility_stay_unit",
                          "Duration of staying in health facility (unit)",
                          "delivery")]

    # Assistance at delivery (two label variants across datasets)
    _assist_map = [
        ("delivery_assist_doctor",    ("assistance at delivery: doctor",
                                       "delivery assistance: doctor")),
        ("delivery_assist_nurse",     ("assistance at delivery: nurse / midwife",
                                       "assistance at delivery: nurse/midwife",
                                       "delivery assistance: nurse/midwife",
                                       "delivery assistance: nurse / midwife")),
        ("delivery_assist_midwife",   ("assistance at delivery: auxiliary midwife",
                                       "delivery assistance: auxiliary midwife")),
        ("delivery_assist_tba",       ("assistance at delivery: traditional birth attendant",
                                       "delivery assistance: traditional birth attendant")),
        ("delivery_assist_chw",       ("assistance at delivery: community health worker",
                                       "delivery assistance: community health worker")),
        ("delivery_assist_relative",  ("assistance at delivery: relative / friend",
                                       "assistance at delivery: relative/friend",
                                       "delivery assistance: relative / friend",
                                       "delivery assistance: relative/friend")),
        ("delivery_assist_none",      ("assistance at delivery: no one",
                                       "delivery assistance: no one")),
        ("delivery_assist_other",     ("assistance at delivery: other",
                                       "delivery assistance: other")),
        ("delivery_assist_no_response", ("assistance at delivery: no response",
                                         "delivery assistance: no response")),
    ]
    for varname, terms in _assist_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "delivery", "yes_no")]

    # Prenatal care provider (some datasets use "prenatal" instead of "antenatal")
    _prenatal_map = [
        ("anc_provider_doctor",  ("prenatal care provider: doctor",
                                   "health professional: doctor")),
        ("anc_provider_nurse",   ("prenatal care provider: nurse/midwife",
                                   "prenatal care provider: nurse / midwife",
                                   "health professional: nurse/midwife",
                                   "health professional: nurse / midwife")),
        ("anc_provider_midwife", ("prenatal care provider: auxiliary midwife",
                                   "health professional: auxiliary midwife",
                                   "prenatal care provider: midwife")),
        ("anc_provider_tba",     ("prenatal care provider: traditional birth attendant",
                                   "health professional: traditional birth attendant")),
        ("anc_provider_chw",     ("prenatal care provider: community health worker",
                                   "health professional: community health worker")),
        ("anc_provider_other",   ("prenatal care provider: other",
                                   "health professional: other")),
        ("anc_provider_no_response", ("prenatal care provider: no response",)),
    ]
    for varname, terms in _prenatal_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "antenatal_care", "yes_no")]

    # HIV testing at delivery
    if _has(text, "tested for hiv during delivery", "tested for aids virus during delivery"):
        return [_explicit("tested_hiv_delivery",
                          "Tested for HIV during delivery", "delivery", "yes_no")]
    if _has(text, "offered test for hiv before delivery"):
        return [_explicit("offered_hiv_test_before_delivery",
                          "Offered HIV test before delivery", "delivery", "yes_no")]
    if _has(text, "received results from test during delivery"):
        return [_explicit("delivery_hiv_results_received",
                          "Received HIV test results during delivery", "delivery", "yes_no")]

    return None


def _postnatal_care(text: str) -> list[CanonicalEntry] | None:
    # Baby checks
    # After _clean_label: "baby's" → "babys", "mother's" → "mothers"
    if _has(text, "babys health checked after leaving health facility",
            "baby checked after the delivery",
            "additional baby check after the delivery",
            "baby checked after delivery"):
        return [_explicit("postnatal_baby_check_after_facility",
                          "Baby's health checked after leaving facility",
                          "postnatal_care", "yes_no")]
    if _has(text, "babys health checked before leaving health facility",
            "baby was checked before leaving"):
        return [_explicit("postnatal_baby_check_before_discharge",
                          "Baby's health checked before leaving facility",
                          "postnatal_care", "yes_no")]
    if _has(text, "number of times baby was checked"):
        return [_explicit("postnatal_baby_check_count",
                          "Number of times baby was checked", "postnatal_care", "continuous")]
    if _has(text, "number of times mothers health was checked",
            "number of times mother was checked"):
        return [_explicit("postnatal_mother_check_count",
                          "Number of times mother was checked", "postnatal_care", "continuous")]
    if _has(text, "place where babys health was checked"):
        return [_explicit("postnatal_baby_check_place",
                          "Place where baby's health was checked", "postnatal_care")]
    if _has(text, "place where mothers health was checked"):
        return [_explicit("postnatal_mother_check_place",
                          "Place where mother's health was checked", "postnatal_care")]

    # How long after delivery
    if _has(text, "how long after delivery did the first check of baby happen") and _has(text, "number"):
        return [_explicit("postnatal_baby_check_timing_number",
                          "Time to first postnatal baby check (number)", "postnatal_care")]
    if _has(text, "how long after delivery did the first check of baby happen") and _has(text, "unit"):
        return [_explicit("postnatal_baby_check_timing_unit",
                          "Time to first postnatal baby check (unit)", "postnatal_care")]
    if _has(text, "how long after delivery did the first check of mother happen") and _has(text, "number"):
        return [_explicit("postnatal_mother_check_timing_number",
                          "Time to first postnatal mother check (number)", "postnatal_care")]
    if _has(text, "how long after delivery did the first check of mother happen") and _has(text, "unit"):
        return [_explicit("postnatal_mother_check_timing_unit",
                          "Time to first postnatal mother check (unit)", "postnatal_care")]

    # Mother checks (after _clean_label: "mother's" → "mothers")
    if _has(text, "mothers health checked after leaving health facility",
            "mothers health checked after the delivery",
            "mothers health checked after the birth of the baby",
            "mother checked after the delivery"):
        return [_explicit("postnatal_mother_check_after_facility",
                          "Mother's health checked after leaving facility",
                          "postnatal_care", "yes_no")]
    if _has(text, "mothers health checked before leaving health facility"):
        return [_explicit("postnatal_mother_check_before_discharge",
                          "Mother's health checked before leaving facility",
                          "postnatal_care", "yes_no")]

    # Person checking
    _pnc_person_baby = [
        ("postnatal_baby_check_doctor",   ("person checking on babys health: doctor",)),
        ("postnatal_baby_check_nurse",    ("person checking on babys health: nurse / midwife",
                                           "person checking on babys health: nurse/midwife")),
        ("postnatal_baby_check_relative", ("person checking on babys health: relative / friend",
                                           "person checking on babys health: relative/friend")),
        ("postnatal_baby_check_tba",      ("person checking on babys health: traditional birth attendant",)),
        ("postnatal_baby_check_chw",      ("person checking on babys health: community health worker",)),
        ("postnatal_baby_check_other",    ("person checking on babys health: other",)),
        ("postnatal_baby_check_no_response", ("person checking on babys health: no response",)),
    ]
    for varname, terms in _pnc_person_baby:
        if _has(text, *terms):
            return [_explicit(varname, text, "postnatal_care", "yes_no")]

    _pnc_person_mother = [
        ("postnatal_mother_check_doctor",   ("person checking on mothers health: doctor",)),
        ("postnatal_mother_check_nurse",    ("person checking on mothers health: nurse / midwife",
                                             "person checking on mothers health: nurse/midwife")),
        ("postnatal_mother_check_relative", ("person checking on mothers health: relative / friend",
                                             "person checking on mothers health: relative/friend")),
        ("postnatal_mother_check_tba",      ("person checking on mothers health: traditional birth attendant",)),
        ("postnatal_mother_check_chw",      ("person checking on mothers health: community health worker",)),
        ("postnatal_mother_check_other",    ("person checking on mothers health: other",)),
        ("postnatal_mother_check_no_response", ("person checking on mothers health: no response",)),
    ]
    for varname, terms in _pnc_person_mother:
        if _has(text, *terms):
            return [_explicit(varname, text, "postnatal_care", "yes_no")]

    # Early newborn care (first 2 days)
    if _has(text, "during two days after birth health care provider: examine cord"):
        return [_explicit("newborn_cord_examined",
                          "Cord examined in first 2 days", "postnatal_care", "yes_no")]
    if _has(text, "during two days after birth health care provider: take temperature"):
        return [_explicit("newborn_temperature_taken",
                          "Temperature taken in first 2 days", "postnatal_care", "yes_no")]
    if _has(text, "during two days after birth health care provider: counsel on breastfeeding"):
        return [_explicit("newborn_breastfeeding_counselled",
                          "Breastfeeding counselled in first 2 days", "postnatal_care", "yes_no")]
    if _has(text, "during two days after birth health care provider observe childs breastfeeding"):
        return [_explicit("newborn_breastfeeding_observed",
                          "Breastfeeding observed in first 2 days", "postnatal_care", "yes_no")]
    if _has(text, "during two days after birth health care provider gave information on"):
        return [_explicit("newborn_danger_signs_info",
                          "Information on danger signs given in first 2 days",
                          "postnatal_care", "yes_no")]

    # Skin-to-skin / drying
    if _has(text, "baby was dried or wiped soon after birth"):
        return [_explicit("newborn_dried_wiped",
                          "Baby was dried or wiped soon after birth",
                          "postnatal_care", "yes_no")]
    if _has(text, "after the birth, baby was put directly on the bare skin of mothers chest",
            "skin-to-skin", "skin to skin"):
        return [_explicit("newborn_skin_to_skin",
                          "Skin-to-skin contact after birth", "postnatal_care", "yes_no")]
    if _has(text, "baby was wrapped up before being placed on mothers chest"):
        return [_explicit("newborn_wrapped_before_skin_to_skin",
                          "Baby wrapped before placed on mother's chest",
                          "postnatal_care", "yes_no")]

    return None


def _early_breastfeeding(text: str) -> list[CanonicalEntry] | None:
    if _exact(text, "breastfed") or _has(text, "ever breastfed", "ever breastfeed",
                                          "is child currently breastfed"):
        return [_explicit("ever_breastfed", "Ever breastfed", "breastfeeding", "yes_no")]
    if _has(text, "time baby put to breast") and _has(text, "number"):
        return [_explicit("time_to_breastfeed_number",
                          "Time baby put to breast (number)", "breastfeeding")]
    if _has(text, "time baby put to breast") and _has(text, "unit"):
        return [_explicit("time_to_breastfeed_unit",
                          "Time baby put to breast (unit)", "breastfeeding")]
    if _has(text, "within first 3 days after delivery, child given anything to drink"):
        return [_explicit("prelacteal_feeds",
                          "Child given anything to drink other than breast milk in first 3 days",
                          "breastfeeding", "yes_no")]
    # Pre-lacteal feed types
    _drink_map = [
        ("prelacteal_plain_water",     ("plain water",)),
        ("prelacteal_sugar_water",     ("sugar or glucose water", "sugar - salt - water",
                                        "sugar salt water")),
        ("prelacteal_milk_other",      ("milk (other than breast milk)",)),
        ("prelacteal_infant_formula",  ("infant formula",)),
        ("prelacteal_fruit_juice",     ("fruit juice",)),
        ("prelacteal_honey",           ("honey",)),
        ("prelacteal_gripe_water",     ("gripe water",)),
        ("prelacteal_tea",             ("tea / infusions", "tea / infusion")),
        ("prelacteal_prescribed_medicine", ("prescribed medicine",)),
        ("prelacteal_other",           ("child given to drink - other",
                                        "child given to drink: other",
                                        "child given to drink other")),
        ("prelacteal_not_given",       ("not given anything to drink",)),
        ("prelacteal_no_response",     ("child given to drink - no response",
                                        "child given to drink: no response",
                                        "child given to drink no response")),
    ]
    if _startswith(text, "child given to drink"):
        for varname, terms in _drink_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "breastfeeding", "yes_no")]
    if _has(text, "time baby was bathed") and _has(text, "number"):
        return [_explicit("time_to_bath_number",
                          "Time baby was bathed (number)", "newborn_care")]
    if _has(text, "time baby was bathed") and _has(text, "unit"):
        return [_explicit("time_to_bath_unit",
                          "Time baby was bathed (unit)", "newborn_care")]
    return None


def _child_at_birth(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "size of child at birth"):
        return [_explicit("child_size_at_birth", "Size of child at birth",
                          "child_at_birth", "categorical")]
    if _has(text, "child weighed at birth", "weighed at birth"):
        return [_explicit("child_weighed_at_birth", "Child weighed at birth",
                          "child_at_birth", "yes_no")]
    if _has(text, "weight at birth (kilograms)", "weight at birth",
            "birth weight (kilograms)", "birth weight"):
        return [_explicit("child_weight_at_birth", "Weight at birth (kg)",
                          "child_at_birth", "continuous")]
    if _has(text, "wanted to get pregnant at the time",
            "wanted to get pregnant at that time",
            "did you want to get pregnant at that time",
            "want to get pregnant at that time"):
        return [_explicit("pregnancy_wanted_then", "Wanted to get pregnant at that time",
                          "child_at_birth", "categorical")]
    if _has(text, "wanted last child then", "wanted last child"):
        return [_explicit("last_child_wanted_then", "Wanted last child at that time",
                          "child_at_birth", "categorical")]
    if _has(text, "wanted child later or did not want more children",
            "wanted baby later or did not want more children",
            "did you want to wait later or not want any more children",
            "did you want to have a baby later",
            "want to have a baby later"):
        return [_explicit("child_wanted_timing", "Wanted child later or not at all",
                          "child_at_birth", "categorical")]
    if _has(text, "age of child"):
        return [_explicit("child_age", "Age of child", "child_at_birth", "continuous")]
    return None


def _domestic_violence(text: str) -> list[CanonicalEntry] | None:
    # Wife beating attitude
    _wb_map = [
        ("dv_wb_burns_food",         ("burns the food", "burns food")),
        ("dv_wb_neglects_children",  ("neglects the children", "neglects children",
                                      "neclects the children", "neclects children")),
        ("dv_wb_argues",             ("argues with husband", "argues with him")),
        ("dv_wb_refuses_sex",        ("refuses sex with husband", "refuses sex with him")),
        ("dv_wb_goes_out",           ("goes out with out telling husband",
                                      "goes out without telling him",
                                      "goes out with out telling him",
                                      "goes out without telling")),
    ]
    # Standalone forms ("If she burns the food", "Burns food", etc.)
    if _startswith(text, "if she ") or _exact(text, "burns food", "neglects children"):
        for varname, terms in _wb_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "domestic_violence", "yes_no")]
    if _has(text, "wife beating justified"):
        for varname, terms in _wb_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "domestic_violence", "yes_no")]
        return [_explicit("dv_wb_justified_other", text, "domestic_violence",
                          "yes_no", confidence="medium")]

    # Physical violence / attack
    if _has(text, "physically attacked"):
        return [_explicit("dv_physically_attacked",
                          "Physically attacked", "domestic_violence", "yes_no")]
    if _has(text, "attack happened during the last 12 months"):
        return [_explicit("dv_attack_last_12months",
                          "Attack happened in last 12 months", "domestic_violence", "yes_no")]
    if _has(text, "number of times attack happened in the last year"):
        return [_explicit("dv_attack_frequency",
                          "Number of times attacked in last year",
                          "domestic_violence", "continuous")]
    if _has(text, "place attack happened the last time"):
        return [_explicit("dv_attack_place",
                          "Place of last attack", "domestic_violence", "categorical")]
    if _has(text, "number of people involved in committing the offence"):
        return [_explicit("dv_offenders_count",
                          "Number of offenders", "domestic_violence", "continuous")]
    if _has(text, "person(s) had a weapon"):
        return [_explicit("dv_weapon_present",
                          "Offender had a weapon", "domestic_violence", "yes_no")]
    if _has(text, "offender(s) had a knife"):
        if _has(text, "knife"):
            return [_explicit("dv_weapon_knife", "Offender had a knife",
                              "domestic_violence", "yes_no")]
        if _has(text, "gun"):
            return [_explicit("dv_weapon_gun", "Offender had a gun",
                              "domestic_violence", "yes_no")]
        if _has(text, "other weapon"):
            return [_explicit("dv_weapon_other", "Offender had other weapon",
                              "domestic_violence", "yes_no")]
        if _has(text, "no response"):
            return [_explicit("dv_weapon_no_response", "Weapon – no response",
                              "domestic_violence")]
    if _has(text, "incident reported to the police"):
        return [_explicit("dv_incident_reported",
                          "Incident reported to police", "domestic_violence", "yes_no")]
    if _has(text, "the last time that this happened, was anything stolen"):
        return [_explicit("dv_theft_occurred",
                          "Anything stolen during incident", "domestic_violence", "yes_no")]
    if _has(text, "number of times victimisation happened in the last year"):
        return [_explicit("dv_victimisation_frequency",
                          "Number of victimisations in last year",
                          "domestic_violence", "continuous")]
    if _has(text, "victimisation happened during the last 12 months"):
        return [_explicit("dv_victimisation_last_12months",
                          "Victimisation in last 12 months", "domestic_violence", "yes_no")]
    if _has(text, "at least one of the offender(s) recognized"):
        return [_explicit("dv_offender_recognized",
                          "Offender was recognized", "domestic_violence", "yes_no")]

    # During pregnancy violence
    if _has(text, "who has done any of these things to physically hurt you while you were pregnant"):
        return [_explicit("dv_violence_during_pregnancy",
                          "Violence during pregnancy", "domestic_violence", "yes_no")]
    if _has(text, "how often did this happen during the last 12 months"):
        return [_explicit("dv_frequency_last_12months",
                          "Frequency of violence in last 12 months",
                          "domestic_violence", "categorical")]

    # Safety
    if _has(text, "feeling safe at home alone after dark"):
        return [_explicit("safety_at_home_after_dark",
                          "Feeling safe at home alone after dark",
                          "domestic_violence", "categorical")]
    if _has(text, "feeling safe walking alone in neighbourhood after dark"):
        return [_explicit("safety_in_neighbourhood_after_dark",
                          "Feeling safe walking in neighbourhood after dark",
                          "domestic_violence", "categorical")]

    return None


def _sexual_behavior(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "age at first sexual intercourse"):
        return [_explicit("age_at_first_sex",
                          "Age at first sexual intercourse",
                          "sexual_behavior", "continuous")]
    if _has(text, "condom used during first sexual intercourse"):
        return [_explicit("condom_at_first_sex",
                          "Condom used at first sexual intercourse",
                          "sexual_behavior", "yes_no")]
    if _has(text, "condom used at last sexual intercourse"):
        return [_explicit("condom_at_last_sex",
                          "Condom used at last sexual intercourse",
                          "sexual_behavior", "yes_no")]
    if _has(text, "condom used with prior sexual partner"):
        return [_explicit("condom_with_prior_partner",
                          "Condom used with prior sexual partner",
                          "sexual_behavior", "yes_no")]
    if _has(text, "relationship to last sexual partner"):
        return [_explicit("last_partner_relationship",
                          "Relationship to last sexual partner",
                          "sexual_behavior", "categorical")]
    if _has(text, "relationship to prior sexual partner"):
        return [_explicit("prior_partner_relationship",
                          "Relationship to prior sexual partner",
                          "sexual_behavior", "categorical")]
    if _has(text, "age of last sexual partner"):
        return [_explicit("last_partner_age",
                          "Age of last sexual partner",
                          "sexual_behavior", "continuous")]
    if _has(text, "age of prior sexual partner"):
        return [_explicit("prior_partner_age",
                          "Age of prior sexual partner",
                          "sexual_behavior", "continuous")]
    if _has(text, "number of sex partners in last 12 months"):
        return [_explicit("sex_partners_last_12months",
                          "Number of sex partners in last 12 months",
                          "sexual_behavior", "continuous")]
    if _has(text, "number of sex partners in lifetime"):
        return [_explicit("sex_partners_lifetime",
                          "Number of sex partners in lifetime",
                          "sexual_behavior", "continuous")]
    if _has(text, "sex with any other man in the last 12 month"):
        return [_explicit("sex_other_partner_last_12months",
                          "Sex with any other man in last 12 months",
                          "sexual_behavior", "yes_no")]
    if _has(text, "time since last sexual intercourse") and _has(text, "number"):
        return [_explicit("time_since_last_sex_number",
                          "Time since last sexual intercourse (number)",
                          "sexual_behavior")]
    if _has(text, "time since last sexual intercourse") and _has(text, "unit"):
        return [_explicit("time_since_last_sex_unit",
                          "Time since last sexual intercourse (unit)",
                          "sexual_behavior")]
    return None


def _hiv_aids(text: str) -> list[CanonicalEntry] | None:
    # Awareness
    if _has(text, "ever heard of hiv or aids", "ever heard of aids", "heard of aids"):
        return [_explicit("heard_of_hiv", "Ever heard of HIV or AIDS",
                          "hiv_aids", "yes_no")]

    # Knowledge
    _knowledge_map = [
        ("hiv_know_condom",         ("can avoid aids virus by using a condom",
                                     "can avoid hiv by using a condom",
                                     "can avoid aids by using a condom")),
        ("hiv_know_faithful",       ("can avoid aids virus by having one uninfected partner",
                                     "can avoid hiv by having one uninfected partner",
                                     "can avoid aids by having one uninfected partner",
                                     "can avoid aids by having one unifected partner")),
        ("hiv_know_abstinence",     ("can avoid aids by not having sex at all",)),
        ("hiv_know_mosquito",       ("can get aids virus from mosquito bites",
                                     "can get hiv from mosquito bites",
                                     "can get aids from mosquito bites")),
        ("hiv_know_food",           ("can get aids virus by sharing food",
                                     "can get hiv by sharing food",
                                     "can get aids by sharing food")),
        ("hiv_know_healthy_looking",("healthy-looking person may have aids virus",
                                     "healthy-looking person may have hiv")),
        ("hiv_know_supernatural",   ("can get aids virus through supernatural",
                                     "can get hiv through supernatural",
                                     "can get aids through supernatural")),
        ("hiv_know_mtct_pregnancy", ("aids virus from mother to child during pregnancy",
                                     "hiv from mother to child during pregnancy",
                                     "aids from mother to child during pregnancy")),
        ("hiv_know_mtct_delivery",  ("aids virus from mother to child during delivery",
                                     "hiv from mother to child during delivery",
                                     "aids from mother to child at delivery",
                                     "aids from mother to child during delivery")),
        ("hiv_know_mtct_breastfeeding", ("aids virus from mother to child through breastfeeding",
                                         "hiv from mother to child through breastfeeding",
                                         "aids from mother to child through breastmilk")),
        ("hiv_know_saliva",         ("fear of getting hiv in contact with the saliva",)),
        ("hiv_know_needle",         ("can get aids virus by injection with needle",
                                     "can get aids by injection with needle",
                                     "can get hiv by injection with needle")),
    ]
    for varname, terms in _knowledge_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "hiv_aids", "yes_no")]

    # Stigma / attitudes
    _stigma_map = [
        ("hiv_stigma_ashamed",          ("ashamed if someone in my family had hiv",)),
        ("hiv_stigma_lose_respect",     ("lose the respect of other people",)),
        ("hiv_stigma_fear_test",        ("people hesitate to take an hiv test",)),
        ("hiv_stigma_talk_badly",       ("people talk badly about people living with hiv",)),
        ("hiv_stigma_allow_school",     ("children living with hiv, or thought to be living with hiv, should be allowed to attend school",)),
        ("hiv_stigma_want_secret",      ("would want it to remain a secret",)),
        ("hiv_stigma_buy_vegetables",   ("would buy fresh vegetables from shopkeeper with aids virus",)),
        ("hiv_stigma_care_for_person",  ("willing to care for person with aids in household",)),
        ("hiv_stigma_allow_teacher",    ("should female teacher with aids virus be allowed to teach",)),
    ]
    for varname, terms in _stigma_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "hiv_aids", "categorical")]

    # MTCT drugs awareness
    if _has(text, "aware of drugs used to reduce the risk of transmission to the baby"):
        return [_explicit("hiv_mtct_drugs_aware",
                          "Aware of drugs to reduce MTCT risk",
                          "hiv_aids", "yes_no")]

    # Testing
    if _has(text, "most recent time of testing for aids virus",
            "most recent time of testing for hiv"):
        return [_explicit("hiv_last_test_timing",
                          "Most recent time of HIV testing",
                          "hiv_aids", "categorical")]
    if _has(text, "ever been tested for aids virus", "ever been tested for hiv"):
        return [_explicit("ever_tested_hiv",
                          "Ever been tested for HIV/AIDS",
                          "hiv_aids", "yes_no")]
    if _has(text, "received results of aids virus test", "received results of hiv test",
            "received results from test", "obtained test results"):
        return [_explicit("hiv_test_results_received",
                          "Received HIV test results",
                          "hiv_aids", "yes_no")]
    if _has(text, "tested for aids virus since test during pregnancy",
            "tested for hiv since test during pregnancy"):
        return [_explicit("tested_hiv_since_pregnancy",
                          "Tested for HIV since pregnancy test",
                          "hiv_aids", "yes_no")]
    if _has(text, "know a place to get hiv test", "know a place to get aids virus test"):
        return [_explicit("know_hiv_test_place",
                          "Knows a place to get HIV test",
                          "hiv_aids", "yes_no")]
    if _has(text, "heard of test kit for hiv testing"):
        return [_explicit("hiv_self_test_kit_heard",
                          "Heard of HIV self-test kit",
                          "hiv_aids", "yes_no")]
    if _has(text, "ever tested yourself using test kit"):
        return [_explicit("hiv_self_test_kit_used",
                          "Ever used HIV self-test kit",
                          "hiv_aids", "yes_no")]
    if _has(text, "has own immunization card", "has immunization card"):
        return [_explicit("has_immunization_card",
                          "Has own immunization card",
                          "hiv_aids", "yes_no")]
    if _has(text, "children living with hiv should be allowed to attend school"):
        return [_explicit("hiv_stigma_allow_school",
                          "Children with HIV should be allowed in school",
                          "hiv_aids", "yes_no")]
    if _has(text, "would buy fresh vegetables from shopseller with hiv",
            "would buy fresh vegetables from shopkeeper with aids"):
        return [_explicit("hiv_stigma_buy_vegetables",
                          "Would buy from shopkeeper with HIV/AIDS",
                          "hiv_aids", "categorical")]
    if _has(text, "should teacher with hiv", "should female teacher with aids virus be allowed to teach"):
        return [_explicit("hiv_stigma_allow_teacher",
                          "HIV+ teacher allowed to teach",
                          "hiv_aids", "yes_no")]
    if _has(text, "healthy-looking person to have aids", "healthy-looking person may have aids",
            "healthy-looking person may have hiv"):
        return [_explicit("hiv_know_healthy_looking",
                          "Healthy-looking person may have HIV",
                          "hiv_aids", "yes_no")]
    if _has(text, "tested for hiv/aids", "ever had hiv test"):
        return [_explicit("ever_tested_hiv", "Ever been tested for HIV/AIDS",
                          "hiv_aids", "yes_no")]
    if _has(text, "received result of hiv test", "received results of hiv test"):
        return [_explicit("hiv_test_results_received",
                          "Received HIV test results", "hiv_aids", "yes_no")]
    if _has(text, "asked for hiv test or was it offered to you"):
        return [_explicit("hiv_test_requested_or_offered",
                          "Asked for or offered HIV test", "hiv_aids", "categorical")]
    if _has(text, "if a member became infected with the virus, would you want"):
        return [_explicit("hiv_stigma_want_secret",
                          "Would want HIV status to remain secret",
                          "hiv_aids", "categorical")]

    return None


def _tobacco_alcohol(text: str) -> list[CanonicalEntry] | None:
    # Smoking
    if _has(text, "currently smoking cigarettes"):
        return [_explicit("currently_smoking",
                          "Currently smoking cigarettes",
                          "tobacco", "yes_no")]
    if _has(text, "ever tried cigarette smoking"):
        return [_explicit("ever_tried_smoking",
                          "Ever tried cigarette smoking",
                          "tobacco", "yes_no")]
    if _has(text, "age when cigarette was smoked for the first time"):
        return [_explicit("age_first_smoked",
                          "Age when first smoked",
                          "tobacco", "continuous")]
    if _has(text, "number of cigarettes smoked in the last 24 hours"):
        return [_explicit("cigarettes_last_24h",
                          "Number of cigarettes smoked in last 24 hours",
                          "tobacco", "continuous")]
    if _has(text, "number of days when cigarettes were smoked in past month"):
        return [_explicit("smoking_days_last_month",
                          "Days smoked cigarettes in last month",
                          "tobacco", "continuous")]
    if _has(text, "used any smoked tobacco products during the last month"):
        return [_explicit("smoked_tobacco_last_month",
                          "Used smoked tobacco products in last month",
                          "tobacco", "yes_no")]
    if _has(text, "ever tried any smoked tobacco products other than cigarettes"):
        return [_explicit("ever_tried_other_smoked_tobacco",
                          "Ever tried other smoked tobacco products",
                          "tobacco", "yes_no")]
    if _has(text, "number of days when tobacco products where smoked in past month"):
        return [_explicit("smoked_tobacco_days_last_month",
                          "Days used smoked tobacco in last month",
                          "tobacco", "continuous")]

    # Smokeless tobacco
    if _has(text, "ever tried any form of smokeless tobacco products"):
        return [_explicit("ever_tried_smokeless_tobacco",
                          "Ever tried smokeless tobacco",
                          "tobacco", "yes_no")]
    if _has(text, "used any smokeless tobacco products during the last month"):
        return [_explicit("smokeless_tobacco_last_month",
                          "Used smokeless tobacco products in last month",
                          "tobacco", "yes_no")]
    if _has(text, "number of days when smokeless tobacco products where used in past month"):
        return [_explicit("smokeless_tobacco_days_last_month",
                          "Days used smokeless tobacco in last month",
                          "tobacco", "continuous")]

    # Tobacco no-response (treat as skip)
    if _has(text, "type of smokeless tobacco product used: no response",
            "type of smoked tobacco product: no response"):
        return []

    # Smoked tobacco type
    _smoked_type_map = [
        ("tobacco_type_cigars",      ("type of smoked tobacco product: cigars",)),
        ("tobacco_type_cigarillos",  ("type of smoked tobacco product: cigarillos",)),
        ("tobacco_type_pipe",        ("type of smoked tobacco product: pipe",)),
        ("tobacco_type_water_pipe",  ("type of smoked tobacco product: water pipe",)),
        ("tobacco_type_other",       ("type of smoked tobacco product: other",)),
    ]
    for varname, terms in _smoked_type_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "tobacco", "yes_no")]

    # Smokeless tobacco type
    _smokeless_type_map = [
        ("tobacco_smokeless_chewing", ("type of smokeless tobacco product used: chewing tobacco",)),
        ("tobacco_smokeless_snuff",   ("type of smokeless tobacco product used: snuff",)),
        ("tobacco_smokeless_dip",     ("type of smokeless tobacco product used: dip",)),
        ("tobacco_smokeless_other",   ("type of smokeless tobacco product used: other",)),
    ]
    for varname, terms in _smokeless_type_map:
        if _has(text, *terms):
            return [_explicit(varname, text, "tobacco", "yes_no")]

    # Alcohol
    if _has(text, "ever drunk alcohol"):
        return [_explicit("ever_drunk_alcohol",
                          "Ever drunk alcohol",
                          "alcohol", "yes_no")]
    if _has(text, "age when alcohol was used for the first time"):
        return [_explicit("age_first_alcohol",
                          "Age at first alcohol use",
                          "alcohol", "continuous")]
    if _has(text, "number of drinks usually consumed"):
        return [_explicit("drinks_per_occasion",
                          "Number of drinks usually consumed",
                          "alcohol", "continuous")]
    if _has(text, "number of days when at least one drink of alcohol was used in past month"):
        return [_explicit("alcohol_days_last_month",
                          "Days drank alcohol in last month",
                          "alcohol", "continuous")]

    return None


def _anthropometry(text: str) -> list[CanonicalEntry] | None:
    if _exact(text, "weight", "weighed"):
        return [_explicit("woman_weight", "Woman's weight (kg)",
                          "anthropometry", "continuous")]
    if _has(text, "weight from card or recall"):
        return [_explicit("woman_weight", "Woman's weight (kg)",
                          "anthropometry", "continuous")]
    if _has(text, "blood pressure measured", "blood pressure"):
        return [_explicit("blood_pressure", "Blood pressure",
                          "anthropometry", "continuous")]
    if _has(text, "number of household members"):
        return [_explicit("hh_members", "Number of household members",
                          "household", "continuous")]
    return None


def _media(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "frequency of reading newspaper or magazine",
            "how often do you read a newspaper"):
        return [_explicit("media_newspaper_frequency",
                          "Frequency of reading newspaper/magazine",
                          "media", "categorical")]
    if _has(text, "frequency of listening to the radio",
            "do you listen to the radio"):
        return [_explicit("media_radio_frequency",
                          "Frequency of listening to radio",
                          "media", "categorical")]
    if _has(text, "frequency of watching tv", "how often do you watch television"):
        return [_explicit("media_tv_frequency",
                          "Frequency of watching TV",
                          "media", "categorical")]
    if _has(text, "ever used a computer or a tablet", "ever used a computer",
            "have you used a computer"):
        return [_explicit("ever_used_computer",
                          "Ever used a computer",
                          "media", "yes_no")]
    if _has(text, "computer usage in the last 12 months",
            "computer / tablet usage in the last 3 months",
            "frequency of computer usage in the last month",
            "in the last 12 months, have you ever used the internet",
            "how often did you use a computer"):
        return [_explicit("computer_usage_recent",
                          "Recent computer usage",
                          "media", "categorical")]
    if _has(text, "internet usage in the last 3 months",
            "internet usage in the last 12 months",
            "frequency of internet usage in the past month",
            "how often did you use the internet"):
        return [_explicit("internet_usage_recent",
                          "Internet usage in last 3 months",
                          "media", "categorical")]
    if _has(text, "ever used internet", "have you ever used the internet"):
        return [_explicit("ever_used_internet",
                          "Ever used internet",
                          "media", "yes_no")]
    if _has(text, "mobile phone usage in the last 3 months"):
        return [_explicit("mobile_phone_usage_recent",
                          "Mobile phone usage in last 3 months",
                          "media", "categorical")]
    if _has(text, "own a mobile phone"):
        return [_explicit("owns_mobile_phone",
                          "Owns a mobile phone",
                          "media", "yes_no")]

    # ICT skills
    _ict_map = [
        ("ict_copy_file",        ("copy or move a file or folder",)),
        ("ict_copy_paste",       ("use a copy / paste in document",)),
        ("ict_connect_device",   ("connect and install a new device",)),
        ("ict_install_software", ("install and configure software",)),
        ("ict_presentation",     ("create an electronic presentation",)),
        ("ict_transfer_file",    ("transfer a file",)),
        ("ict_programming",      ("write a computer program",)),
        ("ict_send_email",       ("send e-mail with attached file",)),
        ("ict_spreadsheet",      ("basic arithmetic formula in a spreadsheet",
                                   "arithmetic formula in a spreadsheet")),
    ]
    if _startswith(text, "during the last 3 months:"):
        for varname, terms in _ict_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "media", "yes_no")]

    return None


def _wealth(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "combined wealth score"):
        return [_explicit("wealth_score_combined",
                          "Combined wealth score", "wealth", "continuous")]
    if _has(text, "urban wealth score"):
        return [_explicit("wealth_score_urban",
                          "Urban wealth score", "wealth", "continuous")]
    if _has(text, "rural wealth score"):
        return [_explicit("wealth_score_rural",
                          "Rural wealth score", "wealth", "continuous")]
    if _has(text, "wealth index score", "wealth index quintile score"):
        return [_explicit("wealth_index_score",
                          "Wealth index score", "wealth", "continuous")]
    if _has(text, "wealth index quintile", "wealth index quintiles",
            "wealth index quintile", "wealth quintile"):
        if _has(text, "urban"):
            return [_explicit("wealth_quintile_urban",
                              "Urban wealth index quintile", "wealth", "categorical")]
        if _has(text, "rural"):
            return [_explicit("wealth_quintile_rural",
                              "Rural wealth index quintile", "wealth", "categorical")]
        return [_explicit("wealth_quintile",
                          "Wealth index quintile", "wealth", "categorical")]
    return None


def _household_assets(text: str) -> list[CanonicalEntry] | None:
    _asset_map = [
        ("asset_radio",           ("radio",)),
        ("asset_tv",              ("television",)),
        ("asset_bicycle",         ("bicycle",)),
        ("asset_refrigerator",    ("refrigerator",)),
        ("asset_electricity",     ("electricity",)),
        ("asset_mobile_phone",    ("mobile phone",)),
        ("asset_non_mobile_phone",("non-mobile phone", "fixed telephone", "landline")),
        ("asset_mosquito_net",    ("mosquito net observed",)),
        ("asset_watch",           ("watch",)),
        ("asset_car",             ("car or truck", "car/truck")),
        ("asset_motorcycle",      ("motorcycle or scooter", "motorcycle/scooter")),
        ("asset_animal_cart",     ("animal-drawn cart", "animal drawn cart")),
        ("asset_computer",        ("computer",)),
        ("asset_internet",        ("internet",)),
        ("asset_boat",            ("boat with motor", "motorboat")),
    ]
    if len(text.split()) <= 5:
        for varname, terms in _asset_map:
            if _exact(text, *terms):
                return [_explicit(varname, text, "household_assets", "yes_no")]
    return None


def _wellbeing(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "estimation of overall happiness"):
        return [_explicit("overall_happiness",
                          "Overall happiness", "wellbeing", "categorical")]
    if _has(text, "life satisfaction expectation one year from now"):
        return [_explicit("life_satisfaction_future",
                          "Life satisfaction expectation (next year)",
                          "wellbeing", "categorical")]
    if _has(text, "life satisfaction in comparison with last year"):
        return [_explicit("life_satisfaction_vs_last_year",
                          "Life satisfaction vs last year",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with ladder step"):
        return [_explicit("life_satisfaction_ladder",
                          "Life satisfaction ladder step",
                          "wellbeing", "continuous")]
    if _has(text, "satisfaction with current income"):
        return [_explicit("satisfaction_income",
                          "Satisfaction with current income",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with family life"):
        return [_explicit("satisfaction_family",
                          "Satisfaction with family life",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with health"):
        return [_explicit("satisfaction_health",
                          "Satisfaction with health",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with current job"):
        return [_explicit("satisfaction_job",
                          "Satisfaction with current job",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with school"):
        return [_explicit("satisfaction_school",
                          "Satisfaction with school",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with friendships"):
        return [_explicit("satisfaction_friendships",
                          "Satisfaction with friendships",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with appearance"):
        return [_explicit("satisfaction_appearance",
                          "Satisfaction with appearance",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with life overall", "satisfaction with your life overall"):
        return [_explicit("satisfaction_life_overall",
                          "Satisfaction with life overall",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with treatment by other people",
            "satisfaction with how others treat you"):
        return [_explicit("satisfaction_treatment_by_others",
                          "Satisfaction with treatment by others",
                          "wellbeing", "categorical")]
    if _has(text, "satisfaction with current residence"):
        return [_explicit("satisfaction_residence",
                          "Satisfaction with current residence",
                          "wellbeing", "categorical")]
    return None


def _functional_difficulties(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "functional difficulties"):
        return [_explicit("functional_difficulties",
                          "Functional difficulties", "functional_disability", "categorical")]
    if _has(text, "difficulty seeing, even if wearing glasses"):
        return [_explicit("difficulty_seeing",
                          "Difficulty seeing", "functional_disability", "categorical")]
    if _has(text, "difficulty hearing, even if using a hearing aid"):
        return [_explicit("difficulty_hearing",
                          "Difficulty hearing", "functional_disability", "categorical")]
    if _has(text, "difficulty walking or climbing steps"):
        return [_explicit("difficulty_walking",
                          "Difficulty walking or climbing steps",
                          "functional_disability", "categorical")]
    if _has(text, "difficulty with self-care, such as washing all over or dressing"):
        return [_explicit("difficulty_self_care",
                          "Difficulty with self-care",
                          "functional_disability", "categorical")]
    if _has(text, "difficulty remembering or concentrating"):
        return [_explicit("difficulty_remembering",
                          "Difficulty remembering or concentrating",
                          "functional_disability", "categorical")]
    if _has(text, "difficulty communicating"):
        return [_explicit("difficulty_communicating",
                          "Difficulty communicating",
                          "functional_disability", "categorical")]
    if _has(text, "use glasses or contact lenses"):
        return [_explicit("uses_glasses",
                          "Uses glasses or contact lenses",
                          "functional_disability", "yes_no")]
    if _has(text, "use hearing aid"):
        return [_explicit("uses_hearing_aid",
                          "Uses hearing aid",
                          "functional_disability", "yes_no")]
    return None


def _discrimination(text: str) -> list[CanonicalEntry] | None:
    _discrim_map = [
        ("discrim_age",          ("felt discriminated: age",)),
        ("discrim_disability",   ("felt discriminated: disability",)),
        ("discrim_sexual_orientation", ("felt discriminated: sexual orientation",)),
        ("discrim_religion",     ("felt discriminated: religion or belief",)),
        ("discrim_ethnic",       ("felt discriminated: ethnic or immigration origin",)),
        ("discrim_other",        ("felt discriminated: any other reason",)),
    ]
    if _has(text, "in the past 12 months, felt discriminated"):
        for varname, terms in _discrim_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "discrimination", "yes_no")]
        return [_explicit("discrim_other_reason", text, "discrimination",
                          "yes_no", confidence="medium")]
    return None


def _menstrual_hygiene(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "used any materials such as sanitary pads, tampons or cloth"):
        return [_explicit("menstrual_materials_used",
                          "Used sanitary materials during menstruation",
                          "menstrual_hygiene", "yes_no")]
    if _has(text, "availability of private place for washing during last menstrual period"):
        return [_explicit("menstrual_private_washing_place",
                          "Private place for washing during menstruation",
                          "menstrual_hygiene", "yes_no")]
    if _has(text, "social activities, school or work days not attended due to menstruation"):
        return [_explicit("menstrual_days_missed",
                          "Days missed school/work due to menstruation",
                          "menstrual_hygiene", "continuous")]
    if _has(text, "materials reusable"):
        return [_explicit("menstrual_materials_reusable",
                          "Menstrual materials reusable",
                          "menstrual_hygiene", "yes_no")]
    return None


def _health_insurance(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "covered by health insurance"):
        return [_explicit("has_health_insurance",
                          "Covered by health insurance",
                          "health_insurance", "yes_no")]
    if _has(text, "type of health insurance: other"):
        return [_explicit("health_insurance_type_other",
                          "Health insurance type: other",
                          "health_insurance", "yes_no")]
    if _has(text, "type of health insurance: no response"):
        return [_explicit("health_insurance_type_no_response",
                          "Health insurance type: no response",
                          "health_insurance")]
    if _has(text, "health insurance"):
        return [_explicit("health_insurance_type",
                          "Type of health insurance",
                          "health_insurance", "categorical")]
    return None


def _water_sanitation(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "main source of drinking water", "main source of water"):
        return [_explicit("drinking_water_source",
                          "Main source of drinking water",
                          "water_sanitation", "categorical")]
    if _has(text, "kind of toilet facility", "type of toilet facility"):
        return [_explicit("toilet_facility_type",
                          "Type of toilet facility",
                          "water_sanitation", "categorical")]
    if _has(text, "treat water to make safer for drinking"):
        return [_explicit("water_treatment_any",
                          "Treat water to make safer for drinking",
                          "water_sanitation", "yes_no")]
    if _has(text, "solar disinfection"):
        return [_explicit("water_solar_disinfection",
                          "Solar disinfection", "water_sanitation", "yes_no")]
    if _exact(text, "boil"):
        return [_explicit("water_boil", "Boil water", "water_sanitation", "yes_no")]
    if _has(text, "add bleach", "add chlorine"):
        return [_explicit("water_bleach_chlorine",
                          "Add bleach/chlorine to water", "water_sanitation", "yes_no")]
    if _has(text, "strain it through a cloth"):
        return [_explicit("water_strain_cloth",
                          "Strain water through cloth", "water_sanitation", "yes_no")]
    if _has(text, "let it stand and settle"):
        return [_explicit("water_let_settle",
                          "Let water stand and settle", "water_sanitation", "yes_no")]
    if _has(text, "time to get water and come back"):
        return [_explicit("water_collection_time",
                          "Time to collect water", "water_sanitation", "continuous")]
    if _has(text, "use water filter"):
        return [_explicit("water_filter", "Use water filter",
                          "water_sanitation", "yes_no")]
    if _has(text, "toilet facility shared"):
        return [_explicit("toilet_shared", "Toilet facility shared",
                          "water_sanitation", "yes_no")]
    if _has(text, "households using this toilet facility"):
        return [_explicit("toilet_households_sharing",
                          "Number of households sharing toilet",
                          "water_sanitation", "continuous")]
    if _has(text, "person fetching water"):
        return [_explicit("water_fetcher",
                          "Person fetching water",
                          "water_sanitation", "categorical")]
    if _has(text, "main source of water used for other purposes"):
        return [_explicit("water_other_source",
                          "Main source of water for other purposes",
                          "water_sanitation", "categorical")]
    return None


def _migration(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "duration of living in current place"):
        return [_explicit("duration_in_current_place",
                          "Duration of living in current place",
                          "migration", "continuous")]
    if _has(text, "place of living prior to moving to current place"):
        return [_explicit("prior_place_of_living",
                          "Prior place of living",
                          "migration", "categorical")]
    if _has(text, "region prior to moving to current place",
            "place of living prior to current place"):
        return [_explicit("prior_region",
                          "Region prior to moving",
                          "migration", "categorical")]
    if _has(text, "number of rooms for sleeping"):
        return [_explicit("sleeping_rooms",
                          "Number of rooms for sleeping",
                          "housing", "continuous")]
    if _has(text, "main material of floor", "floor material"):
        return [_explicit("floor_material",
                          "Main material of floor",
                          "housing", "categorical")]
    if _has(text, "main material of roof"):
        return [_explicit("roof_material",
                          "Main material of roof",
                          "housing", "categorical")]
    if _has(text, "main material of wall"):
        return [_explicit("wall_material",
                          "Main material of wall",
                          "housing", "categorical")]
    if _has(text, "type of fuel using for cooking", "cooking fuel"):
        return [_explicit("cooking_fuel",
                          "Type of cooking fuel",
                          "housing", "categorical")]
    if _has(text, "cooking location"):
        return [_explicit("cooking_location",
                          "Cooking location",
                          "housing", "categorical")]
    if _has(text, "food cooked on stove or open fire", "food cooked on a stove"):
        return [_explicit("cooking_location",
                          "Cooking location (stove or open fire)",
                          "housing", "categorical")]
    if _has(text, "number of rooms in dwelling", "number of rooms used for sleeping and living"):
        return [_explicit("dwelling_rooms",
                          "Number of rooms in dwelling",
                          "housing", "continuous")]
    if _has(text, "fire stove have a chimney", "stove has a chimney"):
        return [_explicit("stove_chimney",
                          "Fire stove has chimney or hood",
                          "housing", "yes_no")]
    if _has(text, "vitamin a dose after last birth", "vitamin a after the birth"):
        return [_explicit("vitamin_a_after_birth",
                          "Vitamin A dose after last birth",
                          "postnatal_care", "yes_no")]
    return None


def _wealth_derived(text: str) -> list[CanonicalEntry] | None:
    """Derived wealth percentile group variables."""
    if _has(text, "percentile group of com1"):
        return [_explicit("wealth_percentile_combined",
                          "Combined wealth percentile group",
                          "wealth", "categorical")]
    if _has(text, "percentile group of urb1"):
        return [_explicit("wealth_percentile_urban",
                          "Urban wealth percentile group",
                          "wealth", "categorical")]
    if _has(text, "percentile group of rur1"):
        return [_explicit("wealth_percentile_rural",
                          "Rural wealth percentile group",
                          "wealth", "categorical")]
    return None


def _ethnicity_religion(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "ethnicity of household head"):
        return [_explicit("hh_head_ethnicity",
                          "Ethnicity of household head",
                          "demographic", "categorical")]
    if _has(text, "religion of household head", "religion of the head of household"):
        return [_explicit("hh_head_religion",
                          "Religion of household head",
                          "demographic", "categorical")]
    return None


def _fgm(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "heard of female circumcision", "heard of female genital",
            "heard of genital cutting", "heard of cutting"):
        return [_explicit("fgm_heard_of",
                          "Heard of female circumcision/FGM",
                          "fgm", "yes_no")]
    if _has(text, "herself been circumcised", "has she been circumcised",
            "ever circumcised", "flesh removed from the genital area",
            "genital area sewn closed"):
        return [_explicit("fgm_self_circumcised",
                          "Herself circumcised",
                          "fgm", "yes_no")]
    if _has(text, "person circumcising respondent", "who circumcised respondent",
            "who circumcised her"):
        return [_explicit("fgm_practitioner",
                          "Person who performed circumcision",
                          "fgm", "categorical")]
    if _has(text, "any of her daughters circumcised", "daughters circumcised"):
        return [_explicit("fgm_daughters_circumcised",
                          "Any daughters circumcised",
                          "fgm", "yes_no")]
    if _has(text, "type of circumcision", "type of cut"):
        return [_explicit("fgm_type",
                          "Type of circumcision",
                          "fgm", "categorical")]
    if _has(text, "female circumcision", "female genital mutilation", "female genital cutting"):
        return [_explicit("fgm_attitude",
                          "Attitude toward female circumcision",
                          "fgm", "categorical")]
    return None


def _symptoms(text: str) -> list[CanonicalEntry] | None:
    """ARI/diarrhea symptoms in WM questionnaire (for women's reporting of child illness)."""
    _symptom_map = [
        ("symptom_fever",          ("child develops a fever", "symptom: fever")),
        ("symptom_fast_breathing", ("child has fast breathing", "child has fast breath",
                                     "child breathes rapidly", "child breathes fast")),
        ("symptom_difficult_breathing", ("child has difficult breathing",
                                         "child has difficulty breathing")),
        ("symptom_not_drinking",   ("child not able to drink or breastfeed",
                                    "child is drinking poorly")),
        ("symptom_blood_stool",    ("child has blood in stools", "child has blood in stool")),
        ("symptom_sicker",         ("child becomes sicker",)),
    ]
    if _startswith(text, "symptoms:"):
        for varname, terms in _symptom_map:
            if _has(text, *terms):
                return [_explicit(varname, text, "illness_symptoms", "yes_no")]
        return []
    if _has(text, "what types of symptoms would cause you to take your child"):
        return [_explicit("symptom_care_seeking",
                          "Symptoms causing care seeking", "illness_symptoms", "categorical")]
    return None


def _malaria_prevention(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "took medicine in order to prevent malaria",
            "medicines taken to prevent malaria"):
        return [_explicit("malaria_preventive_medicine",
                          "Took medicine to prevent malaria",
                          "malaria", "yes_no")]
    if _has(text, "mosquito net observed"):
        return [_explicit("asset_mosquito_net",
                          "Mosquito net observed",
                          "household_assets", "yes_no")]
    if _exact(text, "net number", "mosquito net number", "number of nets"):
        return [_explicit("malaria_net_count",
                          "Number of mosquito nets in household",
                          "malaria", "continuous")]
    if _has(text, "months ago net obtained", "months ago mosquito net obtained"):
        return [_explicit("malaria_net_months_obtained",
                          "Months ago mosquito net obtained",
                          "malaria", "continuous")]
    if _has(text, "net soaked or dipped since obtained",
            "net soaked or dipped",
            "net treated with an insecticide when obtained",
            "net treated with insecticide"):
        return [_explicit("malaria_net_treated",
                          "Net soaked or dipped since obtained",
                          "malaria", "yes_no")]
    if _has(text, "months ago net soaked or dipped", "months ago last soaked or dipped"):
        return [_explicit("malaria_net_months_treated",
                          "Months ago net soaked or dipped",
                          "malaria", "continuous")]
    if _has(text, "medicine to prevent malaria", "antimalarial medicine"):
        return [_explicit("malaria_medicine_type",
                          "Type of malaria medicine taken",
                          "malaria", "categorical")]
    if _has(text, "persons slept under mosquito net last night",
            "slept under mosquito net last night"):
        return [_explicit("malaria_net_slept_under",
                          "Persons who slept under mosquito net last night",
                          "malaria", "continuous")]
    if _startswith(text, "person") and _has(text, "slept under net"):
        return []
    if _has(text, "brand/type of observed net", "brand of mosquito net", "net brand"):
        return [_explicit("malaria_net_brand",
                          "Brand/type of mosquito net",
                          "malaria", "categorical")]
    if _has(text, "times took sp", "times took sp/fansidar", "doses of sp/fansidar",
            "doses of sp ", "sp/fansidar"):
        return [_explicit("malaria_ipt_sp_doses",
                          "Times took SP/Fansidar for malaria prevention",
                          "malaria", "continuous")]
    return None


def _newborn_cord_care(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "what was applied to the cord: chlorhexidine"):
        return [_explicit("cord_chlorhexidine",
                          "Chlorhexidine applied to cord",
                          "postnatal_care", "yes_no")]
    if _has(text, "what was applied to the cord", "something applied to the cord"):
        return [_explicit("cord_substance_applied",
                          "Substance applied to cord",
                          "postnatal_care", "categorical")]
    if _has(text, "what was used to cut the cord", "instrument used to cut the cord",
            "used to cut the cord"):
        return [_explicit("cord_cutting_instrument",
                          "Instrument used to cut the cord",
                          "postnatal_care", "categorical")]
    if _has(text, "during two days after birth health care provider weighed child again"):
        return [_explicit("newborn_weighed_again",
                          "Newborn weighed again in first 2 days",
                          "postnatal_care", "yes_no")]
    return None


def _robbery_crime(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "someone taken or tried taking something, by using force"):
        return [_explicit("robbery_occurred",
                          "Robbery occurred (force or threat)",
                          "crime", "yes_no")]
    return None


def _hiv_counseling(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "counseled about aids or the aids virus"):
        return [_explicit("hiv_counseled",
                          "Counseled about HIV/AIDS",
                          "hiv_aids", "yes_no")]
    if _has(text, "received counseling after being tested",
            "received counselling after being tested",
            "received counseling after test"):
        return [_explicit("hiv_counseling_after_test",
                          "Received counseling after HIV testing",
                          "hiv_aids", "yes_no")]
    return None


def _education_other(text: str) -> list[CanonicalEntry] | None:
    if _has(text, "ever completed that grade/year", "ever completed that grade"):
        return [_explicit("education_grade_completed",
                          "Ever completed that grade",
                          "woman_background", "yes_no")]
    if _has(text, "grade attended at that level during current school year"):
        return [_explicit("current_school_grade",
                          "Grade attended at that level (current school year)",
                          "woman_background", "continuous")]
    if _has(text, "grade attended at that level during previous school year"):
        return [_explicit("prev_school_grade",
                          "Grade attended at that level (previous school year)",
                          "woman_background", "continuous")]
    if _has(text, "highest level of education attended"):
        return [_explicit("education_level", "Highest level of school attended",
                          "woman_background", "categorical")]
    return None


# ---------------------------------------------------------------------------
# Dispatch chain
# ---------------------------------------------------------------------------

_DISPATCH = [
    _response_options,
    _identifiers,
    _survey_metadata,
    _geographic,
    _woman_background,
    _education_other,
    _marriage,
    _birth_history,
    _fertility_preferences,
    _family_planning,
    _antenatal_care,
    _delivery,
    _postnatal_care,
    _newborn_cord_care,
    _early_breastfeeding,
    _child_at_birth,
    _symptoms,
    _domestic_violence,
    _robbery_crime,
    _sexual_behavior,
    _hiv_aids,
    _hiv_counseling,
    _tobacco_alcohol,
    _anthropometry,
    _media,
    _wealth,
    _wealth_derived,
    _household_assets,
    _wellbeing,
    _functional_difficulties,
    _discrimination,
    _menstrual_hygiene,
    _health_insurance,
    _water_sanitation,
    _malaria_prevention,
    _migration,
    _ethnicity_religion,
    _fgm,
]


def canonicalise(label: str) -> list[CanonicalEntry]:
    text = _clean_label(label)
    for fn in _DISPATCH:
        result = fn(text)
        if result is not None:
            return result
    return []


def canonicalize(label: str) -> list[CanonicalEntry]:
    return canonicalise(label)
