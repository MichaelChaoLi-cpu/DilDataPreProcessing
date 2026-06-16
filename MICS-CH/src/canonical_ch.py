"""Rule-based canonicalization helpers for MICS CH (children under 5) column labels.

Key differences from HH/HL rule engines:
- "age" and "sex" refer to the child, not the household head.
- Covers immunization (IM), breastfeeding/infant feeding (BF), diarrhea/ARI (CA),
  malaria (ML), anthropometry (AN), birth registration (BR), early childhood
  education (EC), and vitamin A (VA) modules.
- Many CH datasets include merged household background variables (WS, HC, HH)
  from the household questionnaire; those are canonicalized here too.
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
        _response_options,       # skip first — pure response/dk labels
        _date_or_time,
        _identifiers,
        _child_demographics,
        _birth_registration,
        _early_childhood_education,
        _vitamin_a,
        _breastfeeding_and_infant_feeding,
        _dietary_diversity,
        _diarrhea_and_ari,
        _malaria,
        _immunization_dates,
        _immunization_recall,
        _anthropometry,
        _child_discipline,
        _child_functioning,
        _water_sanitation,
        _household_assets,
        _housing,
        _survey_metadata,
        _derived_background,
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
    text = text.replace("'s", "s")
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
# Ordered vaccine date lookup: combined forms must come before standalone
# ---------------------------------------------------------------------------

_VACCINE_DATE_MAP: list[tuple[str, tuple[str, ...]]] = [
    # Combined DPT variants (check before standalone dpt/hepb)
    ("dpt_1", ("dtp-hepb-hib1", "dtp-hepb1", "dtp hepb hib1", "dtp hepb1",
               "dpthepb-hib1", "dpthepb1", "pentavalent1", "pentavalent 1")),
    ("dpt_2", ("dtp-hepb-hib2", "dtp-hepb2", "dtp hepb hib2", "dtp hepb2",
               "dpthepb-hib2", "dpthepb2", "pentavalent2", "pentavalent 2")),
    ("dpt_3", ("dtp-hepb-hib3", "dtp-hepb3", "dtp hepb hib3", "dtp hepb3",
               "dpthepb-hib3", "dpthepb3", "pentavalent3", "pentavalent 3")),
    # Standalone DPT
    ("dpt_1", ("dpt1", "dtp1")),
    ("dpt_2", ("dpt2", "dtp2")),
    ("dpt_3", ("dpt3", "dtp3")),
    # Standalone HepB
    ("hepb_1", ("hepb1", "hepatitis b1", "hep b1", "hep-b1", "hepatitis b 1")),
    ("hepb_2", ("hepb2", "hepatitis b2", "hep b2", "hep-b2", "hepatitis b 2")),
    ("hepb_3", ("hepb3", "hepatitis b3", "hep b3", "hep-b3", "hepatitis b 3")),
    # Polio (birth dose before numbered doses)
    ("polio_birth", ("polio at birth", "opv0", "opv 0", "polio0", "polio 0", "polio zero")),
    ("polio_1",     ("opv1", "opv 1", "polio1", "polio 1")),
    ("polio_2",     ("opv2", "opv 2", "polio2", "polio 2")),
    ("polio_3",     ("opv3", "opv 3", "polio3", "polio 3")),
    # Standalone HIB (Haemophilus influenzae type b)
    ("hib_1", ("hib1", "hib 1", "haemophilus influenzae b1", "haemophilus 1")),
    ("hib_2", ("hib2", "hib 2", "haemophilus influenzae b2", "haemophilus 2")),
    ("hib_3", ("hib3", "hib 3", "haemophilus influenzae b3", "haemophilus 3")),
    # BCG
    ("bcg", ("bcg",)),
    # Measles / MMR
    ("measles_mmr", ("measles", "mmr", "rouvax", "measles or mmr")),
    # Yellow Fever
    ("yellow_fever", ("yellow fever",)),
    # Vitamin A doses from vaccination card (dose 2 before dose 1 to avoid partial match)
    ("vitamin_a_dose_2", ("vitamin a (2)", "vitamin a dose 2", "receiving vitamin a (2)")),
    ("vitamin_a_dose_1", ("vitamin a (1)", "vitamin a dose 1", "receiving vitamin a (1)",
                          "receiving vitamin a")),
]


# ---------------------------------------------------------------------------
# Pattern matchers
# ---------------------------------------------------------------------------

def _response_options(text: str) -> CanonicalEntry | None:
    """Pure response-option or skip labels — do not assign a canonical variable."""
    _skip = {
        "none", "other", "dk", "others", "no response", "missing",
        "yes", "no", "don't know", "do not know", "n/a", "not applicable",
        "other (specify)", "unknown", "none/no document",
        "none of the above codes", "none of the above",
        "not applicable (n/a)", "na", "ns", "nr", "no answer",
        "not stated", "end",
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


def _date_or_time(text: str) -> list[CanonicalEntry] | None:
    # Child interview date (CMC)
    if _has(text, "date of interview child (cmc)", "child interview date (cmc)",
            "interview date child (cmc)"):
        return [
            _date_component("interview", "year",  "derived", "extract_year_cmc",  "Interview year"),
            _date_component("interview", "month", "derived", "extract_month_cmc", "Interview month"),
        ]
    # Generic interview date (compound → derive all three)
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
    # Data-entry date (questionnaire entry day/month/year)
    if _has(text, "questionnaire entry day", "entry day"):
        return [_date_component("data_entry", "day", "explicit", None, "Data entry day")]
    if _has(text, "questionnaire entry month", "entry month"):
        return [_date_component("data_entry", "month", "explicit", None, "Data entry month")]
    if _has(text, "questionnaire entry year", "entry year"):
        return [_date_component("data_entry", "year", "explicit", None, "Data entry year")]
    # Interview time (handles "start of interview", "interview start", "interview start time")
    if _has(text, "start of interview", "interview start") and _has(text, "hour"):
        return [_explicit("interview_start_hour", "Interview start hour",
                          "interview_time_component", "time_component")]
    if _has(text, "start of interview", "interview start") and _has(text, "minute"):
        return [_explicit("interview_start_minute", "Interview start minute",
                          "interview_time_component", "time_component")]
    if _has(text, "end of interview", "interview end") and _has(text, "hour"):
        return [_explicit("interview_end_hour", "Interview end hour",
                          "interview_time_component", "time_component")]
    if _has(text, "end of interview", "interview end") and _has(text, "minute"):
        return [_explicit("interview_end_minute", "Interview end minute",
                          "interview_time_component", "time_component")]
    if _exact(text, "am/pm"):
        return [_explicit("interview_am_pm", "Interview AM/PM",
                          "interview_time_component", "time_component")]
    # Standalone hour/minute (short label — survey time) only if no other context
    if _exact(text, "hour"):
        return [_explicit("interview_start_hour", "Interview hour",
                          "interview_time_component", "time_component", confidence="medium")]
    if _exact(text, "minute") or _exact(text, "minutes"):
        return [_explicit("interview_start_minute", "Interview minute",
                          "interview_time_component", "time_component", confidence="medium")]
    # Survey day/month/year (older datasets use "Survey" prefix)
    if _has(text, "survey day") or (_exact(text, "day") and not _has(text, "birth")):
        return [_date_component("interview", "day", "explicit", None, "Interview day")]
    if _has(text, "survey month"):
        return [_date_component("interview", "month", "explicit", None, "Interview month")]
    if _has(text, "survey year"):
        return [_date_component("interview", "year", "explicit", None, "Interview year")]
    # Child birth date (CMC)
    if _has(text, "date of birth of child (cmc)", "date of birth (cmc)",
            "child date of birth (cmc)", "cdob", "cmc date of birth of child"):
        return [
            _date_component("child_birth", "year",  "derived", "extract_year_cmc",  "Child birth year"),
            _date_component("child_birth", "month", "derived", "extract_month_cmc", "Child birth month"),
        ]
    # Child birth date (compound label without CMC)
    if _has(text, "childs date of birth", "child's date of birth", "date of birth of child") and \
       not _has(text, "day", "month", "year", "cmc"):
        return [
            _date_component("child_birth", "year",  "derived", "extract_year",  "Child birth year"),
            _date_component("child_birth", "month", "derived", "extract_month", "Child birth month"),
            _date_component("child_birth", "day",   "derived", "extract_day",   "Child birth day"),
        ]
    # Child birth date components (explicit — including "Child's birth day" → "childs birth day")
    if _has(text, "year of birth of child", "year of birth", "childs year of birth",
            "child birth year", "childs birth year", "birth year"):
        return [_explicit("child_birth_year", "Child birth year",
                          "child_demographics", "date_component")]
    if _has(text, "month of birth of child", "month of birth", "childs month of birth",
            "child birth month", "childs birth month", "birth month"):
        return [_explicit("child_birth_month", "Child birth month",
                          "child_demographics", "date_component")]
    if _has(text, "day of birth of child", "day of birth", "childs day of birth",
            "child birth day", "childs birth day", "birth day"):
        return [_explicit("child_birth_day", "Child birth day",
                          "child_demographics", "date_component")]
    return None


def _identifiers(text: str) -> CanonicalEntry | None:
    if _exact(text, "cluster number", "psu", "primary sampling unit",
              "cluster or psu number", "cluster sequential number"):
        return _explicit("cluster_number", "Cluster number", "household_identifier", "identifier")
    if _exact(text, "household number") or \
       _has(text, "household number in sample", "dwelling unit order number"):
        return _explicit("household_number", "Household number", "household_identifier", "identifier")
    # Household/child/individual identifiers (MICS2 era and earlier)
    if _has(text, "household id", "household identification", "household identifier",
            "individual identification", "hh identification"):
        return _explicit("household_number", "Household number", "household_identifier",
                         "identifier", confidence="medium")
    if _has(text, "child id", "child identifier", "child code", "child identification",
            "childs id", "childs name and line number"):
        return _explicit("child_line_number", "Child line number",
                         "household_identifier", "identifier", confidence="medium")
    if _has(text, "caregiver id", "caregiver code", "caretaker code",
            "guardian code", "mother or guardian code", "mother/guardian code",
            "mother/adult caregiver") and not _has(text, "line number"):
        return _explicit("mother_caretaker_line_number", "Mother/caretaker line number",
                         "household_identifier", "identifier", confidence="medium")
    if _has(text, "hh member id", "household member id", "household member identification"):
        return _explicit("hh_member_line_number", "Household member line number",
                         "household_identifier", "identifier", confidence="medium")
    # Module-specific "ID line number" markers (UFID, BR1ID, etc.)
    if _has(text, "id line number") or _exact(text, "id"):
        return _explicit("module_id_line_number", "Module ID line number",
                         "survey_administration", "identifier", confidence="medium")
    if _exact(text, "line number"):
        return _explicit("line_number", "Line number", "household_identifier", "identifier")
    if _has(text, "childs line number", "child line number") or _exact(text, "line number of child"):
        return _explicit("child_line_number", "Child line number",
                         "household_identifier", "identifier")
    if _has(text, "mother", "caretaker", "caregiver") and _has(text, "line number"):
        return _explicit("mother_caretaker_line_number", "Mother/caretaker line number",
                         "household_identifier", "identifier")
    if _exact(text, "stratum"):
        return _explicit("stratum", "Stratum", "survey_design", "identifier")
    # Enumeration/area identifiers
    if _has(text, "ed number", "enumeration district", "enumeration area"):
        return _explicit("enumeration_district", "Enumeration district",
                         "household_identifier", "identifier")
    if _has(text, "questionnaire number", "questionnaire no"):
        return _explicit("questionnaire_number", "Questionnaire number",
                         "survey_administration", "identifier")
    if _has(text, "sample point", "sample code"):
        return _explicit("sample_point", "Sample point",
                         "survey_design", "identifier")
    # Clinic code (Cuba)
    if _has(text, "clinic code", "clinic number"):
        return _explicit("clinic_code", "Clinic code",
                         "survey_administration", "identifier")
    return None


def _child_demographics(text: str) -> CanonicalEntry | None:
    if _exact(text, "sex") or _has(text, "sex of child", "childs sex", "child sex",
                                    "male or female"):
        return _explicit("sex_of_child", "Sex of child", "child_demographics", "categorical")
    if _exact(text, "age (months)", "age in months", "age (in months)",
              "child age (months)", "childs age (months)", "childs age (in months)"):
        return _explicit("child_age_months", "Child age in months",
                         "child_demographics", "continuous")
    if _exact(text, "age (completed years)", "age (years)", "age in years",
              "age in completed years", "age (completed years)", "age") or \
       _has(text, "completed years", "age of child", "childs age"):
        return _explicit("child_age_months", "Child age in months",
                         "child_demographics", "continuous", confidence="medium")
    if _has(text, "age in days", "age days"):
        return _explicit("child_age_days", "Child age in days",
                         "child_demographics", "continuous")
    return None


def _birth_registration(text: str) -> CanonicalEntry | None:
    if _has(text, "birth certificate", "birth registration form",
            "have birth registration"):
        return _explicit("has_birth_certificate", "Child has birth certificate",
                         "birth_registration", "binary")
    if _has(text, "birth registered", "birth was registered", "birth declared",
            "child registered", "birth has been registered") or \
       _exact(text, "birth registration"):
        return _explicit("birth_registered", "Birth is registered",
                         "birth_registration", "binary")
    if _has(text, "reason birth not registered", "why birth not registered",
            "reason for not registering", "birth not registered", "why is his birth",
            "why his birth is not registered", "why his/her birth is not registered",
            "why not registered", "reason for birth not being registered",
            "reason for late registration", "for what main reason did you not register"):
        return _explicit("reason_birth_not_registered", "Reason birth not registered",
                         "birth_registration", "categorical")
    if _has(text, "know how to register", "how to register a birth",
            "knows how to register", "know where to register", "knows where to register",
            "knows what to do to register"):
        return _explicit("knows_how_to_register_birth", "Knows how to register birth",
                         "birth_registration", "binary")
    if _has(text, "main reason") and _has(text, "registration", "register"):
        return _explicit("reason_for_birth_registration", "Reason for birth registration",
                         "birth_registration", "categorical")
    if _has(text, "cost of registration", "fee for registration"):
        return _explicit("birth_registration_cost", "Cost of birth registration",
                         "birth_registration", "continuous", confidence="medium")
    if _has(text, "place of birth registration", "where to register child birth",
            "where did you register", "registration office", "where to go to register"):
        return _explicit("birth_registration_place", "Place of birth registration",
                         "birth_registration", "categorical")
    if _has(text, "deadline for registering") and _has(text, "birth"):
        return _explicit("knows_registration_deadline", "Knows birth registration deadline",
                         "birth_registration", "binary")
    # Age-check filter variable (child is old enough for certain modules)
    if _has(text, "child is 3 years old", "3 years old and more", "child is 3"):
        return _explicit("age_check_3_or_older", "Child is 3 years old or more",
                         "survey_administration", "binary", confidence="medium")
    return None


def _early_childhood_education(text: str) -> CanonicalEntry | None:
    # ECDI developmental milestones (MICS4/5/6)
    if _has(text, "identifies at least ten letters", "identifies ten or more letter",
            "know at least ten letters", "can read letters of the alphabet"):
        return _explicit("ecdi_knows_letters", "ECDI: knows letters of alphabet",
                         "ecdi_milestone", "binary")
    if _has(text, "reads at least four simple", "read at least four simple",
            "can read at least four"):
        return _explicit("ecdi_reads_simple_words", "ECDI: reads simple popular words",
                         "ecdi_milestone", "binary")
    if _has(text, "knows name and recognizes symbol", "knows the name and recognizes",
            "name and recognizes symbol of all numbers", "recognize symbol",
            "attache sounds to sounds", "attach sounds to most",
            "can count the number from 1 to 10", "count from 1 to 10",
            "count 1 to 10"):
        return _explicit("ecdi_knows_numbers_1_to_10", "ECDI: knows numbers 1 to 10",
                         "ecdi_milestone", "binary")
    if _has(text, "able to pick up small object", "pick up small object with 2 fingers",
            "picks up small object"):
        return _explicit("ecdi_fine_motor_skill", "ECDI: fine motor skill (pick up small object)",
                         "ecdi_milestone", "binary")
    if _has(text, "sometimes too sick to play", "too sick to play"):
        return _explicit("ecdi_sometimes_too_sick", "ECDI: sometimes too sick to play",
                         "ecdi_milestone", "binary")
    if _has(text, "follows simple directions", "follow simple directions"):
        return _explicit("ecdi_follows_directions", "ECDI: follows simple directions",
                         "ecdi_milestone", "binary")
    if _has(text, "able to do something independently", "does something independently"):
        return _explicit("ecdi_independence", "ECDI: does something independently",
                         "ecdi_milestone", "binary")
    if _has(text, "gets along well with other children", "gets along with other children"):
        return _explicit("ecdi_gets_along_with_peers", "ECDI: gets along with other children",
                         "ecdi_milestone", "binary")
    if _has(text, "kicks, bites or hits", "kicks bites or hits", "aggressive toward"):
        return _explicit("ecdi_aggressive_behavior", "ECDI: aggressive behavior",
                         "ecdi_milestone", "binary")
    # Parenting/caregiving behavior module
    if _has(text, "develop the intelligence", "develop intelligence"):
        return _explicit("parenting_develops_intelligence", "Parenting: develops child intelligence",
                         "parenting_behavior", "binary")
    if _has(text, "give warm and responsive care", "warm and responsive"):
        return _explicit("parenting_warm_responsive_care", "Parenting: gives warm responsive care",
                         "parenting_behavior", "binary")
    if _has(text, "encourage any participation", "encourages participation"):
        return _explicit("parenting_encourages_participation",
                         "Parenting: encourages participation",
                         "parenting_behavior", "binary")
    if _has(text, "set good example", "modeling good behavior", "model good behavior"):
        return _explicit("parenting_sets_good_example", "Parenting: sets good example",
                         "parenting_behavior", "binary")
    if _has(text, "punish child", "discipline") and _has(text, "harsh", "physical", "violence"):
        return _explicit("parenting_harsh_discipline", "Parenting: harsh discipline",
                         "parenting_behavior", "binary", confidence="medium")
    # ECE attendance
    if _has(text, "attends early childhood education", "attend early childhood education",
            "attend preschool", "attends preschool", "attends early learning",
            "attend early learning", "ever attended early childhood education",
            "attended early childhood education"):
        return _explicit("attends_ece_programme", "Attends early childhood education programme",
                         "early_childhood_education", "binary")
    if _has(text, "type of early childhood education"):
        return _explicit("type_of_ece_programme", "Type of early childhood education programme",
                         "early_childhood_education", "categorical")
    if _has(text, "hours attended education", "hours did he attend", "hours at education",
            "hours of early learning", "number of hours attended in the last",
            "hours did he/she attend this place", "hours in the last 7"):
        return _explicit("hours_ece_per_week", "Hours attended ECE programme per week",
                         "early_childhood_education", "continuous")
    # Books and toys
    if _has(text, "number of childrens books", "childrens books or picture books",
            "children books or picture books"):
        return _explicit("number_of_childrens_books", "Number of childrens books or picture books",
                         "early_childhood_education", "count")
    if _has(text, "how many books are there in the household", "books in the household",
            "how many books"):
        return _explicit("books_in_household", "Books in the household",
                         "early_childhood_education", "count")
    if _has(text, "homemade toys", "toys made at home", "homemae toys"):
        return _explicit("has_homemade_toys", "Has homemade toys", "early_childhood_education", "binary")
    if _has(text, "toys from shops", "toys that came from a store", "toys bought"):
        return _explicit("has_store_toys", "Has toys from shops", "early_childhood_education", "binary")
    if _has(text, "household objects", "outside objects", "sticks", "rocks", "shells", "leaves",
            "bowls, plate", "dishes, plates", "household items like", "collected outside the"):
        return _explicit("has_household_object_toys", "Has household/outside objects as toys",
                         "early_childhood_education", "binary")
    if _has(text, "no playthings", "no toys"):
        return _explicit("no_playthings", "No playthings", "early_childhood_education", "binary")
    # Supervision
    if _has(text, "left alone") and _has(text, "hour", "time", "day", "week"):
        return _explicit("times_left_alone_past_week", "Times left alone past week",
                         "child_care", "count")
    if _has(text, "left") and _has(text, "care of another child", "other child", "older child",
                                    "left in the care") and _has(text, "hour", "time", "day", "week"):
        return _explicit("times_left_with_older_child_past_week",
                         "Times left in care of older child past week",
                         "child_care", "count")
    # Toys variants
    if _has(text, "toys from shops", "toys that came from a store", "toys that came from shop",
            "toys bought", "toy from shop"):
        return _explicit("has_store_toys", "Has toys from shops", "early_childhood_education", "binary")
    if _has(text, "items used for playing", "objects used for playing"):
        return _explicit("play_items_type", "Type of items used for playing",
                         "early_childhood_education", "categorical")
    # Supervision context: "has the child been left in the care of"
    if _has(text, "has the child been left", "child been left in the care"):
        return _explicit("child_left_in_care_of", "Child left in care of (person type)",
                         "child_care", "categorical")
    if _has(text, "how many times has he been alone", "times has he been alone",
            "times has she been alone"):
        return _explicit("times_left_alone_past_week", "Times left alone past week",
                         "child_care", "count")
    # Learning activities with caregiver (books/stories/songs/outside/play/naming × mother/father/other/nobody)
    activity = _detect_learning_activity(text)
    caregiver = _detect_caregiver_role(text)
    if activity and caregiver:
        varname = f"learning_{activity}_{caregiver}"
        text_out = f"Learning activity: {activity.replace('_', ' ')} by {caregiver}"
        return _explicit(varname, text_out, "early_childhood_education", "binary")
    # Learning activity with "Missing" or "No response" flag (Belize MICS5)
    if activity and _has(text, "missing", "no response"):
        varname = f"learning_{activity}_missing_flag"
        return _explicit(varname, f"Learning activity {activity}: missing/no response flag",
                         "early_childhood_education", "binary", confidence="medium")
    return None


_LEARNING_ACTIVITIES: list[tuple[str, tuple[str, ...]]] = [
    ("books",         ("book",)),
    ("tell_stories",  ("stor",)),
    ("sang_songs",    ("song", "sang", "sing")),
    ("took_outside",  ("outside", "took out", "outing", "going out", "go out")),
    ("played_with",   ("play",)),
    ("named_counted", ("named", "counted", "namin", "naming", "counting")),
    ("drew_painted",  ("drew", "painted", "draw", "paint")),
    ("activity_books",("activity book", "filling activity")),
    ("spent_time",    ("spent time", "spend time", "spending time")),
]

_CAREGIVER_ROLES: list[tuple[str, tuple[str, ...]]] = [
    ("mother",  ("mother",)),
    ("father",  ("father",)),
    ("nobody",  ("no one", "nobody", "no person")),
    # "Person" (French "Personne" → "No one") must come before "other"
    ("nobody",  ("person",)),
    ("other",   ("other",)),
]


def _detect_learning_activity(text: str) -> str | None:
    for act_key, terms in _LEARNING_ACTIVITIES:
        if _has(text, *terms):
            return act_key
    return None


def _detect_caregiver_role(text: str) -> str | None:
    for role_key, terms in _CAREGIVER_ROLES:
        if _has(text, *terms):
            return role_key
    return None


def _vitamin_a(text: str) -> CanonicalEntry | None:
    if _exact(text, "vitamin a"):
        return _explicit("received_vitamin_a_on_card", "Vitamin A on immunization card",
                         "immunization", "binary", confidence="medium")
    if _has(text, "child ever received vitamin a", "ever received vitamin a capsule",
            "ever received a vitamin a"):
        return _explicit("ever_received_vitamin_a_supplement",
                         "Child ever received Vitamin A supplement",
                         "vitamin_a", "binary")
    if _has(text, "months ago") and _has(text, "vitamin a", "last dose"):
        return _explicit("months_since_last_vitamin_a",
                         "Months since last Vitamin A dose",
                         "vitamin_a", "continuous")
    if _has(text, "months since the last dose", "number of months since the last dose",
            "months since last dose"):
        return _explicit("months_since_last_vitamin_a",
                         "Months since last Vitamin A dose",
                         "vitamin_a", "continuous")
    if _exact(text, "source of last dose") or \
       (_has(text, "place", "where", "source") and _has(text, "last dose", "vitamin a")):
        return _explicit("place_last_vitamin_a",
                         "Place child received last Vitamin A dose",
                         "vitamin_a", "categorical")
    if _has(text, "illness") and _has(text, "vitamin a", "last dose", "suffered from"):
        return _explicit("illness_at_last_vitamin_a",
                         "Illness child suffered from at last Vitamin A dose",
                         "vitamin_a", "categorical")
    return None


def _breastfeeding_and_infant_feeding(text: str) -> CanonicalEntry | None:
    if _has(text, "ever been breastfed", "ever breastfed", "did you breastfeed"):
        return _explicit("ever_breastfed", "Child ever been breastfed",
                         "breastfeeding", "binary")
    if _has(text, "still being breastfed", "still breastfeeding", "still breastfed",
            "are you still breastfeeding", "currently breastfed", "currently breastfeeding",
            "is currently breastfed"):
        return _explicit("still_breastfeeding", "Child still being breastfed",
                         "breastfeeding", "binary")
    if _has(text, "reason for not breastfeeding"):
        return _explicit("reason_not_breastfeeding", "Reason for not breastfeeding",
                         "breastfeeding", "categorical")
    if _has(text, "breastfed since yesterday", "been fed since yesterday",
            "fed since yesterday"):
        return _explicit("breastfed_since_yesterday", "Child breastfed/fed since yesterday",
                         "breastfeeding", "binary")
    # Liquids/foods given yesterday (various phrasings across MICS rounds)
    if _has(text, "plain water yesterday", "drank plain water", "received plain water",
            "received: plain water", "received water", "child received: plain water",
            "child received plain water") and \
       not _has(text, "source", "treat", "fetch", "other"):
        return _explicit("infant_fed_plain_water_yesterday", "Fed plain water yesterday",
                         "infant_feeding", "binary")
    if _has(text, "infant formula yesterday", "drank infant formula", "received infant formula",
            "baby formula", "commercially sold"):
        return _explicit("infant_fed_formula_yesterday", "Fed infant formula yesterday",
                         "infant_feeding", "binary")
    if _has(text, "times") and _has(text, "infant formula"):
        return _explicit("times_infant_formula_yesterday", "Times fed infant formula yesterday",
                         "infant_feeding", "count")
    if _has(text, "milk yesterday", "drank milk yesterday", "canned", "powdered milk",
            "fresh milk", "received milk"):
        return _explicit("infant_fed_milk_yesterday", "Fed milk yesterday",
                         "infant_feeding", "binary")
    if _has(text, "juice or juice drinks", "sweetened water or juice", "received sweetened water"):
        return _explicit("infant_fed_juice_yesterday", "Fed juice or sweetened water yesterday",
                         "infant_feeding", "binary")
    if _has(text, "soup yesterday", "drank soup"):
        return _explicit("infant_fed_soup_yesterday", "Fed soup yesterday",
                         "infant_feeding", "binary")
    if (_has(text, "vitamin") or _has(text, "mineral")) and \
       _has(text, "supplements", "supplement"):
        return _explicit("infant_fed_vitamin_supplements_yesterday",
                         "Fed vitamin/mineral supplements yesterday",
                         "infant_feeding", "binary")
    if _has(text, "ors yesterday", "oral rehydration solution", "oral rehydration salts",
            "oral rehydration") and _has(text, "yesterday", "drank", "received", "given"):
        return _explicit("infant_fed_ors_yesterday", "Fed ORS yesterday",
                         "infant_feeding", "binary")
    if _has(text, "any other liquid yesterday", "other liquids", "received other liquids"):
        return _explicit("infant_fed_other_liquid_yesterday", "Fed other liquid yesterday",
                         "infant_feeding", "binary")
    if _has(text, "yogurt yesterday", "drank or ate yogurt", "received yogurt",
            "cheese or yogurt"):
        return _explicit("infant_fed_yogurt_yesterday", "Fed yogurt/cheese yesterday",
                         "infant_feeding", "binary")
    if _has(text, "times") and _has(text, "yogurt"):
        return _explicit("times_yogurt_yesterday", "Times fed yogurt yesterday",
                         "infant_feeding", "count")
    if _has(text, "thin porridge yesterday"):
        return _explicit("infant_fed_thin_porridge_yesterday", "Fed thin porridge yesterday",
                         "infant_feeding", "binary")
    if _has(text, "solid or semi-solid food", "solid or semi solid food",
            "solid, semisolid", "solid food yesterday", "received solid or",
            "received solid", "mushy food"):
        return _explicit("infant_fed_solid_food_yesterday", "Fed solid or semi-solid food yesterday",
                         "infant_feeding", "binary")
    if _has(text, "times") and _has(text, "solid", "semi-solid", "semi solid") and _has(text, "food"):
        return _explicit("times_solid_food_yesterday", "Times fed solid or semi-solid food yesterday",
                         "infant_feeding", "count")
    if _has(text, "bottle with a nipple", "bottle with nipple", "nipple"):
        return _explicit("infant_fed_from_bottle_with_nipple_yesterday",
                         "Fed from bottle with nipple yesterday",
                         "infant_feeding", "binary")
    if _has(text, "pasifier", "pacifier", "dummy"):
        return _explicit("infant_used_pacifier_yesterday", "Infant used pacifier yesterday",
                         "infant_feeding", "binary")
    # Exclusive breastfeeding duration
    if _has(text, "months of exclusive breastmilk", "months exclusively breastfed",
            "months of exclusive breastfeeding"):
        return _explicit("months_exclusive_breastfeeding", "Months of exclusive breastfeeding",
                         "breastfeeding", "continuous")
    # Infant feeding received prefix: "received: X" format
    if _has(text, "received:") or _has(text, "child received:"):
        if _has(text, "formula", "commercially sold"):
            return _explicit("infant_fed_formula_yesterday", "Fed infant formula yesterday",
                             "infant_feeding", "binary")
        if _has(text, "juice", "sweetened water"):
            return _explicit("infant_fed_juice_yesterday", "Fed juice/sweetened water yesterday",
                             "infant_feeding", "binary")
        if _has(text, "soup"):
            return _explicit("infant_fed_soup_yesterday", "Fed soup yesterday",
                             "infant_feeding", "binary")
        if _has(text, "solid", "semi-solid", "mushy", "semi solid"):
            return _explicit("infant_fed_solid_food_yesterday",
                             "Fed solid or semi-solid food yesterday",
                             "infant_feeding", "binary")
        if _has(text, "vitamin", "mineral", "supplement"):
            return _explicit("infant_fed_vitamin_supplements_yesterday",
                             "Fed vitamin/mineral supplements yesterday",
                             "infant_feeding", "binary")
        if _has(text, "ors", "oral rehydration"):
            return _explicit("infant_fed_ors_yesterday", "Fed ORS yesterday",
                             "infant_feeding", "binary")
        if _has(text, "milk", "canned", "powdered"):
            return _explicit("infant_fed_milk_yesterday", "Fed milk yesterday",
                             "infant_feeding", "binary")
        if _has(text, "other liquid"):
            return _explicit("infant_fed_other_liquid_yesterday", "Fed other liquid yesterday",
                             "infant_feeding", "binary")
    # Feeding frequency
    if _has(text, "number of times child drank milk", "times child drank milk",
            "number of times drank milk"):
        return _explicit("times_milk_yesterday", "Times fed milk yesterday",
                         "infant_feeding", "count")
    # Commercially fortified baby food
    if _has(text, "commercially fortified baby food", "cerelac", "fortified baby"):
        return _explicit("infant_fed_fortified_baby_food", "Fed commercially fortified baby food",
                         "infant_feeding", "binary")
    # Foods made from grains (catch before dietary_diversity for yesterday-context)
    if _has(text, "foods made from grains", "child ate grains") and _has(text, "yesterday"):
        return _explicit("infant_fed_grains_yesterday", "Fed grain-based foods yesterday",
                         "infant_feeding", "binary")
    return None


def _dietary_diversity(text: str) -> CanonicalEntry | None:
    """Child dietary diversity variables (MICS4/5/6 food groups)."""
    if not _has(text, "child ate", "ate ", "child consumed", "child had",
                "child drank", "number of times"):
        return None
    if _has(text, "commercially fortified baby food", "cerelac"):
        return _explicit("dd_fortified_baby_food", "DD: commercially fortified baby food",
                         "dietary_diversity", "binary")
    if _has(text, "grain", "bread", "rice", "pasta", "porridge", "ugali",
            "maize", "wheat", "millet", "sorghum", "chapati"):
        return _explicit("dd_grains", "DD: grains/starches",
                         "dietary_diversity", "binary")
    if _has(text, "white potato", "white yam", "manioc", "cassava", "yam",
            "plantain", "roots"):
        return _explicit("dd_white_roots_tubers", "DD: white roots/tubers",
                         "dietary_diversity", "binary")
    if _has(text, "pumpkin", "carrot", "squash") and not _has(text, "other"):
        return _explicit("dd_vitamin_a_veg", "DD: vitamin A-rich vegetables",
                         "dietary_diversity", "binary")
    if _has(text, "green leafy vegetable", "dark green leafy"):
        return _explicit("dd_green_leafy_veg", "DD: green leafy vegetables",
                         "dietary_diversity", "binary")
    if _has(text, "mango", "papaya", "apricot") and not _has(text, "other"):
        return _explicit("dd_vitamin_a_fruit", "DD: vitamin A-rich fruits",
                         "dietary_diversity", "binary")
    if _has(text, "other fruits or vegetables", "other fruit or vegetable"):
        return _explicit("dd_other_fruit_veg", "DD: other fruits/vegetables",
                         "dietary_diversity", "binary")
    if _has(text, "organ meat", "liver", "kidney", "heart"):
        return _explicit("dd_organ_meat", "DD: organ meat",
                         "dietary_diversity", "binary")
    if _has(text, "meat", "beef", "pork", "lamb", "goat", "chicken", "duck", "poultry") and \
       not _has(text, "organ"):
        return _explicit("dd_meat_poultry", "DD: meat/poultry",
                         "dietary_diversity", "binary")
    if _has(text, "egg"):
        return _explicit("dd_eggs", "DD: eggs", "dietary_diversity", "binary")
    if _has(text, "fish", "shellfish", "seafood", "shrimp"):
        return _explicit("dd_fish_seafood", "DD: fish/seafood",
                         "dietary_diversity", "binary")
    if _has(text, "bean", "lentil", "pea", "nut", "legume") and \
       not _has(text, "coffee", "cacao"):
        return _explicit("dd_legumes_nuts", "DD: legumes/nuts",
                         "dietary_diversity", "binary")
    if _has(text, "cheese", "yogurt", "dairy") and \
       not _has(text, "milk yesterday", "infant formula"):
        return _explicit("dd_dairy", "DD: dairy (cheese/yogurt)",
                         "dietary_diversity", "binary")
    if _has(text, "sweet", "candy", "chocolate", "sugary"):
        return _explicit("dd_sweets", "DD: sweets/confectionery",
                         "dietary_diversity", "binary")
    if _has(text, "oil", "fat", "butter", "margarine"):
        return _explicit("dd_fats_oils", "DD: fats/oils",
                         "dietary_diversity", "binary")
    if _has(text, "other solid", "other food"):
        return _explicit("dd_other_foods", "DD: other foods",
                         "dietary_diversity", "binary")
    return None


def _diarrhea_and_ari(text: str) -> CanonicalEntry | None:
    # Diarrhea episode fluid management (Bosnia/older MICS style)
    if _has(text, "during diarrhoea episode", "during diarrhea episode",
            "during the diarrhoea", "during the diarrhea"):
        if _has(text, "breastmilk", "breastfed", "breast milk"):
            return _explicit("diarrhea_episode_breastmilk", "Breastmilk during diarrhea episode",
                             "child_illness_treatment", "binary")
        if _has(text, "gruel", "thin porridge"):
            return _explicit("diarrhea_episode_gruel", "Gruel/thin porridge during diarrhea",
                             "child_illness_treatment", "binary")
        if _has(text, "ors packet", "ors sachet", "oral rehydration"):
            return _explicit("diarrhea_treatment_ors_packet", "ORS during diarrhea episode",
                             "child_illness_treatment", "binary")
        if _has(text, "acceptable fluid", "other acceptable"):
            return _explicit("diarrhea_episode_other_fluids",
                             "Other acceptable fluids during diarrhea",
                             "child_illness_treatment", "binary")
        if _has(text, "soup"):
            return _explicit("diarrhea_episode_soup", "Soup during diarrhea episode",
                             "child_illness_treatment", "binary")
        return _explicit("diarrhea_episode_fluid", "Fluid given during diarrhea episode",
                         "child_illness_treatment", "binary", confidence="medium")
    # Blood in stools
    if _has(text, "blood in the stool", "blood in stools", "blood in stool",
            "there was blood in the stools"):
        return _explicit("blood_in_stool", "Blood in stool during illness",
                         "child_illness", "binary")
    # Other illness in last 2 weeks
    if _has(text, "other illness in last 2 weeks", "other illness last two weeks"):
        return _explicit("other_illness_last_2_weeks", "Other illness in last 2 weeks",
                         "child_illness", "binary")
    # Diarrhea
    if _has(text, "diarrhea in last 2 weeks", "diarrhoea in last 2 weeks",
            "had diarrhea", "had diarrhoea", "suffer from diarrhea", "suffer from diarrhoea"):
        return _explicit("diarrhea_last_2_weeks", "Child had diarrhea in last 2 weeks",
                         "child_illness", "binary")
    if _has(text, "less to drink", "drank less", "given less to drink") and \
       _has(text, "diarrhea", "diarrhoea", "illness"):
        return _explicit("fluid_intake_during_diarrhea", "Fluid intake during diarrhea",
                         "child_illness", "categorical")
    if _has(text, "less to eat", "ate less", "given less to eat") and \
       _has(text, "diarrhea", "diarrhoea", "illness"):
        return _explicit("food_intake_during_diarrhea", "Food intake during diarrhea",
                         "child_illness", "categorical")
    # ORS and treatment
    if _has(text, "liquid prepared from a sachet", "fluid made from special packet",
            "liquid from a sachet"):
        return _explicit("diarrhea_treatment_ors_packet", "Treated with ORS from sachet",
                         "child_illness_treatment", "binary")
    if _has(text, "pre-packaged ors", "prepackaged ors", "pre packaged ors"):
        return _explicit("diarrhea_treatment_ors_prepackaged", "Treated with pre-packaged ORS",
                         "child_illness_treatment", "binary")
    if (_has(text, "government", "govt") and
            _has(text, "recommended homemade fluid", "homemade fluid",
                "homemade liquid", "recommended homemade liquid")):
        return _explicit("diarrhea_treatment_homemade_fluid",
                         "Treated with govt-recommended homemade fluid",
                         "child_illness_treatment", "binary")
    if _has(text, "stool", "stools", "excrement") and \
       _has(text, "dispose", "disposal", "did with", "what"):
        return _explicit("stool_disposal_method", "Method of stool disposal",
                         "sanitation_practice", "categorical")
    # ARI / Cough
    if _has(text, "cough in last 2 weeks", "ill with cough", "suffered from cough",
            "suffer from cough") or \
       (_has(text, "cough") and _has(text, "last two weeks", "last 2 weeks")):
        return _explicit("cough_last_2_weeks", "Child had cough in last 2 weeks",
                         "child_illness", "binary")
    if _has(text, "difficulty breathing", "faster breathing", "difficult breathing",
            "breathing faster", "rapid breathing"):
        return _explicit("fast_or_difficult_breathing", "Fast or difficult breathing during cough",
                         "child_illness", "binary")
    if _has(text, "problem in chest", "chest") and \
       _has(text, "blocked nose", "symptoms due to"):
        return _explicit("chest_problem_or_blocked_nose", "Symptoms from chest problem or blocked nose",
                         "child_illness", "binary")
    # Care seeking
    # ORS sachet source and cost (handle both "sachet" and "packet" naming)
    if _has(text, "obtain the ors sachet", "obtain ors sachet", "get the ors sachet",
            "obtain the ors", "get the ors packet", "where did you get the ors",
            "get the ors"):
        return _explicit("ors_sachet_source", "Source where ORS sachet obtained",
                         "child_illness_treatment", "categorical")
    if _has(text, "pay for the ors sachet", "pay for ors sachet", "cost of ors",
            "pay for the ors packet", "pay for the ors"):
        return _explicit("ors_sachet_cost", "Cost of ORS sachet",
                         "child_illness_treatment", "continuous", confidence="medium")
    # "Was he given a liquid prepared from a packet" → ORS packet
    if _has(text, "liquid prepared from a packet", "liquid from a packet"):
        return _explicit("diarrhea_treatment_ors_packet", "Treated with ORS from packet/sachet",
                         "child_illness_treatment", "binary")
    if _has(text, "sought advice or treatment", "sought care",
            "seek advice or treatment", "seek care", "sought advice or teatment",
            "seen by the services", "seen by a health"):
        return _explicit("sought_care_for_illness", "Sought care for child illness",
                         "child_illness_care_seeking", "binary")
    # Care-seeking locations (context marker: "place sought care" or "advice:" prefix)
    _cs = _has(text, "place sought care", "advice:")
    if _cs and _has(text, "government hospital", "govt hospital", "public hospital",
                    "district hospital"):
        return _explicit("care_seeking_public_hospital", "Care sought at public hospital",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "health center", "health centre", "health center", "chc", "ihc",
                    "integrated health", "district health"):
        return _explicit("care_seeking_public_health_centre", "Care sought at public health centre",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "health post"):
        return _explicit("care_seeking_public_health_post", "Care sought at public health post",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "village health worker", "community health worker", "health group",
                    "health worker"):
        return _explicit("care_seeking_community_health_worker",
                         "Care sought from community health worker",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "mobile", "outreach"):
        return _explicit("care_seeking_mobile_or_outreach", "Care sought at mobile/outreach clinic",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "other public"):
        return _explicit("care_seeking_other_public", "Care sought at other public source",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "private hospital", "private clinic"):
        return _explicit("care_seeking_private_hospital", "Care sought at private hospital/clinic",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "private physician", "private doctor"):
        return _explicit("care_seeking_private_physician", "Care sought from private physician",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "pharmacy", "pharmacist", "drug seller"):
        return _explicit("care_seeking_pharmacy", "Care sought at pharmacy",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "clinic") and not _has(text, "health", "hospital"):
        return _explicit("care_seeking_clinic", "Care sought at clinic",
                         "child_illness_care_seeking", "binary", confidence="medium")
    if _cs and _has(text, "relative", "friend"):
        return _explicit("care_seeking_relative_or_friend", "Care sought from relative or friend",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "shop"):
        return _explicit("care_seeking_shop", "Care sought at shop",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "traditional practitioner", "traditional healer"):
        return _explicit("care_seeking_traditional_practitioner",
                         "Care sought from traditional practitioner",
                         "child_illness_care_seeking", "binary")
    if _cs and _has(text, "other private", "other medical"):
        return _explicit("care_seeking_other_private_medical", "Care sought at other private source",
                         "child_illness_care_seeking", "binary")
    # "Advice: Hospital" without qualifier → generic hospital
    if _cs and _has(text, "hospital"):
        return _explicit("care_seeking_hospital", "Care sought at hospital",
                         "child_illness_care_seeking", "binary", confidence="medium")
    # Catch-all for "Advice: Other" and similar
    if _cs and _has(text, "other"):
        return _explicit("care_seeking_other", "Care sought at other source",
                         "child_illness_care_seeking", "binary", confidence="medium")
    # Care-seeking at health facility (older MICS phrasing)
    if _has(text, "child seen at health facility", "seen at a health facility",
            "seen by health facility"):
        return _explicit("sought_care_for_illness", "Sought care for child illness",
                         "child_illness_care_seeking", "binary")
    if _has(text, "child took medicine prescribed at health facility",
            "took medicine prescribed"):
        return _explicit("medicine_given_for_illness", "Medicine given for illness",
                         "child_illness_treatment", "binary")
    if _has(text, "advice or treatment during illness", "child taken to a health facility"):
        return _explicit("sought_care_for_illness", "Sought care for child illness",
                         "child_illness_care_seeking", "binary")
    # During illness, did he drink much less (older MICS phrasing)
    if _has(text, "during illness did he drink", "during illness did she drink",
            "during illness did the child drink"):
        return _explicit("fluid_intake_during_diarrhea", "Fluid intake during illness",
                         "child_illness", "categorical")
    # Medicine given
    if _has(text, "given medicine", "child take any medication", "given any medicine"):
        return _explicit("medicine_given_for_illness", "Medicine given for illness",
                         "child_illness_treatment", "binary")
    # Drug names — check injection before oral (more specific)
    if _has(text, "antibiotic") and _has(text, "injection"):
        return _explicit("medicine_antibiotic_injection", "Antibiotic injection given",
                         "child_illness_treatment", "binary")
    if _has(text, "antibiotic"):
        return _explicit("medicine_antibiotic_oral", "Antibiotic pill/syrup given",
                         "child_illness_treatment", "binary")
    if _has(text, "antimotility"):
        return _explicit("medicine_antimotility", "Antimotility medicine given",
                         "child_illness_treatment", "binary")
    if _has(text, "zinc"):
        return _explicit("medicine_zinc", "Zinc given", "child_illness_treatment", "binary")
    if _has(text, "paracetamol", "panadol", "acetaminophen", "efferalgan"):
        return _explicit("medicine_paracetamol", "Paracetamol/Panadol given",
                         "child_illness_treatment", "binary")
    if _exact(text, "aspirin") or (_has(text, "aspirin") and not _has(text, "chloro")):
        return _explicit("medicine_aspirin", "Aspirin given", "child_illness_treatment", "binary")
    if _has(text, "ibuprofen", "ibupropfen"):
        return _explicit("medicine_ibuprofen", "Ibuprofen given",
                         "child_illness_treatment", "binary")
    if _has(text, "intravenous", "iv fluid"):
        return _explicit("medicine_intravenous", "Intravenous fluid given",
                         "child_illness_treatment", "binary")
    if _has(text, "pain reliever", "analgesic", "pain killers"):
        return _explicit("medicine_analgesic", "Analgesic/pain reliever given",
                         "child_illness_treatment", "binary")
    if _has(text, "home remedy", "herbal medicine", "herbal remedy"):
        return _explicit("medicine_home_remedy", "Home remedy/herbal medicine given",
                         "child_illness_treatment", "binary")
    # "Medicine: X" / "Other treatment: X" / "Medication given: X" — structured medication label
    _med_ctx = _has(text, "medication given:", "medication provided", "medication prescribed",
                    "medicine given:", "medicine provided", "medicine prescribed",
                    "drug given", "drug prescribed", "treatment given",
                    "medicine:", "other treatment:", "treatment:")
    if _med_ctx or (_exact(text.split(":")[0].strip(), "medicine") and ":" in text):
        if _has(text, "n/a", "not applicable"):
            return _explicit("medicine_not_applicable", "Medication: not applicable",
                             "child_illness_treatment", "binary")
        if _has(text, "dk") or _exact(text.split(":")[-1].strip(), "dk"):
            return _explicit("medicine_dk", "Medication: don't know",
                             "child_illness_treatment", "binary")
        if _has(text, "other"):
            return _explicit("medicine_other", "Medication: other",
                             "child_illness_treatment", "binary")
        if _has(text, "artemisinin", "act", "coartem"):
            return _explicit("antimalarial_act", "Antimalarial: ACT",
                             "malaria_treatment", "binary")
        if _has(text, " sp", ":sp") or _exact(text.split(":")[-1].strip(), "sp"):
            return _explicit("antimalarial_sp_fansidar", "Antimalarial: SP/Fansidar",
                             "malaria_treatment", "binary")
        if _has(text, "paracetamol", "panadol", "efferalgan"):
            return _explicit("medicine_paracetamol", "Paracetamol/Panadol given",
                             "child_illness_treatment", "binary")
        if _has(text, "analgesic", "pain reliever"):
            return _explicit("medicine_analgesic", "Analgesic/pain reliever given",
                             "child_illness_treatment", "binary")
    if _has(text, "where did you receive") and _has(text, "antibiotic"):
        return _explicit("antibiotic_source", "Source where antibiotics obtained",
                         "child_illness_treatment", "categorical")
    if _has(text, "how much did you pay") and _has(text, "antibiotic"):
        return _explicit("antibiotic_cost", "Cost of antibiotics",
                         "child_illness_treatment", "continuous", confidence="medium")
    # Anything else given to treat diarrhoea
    if _has(text, "anything else given to treat", "anything else used to treat"):
        return _explicit("other_diarrhea_treatment", "Other treatment given for diarrhea",
                         "child_illness_treatment", "binary")
    # Fever management: undressing
    if _has(text, "child undressed to the minimum", "undressed to minimum",
            "undressed child"):
        return _explicit("fever_management_undress", "Fever management: child undressed",
                         "child_illness_treatment", "binary")
    # Danger signs
    _ds = _has(text, "symptom", "danger sign")
    if _ds and _has(text, "not able to drink", "cannot drink", "not able to breastfeed"):
        return _explicit("danger_sign_cannot_drink_or_breastfeed",
                         "Danger sign: cannot drink or breastfeed",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "child becomes sicker", "getting sicker", "child is getting sicker"):
        return _explicit("danger_sign_child_gets_sicker", "Danger sign: child gets sicker",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "develops fever", "develops a fever"):
        return _explicit("danger_sign_fever", "Danger sign: develops fever",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "faster breathing", "has faster breathing", "rapid breathing"):
        return _explicit("danger_sign_fast_breathing", "Danger sign: fast breathing",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "difficult breathing", "difficulty breathing"):
        return _explicit("danger_sign_difficult_breathing", "Danger sign: difficult breathing",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "blood in stool"):
        return _explicit("danger_sign_blood_in_stool", "Danger sign: blood in stool",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "drinking poorly", "drinks poorly", "drinks with difficulty"):
        return _explicit("danger_sign_drinks_poorly", "Danger sign: drinks poorly",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "diarrhea or vomit"):
        return _explicit("danger_sign_diarrhea_or_vomiting",
                         "Danger sign: diarrhea or vomiting",
                         "child_illness_danger_sign", "binary")
    if _ds and _has(text, "other"):
        return _explicit("danger_sign_other", "Danger sign: other",
                         "child_illness_danger_sign", "binary", confidence="medium")
    return None


def _malaria(text: str) -> CanonicalEntry | None:
    if (_has(text, "fever") and
            _has(text, "last 2 weeks", "last two weeks", "in the last two weeks")):
        return _explicit("fever_last_2_weeks", "Child had fever in last 2 weeks",
                         "child_illness", "binary")
    if _has(text, "sought care", "seen by", "seek advice", "advice or treatment",
            "seen by the services") and \
       (_has(text, "fever") or _exact(text, "was he/she seen by the services of a facility")):
        return _explicit("sought_care_for_fever", "Sought care for fever",
                         "malaria_care_seeking", "binary")
    if _has(text, "medication", "medicine", "treatment") and \
       _has(text, "fever", "malaria") and not _has(text, "before going", "before seeking"):
        return _explicit("received_antimalarial_treatment", "Received antimalarial treatment",
                         "malaria_treatment", "binary")
    if _has(text, "medication", "treatment") and \
       _has(text, "before going", "before seeking"):
        return _explicit("home_antimalarial_before_facility",
                         "Home antimalarial treatment before seeking care",
                         "malaria_treatment", "binary")
    # Specific antimalarials — ACT/combination before single agents
    if _has(text, "artesunate and amodiaquine", "as-aq", "asaq", "coartem",
            "artemether", "act"):
        return _explicit("antimalarial_act", "Antimalarial: ACT (combination)",
                         "malaria_treatment", "binary")
    if _has(text, "sp/fansidar", "sp fansidar", "sulfadoxine", "fansidar"):
        return _explicit("antimalarial_sp_fansidar", "Antimalarial: SP/Fansidar",
                         "malaria_treatment", "binary")
    if _has(text, "chloroquine"):
        return _explicit("antimalarial_chloroquine", "Antimalarial: Chloroquine",
                         "malaria_treatment", "binary")
    if _has(text, "amodiaquine"):
        return _explicit("antimalarial_amodiaquine", "Antimalarial: Amodiaquine",
                         "malaria_treatment", "binary")
    if _has(text, "quinine") and not _has(text, "chloroquine"):
        return _explicit("antimalarial_quinine", "Antimalarial: Quinine",
                         "malaria_treatment", "binary")
    if _has(text, "artesunate"):
        return _explicit("antimalarial_artesunate", "Antimalarial: Artesunate",
                         "malaria_treatment", "binary")
    if _has(text, "other antimalarial"):
        return _explicit("antimalarial_other", "Antimalarial: other",
                         "malaria_treatment", "binary")
    # Antipyretics in malaria context
    if _has(text, "paracetamol", "panadol", "acetaminophen", "efferalgan") and \
       _has(text, "medication", "prescribed", "given", "treatment"):
        return _explicit("medicine_paracetamol", "Paracetamol/Panadol given",
                         "child_illness_treatment", "binary")
    if _has(text, "ibuprofen", "ibupropfen") and \
       _has(text, "medication", "prescribed", "given", "treatment"):
        return _explicit("medicine_ibuprofen", "Ibuprofen given",
                         "child_illness_treatment", "binary")
    if _has(text, "aspirin") and \
       _has(text, "medication", "prescribed", "given", "treatment"):
        return _explicit("medicine_aspirin", "Aspirin given", "child_illness_treatment", "binary")
    if _has(text, "days") and _has(text, "start taking antimalarial", "to start antimalarial",
                                    "after fever started took anti-malarial",
                                    "after fever started took antimalarial"):
        return _explicit("days_to_start_antimalarial", "Days from illness to start antimalarial",
                         "malaria_treatment", "continuous")
    if _has(text, "where did you receive", "where did you get", "obtain") and \
       _has(text, "antimalarial", "anti-malarial", "anti malaria"):
        return _explicit("antimalarial_source", "Source where antimalarials obtained",
                         "malaria_treatment", "categorical")
    if _has(text, "how much did you pay") and \
       _has(text, "antimalarial", "anti-malarial", "anti malaria"):
        return _explicit("antimalarial_cost", "Cost of antimalarials",
                         "malaria_treatment", "continuous", confidence="medium")
    if _has(text, "months ago") and _has(text, "mosquito net", "net") and \
       _has(text, "obtained", "acquired", "got"):
        return _explicit("months_mosquito_net_owned", "Months since mosquito net obtained",
                         "malaria_prevention", "continuous")
    if _has(text, "brand") and _has(text, "mosquito net", "net"):
        return _explicit("mosquito_net_brand", "Brand of mosquito net",
                         "malaria_prevention", "categorical")
    if _has(text, "mosquito net observed", "net observed"):
        return _explicit("mosquito_net_observed", "Mosquito net observed by interviewer",
                         "malaria_prevention", "binary")
    # Mosquito net
    if _has(text, "slept under", "sleep under") and \
       _has(text, "mosquito net", "net") and _has(text, "last night"):
        return _explicit("child_slept_under_net_last_night",
                         "Child slept under mosquito net last night",
                         "malaria_prevention", "binary")
    if _has(text, "how long") and _has(text, "mosquito net", "net") and \
       _has(text, "owned", "had"):
        return _explicit("months_mosquito_net_owned", "Months household owned mosquito net",
                         "malaria_prevention", "continuous")
    if _has(text, "type of mosquito net", "type") and _has(text, "net"):
        return _explicit("mosquito_net_type", "Type of mosquito net",
                         "malaria_prevention", "categorical")
    if _has(text, "net") and _has(text, "treated") and \
       not _has(text, "since then", "soaked"):
        return _explicit("mosquito_net_was_treated_when_obtained",
                         "Mosquito net was treated when obtained",
                         "malaria_prevention", "binary")
    if _has(text, "soaked") and _has(text, "net", "liquid"):
        return _explicit("mosquito_net_retreated", "Mosquito net retreated since obtained",
                         "malaria_prevention", "binary")
    if _has(text, "time elapsed") and _has(text, "soaked", "net"):
        return _explicit("months_since_net_retreated", "Months since mosquito net was retreated",
                         "malaria_prevention", "continuous")
    return None


def _immunization_dates(text: str) -> CanonicalEntry | None:
    """Vaccination card date columns (day/month/year per vaccine)."""
    if not _has(text, "day", "month", "year"):
        return None
    if _has(text, "interview") or (
        _has(text, "birth") and not _has(text, "immunization", "vaccination", "bcg", "vaccine")
    ):
        return None

    component = "day" if "day" in text else ("month" if "month" in text else "year")

    for vax_key, terms in _VACCINE_DATE_MAP:
        if _has(text, *terms):
            label = vax_key.replace("_", " ").title()
            return _explicit(
                f"{vax_key}_vaccination_{component}",
                f"{label} vaccination {component}",
                "immunization_date",
                "date_component",
            )
    return None


def _immunization_recall(text: str) -> CanonicalEntry | None:
    """Recall-based immunization questions (not from card)."""
    if _has(text, "vaccination card for child", "child has vaccination card",
            "does the child have a vaccination card", "vaccination card") and \
       not _has(text, "besides", "including"):
        return _explicit("has_vaccination_card", "Child has vaccination card",
                         "immunization", "binary")
    if _has(text, "ever received any vaccinations", "child ever received any vaccinations",
            "ever received any vaccines", "received vaccinations including"):
        return _explicit("ever_received_any_vaccination", "Child ever received any vaccination",
                         "immunization", "binary")
    if _has(text, "received any other vaccinations", "any other vaccinations",
            "besides the vaccinations on the card"):
        return _explicit("received_other_vaccinations", "Child received other vaccinations",
                         "immunization", "binary")
    # BCG
    if _has(text, "ever given bcg", "ever had bcg", "received a bcg",
            "received bcg", "vaccination against bcg"):
        return _explicit("ever_bcg", "Child ever given BCG vaccination", "immunization", "binary")
    # Polio
    if _has(text, "ever given polio", "ever had polio", "received a vaccination against polio",
            "vaccination against polio", "received polio"):
        return _explicit("ever_polio", "Child ever given Polio vaccination", "immunization", "binary")
    if _has(text, "polio first given just after birth", "first polio given at birth",
            "polio first given", "first polio vaccine given", "when was the first") and \
       _has(text, "polio"):
        return _explicit("polio_first_dose_timing", "Polio first dose timing",
                         "immunization", "categorical")
    if _has(text, "times child given polio", "times given polio", "how many times") and \
       _has(text, "polio"):
        return _explicit("polio_doses_received", "Number of Polio doses received",
                         "immunization", "count")
    # DPT
    if _has(text, "ever given dpt", "ever given dtp", "child ever given dtp",
            "received a dtp-hepb-hib", "dtp-hepb-hib vaccination"):
        return _explicit("ever_dpt", "Child ever given DPT vaccination", "immunization", "binary")
    if _has(text, "times child given dpt", "times given dpt", "times given dtp",
            "how many times") and _has(text, "dpt", "dtp"):
        return _explicit("dpt_doses_received", "Number of DPT doses received",
                         "immunization", "count")
    # Hepatitis B
    if _has(text, "ever given hepatitis b", "ever given hepb", "ever received hepatitis b",
            "child ever given hepatitis", "hepatitis vaccination",
            "vaccination against hepatitis"):
        return _explicit("ever_hepb", "Child ever given Hepatitis B vaccination",
                         "immunization", "binary")
    if _has(text, "hepatitis b first given within 24", "hepb first given"):
        return _explicit("hepb_first_dose_timing",
                         "Hepatitis B first dose timing (within 24h vs later)",
                         "immunization", "categorical")
    if _has(text, "times child given hepatitis", "times given hepatitis",
            "how many times was the hepatitis") and _has(text, "hepatitis b", "hepb", "hepatitis"):
        return _explicit("hepb_doses_received", "Number of Hepatitis B doses received",
                         "immunization", "count")
    # Measles / MMR
    if _has(text, "ever given measles", "ever given mmr", "ever received measles",
            "vaccination against measles"):
        return _explicit("ever_measles_mmr", "Child ever given Measles/MMR vaccination",
                         "immunization", "binary")
    # Yellow Fever (also "ever been given yellow fever")
    if _has(text, "ever given yellow fever", "ever been given yellow fever",
            "ever received yellow fever", "vaccination against yellow fever",
            "has ever been given yellow fever"):
        return _explicit("ever_yellow_fever", "Child ever given Yellow Fever vaccination",
                         "immunization", "binary")
    # Vitamin A (immunization card context)
    if _has(text, "vitamin a dose within last 6 months", "given vitamin a dose within",
            "received vitamin a in last 6", "received vitamin a"):
        return _explicit("received_vitamin_a_last_6_months",
                         "Child received Vitamin A dose in last 6 months",
                         "immunization", "binary")
    if _has(text, "how many times vitamin a", "how many times") and _has(text, "vitamin a"):
        return _explicit("vitamin_a_doses_received", "Number of Vitamin A doses received",
                         "immunization", "count")
    if _has(text, "participated in") and \
       _has(text, "campaign", "national immunization day", "vaccination day",
            "routine activity"):
        return _explicit("participated_in_vaccination_campaign",
                         "Child participated in vaccination campaign",
                         "immunization", "binary")
    if _has(text, "selected for nutrition survey"):
        return _explicit("selected_for_nutrition_survey", "Selected for nutrition survey",
                         "survey_administration", "binary")
    return None


def _anthropometry(text: str) -> CanonicalEntry | None:
    if _has(text, "childs weight", "weight (kilograms)", "weight (kg)") or \
       _exact(text, "weight"):
        return _explicit("child_weight_kg", "Child weight in kilograms",
                         "anthropometry", "continuous")
    if _has(text, "childs length or height", "length or height", "height or length",
            "childs length", "childs height") or \
       _exact(text, "height") or _exact(text, "length"):
        return _explicit("child_height_or_length_cm", "Child height or length in cm",
                         "anthropometry", "continuous")
    # Standalone computed indicator names (without z-score/% qualifier — older datasets)
    if _exact(text, "height for age") or _exact(text, "height-for-age"):
        return _explicit("height_for_age_zscore", "Height-for-age indicator",
                         "anthropometry_zscore", "continuous", confidence="medium")
    if _exact(text, "weight for age") or _exact(text, "weight-for-age"):
        return _explicit("weight_for_age_zscore", "Weight-for-age indicator",
                         "anthropometry_zscore", "continuous", confidence="medium")
    if _exact(text, "weight for height") or _exact(text, "weight-for-height"):
        return _explicit("weight_for_height_zscore", "Weight-for-height indicator",
                         "anthropometry_zscore", "continuous", confidence="medium")
    if _has(text, "measured lying", "measured standing", "lying or standing",
            "lying down or standing", "measured supine"):
        return _explicit("measurement_position", "Child measurement position (lying/standing)",
                         "anthropometry", "categorical")
    if _has(text, "measurer") and _has(text, "id", "identification", "code", "number"):
        return _explicit("measurer_id", "Measurer identification",
                         "anthropometry", "identifier")
    if _has(text, "result of measurement", "measurement result", "measurement results"):
        return _explicit("measurement_result", "Result of anthropometric measurement",
                         "anthropometry", "categorical")
    # Z-scores
    if _has(text, "height for age z-score", "height-for-age z-score", "haz"):
        return _explicit("height_for_age_zscore", "Height-for-age Z-score",
                         "anthropometry_zscore", "continuous")
    if _has(text, "weight for age z-score", "weight-for-age z-score", "waz"):
        return _explicit("weight_for_age_zscore", "Weight-for-age Z-score",
                         "anthropometry_zscore", "continuous")
    if _has(text, "weight for height z-score", "weight-for-height z-score", "whz"):
        return _explicit("weight_for_height_zscore", "Weight-for-height Z-score",
                         "anthropometry_zscore", "continuous")
    # Percentiles
    if _has(text, "height for age percentile", "height-for-age percentile", "hap"):
        return _explicit("height_for_age_percentile", "Height-for-age percentile",
                         "anthropometry_percentile", "continuous")
    if _has(text, "weight for age percentile", "weight-for-age percentile", "wap"):
        return _explicit("weight_for_age_percentile", "Weight-for-age percentile",
                         "anthropometry_percentile", "continuous")
    if _has(text, "weight for height percentile", "weight-for-height percentile", "whp"):
        return _explicit("weight_for_height_percentile", "Weight-for-height percentile",
                         "anthropometry_percentile", "continuous")
    # Percent of median — "height-for-age % of median" / "percent of median" / etc.
    if _has(text, "height for age percent", "height-for-age percent", "ham") or \
       (_has(text, "height-for-age") and _has(text, "% of median", "percent of median",
                                               "percent of reference median")):
        return _explicit("height_for_age_pct_median", "Height-for-age % of reference median",
                         "anthropometry_pct_median", "continuous")
    if _has(text, "weight for age percent", "weight-for-age percent", "wam") or \
       (_has(text, "weight-for-age") and _has(text, "% of median", "percent of median",
                                               "percent of reference median")):
        return _explicit("weight_for_age_pct_median", "Weight-for-age % of reference median",
                         "anthropometry_pct_median", "continuous")
    if _has(text, "weight for height percent", "weight-for-height percent", "whm") or \
       (_has(text, "weight-for-height") and _has(text, "% of median", "percent of median",
                                                   "percent of reference median")):
        return _explicit("weight_for_height_pct_median", "Weight-for-height % of reference median",
                         "anthropometry_pct_median", "continuous")
    # BMI
    if _has(text, "body mass index z-score", "bmi z-score", "bmi-for-age z-score"):
        return _explicit("bmi_for_age_zscore", "BMI-for-age Z-score",
                         "anthropometry_zscore", "continuous")
    if _has(text, "body mass index who", "bmi who", "body mass index") and \
       not _has(text, "z-score", "flag"):
        return _explicit("bmi_value", "Body mass index",
                         "anthropometry", "continuous")
    # WHO anthropometry flags (WHO reference)
    if _has(text, "bmi flag", "body mass index flag"):
        return _explicit("bmi_flag", "BMI flag (WHO)",
                         "anthropometry", "binary")
    if _has(text, "height for age flag", "height-for-age flag"):
        return _explicit("height_for_age_flag", "Height-for-age flag (WHO)",
                         "anthropometry", "binary")
    if _has(text, "weight for age flag", "weight-for-age flag"):
        return _explicit("weight_for_age_flag", "Weight-for-age flag (WHO)",
                         "anthropometry", "binary")
    if _has(text, "weight for height flag", "weight-for-height flag",
            "weight for height age flag", "weight for height - age flag"):
        return _explicit("weight_for_height_flag", "Weight-for-height flag (WHO)",
                         "anthropometry", "binary")
    # Measurement date
    if _has(text, "day of measurement", "measurement day"):
        return _explicit("measurement_day", "Day of anthropometric measurement",
                         "anthropometry", "date_component")
    if _has(text, "month of measurement", "measurement month"):
        return _explicit("measurement_month", "Month of anthropometric measurement",
                         "anthropometry", "date_component")
    if _has(text, "year of measurement", "measurement year"):
        return _explicit("measurement_year", "Year of anthropometric measurement",
                         "anthropometry", "date_component")
    # Flags and hemoglobin
    if _has(text, "flag for anthropometric", "anthropometric flag",
            "anthropometric indicators") or _exact(text, "flag"):
        return _explicit("anthropometry_flag", "Flag for anthropometric indicators",
                         "anthropometry", "binary")
    if _has(text, "hemoglobin", "haemoglobin", "glomobine", "hb result"):
        return _explicit("hemoglobin_result", "Hemoglobin test result",
                         "anthropometry", "continuous")
    if _has(text, "checked blood", "blood check"):
        return _explicit("blood_checked", "Blood checked", "anthropometry", "binary")
    if _has(text, "filled in two lines", "two lines filled"):
        return _explicit("two_lines_filled", "Two lines filled in measurement",
                         "anthropometry", "binary")
    return None


def _water_sanitation(text: str) -> CanonicalEntry | None:
    if _has(text, "main source of drinking water", "source of drinking water",
            "main source of water drunk"):
        return _explicit("drinking_water_source", "Main source of drinking water",
                         "water_sanitation", "categorical")
    if _has(text, "main source of water used for other purposes", "other water source"):
        return _explicit("other_water_source", "Other water source",
                         "water_sanitation", "categorical")
    if _has(text, "time to get water", "time to fetch water", "average time to fetch"):
        return _explicit("time_to_fetch_water", "Time to fetch water and return",
                         "water_sanitation", "continuous")
    if _has(text, "distance") and _has(text, "water source", "fetch water"):
        return _explicit("distance_to_water_source", "Distance to water source",
                         "water_sanitation", "continuous")
    if _has(text, "who usually goes to the water", "person") and \
       _has(text, "fetching water", "fetch water", "goes to the water"):
        return _explicit("person_who_fetches_water", "Person who fetches water",
                         "water_sanitation", "categorical")
    if _has(text, "treat water", "treat the water", "treat drinking water"):
        return _explicit("treats_drinking_water", "Treats drinking water",
                         "water_sanitation", "binary")
    if _has(text, "boiling", "boil water") or _exact(text, "boil"):
        return _explicit("water_treatment_boil", "Water treatment: boiling",
                         "water_sanitation", "binary")
    if _has(text, "bleach", "chlorine"):
        return _explicit("water_treatment_bleach_chlorine", "Water treatment: bleach/chlorine",
                         "water_sanitation", "binary")
    if _has(text, "strain", "cloth", "cotton") and _has(text, "filter", "strain"):
        return _explicit("water_treatment_cloth_filter", "Water treatment: cloth filter",
                         "water_sanitation", "binary")
    if _has(text, "ceramic", "sand", "composite", "water filter") and _has(text, "filter"):
        return _explicit("water_treatment_filter", "Water treatment: ceramic/sand filter",
                         "water_sanitation", "binary")
    if _has(text, "solar disinfection"):
        return _explicit("water_treatment_solar", "Water treatment: solar disinfection",
                         "water_sanitation", "binary")
    if _has(text, "settle", "decant", "let it stand"):
        return _explicit("water_treatment_settle", "Water treatment: settle and decant",
                         "water_sanitation", "binary")
    if _has(text, "kind of toilet", "toilet facility", "type of toilet"):
        return _explicit("toilet_facility_type", "Type of toilet facility",
                         "water_sanitation", "categorical")
    if _has(text, "share") and _has(text, "toilet"):
        return _explicit("toilet_shared", "Toilet shared with other households",
                         "water_sanitation", "binary")
    if _has(text, "how many households") and _has(text, "toilet"):
        return _explicit("households_sharing_toilet", "Number of households sharing toilet",
                         "water_sanitation", "count")
    return None


def _household_assets(text: str) -> CanonicalEntry | None:
    _asset_map = [
        # Combined forms FIRST to avoid partial-match from shorter terms below
        ("refrigerator",         ("refrigerator",)),
        ("freezer",              ("freezer",)),
        ("electricity",          ("electricity",)),
        ("radio",                ("radio",)),
        ("television",           ("television", " tv")),
        ("computer",             ("computer",)),
        ("air_conditioner",      ("air conditioner", "air conditioning", "airconditioner")),
        ("mobile_phone",         ("mobile phone", "mobile telephone")),
        ("fixed_telephone_line", ("non-mobile phone", "landline phone", "landline telephone",
                                  "fixed telephone")),
        ("watch_or_clock",       ("watch", "clock")),
        ("bicycle",              ("bicycle",)),
        ("motorcycle",           ("motorcycle", "scooter")),
        ("animal_drawn_cart",    ("animal-drawn cart", "animal drawn cart")),
        ("car_or_truck",         ("car/truck", "car or truck", "car, truck")),
        ("motorboat",            ("motorboat", "motor boat")),
        ("generator",            ("generator",)),
        ("water_pump",           ("water pump",)),
        ("stove_or_cooker",      ("stove/cooker", "stove or cooker", "cooking stove")),
    ]
    # Must be a short label (≤6 words) to avoid grabbing longer sentences
    if len(text.split()) <= 6:
        for asset_key, terms in _asset_map:
            if _has(text, *terms):
                return _explicit(f"household_has_{asset_key}",
                                 f"Household has {asset_key.replace('_', ' ')}",
                                 "household_asset", "binary")
    return None


def _housing(text: str) -> CanonicalEntry | None:
    if _has(text, "main material of floor", "floor material"):
        return _explicit("floor_material", "Main material of floor", "housing", "categorical")
    if _has(text, "main material of roof", "roof material"):
        return _explicit("roof_material", "Main material of roof", "housing", "categorical")
    if _has(text, "main material of wall", "wall material"):
        return _explicit("wall_material", "Main material of wall", "housing", "categorical")
    if _has(text, "type of fuel", "fuel") and _has(text, "cooking"):
        return _explicit("cooking_fuel_type", "Type of cooking fuel", "housing", "categorical")
    if _has(text, "open fire", "open stove") and _has(text, "cook"):
        return _explicit("cooking_on_open_fire", "Cooks on open fire or stove",
                         "housing", "categorical")
    if _has(text, "chimney", "hood") and _has(text, "fire", "stove"):
        return _explicit("cooking_chimney_or_hood", "Cooking fire/stove has chimney or hood",
                         "housing", "binary")
    if _has(text, "place where you cook", "cooking location", "location") and _has(text, "cook"):
        return _explicit("cooking_location", "Location where cooking takes place",
                         "housing", "categorical")
    if _has(text, "number of rooms") and _has(text, "sleeping"):
        return _explicit("rooms_for_sleeping", "Number of rooms used for sleeping",
                         "housing", "count")
    if _has(text, "floor area", "surface area of floor"):
        return _explicit("floor_area", "Floor area", "housing", "continuous")
    if _has(text, "owns land", "own land", "member of your household own land"):
        return _explicit("household_owns_land", "Household member owns land",
                         "housing", "binary")
    if _has(text, "hectares") and _has(text, "land", "agricultural"):
        return _explicit("hectares_of_agricultural_land", "Hectares of agricultural land",
                         "housing", "continuous")
    if _exact(text, "livestock") or _has(text, "own livestock", "owns livestock",
                                          "any livestock"):
        return _explicit("household_owns_livestock", "Household owns livestock",
                         "housing", "binary")
    # Livestock counts
    if _has(text, "number of") and _has(text, "cow", "bull", "cattle", "ox"):
        return _explicit("number_of_cattle", "Number of cattle/cows/bulls",
                         "livestock", "count")
    if _has(text, "number of") and _has(text, "horse", "donkey", "mule"):
        return _explicit("number_of_equines", "Number of horses/donkeys/mules",
                         "livestock", "count")
    if _has(text, "number of") and _has(text, "goat"):
        return _explicit("number_of_goats", "Number of goats", "livestock", "count")
    if _has(text, "number of") and _has(text, "sheep"):
        return _explicit("number_of_sheep", "Number of sheep", "livestock", "count")
    if _has(text, "number of") and _has(text, "pig", "pigs", "swine"):
        return _explicit("number_of_pigs", "Number of pigs", "livestock", "count")
    if _has(text, "number of") and _has(text, "chicken", "poultry", "bird"):
        return _explicit("number_of_poultry", "Number of poultry/chickens",
                         "livestock", "count")
    if _has(text, "title", "deed") and _has(text, "household", "property"):
        return _explicit("household_has_property_title", "Household has property title/deed",
                         "housing", "binary")
    if _has(text, "owner") and _has(text, "household", "dwelling"):
        return _explicit("household_is_owner", "Household is owner of dwelling",
                         "housing", "binary")
    if _has(text, "safe from being evicted", "fear of eviction"):
        return _explicit("feels_safe_from_eviction", "Feels safe from eviction",
                         "housing", "binary")
    if _has(text, "been evicted"):
        return _explicit("has_been_evicted", "Has been evicted", "housing", "binary")
    # Property tenure documents
    if _has(text, "type of property document") or \
       _has(text, "property tax", "sale certificate", "electricity/water/telephone bill",
            "informal agreement", "oral agreement", "occupation with owner",
            "occupation without owner"):
        return _explicit("property_document_type", "Type of property tenure document",
                         "housing_tenure", "categorical")
    # Housing quality indicators (HC15)
    if _has(text, "flimsy door", "flimsy") and _has(text, "door"):
        return _explicit("housing_flimsy_door", "Housing: flimsy door",
                         "housing_quality", "binary")
    if _has(text, "cracks", "opening in walls"):
        return _explicit("housing_cracks_in_walls", "Housing: cracks in walls",
                         "housing_quality", "binary")
    if _has(text, "no window") or (_has(text, "window") and _has(text, "broken glass")):
        return _explicit("housing_inadequate_window", "Housing: no or broken window",
                         "housing_quality", "binary")
    if _has(text, "holes in the roof", "incomplete roof"):
        return _explicit("housing_inadequate_roof", "Housing: holes or incomplete roof",
                         "housing_quality", "binary")
    # Hazard location (HC15h)
    if _has(text, "landslide", "flood", "river bank", "steep hill", "garbage pile",
            "industrial pollution", "railway", "power plant", "overpass",
            "electrical cable", "voltage cable", "narrow passage", "cables near dwelling",
            "cables connecting the neighborhood"):
        return _explicit("housing_hazard_location", "Housing in hazard-prone area",
                         "housing_quality", "binary")
    return None


def _survey_metadata(text: str) -> CanonicalEntry | None:
    # Consent and interview control (MICS5/6)
    if _exact(text, "consent"):
        return _explicit("consent", "Respondent consented to interview",
                         "survey_administration", "binary")
    if _has(text, "first interview") and _has(text, "respondent", "this"):
        return _explicit("is_first_interview", "First interview with this respondent",
                         "survey_administration", "binary")
    if _exact(text, "finish") or _exact(text, "finished"):
        return _explicit("interview_finish", "Interview finished",
                         "survey_administration", "binary")
    # Language / interpreter
    if _has(text, "language of the questionnaire", "language of the interview",
            "interview language", "language of interview"):
        return _explicit("interview_language", "Language of interview/questionnaire",
                         "survey_administration", "categorical")
    if _has(text, "native language of the respondent", "respondents native language"):
        return _explicit("respondent_native_language", "Respondent native language",
                         "survey_administration", "categorical")
    if _has(text, "translator used", "use of interpreter", "interpreter used",
            "interpretation used"):
        return _explicit("translator_used", "Translator used",
                         "survey_administration", "binary")
    # Number of visits / revisits
    if _has(text, "number of visits") or _exact(text, "visits"):
        return _explicit("number_of_visits", "Number of visits",
                         "survey_administration", "count")
    # Personnel identifiers
    if _has(text, "interviewer name") or \
       (_has(text, "interviewer") and not _has(text, "household")):
        return _explicit("interviewer_number", "Interviewer number",
                         "survey_administration", "identifier")
    if _has(text, "household interviewer"):
        return _explicit("household_interviewer", "Household interviewer",
                         "survey_administration", "identifier")
    if _has(text, "interviewer number", "interviewer code", "interviewer no"):
        return _explicit("interviewer_number", "Interviewer number",
                         "survey_administration", "identifier")
    if _has(text, "supervisor number", "supervisor code", "supervisors number",
            "supervisor's number"):
        return _explicit("supervisor_number", "Supervisor number",
                         "survey_administration", "identifier")
    if _has(text, "field supervisor"):
        return _explicit("supervisor_number", "Field supervisor number",
                         "survey_administration", "identifier")
    if _has(text, "office control") or \
       (_has(text, "controller") and _has(text, "code", "number")):
        return _explicit("supervisor_number", "Supervisor/controller number",
                         "survey_administration", "identifier", confidence="medium")
    if _has(text, "team leader"):
        return _explicit("team_leader_number", "Team leader number",
                         "survey_administration", "identifier")
    if _has(text, "data entry") and _has(text, "clerk", "number", "operator", "code",
                                         "agent", "by"):
        return _explicit("data_entry_clerk", "Data entry clerk",
                         "survey_administration", "identifier")
    if _has(text, "main data digitizer", "digitizer"):
        return _explicit("data_entry_clerk", "Data entry clerk (digitizer)",
                         "survey_administration", "identifier")
    if _has(text, "reviewer") and not _has(text, "needs_review"):
        return _explicit("reviewer", "Reviewer", "survey_administration", "identifier")
    if _has(text, "editor"):
        return _explicit("editor", "Editor", "survey_administration", "identifier")
    if _has(text, "field editor"):
        return _explicit("field_editor", "Field editor",
                         "survey_administration", "identifier")
    if _has(text, "encoder") or _has(text, "digitizer"):
        return _explicit("data_entry_clerk", "Data entry clerk",
                         "survey_administration", "identifier")
    # Geography
    if _exact(text, "area") or _exact(text, "milieu") or _exact(text, "environment"):
        return _explicit("area", "Area (urban/rural)", "geography", "categorical")
    if _exact(text, "region") or _has(text, "region number"):
        return _explicit("region", "Region", "geography", "categorical")
    if _has(text, "province"):
        return _explicit("province", "Province", "geography", "categorical")
    if _exact(text, "district") or _has(text, "district/sub-district"):
        return _explicit("district", "District", "geography", "categorical")
    if _exact(text, "department") or _has(text, "department number"):
        return _explicit("province", "Department/Province", "geography", "categorical")
    if _exact(text, "prefecture"):
        return _explicit("province", "Prefecture", "geography", "categorical")
    if _has(text, "wilaya") or _has(text, "moughataa") or _has(text, "commune"):
        return _explicit("district", "Administrative unit (commune/wilaya)",
                         "geography", "categorical")
    if _has(text, "ward", "village") and not _has(text, "head of"):
        return _explicit("village_or_ward", "Village/ward",
                         "geography", "categorical")
    if _has(text, "building number") or _has(text, "structure"):
        return _explicit("building_number", "Building number",
                         "household_identifier", "identifier")
    # Interview result
    if _has(text, "result", "outcome") and \
       _has(text, "interview", "children under 5", "child", "survey for child"):
        return _explicit("child_interview_result", "Result of child interview",
                         "survey_administration", "categorical")
    if _has(text, "result", "outcome") and _has(text, "household interview", "hh interview"):
        return _explicit("household_interview_result", "Result of household interview",
                         "survey_administration", "categorical")
    # Household/survey composition counts
    if _has(text, "number of household members"):
        return _explicit("number_of_household_members", "Number of household members",
                         "household_composition", "count")
    if _has(text, "total eligible women", "number of eligible women"):
        return _explicit("total_eligible_women", "Total eligible women",
                         "survey_administration", "count")
    if _has(text, "womens questionnaires completed", "women interviews completed",
            "women questionnaires completed", "number of women"):
        return _explicit("number_of_women_questionnaires_completed",
                         "Number of women questionnaires completed",
                         "survey_administration", "count")
    if _has(text, "total children under 5", "children under 5"):
        return _explicit("number_of_children_under_5", "Number of children under 5",
                         "household_composition", "count")
    if _has(text, "child interviews completed", "child questionnaires completed",
            "children under 5 questionnaires completed"):
        return _explicit("number_of_child_questionnaires_completed",
                         "Number of child questionnaires completed",
                         "survey_administration", "count")
    if _has(text, "respondent") and _has(text, "questionnaire", "line number"):
        return _explicit("respondent_line_number", "Respondent line number",
                         "survey_administration", "identifier")
    if _has(text, "hh selected for") or _has(text, "selected for anaemia"):
        return _explicit("selected_for_nutrition_survey", "Selected for nutrition/anaemia survey",
                         "survey_administration", "binary")
    if _has(text, "household selected for man", "selected for man's interview",
            "selected for male", "household selected for male"):
        return _explicit("selected_for_male_interview", "Household selected for male interview",
                         "survey_administration", "binary")
    if _has(text, "total eligible men", "number of eligible men"):
        return _explicit("total_eligible_men", "Total eligible men",
                         "survey_administration", "count")
    if _has(text, "health insurance") and _has(text, "type", "coverage", "has"):
        return _explicit("health_insurance_type", "Type of health insurance",
                         "household_member_background", "categorical")
    if _has(text, "universal child allowance", "child allowance"):
        return _explicit("receives_child_allowance", "Receives child allowance",
                         "household_member_background", "binary", confidence="medium")
    if _has(text, "country of birth"):
        return _explicit("country_of_birth", "Country of birth",
                         "household_member_background", "categorical")
    if _has(text, "name") and not _has(text, "country", "region", "district",
                                        "village", "commune"):
        return _explicit("respondent_name", "Name of respondent",
                         "survey_administration", "identifier", confidence="medium")
    return None


def _derived_background(text: str) -> CanonicalEntry | None:
    if _has(text, "relative children weight", "sample weight", "children weight",
            "weighting coefficient child"):
        return _explicit("child_sample_weight", "Child sample weight",
                         "survey_design", "weight")
    if _exact(text, "wealth index score") or _has(text, "wealth score",
                                                   "score for economic",
                                                   "combined wealth score"):
        return _explicit("wealth_score", "Wealth index score",
                         "household_ses", "continuous")
    if _has(text, "urban wealth index quintile"):
        return _explicit("urban_wealth_index_quintile", "Urban wealth index quintile",
                         "household_ses", "ordinal")
    if _has(text, "rural wealth index quintile"):
        return _explicit("rural_wealth_index_quintile", "Rural wealth index quintile",
                         "household_ses", "ordinal")
    if _has(text, "wealth index quintile") and not _has(text, "urban", "rural"):
        return _explicit("wealth_index_quintile", "Wealth index quintile",
                         "household_ses", "ordinal")
    if _exact(text, "mothers education") or \
       _has(text, "mother education", "education of the mother",
            "education level of mother", "mothers education level"):
        return _explicit("mother_education", "Mothers education level",
                         "household_member_background", "categorical")
    if _has(text, "ethnicity of household head", "ethnicity of the head",
            "ethnicity of head"):
        return _explicit("ethnicity_of_household_head", "Ethnicity of household head",
                         "household_head_demographics", "categorical")
    if _has(text, "religion of household head", "religion of the head",
            "religion of head") or _exact(text, "religion"):
        return _explicit("religion_of_household_head", "Religion of household head",
                         "household_head_demographics", "categorical")
    if _has(text, "age of mother", "mothers age", "age of the mother"):
        return _explicit("age_of_mother", "Age of mother/caretaker",
                         "household_member_background", "continuous")
    if _has(text, "mother in household", "mother lives in household",
            "mmenage", "mother in hh"):
        return _explicit("mother_lives_in_household", "Mother lives in household",
                         "household_member_background", "binary")
    if _has(text, "relationship to the head", "relationship to head"):
        return _explicit("relationship_to_head", "Relationship to head of household",
                         "household_member_background", "categorical")
    if _has(text, "highest level of education attended",
            "highest level of school attended",
            "highest level of education attained",
            "highest education level"):
        return _explicit("highest_education_level", "Highest level of education attended",
                         "education", "categorical")
    if _has(text, "highest grade completed"):
        return _explicit("highest_grade_completed", "Highest grade completed",
                         "education", "ordinal")
    if _has(text, "highest grade attended at that level", "highest grade attended"):
        return _explicit("highest_grade_attended", "Highest grade attended at level",
                         "education", "ordinal")
    if _has(text, "years of schooling") and _has(text, "would like", "aspiration"):
        return _explicit("education_aspiration", "Education aspiration for child",
                         "education", "continuous", confidence="medium")
    if _has(text, "residential environment") or _exact(text, "milieu", "environment"):
        return _explicit("area", "Area", "geography", "categorical", confidence="medium")
    return None


def _child_discipline(text: str) -> CanonicalEntry | None:
    """Child discipline module (MICS5/6 CD module)."""
    # Check context markers first
    _cd = _has(text, "shook child", "spanked", "slapped child", "hit child",
               "beat child", "shouted", "yelled", "screamed at child",
               "took away privileges", "explained why behaviour",
               "gave child something else to do", "kept child from doing",
               "physically punished to be brought up",
               "called child stupid", "named child badly",
               "left child alone", "locked child in a room",
               "shook", "slap", "hit or slap", "beat")
    if not _cd:
        return None
    if _has(text, "shook child", "shook"):
        return _explicit("discipline_shake", "Discipline: shook child",
                         "child_discipline", "binary")
    if _has(text, "shouted", "yelled", "screamed"):
        return _explicit("discipline_shout", "Discipline: shouted/yelled at child",
                         "child_discipline", "binary")
    if _has(text, "took away privileges", "taking away privileges"):
        return _explicit("discipline_took_privileges", "Discipline: took away privileges",
                         "child_discipline", "binary")
    if _has(text, "explained why behaviour", "explained why behavior",
            "explaining why"):
        return _explicit("discipline_explain", "Discipline: explained why behaviour wrong",
                         "child_discipline", "binary")
    if _has(text, "gave child something else to do", "gave something else to do"):
        return _explicit("discipline_redirect", "Discipline: redirected child",
                         "child_discipline", "binary")
    if _has(text, "hit or slapped child on the face", "slapped on the face"):
        return _explicit("discipline_slap_face", "Discipline: slapped child on face",
                         "child_discipline", "binary")
    if _has(text, "hit or slapped child on the hand", "slapped on the hand",
            "slapped on the arm"):
        return _explicit("discipline_slap_hand", "Discipline: slapped child on hand/arm",
                         "child_discipline", "binary")
    if _has(text, "spanked", "slapped child on bottom", "hit child on the bottom",
            "hit on the bottom"):
        return _explicit("discipline_spank", "Discipline: spanked child",
                         "child_discipline", "binary")
    if _has(text, "beat child up", "beat child"):
        return _explicit("discipline_beat", "Discipline: beat child",
                         "child_discipline", "binary")
    if _has(text, "hit child on the bottom or elsewhere with belt",
            "hit with belt", "hit with brush", "hit with stick"):
        return _explicit("discipline_hit_object", "Discipline: hit child with object",
                         "child_discipline", "binary")
    if _has(text, "physically punished to be brought up"):
        return _explicit("discipline_belief_physical_punishment",
                         "Belief: child needs physical punishment",
                         "child_discipline", "binary")
    if _has(text, "called child stupid", "names", "named child badly",
            "called names", "name-calling"):
        return _explicit("discipline_psychological_aggression",
                         "Discipline: psychological aggression",
                         "child_discipline", "binary")
    return _explicit("discipline_other", "Discipline method: other",
                     "child_discipline", "binary", confidence="medium")


def _child_functioning(text: str) -> CanonicalEntry | None:
    """Child functioning/disability module (MICS6 CF module)."""
    _cf = _has(text, "difficulty seeing", "difficulty hearing",
               "difficulty walking", "difficulty learning",
               "difficulty playing", "difficulty communicating",
               "without using equipment", "when using equipment",
               "hearing aid", "vision problem",
               "compared with children of the same age",
               "requires care")
    if not _cf:
        return None
    if _has(text, "difficulty seeing", "vision problem"):
        return _explicit("cf_difficulty_seeing", "Child functioning: difficulty seeing",
                         "child_functioning", "categorical")
    if _has(text, "difficulty hearing"):
        return _explicit("cf_difficulty_hearing", "Child functioning: difficulty hearing",
                         "child_functioning", "categorical")
    if _has(text, "hearing aid"):
        return _explicit("cf_uses_hearing_aid", "Child uses hearing aid",
                         "child_functioning", "binary")
    if _has(text, "difficulty walking") or \
       (_has(text, "walking") and _has(text, "without using equipment",
                                        "when using equipment", "compared with")):
        return _explicit("cf_difficulty_walking", "Child functioning: difficulty walking",
                         "child_functioning", "categorical")
    if _has(text, "difficulty learning", "learning things") and \
       _has(text, "compared with"):
        return _explicit("cf_difficulty_learning", "Child functioning: difficulty learning",
                         "child_functioning", "categorical")
    if _has(text, "difficulty playing") and _has(text, "compared with"):
        return _explicit("cf_difficulty_playing", "Child functioning: difficulty playing",
                         "child_functioning", "categorical")
    if _has(text, "difficulty communicating"):
        return _explicit("cf_difficulty_communicating",
                         "Child functioning: difficulty communicating",
                         "child_functioning", "categorical")
    if _has(text, "requires care") and _has(text, "other"):
        return _explicit("cf_requires_care_other", "Child requires care: other type",
                         "child_functioning", "categorical")
    if _has(text, "requires care"):
        return _explicit("cf_requires_care", "Child requires care",
                         "child_functioning", "categorical")
    return None
