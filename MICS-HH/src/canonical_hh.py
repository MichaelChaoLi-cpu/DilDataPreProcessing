"""Rule-based canonicalization helpers for MICS HH column labels.

The rules here are intentionally conservative:
- compound assets stay compound;
- deterministic date variables may emit multiple derived canonical variables;
- qualifiers such as automatic/semi-automatic washing machine are normalized
  to the same household asset entity.
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
    ignored_qualifiers: tuple[str, ...] = ()
    confidence: str = "medium"
    needs_review: bool = False
    notes: tuple[str, ...] = ()

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
            "ignored_qualifiers": list(self.ignored_qualifiers) if self.ignored_qualifiers else None,
            "needs_review": self.needs_review if self.needs_review else None,
            "notes": list(self.notes) if self.notes else None,
        }
        for key, value in optional.items():
            if value is not None:
                data[key] = value
        return data


_ASSET_TERMS: list[tuple[str, str]] = [
    ("automatic washing machine", "washing_machine"),
    ("semi automatic washing machine", "washing_machine"),
    ("semi-automatic washing machine", "washing_machine"),
    ("washing machine", "washing_machine"),
    ("clothes washing machine", "washing_machine"),
    ("drying machine", "clothes_dryer"),
    ("clothes dryer", "clothes_dryer"),
    ("dryer", "clothes_dryer"),
    ("dish washing machine", "dishwasher"),
    ("dishwashing machine", "dishwasher"),
    ("dish washer", "dishwasher"),
    ("dishwasher", "dishwasher"),
    ("fixed telephone line", "fixed_telephone_line"),
    ("landline telephone", "fixed_telephone_line"),
    ("landline phone", "fixed_telephone_line"),
    ("non-mobile phone", "fixed_telephone_line"),
    ("non mobile phone", "fixed_telephone_line"),
    ("mobile telephone", "mobile_phone"),
    ("mobile phone", "mobile_phone"),
    ("smartphone", "smartphone"),
    ("smart phone", "smartphone"),
    ("desktop pc", "desktop_computer"),
    ("desktop computer", "desktop_computer"),
    ("laptop computer", "laptop_computer"),
    ("laptop", "laptop_computer"),
    ("tablet", "tablet"),
    ("computer", "computer"),
    ("refrigerator", "refrigerator"),
    ("fridge", "refrigerator"),
    ("deep freezer", "freezer"),
    ("standalone freezer", "freezer"),
    ("freezer", "freezer"),
    ("television", "television"),
    ("smart/flat screen tv", "television"),
    ("flat screen tv", "television"),
    ("crt tv", "television"),
    ("tv", "television"),
    ("radio", "radio"),
    ("electricity", "electricity"),
    ("air conditioner", "air_conditioner"),
    ("air conditioning", "air_conditioner"),
    ("airconditioner", "air_conditioner"),
    ("electric fan", "electric_fan"),
    ("fan", "fan"),
    ("microwave oven", "microwave_oven"),
    ("microwave", "microwave_oven"),
    ("water heater", "water_heater"),
    ("boiler", "water_heater"),
    ("electric kettle", "electric_kettle"),
    ("rice cooker", "rice_cooker"),
    ("sewing machine", "sewing_machine"),
    ("mechanical sewing machine", "sewing_machine"),
    ("electric sewing machine", "sewing_machine"),
    ("vacuum cleaner", "vacuum_cleaner"),
    ("electric iron", "iron"),
    ("cloth iron", "iron"),
    ("iron", "iron"),
    ("gas stove", "gas_stove"),
    ("kerosene stove", "kerosene_stove"),
    ("electric stove", "electric_stove"),
    ("cooking range", "stove"),
    ("stove", "stove"),
    ("solar panel", "solar_panel"),
    ("generator", "generator"),
    ("water filter", "water_filter"),
    ("water dispenser", "water_dispenser"),
    ("water pump", "water_pump"),
    ("electric water pump", "water_pump"),
    ("dvd/cd player", "dvd_cd_player"),
    ("cd/dvd player", "dvd_cd_player"),
    ("dvd player", "dvd_player"),
    ("cd player", "cd_player"),
    ("vcr", "vcr"),
    ("cable tv", "cable_tv"),
    ("satellite dish", "satellite_dish"),
    ("digital dish", "satellite_dish"),
    ("bed", "bed"),
    ("chair", "chair"),
    ("table", "table"),
    ("dining table", "dining_table"),
    ("sofa", "sofa"),
    ("cupboard", "cupboard"),
    ("closet", "closet"),
    ("wardrobe", "wardrobe"),
    ("watch", "watch"),
    ("bicycle", "bicycle"),
    ("motorcycle", "motorcycle"),
    ("motor scooter", "motorcycle"),
    ("scooter", "motorcycle"),
    ("car", "car_or_truck"),
    ("truck", "car_or_truck"),
    ("boat with motor", "boat_with_motor"),
    ("motorboat", "boat_with_motor"),
    ("motor boat", "boat_with_motor"),
    ("tractor", "tractor"),
    ("clock", "clock"),
]

_ANIMAL_TERMS: list[tuple[str, str]] = [
    ("horses", "horses_donkeys_mules"),
    ("donkeys", "horses_donkeys_mules"),
    ("mules", "horses_donkeys_mules"),
    ("goats", "goats"),
    ("sheep", "sheep"),
    ("pigs", "pigs"),
    ("cows", "cattle"),
    ("bulls", "cattle"),
    ("cattle", "cattle"),
    ("chickens", "chickens"),
    ("ducks", "ducks"),
    ("camels", "camels"),
]

_COMPOUND_EXCEPTIONS = {
    "cd/dvd player": "dvd_cd_player",
    "dvd/cd player": "dvd_cd_player",
    "cd/dvd/dvx player": "dvd_cd_player",
    "3g/4g": None,
}


def canonicalize_label(label: str) -> list[CanonicalEntry]:
    text = _clean_label(label)
    if not text:
        return [_fallback(label)]

    date_entries = _canonicalize_date_or_time(text)
    if date_entries:
        return date_entries

    meta_entry = _canonicalize_metadata(text)
    if meta_entry:
        return [meta_entry]

    high_frequency_entry = _canonicalize_high_frequency_vars(text)
    if high_frequency_entry:
        return [high_frequency_entry]

    reason_entry = _canonicalize_reason(text)
    if reason_entry:
        return [reason_entry]

    affordability_entry = _canonicalize_affordability(text)
    if affordability_entry:
        return [affordability_entry]

    count_entry = _canonicalize_count(text)
    if count_entry:
        return [count_entry]

    possession_entry = _canonicalize_possession(text)
    if possession_entry:
        return [possession_entry]

    return [_fallback(label)]


def _clean_label(label: str) -> str:
    text = str(label or "").strip()
    text = _VAR_PREFIX_RE.sub("", text)
    text = text.replace("_", " ")
    text = text.replace("?", "")
    text = text.replace("’", "'")
    text = text.replace("&", " and ")
    text = text.replace(" / ", "/")
    text = text.replace(" - ", " ")
    text = text.lower()
    text = _SPACE_RE.sub(" ", text).strip(" :;,.")
    return text


def _slug(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def _canonicalize_date_or_time(text: str) -> list[CanonicalEntry] | None:
    if _has_any(text, ("date of interview", "interview date")) and not _has_any(text, ("birth", "built")):
        return [
            _date_component("interview", "year", "derived", "extract_year", "Interview year"),
            _date_component("interview", "month", "derived", "extract_month", "Interview month"),
            _date_component("interview", "day", "derived", "extract_day", "Interview day"),
        ]

    if _has_any(text, ("year of interview", "interview year", "survey year")):
        return [_date_component("interview", "year", "explicit", None, "Interview year")]
    if _has_any(text, ("month of interview", "interview month", "survey month")):
        return [_date_component("interview", "month", "explicit", None, "Interview month")]
    if _has_any(text, ("day of interview", "interview day")):
        return [_date_component("interview", "day", "explicit", None, "Interview day")]

    event = None
    if _has_any(text, ("start of interview", "interview start", "start time")):
        event = "interview_start"
    elif _has_any(text, ("end of interview", "interview end", "end time")):
        event = "interview_end"
    if event:
        if _has_any(text, ("hour", "hours")):
            return [_time_component(event, "hour")]
        if _has_any(text, ("minute", "minutes", "min")):
            return [_time_component(event, "minute")]
        if _has_any(text, ("time", "timestamp")):
            return [
                _time_component(event, "hour", "derived", "extract_hour"),
                _time_component(event, "minute", "derived", "extract_minute"),
            ]
    return None


def _date_component(event: str, component: str, source_kind: str, derivation: str | None, text: str) -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname=f"{event}_{component}",
        canonical_text=text,
        measure_type="interview_date_component",
        event=event,
        component=component,
        response_type="date_component",
        source_kind=source_kind,
        derivation=derivation,
        confidence="high",
    )


def _time_component(
    event: str,
    component: str,
    source_kind: str = "explicit",
    derivation: str | None = None,
) -> CanonicalEntry:
    label = f"{event.replace('_', ' ').title()} {component}"
    return CanonicalEntry(
        canonical_varname=f"{event}_{component}",
        canonical_text=label,
        measure_type="interview_time_component",
        event=event,
        component=component,
        response_type="time_component",
        source_kind=source_kind,
        derivation=derivation,
        confidence="high",
    )


def _canonicalize_metadata(text: str) -> CanonicalEntry | None:
    patterns = [
        (("cluster number", "cluster no", "cluster"), "cluster_number", "Cluster number", "household_identifier"),
        (("household number", "household no"), "household_number", "Household number", "household_identifier"),
        (("interviewer number", "interviewer no"), "interviewer_number", "Interviewer number", "interview_metadata"),
        (("supervisor number", "supervisor no"), "supervisor_number", "Supervisor number", "interview_metadata"),
        (("result of hh interview", "result of household interview", "household interview result", "household interview outcome", "interview outcome"), "household_interview_result", "Household interview result", "questionnaire_result"),
        (("sample weight household", "sample weight - household", "household sample weight"), "household_sample_weight", "Household sample weight", "sample_weight"),
        (("area",), "area", "Area", "geography"),
        (("region",), "region", "Region", "geography"),
        (("district",), "district", "District", "geography"),
        (("stratum",), "stratum", "Stratum", "geography"),
    ]
    for needles, varname, label, measure_type in patterns:
        if text in needles or _has_any(text, needles):
            return CanonicalEntry(
                canonical_varname=varname,
                canonical_text=label,
                measure_type=measure_type,
                response_type="identifier" if measure_type.endswith("identifier") else None,
                confidence="high",
            )
    return None


def _entry(
    varname: str,
    canonical_text: str,
    measure_type: str,
    *,
    relation: str | None = None,
    response_type: str | None = None,
    entities: tuple[str, ...] = (),
    event: str | None = None,
    component: str | None = None,
) -> CanonicalEntry:
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=canonical_text,
        measure_type=measure_type,
        relation=relation,
        response_type=response_type,
        entities=entities,
        event=event,
        component=component,
        confidence="high",
    )


def _canonicalize_high_frequency_vars(text: str) -> CanonicalEntry | None:
    """Rules promoted from high-frequency unmapped clusters."""
    count_patterns = [
        (("children under age 5", "children under 5", "children aged under 5", "children under five"), "number_of_children_under_5", "Number of children under age 5", ("children_under_5",)),
        (("women 15-49", "women 15 - 49", "women 15 49", "women aged 15-49", "women aged 15 - 49", "women aged 15 49", "eligible women"), "number_of_women_15_49", "Number of women aged 15-49", ("women_15_49",)),
        (("men 15-49", "men 15 - 49", "men 15 49", "men aged 15-49", "men aged 15 - 49", "men aged 15 49"), "number_of_men_15_49", "Number of men aged 15-49", ("men_15_49",)),
        (("under - 5 questionnaires completed", "under 5 questionnaires completed", "children under 5 questionnaires completed", "questionnaires for under 5", "questionnaires for children under 5"), "number_of_under_5_questionnaires_completed", "Number of under-5 questionnaires completed", ("under_5_questionnaires",)),
        (("women questionnaires completed", "women's questionnaires completed", "woman' questionnaires completed", "woman's questionnaires completed", "completed women's questionnaires", "completed women questionnaires"), "number_of_women_questionnaires_completed", "Number of women's questionnaires completed", ("women_questionnaires",)),
        (("man' questionnaires completed", "men questionnaires completed", "men's questionnaires completed", "man's questionnaires completed", "completed men's questionnaires", "completed men questionnaires"), "number_of_men_questionnaires_completed", "Number of men's questionnaires completed", ("men_questionnaires",)),
        (("cf questionnaires completed", "child interviews completed", "completed child interviews", "interviewed children"), "number_of_child_questionnaires_completed", "Number of child questionnaires completed", ("child_questionnaires",)),
        (("children age 5-17", "children aged 5-17", "children aged 5 to 17", "children aged 1-17", "children aged 1 to 17"), "number_of_children_5_17", "Number of children aged 5-17", ("children_5_17",)),
        (("children aged 2-14", "children aged 2 to 14", "children 2-14", "children 5-14", "children aged 5-14", "children aged 5 to 14"), "number_of_children_2_14", "Number of children aged 2-14", ("children_2_14",)),
        (("mosquito nets",), "number_of_mosquito_nets", "Number of mosquito nets", ("mosquito_nets",)),
        (("rooms used for sleeping", "rooms for sleeping", "sleeping rooms"), "number_of_rooms_used_for_sleeping", "Number of rooms used for sleeping", ("sleeping_rooms",)),
    ]
    if _has_any(text, ("number of", "total number", "total children", "total eligible", "how many", "questionnaires completed", "interviews completed", "children under", "women 15", "women aged", "rooms used", "rooms for sleeping", "mosquito nets")):
        for needles, varname, label, entities in count_patterns:
            if _has_any(text, needles):
                return _entry(varname, label, "count", relation="number_of", response_type="count", entities=entities)

    if _has_any(text, ("wealth index quintile", "wealth quintile", "wealth index quintiles", "wealth quintiles")):
        if "urban" in text:
            return _entry("urban_wealth_index_quintile", "Urban wealth index quintile", "wealth_index", response_type="ordinal")
        if "rural" in text:
            return _entry("rural_wealth_index_quintile", "Rural wealth index quintile", "wealth_index", response_type="ordinal")
        return _entry("wealth_index_quintile", "Wealth index quintile", "wealth_index", response_type="ordinal")
    if _has_any(text, ("wealth index score", "combined wealth score", "wealth score")):
        if "urban" in text:
            return _entry("urban_wealth_score", "Urban wealth score", "wealth_index", response_type="continuous")
        if "rural" in text:
            return _entry("rural_wealth_score", "Rural wealth score", "wealth_index", response_type="continuous")
        if "combined" in text or "wealth index score" in text or text == "wealth score":
            return _entry("wealth_score", "Wealth score", "wealth_index", response_type="continuous")

    demographics = [
        (("sex of household head", "sex of the household head", "sex of head of household", "sex of the head of household"), "sex_of_household_head", "Sex of household head", "household_head_demographics", "category"),
        (("sex",), "sex_of_household_head", "Sex of household head", "household_head_demographics", "category"),
        (("education of household head", "education level of household head", "educational level of household head", "education level of the head of household", "education of the head of household"), "education_of_household_head", "Education of household head", "household_head_demographics", "category"),
        (("religion of household head", "household head's religion", "religion of the head of household", "head of household's religion"), "religion_of_household_head", "Religion of household head", "household_head_demographics", "category"),
        (("ethnicity of household head", "ethnic group of household head", "ethnicity of the head of household", "household head's ethnic group"), "ethnicity_of_household_head", "Ethnicity of household head", "household_head_demographics", "category"),
        (("mother tongue of household head", "language of household head", "household head's mother tongue", "mother tongue of the household head", "mother tongue of the head of household"), "mother_tongue_of_household_head", "Mother tongue of household head", "household_head_demographics", "category"),
        (("age of household head",), "age_of_household_head", "Age of household head", "household_head_demographics", "age"),
        (("age",), "age_of_household_head", "Age of household head", "household_head_demographics", "age"),
    ]
    for needles, varname, label, measure_type, response_type in demographics:
        if needles in {(("age",)), (("sex",))}:
            if text in needles:
                return _entry(varname, label, measure_type, response_type=response_type)
            continue
        if text in needles or _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    housing = [
        (("main material of roof", "main roof material", "main material of the roof"), "main_material_of_roof", "Main material of roof", "housing_material"),
        (("main material of floor", "main material of the floor", "main floor material"), "main_material_of_floor", "Main material of floor", "housing_material"),
        (("main material of exterior wall", "main exterior wall material", "main material of the exterior walls", "main material of exterior walls", "main material of wall", "main wall material"), "main_material_of_exterior_wall", "Main material of exterior wall", "housing_material"),
        (("type of fuel using for cooking", "type of fuel used for cooking", "fuel used for cooking", "fuel using for cooking"), "type_of_fuel_used_for_cooking", "Type of fuel used for cooking", "cooking_fuel"),
        (("type of cookstove mainly used for cooking",), "type_of_cookstove_used_for_cooking", "Type of cookstove used for cooking", "cooking_technology"),
        (("type of energy source for cookstove",), "type_of_energy_source_for_cookstove", "Type of energy source for cookstove", "cooking_energy"),
        (("food cooked on stove or open fire",), "food_cooked_on_stove_or_open_fire", "Food cooked on stove or open fire", "cooking_technology"),
        (("does the fire stove have a chimney or a hood", "stove have a chimney or a hood"), "cookstove_has_chimney_or_hood", "Cookstove has chimney or hood", "cooking_technology"),
        (("cooking location", "place for cooking"), "cooking_location", "Cooking location", "cooking_location"),
        (("household owns the dwelling", "household own the dwelling"), "household_owns_dwelling", "Household owns the dwelling", "housing_tenure"),
        (("type of lighting in household", "type of lighting in the household"), "type_of_lighting", "Type of lighting in household", "housing_energy"),
        (("type of space heating in household",), "type_of_space_heating", "Type of space heating in household", "housing_energy"),
        (("type of energy source for heater",), "type_of_energy_source_for_heater", "Type of energy source for heater", "housing_energy"),
        (("space heater have a chimney",), "space_heater_has_chimney", "Space heater has chimney", "housing_energy"),
        (("internet access at home",), "internet_access_at_home", "Internet access at home", "household_service"),
        (("number of rooms in dwelling",), "number_of_rooms_in_dwelling", "Number of rooms in dwelling", "housing_characteristics"),
    ]
    for needles, varname, label, measure_type in housing:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type="category")

    water_sanitation = [
        (("main source of drinking water",), "main_source_of_drinking_water", "Main source of drinking water", "water_source", "category"),
        (("main source of water used for other purposes", "main source of water used for other things", "main source of water for other purposes"), "main_source_of_water_other_purposes", "Main source of water used for other purposes", "water_source", "category"),
        (("location of the water source", "location of water source", "water source location", "where is that water source located", "where is this water source located"), "location_of_water_source", "Location of water source", "water_source", "category"),
        (("main source of water",), "main_source_of_water", "Main source of water", "water_source", "category"),
        (("person collecting water", "person fetching water"), "person_collecting_water", "Person collecting water", "water_collection", "category"),
        (("time (in minutes) to get water", "time (in minutes) to fetch water", "time (in minutes) to get water and return", "time to get water and come back"), "time_to_get_water_minutes", "Time in minutes to get water and return", "water_collection", "duration_minutes"),
        (("number of times person collected water", "number of times the person has collected water", "number of times the person fetched water"), "number_of_times_collected_water_last_7_days", "Number of times person collected water in last seven days", "water_collection", "count"),
        (("treat water to make safer for drinking", "treatment to make water safer to drink", "treated water to make it safer to drink", "do anything to the water to make it safer to drink", "done anything to the water to make it safer to drink"), "treat_water_to_make_safer", "Treat water to make safer for drinking", "water_treatment", "yes_no"),
        (("type of toilet facility", "kind of toilet facility", "type of toilet"), "type_of_toilet_facility", "Type of toilet facility", "sanitation", "category"),
        (("households using this toilet facility", "households using this toilet", "households using this sanitation facility", "number of households using this toilet", "how many households in total use this toilet"), "number_of_households_using_toilet", "Number of households using this toilet facility", "sanitation", "count"),
        (("toilet facility shared", "toilet facility is shared"), "toilet_facility_shared", "Toilet facility shared", "sanitation", "yes_no"),
        (("toilet shared with other household", "toilet shared with other households", "share this toilet facility", "share these toilets", "toilet shared with other known household"), "toilet_shared_with_other_households_or_public", "Toilet shared with other households or public", "sanitation", "yes_no"),
        (("pit latrine or septic tank", "has the pit latrine or septic tank been emptied"), "pit_latrine_or_septic_tank_emptied", "Pit latrine or septic tank ever emptied", "sanitation", "yes_no"),
        (("place the contents were emptied", "place where the contents were emptied", "place where contents were emptied"), "place_where_toilet_contents_emptied", "Place where toilet contents were emptied", "sanitation", "category"),
        (("location of the toilet facility", "location of toilet facility", "location of the toilet faciltity"), "location_of_toilet_facility", "Location of toilet facility", "sanitation", "category"),
        (("there been any time in the last month without sufficient water", "time in the last month without sufficient water", "without sufficient water"), "insufficient_water_last_month", "Any time in last month without sufficient water", "water_availability", "yes_no"),
    ]
    for needles, varname, label, measure_type, response_type in water_sanitation:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    water_treatments = [
        (("add bleach/chlorine", "add bleach / chlorine", "adding bleach/chlorine"), "water_treatment_add_bleach_chlorine", "Water treatment: add bleach or chlorine"),
        (("let it stand and settle", "letting it settle", "let it settle"), "water_treatment_let_stand_and_settle", "Water treatment: let it stand and settle"),
        (("strain it through a cloth", "filter through cloth", "filtering through cloth"), "water_treatment_strain_through_cloth", "Water treatment: strain through cloth"),
        (("solar disinfection",), "water_treatment_solar_disinfection", "Water treatment: solar disinfection"),
        (("water treatment: boil", "water treatment: boiling", "water treatment: boiling", "water treatment boiling", "boil"), "water_treatment_boil", "Water treatment: boil"),
        (("water treatment: no response",), "water_treatment_no_response", "Water treatment: no response"),
        (("water treatment: other", "water treatment other"), "water_treatment_other", "Water treatment: other"),
        (("water treatment: dk", "water treatment dk"), "water_treatment_dk", "Water treatment: don't know"),
        (("water treatment: missing",), "water_treatment_missing", "Water treatment: missing"),
    ]
    for needles, varname, label in water_treatments:
        if _has_any(text, needles):
            return _entry(varname, label, "water_treatment_method", response_type="yes_no")

    handwashing = [
        (("place where household members most often wash their hands", "place where household members wash their hands", "place where household members wash hands"), "place_where_household_members_wash_hands", "Place where household members wash hands", "handwashing", "category"),
        (("usual place for handwashing",), "usual_place_for_handwashing", "Usual place for handwashing", "handwashing", "category"),
        (("water available at the place for handwashing", "water available at the specific handwashing place", "water available at the place for hand washing", "water available at the location for hand washing"), "water_available_at_handwashing_place", "Water available at handwashing place", "handwashing", "yes_no"),
        (("soap/other material available", "soap / other material available", "soap or other material available", "soap or detergent present", "soap or other cleaning products", "soap or handwashing products"), "soap_or_other_material_available_for_handwashing", "Soap or other material available for handwashing", "handwashing", "yes_no"),
        (("hand washing material shown", "handwashing material shown"), "handwashing_material_shown", "Handwashing material shown", "handwashing", "yes_no"),
        (("not able / does not want to show", "not able /does not want to show", "does not want to show"), "handwashing_place_not_shown", "Handwashing place not shown", "handwashing", "yes_no"),
        (("bar soap",), "handwashing_material_bar_soap", "Handwashing material: bar soap", "handwashing_material", "yes_no"),
        (("liquid soap",), "handwashing_material_liquid_soap", "Handwashing material: liquid soap", "handwashing_material", "yes_no"),
        (("detergent", "laundry soap"), "handwashing_material_detergent", "Handwashing material: detergent", "handwashing_material", "yes_no"),
        (("ash / mud / sand", "ash/mud/sand"), "handwashing_material_ash_mud_sand", "Handwashing material: ash, mud, or sand", "handwashing_material", "yes_no"),
    ]
    for needles, varname, label, measure_type, response_type in handwashing:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    child_selection = [
        (("child line number", "child's line number"), "selected_child_line_number", "Selected child line number", "child_selection", "identifier"),
        (("rank number of the selected child", "child's rank number", "selected child's rank", "selected child rank number", "rank number of child"), "selected_child_rank_number", "Selected child rank number", "child_selection", "ordinal"),
        (("child's age", "child's age"), "selected_child_age", "Selected child's age", "child_selection", "age"),
        (("flag for correct child line number",), "flag_correct_child_line_number", "Flag for correct child line number", "child_selection", "flag"),
    ]
    for needles, varname, label, measure_type, response_type in child_selection:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    child_discipline = [
        (("took away privileges", "took away a privilege"), "discipline_took_away_privileges", "Took away privileges", "child_discipline", "yes_no"),
        (("explained why behaviour was wrong", "explained why behavior was wrong", "explained why their behavior was wrong"), "discipline_explained_why_behavior_was_wrong", "Explained why behavior was wrong", "child_discipline", "yes_no"),
        (("spanked, hit or slapped", "slap, hit or spank", "spanked hit or slapped"), "discipline_spanked_hit_or_slapped_bottom_bare_hand", "Spanked, hit, or slapped child on bottom with bare hand", "child_discipline", "yes_no"),
        (("hit or slapped child on the hand", "hit/slapped on hand", "hit or slapped on the hand"), "discipline_hit_or_slapped_hand_arm_leg", "Hit or slapped child on hand, arm, or leg", "child_discipline", "yes_no"),
        (("hit child on the bottom or elsewhere with belt", "belt, brush, stick", "stick or other hard object"), "discipline_hit_with_object", "Hit child with belt, brush, stick, or other object", "child_discipline", "yes_no"),
        (("beat child up as hard as one could", "beat him/her up with an implement"), "discipline_beat_child_hard", "Beat child as hard as one could", "child_discipline", "yes_no"),
        (("child needs to be physically punished",), "attitude_child_needs_physical_punishment", "Child needs physical punishment to be raised properly", "child_discipline_attitude", "yes_no"),
        (("do you believe to bring up", "nedd to punish", "need to punish"), "attitude_child_needs_physical_punishment", "Child needs physical punishment to be raised properly", "child_discipline_attitude", "yes_no"),
        (("called child dumb",), "discipline_called_child_names", "Called child dumb, lazy, or another name", "child_discipline", "yes_no"),
        (("called him/her dumb", "called him/her dumb, lazy"), "discipline_called_child_names", "Called child dumb, lazy, or another name", "child_discipline", "yes_no"),
        (("shook child",), "discipline_shook_child", "Shook child", "child_discipline", "yes_no"),
        (("shook him/her",), "discipline_shook_child", "Shook child", "child_discipline", "yes_no"),
        (("gave child something else to do",), "discipline_gave_child_something_else_to_do", "Gave child something else to do", "child_discipline", "yes_no"),
        (("gave him/hersomething else to do", "gave him/her something else to do"), "discipline_gave_child_something_else_to_do", "Gave child something else to do", "child_discipline", "yes_no"),
        (("shouted, yelled or screamed",), "discipline_shouted_yelled_screamed", "Shouted, yelled, or screamed at child", "child_discipline", "yes_no"),
        (("shouted yelled at or screamed",), "discipline_shouted_yelled_screamed", "Shouted, yelled, or screamed at child", "child_discipline", "yes_no"),
        (("hit or slapped child on the face", "hit or slapped him/her on the face", "hit/slap him/her on the face", "face, head or ears"), "discipline_hit_or_slapped_face_head_ears", "Hit or slapped child on face, head, or ears", "child_discipline", "yes_no"),
        (("hit or slapped him/her on the hand",), "discipline_hit_or_slapped_hand_arm_leg", "Hit or slapped child on hand, arm, or leg", "child_discipline", "yes_no"),
        (("explaned why something was wrong",), "discipline_explained_why_behavior_was_wrong", "Explained why behavior was wrong", "child_discipline", "yes_no"),
        (("hit him/her on the bottom with or elsewhere with a belt",), "discipline_hit_with_object", "Hit child with belt, brush, stick, or other object", "child_discipline", "yes_no"),
    ]
    for needles, varname, label, measure_type, response_type in child_discipline:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    other_patterns = [
        (("primary sampling unit", "primary sample unit", "primary samplig unit"), "primary_sampling_unit", "Primary sampling unit", "sample_design", "identifier"),
        (("strata",), "stratum", "Stratum", "geography", "category"),
        (("province",), "province", "Province", "geography", "category"),
        (("respondent to hh questionnaire", "respondent to household questionnaire"), "respondent_to_household_questionnaire", "Respondent to household questionnaire", "respondent_identity", "identifier"),
        (("respondent hh questionnaire",), "respondent_to_household_questionnaire", "Respondent to household questionnaire", "respondent_identity", "identifier"),
        (("women interviews completed",), "number_of_women_questionnaires_completed", "Number of women's questionnaires completed", "count", "count"),
        (("does any member of your household have the following things", "does any member of your household have the following things:"), "household_assets_following_items", "Household assets: following items", "instrument_flow", "marker"),
        (("how many of the following animals does your household have", "how many of the following animals does your household have:"), "household_animals_following_items", "Household animals: following items", "instrument_flow", "marker"),
        (("data entry clerk",), "data_entry_clerk", "Data entry clerk", "data_processing_metadata", "identifier"),
        (("field editor",), "field_editor", "Field editor", "fieldwork_metadata", "identifier"),
        (("translator used",), "translator_used", "Translator used", "fieldwork_metadata", "yes_no"),
        (("finish",), "finish", "Finish", "fieldwork_metadata", "status"),
        (("language of the interview", "interview language"), "interview_language", "Interview language", "language", "category"),
        (("language of the questionnaire", "questionnaire language"), "questionnaire_language", "Questionnaire language", "language", "category"),
        (("native language of the respondent", "respondent's mother tongue", "respondent's native language"), "respondent_native_language", "Respondent native language", "language", "category"),
        (("salt iodization test outcome", "salt iodization recheck test outcome", "result of salt iodation test", "result of salt iodization test", "type of salt"), "salt_iodization_test_outcome", "Salt iodization test outcome", "salt_iodization", "category"),
        (("consent for water quality", "consent for water testing"), "consent_for_water_quality_test", "Consent for water quality test", "consent", "yes_no"),
        (("consent",), "consent", "Consent", "consent", "yes_no"),
        (("household owns any animals", "household own any animals", "household owns animals"), "household_owns_any_animals", "Household owns any animals", "animal_ownership", "yes_no"),
        (("household has mosquito nets", "household owns mosquito nets"), "household_has_mosquito_nets", "Household has mosquito nets", "asset_possession", "yes_no"),
        (("any member have a mobile telephone",), "any_household_member_has_mobile_phone", "Any household member has mobile phone", "asset_possession", "yes_no"),
        (("any household member own bank account", "any household member has a bank account", "any household member owns a bank account", "does any member of this household have a bank account"), "any_household_member_has_bank_account", "Any household member has bank account", "financial_inclusion", "yes_no"),
        (("any household member own land that can be used for agriculture", "does any member of your household own any land for agriculture", "some household members own land that can be used for agriculture"), "any_household_member_owns_agricultural_land", "Any household member owns agricultural land", "land_ownership", "yes_no"),
        (("hectares of agricultural land",), "hectares_of_agricultural_land_owned", "Hectares of agricultural land owned by household members", "land_ownership", "area"),
        (("acres of agricultural land",), "acres_of_agricultural_land_owned", "Acres of agricultural land owned by household members", "land_ownership", "area"),
        (("other household members", "other household member", "other household memebers"), "other_household_members", "Other household members", "household_roster", "count"),
        (("introduction hh listing", "hh listing introduction"), "introduction_hh_listing", "Introduction HH listing", "instrument_flow", "marker"),
        (("hh selected for questionnaire for men",), "hh_selected_for_questionnaire_for_men", "Household selected for questionnaire for men", "sample_selection", "yes_no"),
        (("hh selected for blank testing", "hh selected for blank test", "household selected for blank test"), "hh_selected_for_blank_testing", "Household selected for blank testing", "sample_selection", "yes_no"),
        (("hh selected for water quality testing",), "hh_selected_for_water_quality_testing", "Household selected for water quality testing", "sample_selection", "yes_no"),
        (("water quality prompt",), "water_quality_prompt", "Water quality prompt", "water_quality_test", "prompt"),
        (("blank water test available",), "blank_water_test_available", "Blank water test available", "water_quality_test", "yes_no"),
        (("water was collected from the source",), "water_was_collected_from_source", "Water was collected from the source", "water_quality_test", "yes_no"),
        (("source of water where the glass of water was collected",), "source_of_glass_water_for_test", "Source of water where glass of water was collected", "water_quality_test", "category"),
        (("main source of water was shown",), "main_source_of_water_shown", "Main source of water was shown", "water_quality_test", "yes_no"),
        (("source water sample collected",), "source_water_sample_collected", "Source water sample collected", "water_quality_test", "yes_no"),
        (("source water test (100ml)",), "source_water_test_100ml", "Source water test 100ml", "water_quality_test", "result"),
        (("household water test (100ml)",), "household_water_test_100ml", "Household water test 100ml", "water_quality_test", "result"),
        (("blank water test (100ml)",), "blank_water_test_100ml", "Blank water test 100ml", "water_quality_test", "result"),
        (("result of water quality test",), "result_of_water_quality_test", "Result of water quality test", "water_quality_test", "result"),
        (("a glass of water that you would give to a child to drink was provided",), "glass_of_child_drinking_water_provided", "Glass of child drinking water provided", "water_quality_test", "yes_no"),
        (("weight for source wqt",), "source_water_quality_test_weight", "Weight for source water quality test", "sample_weight", "weight"),
        (("weight for household wqt",), "household_water_quality_test_weight", "Weight for household water quality test", "sample_weight", "weight"),
        (("household weight",), "household_sample_weight", "Household sample weight", "sample_weight", "weight"),
        (("regr factor score",), "wealth_score", "Wealth score", "wealth_index", "continuous"),
        (("percentile group of urb1",), "urban_wealth_index_decile", "Urban wealth index decile", "wealth_index", "ordinal"),
        (("percentile group of rur1",), "rural_wealth_index_decile", "Rural wealth index decile", "wealth_index", "ordinal"),
        (("percentile group of com1",), "wealth_index_decile", "Wealth index decile", "wealth_index", "ordinal"),
        (("line number",), "line_number", "Line number", "identifier", "identifier"),
        (("measurer number",), "measurer_number", "Measurer number", "fieldwork_metadata", "identifier"),
    ]
    for needles, varname, label, measure_type, response_type in other_patterns:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    if _has_any(text, ("end of water quality test", "water quality test end", "end of water test")):
        if _has_any(text, ("hour",)):
            return _entry("water_quality_test_end_hour", "Water quality test end hour", "water_quality_test_time", response_type="time_component", event="water_quality_test_end", component="hour")
        if _has_any(text, ("minute", "minutes")):
            return _entry("water_quality_test_end_minute", "Water quality test end minute", "water_quality_test_time", response_type="time_component", event="water_quality_test_end", component="minute")

    if _has_any(text, ("start of water quality test", "water quality test start", "start of water test")):
        if _has_any(text, ("hour",)):
            return _entry("water_quality_test_start_hour", "Water quality test start hour", "water_quality_test_time", response_type="time_component", event="water_quality_test_start", component="hour")
        if _has_any(text, ("minute", "minutes")):
            return _entry("water_quality_test_start_minute", "Water quality test start minute", "water_quality_test_time", response_type="time_component", event="water_quality_test_start", component="minute")

    if _has_any(text, ("time of recording test results",)):
        if _has_any(text, ("hour",)):
            return _entry("water_quality_results_recording_hour", "Water quality results recording hour", "water_quality_test_time", response_type="time_component", event="water_quality_results_recording", component="hour")
        if _has_any(text, ("minute", "minutes")):
            return _entry("water_quality_results_recording_minute", "Water quality results recording minute", "water_quality_test_time", response_type="time_component", event="water_quality_results_recording", component="minute")

    if _has_any(text, ("year of recording test results",)):
        return _entry("water_quality_results_recording_year", "Water quality results recording year", "water_quality_test_date", response_type="date_component", event="water_quality_results_recording", component="year")
    if _has_any(text, ("month of recording test results",)):
        return _entry("water_quality_results_recording_month", "Water quality results recording month", "water_quality_test_date", response_type="date_component", event="water_quality_results_recording", component="month")
    if _has_any(text, ("day of recording test results",)):
        return _entry("water_quality_results_recording_day", "Water quality results recording day", "water_quality_test_date", response_type="date_component", event="water_quality_results_recording", component="day")

    if _has_any(text, ("year of water quality test",)):
        return _entry("water_quality_test_year", "Water quality test year", "water_quality_test_date", response_type="date_component", event="water_quality_test", component="year")
    if _has_any(text, ("month of water quality test",)):
        return _entry("water_quality_test_month", "Water quality test month", "water_quality_test_date", response_type="date_component", event="water_quality_test", component="month")
    if _has_any(text, ("day of water quality test",)):
        return _entry("water_quality_test_day", "Water quality test day", "water_quality_test_date", response_type="date_component", event="water_quality_test", component="day")

    child_labor = [
        (("household chores: washing clothes",), "child_labor_household_chores_washing_clothes", "Household chores: washing clothes", "child_labor", "yes_no"),
        (("household chores: shopping",), "child_labor_household_chores_shopping", "Household chores: shopping", "child_labor", "yes_no"),
        (("household chores: other",), "child_labor_household_chores_other", "Household chores: other", "child_labor", "yes_no"),
        (("household chores: caring for old or sick",), "child_labor_household_chores_caring_for_old_or_sick", "Household chores: caring for old or sick", "child_labor", "yes_no"),
        (("fetched water or collected firewood",), "child_labor_fetched_water_or_collected_firewood", "Fetched water or collected firewood", "child_labor", "yes_no"),
        (("number of hours",), "child_labor_number_of_hours", "Number of hours", "child_labor", "hours"),
        (("hours spent fetching water or collecting firewood",), "child_labor_hours_fetching_water_or_firewood", "Hours spent fetching water or collecting firewood", "child_labor", "hours"),
        (("activities required working with dangerous tools or heavy machinery",), "child_labor_dangerous_tools_or_heavy_machinery", "Activities required working with dangerous tools or heavy machinery", "child_labor_hazard", "yes_no"),
        (("description of work: exposed to dust",), "child_labor_exposed_to_dust_fumes_or_gas", "Description of work: exposed to dust, fumes, or gas", "child_labor_hazard", "yes_no"),
        (("description of work: exposed to extreme temperatures",), "child_labor_exposed_to_extreme_temperatures_or_humidity", "Description of work: exposed to extreme temperatures or humidity", "child_labor_hazard", "yes_no"),
        (("description of work: exposed to loud noise",), "child_labor_exposed_to_loud_noise_or_vibration", "Description of work: exposed to loud noise or vibration", "child_labor_hazard", "yes_no"),
        (("description of work: required to work at heights",), "child_labor_required_to_work_at_heights", "Description of work: required to work at heights", "child_labor_hazard", "yes_no"),
        (("description of work: exposed to other",), "child_labor_exposed_to_other_hazard", "Description of work: exposed to other hazard", "child_labor_hazard", "yes_no"),
    ]
    for needles, varname, label, measure_type, response_type in child_labor:
        if _has_any(text, needles):
            return _entry(varname, label, measure_type, response_type=response_type)

    return None


def _canonicalize_reason(text: str) -> CanonicalEntry | None:
    if not _has_any(text, ("reason", "why")):
        return None
    entity = _extract_entity(text)
    if not entity:
        return None
    return CanonicalEntry(
        canonical_varname=f"reason_no_{entity}",
        canonical_text=f"Reason household does not have {entity.replace('_', ' ')}",
        measure_type="reason",
        relation="reason_not_have",
        entities=(entity,),
        response_type="category",
        confidence="high",
    )


def _canonicalize_affordability(text: str) -> CanonicalEntry | None:
    if not _has_any(text, ("can afford", "afford")):
        return None
    entity = _extract_entity(text)
    if not entity:
        return None
    return CanonicalEntry(
        canonical_varname=f"can_afford_{entity}",
        canonical_text=f"Can afford {entity.replace('_', ' ')}",
        measure_type="affordability",
        relation="can_afford",
        entities=(entity,),
        response_type="yes_no",
        confidence="high",
    )


def _canonicalize_count(text: str) -> CanonicalEntry | None:
    if not _has_any(text, ("number of", "how many", "total number")):
        return None
    entity = _extract_entity(text)
    if entity:
        return CanonicalEntry(
            canonical_varname=f"number_of_{entity}",
            canonical_text=f"Number of {entity.replace('_', ' ')}",
            measure_type="count",
            relation="number_of",
            entities=(entity,),
            response_type="count",
            confidence="high",
        )
    if _has_any(text, ("household members", "hh members")):
        return CanonicalEntry(
            canonical_varname="number_of_household_members",
            canonical_text="Number of household members",
            measure_type="count",
            relation="number_of",
            entities=("household_members",),
            response_type="count",
            confidence="high",
        )
    return None


def _canonicalize_possession(text: str) -> CanonicalEntry | None:
    relation = None
    item_text = text
    prefixes = [
        "does your household own:",
        "does your household have:",
        "does household have",
        "household has:",
        "household have:",
        "the household has:",
        "house has:",
        "does a member of this household have",
        "does any member of this household have",
        "does any member of your household have",
        "any household member owns:",
        "any member of household own:",
        "household owns",
        "household has",
        "household have",
    ]
    for prefix in prefixes:
        if item_text.startswith(prefix):
            relation = "household_has"
            item_text = item_text[len(prefix):].strip(" :")
            break

    entities = _extract_entities(item_text)
    if not entities:
        return None

    if relation is None and _is_bare_asset_label(text, entities):
        relation = "household_has"
    if relation is None:
        return None

    ignored = _ignored_qualifiers(item_text)
    entity_operator = _entity_operator(item_text, len(entities))
    is_compound = len(entities) > 1
    measure_type = "animal_ownership" if all(_is_animal(e) for e in entities) else "asset_possession"

    var_entity = f"_{entity_operator}_".join(entities) if is_compound and entity_operator else "_and_".join(entities)
    varname = f"{relation}_{var_entity}"
    text_entities = f" {entity_operator or 'and'} ".join(e.replace("_", " ") for e in entities)
    canonical_text = f"Household has {text_entities}"

    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=canonical_text,
        measure_type=measure_type,
        relation=relation,
        entities=tuple(entities),
        entity_operator=entity_operator,
        is_compound=is_compound,
        response_type="yes_no",
        ignored_qualifiers=tuple(ignored),
        confidence="high" if relation else "medium",
    )


def _extract_entity(text: str) -> str | None:
    entities = _extract_entities(text)
    return entities[0] if entities else None


def _extract_entities(text: str) -> list[str]:
    normalized = _normalize_asset_text(text)
    for exception, entity in _COMPOUND_EXCEPTIONS.items():
        if exception in normalized and entity:
            return [entity]

    parts = _split_compound(normalized)
    entities: list[str] = []
    for part in parts:
        entity = _match_entity(part)
        if entity and entity not in entities:
            entities.append(entity)
    if entities:
        return entities

    entity = _match_entity(normalized)
    return [entity] if entity else []


def _split_compound(text: str) -> list[str]:
    if not _has_any(text, ("/", " or ", " and ")):
        return [text]
    protected = text
    for exception in _COMPOUND_EXCEPTIONS:
        protected = protected.replace(exception, exception.replace("/", "__slash__"))
    parts = re.split(r"\s*/\s*|\s+or\s+|\s+and\s+|,\s*", protected)
    parts = [p.replace("__slash__", "/").strip() for p in parts if p.strip()]

    # Carry head noun context: "washing machine/dryer" -> "washing machine", "clothes dryer".
    enriched: list[str] = []
    previous = ""
    for part in parts:
        if part == "dryer" and "washing machine" in previous:
            enriched.append("clothes dryer")
        elif part in {"screen tv", "flat screen tv"}:
            enriched.append("television")
        else:
            enriched.append(part)
        previous = part
    return enriched or [text]


def _match_entity(text: str) -> str | None:
    normalized = _normalize_asset_text(text)
    if "hair dryer" in normalized:
        return "hair_dryer"
    if "dish washing machine" in normalized or "dishwashing machine" in normalized:
        return "dishwasher"
    if "washing machine" in normalized:
        return "washing_machine"

    for term, entity in _ASSET_TERMS:
        if term in normalized:
            return entity
    for term, entity in _ANIMAL_TERMS:
        if term in normalized:
            return entity
    return None


def _normalize_asset_text(text: str) -> str:
    text = text.replace("semi-automatic", "semi automatic")
    text = text.replace("air-conditioner", "air conditioner")
    text = text.replace("air conditioning", "air conditioner")
    text = text.replace("dinning", "dining")
    text = text.replace("solar panels", "solar panel")
    return _SPACE_RE.sub(" ", text).strip(" :;,.")


def _entity_operator(text: str, n_entities: int) -> str | None:
    if n_entities <= 1:
        return None
    if "/" in text or " or " in text:
        return "or"
    if " and " in text:
        return "and"
    return "or"


def _ignored_qualifiers(text: str) -> list[str]:
    ignored = []
    if "automatic washing machine" in text:
        ignored.append("automatic")
    if "semi automatic washing machine" in text or "semi-automatic washing machine" in text:
        ignored.append("semi_automatic")
    return ignored


def _is_bare_asset_label(text: str, entities: list[str]) -> bool:
    if not entities:
        return False
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return len(tokens) <= 5


def _is_animal(entity: str) -> bool:
    return entity in {e for _, e in _ANIMAL_TERMS}


def _fallback(label: str) -> CanonicalEntry:
    text = _clean_label(label)
    varname = _slug(text)
    return CanonicalEntry(
        canonical_varname=varname,
        canonical_text=str(label or "").strip(),
        measure_type="unknown",
        confidence="low",
        needs_review=True,
        notes=("fallback_from_label",),
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
