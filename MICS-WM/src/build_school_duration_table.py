"""
P09 step 2 — Build the country × year school-system duration table from the
World Bank API, plus the MICS dataset_name → ISO3 mapping.

Indicators (theoretical durations, by country-year):
  SE.PRM.DURS     primary
  SE.SEC.DURS.LO  lower secondary
  SE.SEC.DURS.UP  upper secondary

Education-system durations apply to the years a person ATTENDED school, not
the survey year — the duration series is kept in full (1970–2023) so that
years-of-schooling construction (P09-3) can look up each person's school-entry
year (survey_year − age + 6).

Outputs:
  data/WM/school_durations.csv    (iso3, year, prim_dur, lowsec_dur, upsec_dur)
  data/WM/dataset_iso3_map.csv    (dataset_name, country_guess, iso3, survey_year, match_kind)

Usage:
  python build_school_duration_table.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd
import psycopg2

_PROJECT_ROOT = Path(__file__).parent.parent.parent
OUT_DIR = _PROJECT_ROOT / "MICS-WM" / "data" / "WM"

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
INDICATORS = {
    "SE.PRM.DURS": "prim_dur",
    "SE.SEC.DURS.LO": "lowsec_dur",
    "SE.SEC.DURS.UP": "upsec_dur",
}
YEARS = "1970:2023"

# MICS entities whose names don't fuzzy-match World Bank names
MANUAL_ISO3 = {
    "kosovo under unsc res. 1244": "XKX",
    "kosovo": "XKX",
    "cote d'ivoire": "CIV",
    "côte d'ivoire": "CIV",
    "lao pdr": "LAO",
    "laopdr": "LAO",
    "congo, democratic republic of": "COD",
    "democratic republic of congo": "COD",
    "korea, dpr": "PRK",
    "dpr korea": "PRK",
    "swaziland": "SWZ",     # renamed Eswatini in WB
    "eswatini": "SWZ",
    "macedonia": "MKD",
    "north macedonia": "MKD",
    "the former yugoslav republic of macedonia": "MKD",
    "turks and caicos": "TCA",
    "turks and caicos islands": "TCA",
    "venezuela": "VEN",
    "bolivia": "BOL",
    "moldova": "MDA",
    "iran": "IRN",
    "syria": "SYR",
    "syrian arab republic": "SYR",
    "egypt": "EGY",
    "gambia": "GMB",
    "the gambia": "GMB",
    "kyrgyz republic": "KGZ",
    "kyrgyzstan": "KGZ",
    "vietnam": "VNM",
    "viet nam": "VNM",
    "state of palestine": "PSE",
    "palestinians in lebanon": "LBN",   # camps surveyed inside Lebanon
    "lebanon (palestinians)": "LBN",
    "yemen": "YEM",
    "tanzania": "TZA",
    "st. lucia": "LCA",
    "saint lucia": "LCA",
    "sao tome and principe": "STP",
    "são tomé and príncipe": "STP",
    "cape verde": "CPV",
    "cabo verde": "CPV",
    "guinea bissau": "GNB",
    "guinea-bissau": "GNB",
    "micronesia": "FSM",
    "trinidad and tobago": "TTO",
    "central african republic": "CAF",
    "samoa": "WSM",
    "tuvalu": "TUV",
    "tonga": "TON",
    "fiji": "FJI",
    "vanuatu": "VUT",
    "kiribati": "KIR",
    "nauru": "NRU",
    "congo": "COG",
    "drcongo": "COD",
    "dr congo": "COD",
    "lao people's democratic republic lsis": "LAO",
    "lao people's democratic republic": "LAO",
    "macedonia, the former yugoslav republic of": "MKD",
    "sao tome and principle": "STP",   # typo in dataset name
    "somalia": "SOM",
    "st.lucia": "LCA",
    "samoa": "WSM",
}

# Kosovo (XKX) has no WB duration series. Injected manually:
# Yugoslav-era 4+4+4 until the 2002/03 reform, then 5+4+3.
KOSOVO_DURATIONS = (
    [{"iso3": "XKX", "year": y, "prim_dur": 4, "lowsec_dur": 4, "upsec_dur": 4}
     for y in range(1970, 2003)]
    + [{"iso3": "XKX", "year": y, "prim_dur": 5, "lowsec_dur": 4, "upsec_dur": 3}
       for y in range(2003, 2024)]
)

# Sub-national qualifiers to strip before matching
STRIP_PARENS = re.compile(r"\((south|north|dakar|punjab|sindh|gilgit baltistan|balochistan|"
                          r"khyber pakhtunkhwa|roma, ashkali, and egyptian communities|"
                          r"north only|south only|selected districts.*?)\)", re.I)


def fetch_wb(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_indicator(code: str) -> pd.DataFrame:
    rows, page = [], 1
    while True:
        url = (f"https://api.worldbank.org/v2/country/all/indicator/{code}"
               f"?format=json&date={YEARS}&per_page=20000&page={page}")
        payload = fetch_wb(url)
        meta, data = payload[0], payload[1] or []
        for d in data:
            if d["value"] is not None and d["countryiso3code"]:
                rows.append({"iso3": d["countryiso3code"],
                             "year": int(d["date"]),
                             INDICATORS[code]: float(d["value"])})
        if page >= meta["pages"]:
            break
        page += 1
    df = pd.DataFrame(rows)
    print(f"  {code}: {len(df)} rows, {df.iso3.nunique()} countries")
    return df


def get_dataset_names() -> list[str]:
    conn = psycopg2.connect(**DB_PARAMS)
    names = set()
    with conn.cursor() as cur:
        for t in ("final_WM_MICS", "final_HL_MICS", "final_CH_MICS"):
            cur.execute(f'SELECT DISTINCT dataset_name FROM "{t}"')
            names.update(r[0] for r in cur.fetchall())
    conn.close()
    return sorted(names)


def extract_country(dataset_name: str) -> str:
    s = dataset_name
    s = re.sub(r"MICS\d.*$|MICS \d.*$|\d{4}.*MICS.*$|MICS.*$", "", s).strip(" _-")
    s = STRIP_PARENS.sub("", s).strip(" _-")
    s = re.sub(r"_?Datasets?.*$|_?SPSS.*$|_?Datafiles?.*$|_LSIS.*$", "", s, flags=re.I).strip(" _-")
    s = re.sub(r"\d{4}(-\d{2,4})?$", "", s).strip(" _-")
    s = s.replace("_", " ").strip()
    if not s:  # names like "MICS6 Samoa Datasets" where MICS-prefix strip ate everything
        s = re.sub(r"MICS\s*\d*|SPSS|Datasets?|Datafiles?|\b\d+\b", "", dataset_name, flags=re.I)
        s = s.replace("_", " ").strip(" _-")
    return s


def _norm_key(s: str) -> str:
    """Normalization for name matching: unicode form, apostrophes, parens, spacing."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("’", "'").lower()
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_survey_year(dataset_name: str) -> int:
    m = re.search(r"(19|20)\d\d", dataset_name)
    if m:
        return int(m.group())
    round_mid = {"MICS2": 2000, "MICS3": 2006, "MICS4": 2011, "MICS5": 2014, "MICS6": 2019}
    for rnd, yr in round_mid.items():
        if rnd.lower() in dataset_name.lower():
            return yr
    return 2010


def main() -> None:
    print("Fetching World Bank duration indicators ...")
    dfs = [fetch_indicator(code) for code in INDICATORS]
    dur = dfs[0]
    for d in dfs[1:]:
        dur = dur.merge(d, on=["iso3", "year"], how="outer")
    dur = pd.concat([dur, pd.DataFrame(KOSOVO_DURATIONS)], ignore_index=True)
    dur = dur.sort_values(["iso3", "year"])
    dur_path = OUT_DIR / "school_durations.csv"
    dur.to_csv(dur_path, index=False)
    print(f"saved: {dur_path}  ({len(dur)} rows)")

    print("\nFetching WB country list ...")
    payload = fetch_wb("https://api.worldbank.org/v2/country?format=json&per_page=400")
    wb_names = {_norm_key(c["name"]): c["id"] for c in payload[1]
                if c["region"]["id"] != "NA"}  # skip aggregates

    print("Mapping dataset names ...")
    rows = []
    for ds in get_dataset_names():
        country = extract_country(ds)
        key = _norm_key(country)
        iso3, kind = None, "unmatched"
        if key in MANUAL_ISO3:
            iso3, kind = MANUAL_ISO3[key], "manual"
        elif key in wb_names:
            iso3, kind = wb_names[key], "exact"
        else:
            hits = [v for k, v in wb_names.items() if key and (key in k or k in key)]
            if len(set(hits)) == 1:
                iso3, kind = hits[0], "substring"
        rows.append({"dataset_name": ds, "country_guess": country, "iso3": iso3,
                     "survey_year": extract_survey_year(ds), "match_kind": kind})

    m = pd.DataFrame(rows)
    map_path = OUT_DIR / "dataset_iso3_map.csv"
    m.to_csv(map_path, index=False)
    n_bad = (m.match_kind == "unmatched").sum()
    print(f"saved: {map_path}  ({len(m)} datasets, unmatched: {n_bad})")
    if n_bad:
        print(m[m.match_kind == "unmatched"][["dataset_name", "country_guess"]].to_string(index=False))
    # coverage check: matched iso3 present in duration table?
    have_dur = set(dur.iso3)
    missing_dur = m[m.iso3.notna() & ~m.iso3.isin(have_dur)]
    if len(missing_dur):
        print(f"\nISO3 with no duration data ({missing_dur.iso3.nunique()}):")
        print(missing_dur[["dataset_name", "iso3"]].to_string(index=False))


if __name__ == "__main__":
    main()
