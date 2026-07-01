"""
Scan all wm.yaml files to extract value_labels for all columns that map to
education_level. Output two files:

  data/WM/education_label_scan.csv   -- raw labels per (dataset, column, code)
  data/WM/education_harmonize_map.csv -- proposed ISCED 4-level mapping per row above

ISCED harmonization:
  0 = No education / Pre-primary
  1 = Primary
  2 = Secondary (lower + upper)
  3 = Higher / Tertiary
  -1 = Sentinel / Missing (96/97/98/99/DK/inconsistent)
  NaN = Not mapped (needs manual review)

Run:
  python scan_education_labels.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

RAW_DIR = DATA_DIR / "WM" / "raw"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

# ---------------------------------------------------------------------------
# ISCED 4-level keyword rules (applied to lowercased label text)
# Order matters: more specific rules first.
# ---------------------------------------------------------------------------

SENTINEL_CODES = {96.0, 97.0, 98.0, 99.0, 9.0, 9999.0}
SENTINEL_KEYWORDS = {
    # Keep only keywords long enough to avoid false-positive substring matches.
    # Removed 2-letter codes: "na"(→vocational), "nd"(→secondary), "nr", "ns"
    # "nsp" would match "transport" — also removed.
    "missing", "don't know", "do not know", "no response", "inconsistent",
    "not applicable", "refused", "manquant",
    "ne sait pas", "sans objet", "incoherent", "incohérence",
    "incohérent", "no sabe", "donnee manquante", "données manquantes",
    "cannot be determined", "mather not in hh", "don'tk",
    "other, not regular", "other", "autre",
    "mère non dans le ménage", "mere non dans le menage",  # mother not in HH
    "em branco", "nao sabe", "não sabe",    # Portuguese: blank / don't know
    "non déclaré", "non declare",           # French: not declared
    "in branco",                            # Portuguese variant
    "não declarado", "nao declarado",
    # Single standalone codes — only safe when label IS just the abbreviation
    # but substring matching is too risky, so also removed "dk".
}

NONE_KEYWORDS = {
    # English
    "no education", "no schooling", "no school", "none", "never",
    "never attended", "no grade", "0 years", "zero", "nunca",
    "without education", "not educated", "illiterate",
    "preschool", "pre-school", "pre school", "pre-primary", "pre primary",
    "nursery", "nursey", "kindergarten", "kg",
    "early childhood", "ece",
    "day care",
    # French
    "sans instruction", "sans education", "sans niveau", "sans",
    "aucun", "jamais", "préscolaire", "prescolaire", "maternelle",
    "pré-scolaire", "pre-scolaire",
    "pré escolar", "non or ece", "nenhum",
    # Spanish / Portuguese
    "sin educación", "sin educacion", "ninguno", "ninguna",
    "nenhuma", "pre escolar", "pre-escolar",
    "inicial", "jardín", "jardim", "grado especial",
    # Dutch
    "kleuterschool",
    # Spanish / other language variants
    "preescolar", "pré-escolar", "pré escolar",
    "sin escolarización", "sin escolarizacion",
    "primera infancia",   # "educación para la primera infancia"
    "not school",
    "pre-primario", "preprimario",   # Spanish: pre-primary
    # Religious/informal primary-equivalent — map to 0
    "khalwa", "coranique", "mahadra", "ecole coranique",
    "koranic", "pre school madrasa",
}

PRIMARY_KEYWORDS = {
    # English
    "primary", "elementary", "elementar", "basic", "baisic",
    "grade 1", "grade 2", "grade 3", "grade 4", "grade 5", "grade 6",
    "grades 1", "grades 2", "grades 3", "grades 4", "grades 5",
    "primary incomplete", "primary complete",
    "ecole primaire",
    "reception", "infant",   # UK infant/primary years
    "initial",               # some MICS2 use "initial" for primary
    # Spanish / Portuguese
    "primaria", "primário", "primaire", "básico", "basico", "básica",
    "sd",                    # Indonesia: Sekolah Dasar
    "eeb",                   # Paraguay: Educación Escolar Básica (grades 1-9)
    "egb",                   # Argentina/Ecuador: Educación General Básica
    "programas de alfabetización", "literacy program",
    # Non-formal/informal equivalent to primary
    "non-formal", "non formal", "nonformal", "non formel",
    "programme non-formel", "programme informel", "programme non formel",
    "programme non-formel", "informal programme",
    "curriculo nao official", "curriculo não official",  # Guinea-Bissau
    "non official", "non-official",
    "fondamental",           # French: fondamental 1/2 in CAR/Congo = primary level
    "literacy",              # Lesotho MELEVEL literacy = non-formal primary
    "jamal",                 # Pakistan non-formal literacy program
    "adult literacy",
    # Dutch
    "basis speciaal",        # special primary school (Netherlands)
    "lagere school", "basisonderwijs",   # Dutch: primary school / basic education
    # Other language
    "elemantry",
}

SECONDARY_KEYWORDS = {
    # English
    "secondary", "secondaire", "middle", "junior",
    "lower secondary", "upper secondary",
    "high school", "highschool", "senior secondary",
    "secondary incomplete", "secondary complete",
    "secondary or higher",
    "lycee", "lycée",
    "enseignement secondaire",
    "baccalauréat", "baccalaureat",
    "moyen", "troisième", "première", "terminale",
    "secondary education",
    "vocational", "technical", "vocation", "technic",
    "professional", "professionnel",
    "post-primary", "post primary",
    "initial vocational", "high technical",
    "master craft",
    "voc./comm./tech", "voc/comm/tech",
    "vet", "tvet",
    # Spanish / Portuguese / country-specific
    "bachillerato", "bacharel", "bacharelato",
    "polimodal",             # Argentina: upper secondary
    "diversificado",         # Central America: upper secondary
    "media", "educ. media", "educación media", "educacion media",
    "ex bachillerato",
    "pre universitario", "pre-universitario",
    "preuniversitario", "pre universitaria",
    "obrero calificado",     # Cuba: skilled worker (vocational secondary)
    "ciclo comun",           # Honduras: lower secondary
    "sss", "shs",            # Ghana: Senior Secondary School
    "jss", "jhs",            # Ghana: Junior Secondary/High School (lower sec)
    "matric", "matriculation",  # South Africa: grade 12 / secondary completion
    "sm", "smp",             # Indonesia: Sekolah Menengah (secondary)
    "polyvalent", "pts",
    "texnikum", "texnikumi", # Russian/CIS: technical secondary
    "collège", "college prep",
    # French vocational
    "format. prof", "cap", "btp", "bts",
    "enseignement technique", "technique professionnel",
    # Other
    "high",                  # short label "High" in some datasets
    "general high",
    "average",               # some CIS datasets: "Average" = incomplete secondary
    "average - special",
    "intermediat", "intermediate",
    "preparatory",           # Egypt: preparatory = middle school (lower secondary)
    "assas",                 # Algeria: possibly "assas" level = secondary
    "ptu",                   # Russia: vocational lower-secondary
    "eeb (3er ciclo)",       # Paraguay: upper cycle of basic = lower secondary
    "smp/sm",                # Indonesia
    "terciaria no univ",     # tertiary non-university = vocational post-sec; leave as 2
    "cet", "itvet", "votec",
    "tech voc", "tech. voc",
    "special needs education",  # treat as secondary equivalent
    "faa special school",
    "adult education",       # treat as secondary equivalent
    "religious school",      # classify above primary
    "tech/voc", "voc/ comm", "prof/t",    # vocational/technical (space variants)
    "general education school", "general educational school",  # Mongolia
    "preporatory",           # typo of preparatory (Palestine)
    "certificate",           # Thailand VCE/TCE certificate
    # Spanish / Portuguese secondary
    "secundaria", "secundário", "secundario", "secundária",
    "secundare",             # typo of secondaire
    "gymnasium",             # Russian/CIS: secondary school (gymnasium)
    "teknikum", "texnikum",
    # Indonesian
    "sekolah menengah",
    # French secondary
    "fondamental 2",         # CAR/Congo: fondamental 2 = lower secondary (grades 7-9)
    # Typos / phonetic spellings
    "secondare",             # typo of secondaire
    # Dutch special education (primary level but in secondary section = treat as 2?)
    # "basis speciaal" → actually primary level → goes to PRIMARY
    # Non-standard curriculum appears at code 5-6 in many MICS2 datasets.
    # Usually means informal/non-formal secondary-equivalent → classify as 2.
    "non-standard", "nonstandard", "non standard", "non-standart", "nonstandart",
    "tecnico profissional", "técnico profissional",  # Sao Tome Portuguese vocational
}

HIGHER_KEYWORDS = {
    # English
    "higher", "tertiary", "university", "college",
    "bachelor", "master", "doctorate", "phd", "ph.d",
    "post-secondary", "post secondary", "post sec",
    "supérieur", "superieur", "superior",
    "enseignement supérieur",
    "graduate", "postgraduate", "post graduate", "posgrado", "postgrado",
    "diploma", "degree", "licence",
    "master's", "doctor", "associates",
    "bsc", "msc", "mba",
    "upper secondary and higher",  # combined code spanning 2+3 — err toward 3
    # Spanish / Portuguese
    "terciaria", "terciario", "universitaria", "universitario",
    "universitaire",
    # Other
    "academy",
    "long apprentice", "short apprentice",  # Suriname: post-secondary apprenticeship
    "brevet de technicien", "bts",          # France BTS = post-secondary vocational
    "unvirsty",
    "diplome", "diplôme",    # Iraq WM11 code 4: diploma = post-secondary
    # Spanish / Portuguese
    "terciário", "terciario",   # Portuguese: tertiary
    "posgrado", "postgrado",
    "universitário",
}


def _fix_mojibake(s: str) -> str:
    """Attempt to fix Latin-1 mojibake in strings (e.g. 'PrÃ©' → 'Pré')."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def classify_label(code: float | None, label: str) -> int | None:
    """Return 0/1/2/3/-1/None.  None means needs manual review."""
    if code is None:
        return None
    if code in SENTINEL_CODES:
        return -1
    label = _fix_mojibake(label)
    low = label.lower().strip()
    if not low or low == "nan":
        return None
    # Exact-match short abbreviations (too short for safe substring check)
    if low in {"dk", "nsp", "ns", "nd", "nr", "na", "n/a", "n.a.", "n.r.", "n.s."}:
        return -1
    if any(kw in low for kw in SENTINEL_KEYWORDS):
        return -1
    # Pre-primary guard: must come before PRIMARY because "primary" is a substring
    # of "pre-primary", "pre-primary or none", etc.  Note: "Primary, pre-primary or none"
    # still falls through to PRIMARY below (it starts with "Primary").
    _pre_primary = {
        "pre-primary", "pre primary", "pré-primaire", "pre-primaire",
        "pre-primary or none", "preprimaire", "préprimaire",
        "prebásic", "prebasic",   # Honduras: pre-básica (pre-school)
        "pre-scolaire", "préscolaire",  # variant spellings
    }
    if any(kw in low for kw in _pre_primary) and not low.startswith("primary"):
        return 0
    if any(kw in low for kw in HIGHER_KEYWORDS):
        return 3
    if any(kw in low for kw in SECONDARY_KEYWORDS):
        return 2
    if any(kw in low for kw in PRIMARY_KEYWORDS):
        return 1
    if any(kw in low for kw in NONE_KEYWORDS):
        return 0
    return None


# ---------------------------------------------------------------------------
# Build target column set from ind_que
# ---------------------------------------------------------------------------

def get_edu_cols_per_dataset() -> dict[str, list[str]]:
    """Return {dataset_name: [col1, col2, ...]} from ind_que for education_level."""
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT dataset_name, column_in_raw_sav
                FROM "ind_que_WM_MICS"
                WHERE canonical_varname = 'education_level'
                ORDER BY dataset_name, column_in_raw_sav
            """)
            rows = cur.fetchall()
    finally:
        conn.close()
    result: dict[str, list[str]] = {}
    for ds, col in rows:
        result.setdefault(ds, []).append(col)
    return result


# ---------------------------------------------------------------------------
# Scan yaml files
# ---------------------------------------------------------------------------

def extract_value_labels(wm_yaml: Path, target_cols: list[str]) -> list[dict]:
    """Parse wm.yaml and return value-label rows for target columns."""
    try:
        with open(wm_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"  WARN: cannot parse {wm_yaml}: {e}")
        return []

    # wm.yaml has a top-level 'columns' key containing the list
    if isinstance(data, dict):
        entries = data.get("columns", [])
    elif isinstance(data, list):
        entries = data
    else:
        return []

    rows = []
    for entry in entries:
        col = entry.get("column_in_raw_sav", "")
        if col not in target_cols:
            continue
        labels = entry.get("value_labels") or {}
        col_label = entry.get("column_label_in_raw_sav", "")
        if not labels:
            # No value labels at all — record a placeholder so we know
            rows.append({
                "column_in_raw_sav": col,
                "column_label": col_label,
                "raw_code": None,
                "raw_label": "(no value labels in yaml)",
                "isced": None,
            })
        else:
            for code, lbl in sorted(labels.items(), key=lambda x: str(x[0])):
                try:
                    fcode = float(code)
                except (ValueError, TypeError):
                    fcode = None
                rows.append({
                    "column_in_raw_sav": col,
                    "column_label": col_label,
                    "raw_code": fcode,
                    "raw_label": str(lbl),
                    "isced": classify_label(fcode, str(lbl)) if fcode is not None else None,
                })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    edu_cols = get_edu_cols_per_dataset()
    print(f"Datasets with education_level in ind_que: {len(edu_cols)}")

    all_rows = []
    no_yaml = []
    no_cols_found = []

    for ds_name, cols in sorted(edu_cols.items()):
        ds_dir = RAW_DIR / ds_name
        wm_yaml = ds_dir / "wm.yaml"
        if not wm_yaml.exists():
            no_yaml.append(ds_name)
            continue
        rows = extract_value_labels(wm_yaml, cols)
        if not rows:
            no_cols_found.append(ds_name)
            continue
        for r in rows:
            r["dataset_name"] = ds_name
        all_rows.extend(rows)

    print(f"  Missing wm.yaml:          {len(no_yaml)}")
    print(f"  Col not found in yaml:    {len(no_cols_found)}")
    print(f"  Total label rows:         {len(all_rows)}")

    df = pd.DataFrame(all_rows, columns=[
        "dataset_name", "column_in_raw_sav", "column_label",
        "raw_code", "raw_label", "isced"
    ])

    # Mark which rows need manual review
    df["needs_review"] = df["isced"].isna()

    out_scan = DATA_DIR / "WM" / "education_label_scan.csv"
    df.to_csv(out_scan, index=False)
    print(f"\nScan saved → {out_scan}")

    # Summary: how many labels need manual review?
    n_review = df[df["needs_review"]].shape[0]
    n_total = df[df["raw_code"].notna()].shape[0]
    print(f"Auto-classified: {n_total - n_review}/{n_total} rows")
    print(f"Needs review:    {n_review} rows")

    if n_review > 0:
        print("\nUnclassified labels (sample):")
        sample = (df[df["needs_review"] & df["raw_code"].notna()]
                  [["dataset_name", "column_in_raw_sav", "raw_code", "raw_label"]]
                  .drop_duplicates(subset=["raw_label"])
                  .head(40))
        print(sample.to_string(index=False))

    if no_yaml:
        print(f"\nDatasets missing wm.yaml ({len(no_yaml)}):")
        for d in no_yaml:
            print(f"  {d}")

    if no_cols_found:
        print(f"\nDatasets where target cols not in wm.yaml ({len(no_cols_found)}):")
        for d in no_cols_found:
            print(f"  {d}")


if __name__ == "__main__":
    main()
