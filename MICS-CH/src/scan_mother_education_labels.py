"""
Scan all ch.yaml files to extract value_labels for columns mapped to
mother_education, then auto-classify each code to ISCED 4-level.

Outputs:
  data/CH/mother_education_label_scan.csv
  data/CH/mother_education_harmonize_map.csv

Run:
  python scan_mother_education_labels.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

RAW_DIR = DATA_DIR / "CH" / "raw"
CH_YAML = DATA_DIR / "CH" / "alignment_v2.yaml"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

# ---------------------------------------------------------------------------
# Classification rules  (identical to WM scan — shared multilingual keywords)
# ---------------------------------------------------------------------------

SENTINEL_CODES = {96.0, 97.0, 98.0, 99.0, 9.0, 9999.0}
SENTINEL_KEYWORDS = {
    "missing", "don't know", "do not know", "no response", "inconsistent",
    "not applicable", "refused", "manquant",
    "ne sait pas", "sans objet", "incoherent", "incohérence",
    "incohérent", "no sabe", "donnee manquante", "données manquantes",
    "cannot be determined", "mather not in hh", "don'tk",
    "other, not regular", "other", "autre",
    "mère non dans le ménage", "mere non dans le menage",
    "em branco", "nao sabe", "não sabe",
    "non déclaré", "non declare",
    "não declarado", "nao declarado",
    # Mother not in household (various languages)
    "not in hh", "no living in hh", "not living in hh",
    "não vive no agregado", "nao vive no agregado",
    "não vive no af", "nao vive no af",
    "no vive en el hogar", "no está en el hogar", "no esta en el hogar",
    "not in household",
    # Other sentinel
    "no information", "no se puede determinar",
    "nsp/nd", "nsp/nr",
}

NONE_KEYWORDS = {
    "no education", "no schooling", "no school", "none", "never",
    "never attended", "no grade", "0 years", "zero", "nunca",
    "without education", "not educated", "illiterate",
    "preschool", "pre-school", "pre school", "pre-primary", "pre primary",
    "nursery", "nursey", "kindergarten", "kg",
    "early childhood", "ece",
    "day care",
    "sans instruction", "sans education", "sans niveau", "sans",
    "aucun", "jamais", "préscolaire", "prescolaire", "maternelle",
    "pré-scolaire", "pre-scolaire",
    "pré escolar", "non or ece", "nenhum",
    "sin educación", "sin educacion", "ninguno", "ninguna",
    "sin instruccion", "sin instrucción",  # Bolivia: no education
    "non scolarisé", "non scolarise",      # French: not schooled
    "nenhuma", "pre escolar", "pre-escolar",
    "inicial", "jardín", "jardim", "grado especial",
    "kleuterschool",
    "preescolar", "pré-escolar", "pré escolar",
    "sin escolarización", "sin escolarizacion",
    "primera infancia",
    "not school",
    "pre-primario", "preprimario",
    "khalwa", "coranique", "mahadra", "ecole coranique",
    "koranic", "pre school madrasa",
}

PRIMARY_KEYWORDS = {
    "primary", "elementary", "elementar", "basic", "baisic",
    "grade 1", "grade 2", "grade 3", "grade 4", "grade 5", "grade 6",
    "grades 1", "grades 2", "grades 3", "grades 4", "grades 5",
    "primary incomplete", "primary complete",
    "ecole primaire",
    "reception", "infant",
    "initial",
    "primaria", "primário", "primaire", "básico", "basico", "básica",
    "sd",
    "eeb", "egb",
    "programas de alfabetización", "literacy program",
    "non-formal", "non formal", "nonformal", "non formel",
    "non-fomel", "non fomel",   # typo variant seen in Togo
    "programme non-formel", "programme informel", "programme non formel",
    "programme non-formel", "informal programme",
    "paket a", "package a",    # Indonesia non-formal primary equivalent
    "néant",                   # French: nothing = no education
    "curriculo nao official", "curriculo não official",
    "non official", "non-official",
    "fondamental",
    "literacy",
    "jamal",
    "adult literacy",
    "basis speciaal",
    "lagere school", "basisonderwijs",
    "elemantry",
}

SECONDARY_KEYWORDS = {
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
    "bachillerato", "bacharel", "bacharelato",
    "polimodal",
    "diversificado",
    "media", "educ. media", "educación media", "educacion media",
    "ex bachillerato",
    "pre universitario", "pre-universitario",
    "preuniversitario", "pre universitaria",
    "obrero calificado",
    "ciclo comun",
    "sss", "shs",
    "jss", "jhs",
    "matric", "matriculation",
    "sm", "smp",
    "polyvalent", "pts",
    "texnikum", "texnikumi",
    "collège", "college prep",
    "format. prof", "cap", "btp",
    "enseignement technique", "technique professionnel",
    "high",
    "general high",
    "average",
    "average - special",
    "intermediat", "intermediate",
    "preparatory",
    "assas",
    "ptu",
    "eeb (3er ciclo)",
    "smp/sm",
    "terciaria no univ",
    "cet", "itvet", "votec",
    "tech voc", "tech. voc",
    "special needs education",
    "faa special school",
    "adult education",
    "religious school",
    "tech/voc", "voc/ comm", "prof/t",
    "general education school", "general educational school",
    "preporatory",
    "certificate",
    "secundaria", "secundário", "secundario", "secundária",
    "secundare",
    "gymnasium",
    "teknikum", "texnikum",
    "sekolah menengah",
    "fondamental 2",
    "secondare",
    "non-standard", "nonstandard", "non standard", "non-standart", "nonstandart",
    "tecnico profissional", "técnico profissional",
    "paket b", "package b",   # Indonesia non-formal secondary equivalent
}

HIGHER_KEYWORDS = {
    "higher", "tertiary", "university", "college",
    "bachelor", "master", "doctorate", "phd", "ph.d",
    "post-secondary", "post secondary", "post sec",
    "supérieur", "superieur", "superior",
    "enseignement supérieur",
    "graduate", "postgraduate", "post graduate", "posgrado", "postgrado",
    "diploma", "degree", "licence",
    "master's", "doctor", "associates",
    "bsc", "msc", "mba",
    "upper secondary and higher",
    "terciaria", "terciario", "universitaria", "universitario",
    "universitaire",
    "terciário", "terciario",
    "posgrado", "postgrado",
    "universitário",
    "academy",
    "long apprentice", "short apprentice",
    "brevet de technicien", "bts",
    "unvirsty",
    "diplome", "diplôme",
}

_PRE_PRIMARY = {
    "pre-primary", "pre primary", "pré-primaire", "pre-primaire",
    "pre-primary or none", "preprimaire", "préprimaire",
    "prebásic", "prebasic",
    "pre-scolaire", "préscolaire",
}


def _fix_mojibake(s: str) -> str:
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def classify_label(code: float | None, label: str) -> int | None:
    if code is None:
        return None
    if code in SENTINEL_CODES:
        return -1
    label = _fix_mojibake(label)
    low = label.lower().strip()
    if not low or low == "nan":
        return None
    if low in {"dk", "nsp", "ns", "nd", "nr", "na", "n/a", "n.a.", "n.r.", "n.s."}:
        return -1
    if any(kw in low for kw in SENTINEL_KEYWORDS):
        return -1
    if any(kw in low for kw in _PRE_PRIMARY) and not low.startswith("primary"):
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
# DB helpers
# ---------------------------------------------------------------------------

def get_edu_cols_per_dataset() -> dict[str, list[str]]:
    conn = psycopg2.connect(**DB_PARAMS)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT dataset_name, column_in_raw_sav
                FROM "ind_que_CH_MICS"
                WHERE canonical_varname = 'mother_education'
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
# Scan
# ---------------------------------------------------------------------------

def extract_value_labels(ch_yaml: Path, target_cols: list[str]) -> list[dict]:
    try:
        with open(ch_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"  WARN: {ch_yaml}: {e}")
        return []

    entries = data.get("columns", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []

    rows = []
    for entry in entries:
        col = entry.get("column_in_raw_sav", "")
        if col not in target_cols:
            continue
        labels = entry.get("value_labels") or {}
        col_label = entry.get("column_label_in_raw_sav", "")
        if not labels:
            rows.append({
                "column_in_raw_sav": col,
                "column_label": col_label,
                "raw_code": None,
                "raw_label": "(no value labels)",
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
# Build harmonize map
# ---------------------------------------------------------------------------

def build_map(scan: pd.DataFrame, col_prio: pd.DataFrame) -> pd.DataFrame:
    import psycopg2, numpy as np
    conn = psycopg2.connect(**DB_PARAMS)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT dataset_name, mother_education::text AS mother_education, COUNT(*) AS n_rows
            FROM "final_CH_MICS"
            WHERE mother_education IS NOT NULL
            GROUP BY dataset_name, mother_education
        """)
        db_pairs = pd.DataFrame(cur.fetchall(),
                                columns=["dataset_name", "edu_val", "n_rows"])
    conn.close()
    db_pairs["raw_code"] = pd.to_numeric(db_pairs["edu_val"], errors="coerce")

    scan_p = scan.merge(col_prio, on=["dataset_name", "column_in_raw_sav"], how="left")
    scan_p["col_rank"] = scan_p["col_rank"].fillna(99)

    scan_valid = scan_p[(scan_p["isced"].notna()) & (scan_p["isced"] >= 0)].copy()
    best = (scan_valid.sort_values("col_rank")
            .groupby(["dataset_name", "raw_code"]).first().reset_index()
            [["dataset_name", "raw_code", "column_in_raw_sav", "col_rank", "raw_label", "isced"]])

    sentinel = (scan_p[scan_p["isced"] == -1]
                .groupby(["dataset_name", "raw_code"]).first().reset_index()
                [["dataset_name", "raw_code"]])
    sentinel["is_sentinel"] = True

    result = db_pairs.merge(best, on=["dataset_name", "raw_code"], how="left")
    result = result.merge(sentinel, on=["dataset_name", "raw_code"], how="left")
    result["is_sentinel"] = result["is_sentinel"].fillna(False)
    result["harmonized"] = result["isced"]
    result.loc[result["is_sentinel"] & result["harmonized"].isna(), "harmonized"] = -1
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import numpy as np
    edu_cols = get_edu_cols_per_dataset()
    print(f"Datasets with mother_education in ind_que: {len(edu_cols)}")

    all_rows: list[dict] = []
    for ds_name, cols in sorted(edu_cols.items()):
        ch_yaml = RAW_DIR / ds_name / "ch.yaml"
        if not ch_yaml.exists():
            print(f"  WARN: missing {ch_yaml}")
            continue
        rows = extract_value_labels(ch_yaml, cols)
        for r in rows:
            r["dataset_name"] = ds_name
        all_rows.extend(rows)

    scan = pd.DataFrame(all_rows, columns=[
        "dataset_name", "column_in_raw_sav", "column_label",
        "raw_code", "raw_label", "isced"
    ])
    scan["needs_review"] = scan["isced"].isna()

    out_scan = DATA_DIR / "CH" / "mother_education_label_scan.csv"
    scan.to_csv(out_scan, index=False)

    n_total = scan[scan["raw_code"].notna()].shape[0]
    n_review = scan[scan["needs_review"] & scan["raw_code"].notna()].shape[0]
    print(f"Total label rows:  {len(scan)}")
    print(f"Auto-classified:   {n_total - n_review}/{n_total}")
    print(f"Needs review:      {n_review}")

    if n_review:
        print("\nUnclassified:")
        sample = (scan[scan["needs_review"] & scan["raw_code"].notna()]
                  [["dataset_name", "column_in_raw_sav", "raw_code", "raw_label"]]
                  .drop_duplicates("raw_label").head(40))
        print(sample.to_string(index=False))

    # Build column priority from alignment yaml
    print("\nReading CH alignment yaml for column priority ...")
    with open(CH_YAML) as f:
        alignment = yaml.safe_load(f)
    entries = alignment.get("mother_education", [])
    col_order = [{"dataset_name": e.get("dataset_name"),
                  "column_in_raw_sav": e.get("column_in_raw_sav")}
                 for e in entries]
    col_prio = pd.DataFrame(col_order)
    col_prio["col_rank"] = col_prio.groupby("dataset_name").cumcount()

    # Build harmonize map
    result = build_map(scan, col_prio)

    total = result["n_rows"].sum()
    print("\n=== 映射分布 ===")
    for lvl, lbl in [(0,"0-无教育"),(1,"1-小学"),(2,"2-中学"),(3,"3-高等"),(-1,"sentinel→NaN"),(np.nan,"未映射NaN")]:
        if pd.isna(lvl):
            n = result[result["harmonized"].isna()]["n_rows"].sum()
        else:
            n = result[result["harmonized"] == lvl]["n_rows"].sum()
        print(f"  {lbl:<20} {int(n):>8,}  ({100*n/total:.1f}%)")

    unmapped = result[result["harmonized"].isna()]
    print(f"\n未映射pairs: {len(unmapped)}")
    if len(unmapped):
        print(unmapped[["dataset_name","edu_val","n_rows"]].sort_values("n_rows",ascending=False).head(10).to_string(index=False))

    out_map = DATA_DIR / "CH" / "mother_education_harmonize_map.csv"
    result.to_csv(out_map, index=False)
    print(f"\nScan  → {out_scan}")
    print(f"Map   → {out_map}")


if __name__ == "__main__":
    main()
