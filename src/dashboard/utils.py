"""Country/round extraction and validation helpers."""
import re

ALL_ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]

# Plotly choropleth uses these country names
COUNTRY_CORRECTIONS: dict[str, str | None] = {
    "Viet Nam": "Vietnam",
    "State of Palestine": "Palestinian Territory",
    "Palestinians in Lebanon": None,       # population group, not a country
    "Congo, Democratic Republic of": "Democratic Republic of the Congo",
    "DRCongo": "Democratic Republic of the Congo",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "The Gambia": "Gambia",
    "Republic of North Macedonia": "North Macedonia",
    "Swaziland": "Eswatini",
    "Sao Tome and Principle": "Sao Tome and Principe",
    "Guinea Bissau": "Guinea-Bissau",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Trinidad and Tobago": "Trinidad and Tobago",
}

_SUBNATIONAL = re.compile(
    r"\s+(Punjab|Sindh|Khyber[\s_]+Pakhtunkhwa|Gilgit[\s_]+Baltistan"
    r"|Azad[\s_]+Jammu[\s_]+and[\s_]+Kashmir|Balochistan"
    r"|Dakar|Selected[\s_]+Districts.*|14[\s_]+Provinces"
    r"|Sub-national|Northeast[\s_]+Zone|Somaliland"
    r"|Roma[\s_]+Settlements)",
    re.IGNORECASE,
)


def extract_country(dataset_name: str) -> str | None:
    """Parse country name from a MICS dataset_name string.

    Sub-national datasets are collapsed to their parent country.
    Returns None for entries that are not countries (e.g. Palestinians in Lebanon).
    """
    name = dataset_name

    # Strip MICS round + everything after
    name = re.sub(r"\s*_?MICS\s*[2-6].*", "", name)
    # Strip year + everything after
    name = re.sub(r"[\s_]+[12][0-9]{3}[\s_].*", "", name)
    # Strip "SPSS Datasets" etc.
    name = re.sub(r"\s+SPSS.*", "", name, flags=re.IGNORECASE)
    # Strip parenthetical sub-national qualifiers
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Strip known sub-national region names
    name = _SUBNATIONAL.sub("", name)
    # Clean trailing underscores/spaces
    name = name.strip("_ ").strip()

    if name in COUNTRY_CORRECTIONS:
        return COUNTRY_CORRECTIONS[name]  # None means skip
    return name or None


def extract_round(dataset_name: str) -> str:
    dn = dataset_name
    if "MICS6" in dn:
        return "MICS6"
    if "MICS5" in dn:
        return "MICS5"
    if "MICS4" in dn:
        return "MICS4"
    if "MICS3" in dn:
        return "MICS3"
    if "MICS2" in dn:
        return "MICS2"
    if re.search(r"200[5-7]", dn):
        return "MICS3"
    if re.search(r"199[5-9]|200[0-2]", dn):
        return "MICS2"
    return "Unknown"


_VALID_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_safe_identifier(name: str) -> bool:
    """Reject strings that are not valid SQL identifiers (injection guard)."""
    return bool(_VALID_IDENT.match(name))
