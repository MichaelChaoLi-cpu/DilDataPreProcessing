"""
Generic scanner for any MICS WM media-frequency variable.

Classifies value labels into a harmonized 4-level frequency scale:
  0 = Never / Not at all
  1 = Less than once a week (incl. "at least once a month")
  2 = At least once a week (but not every day)
  3 = Almost every day / Every day
 -1 = Sentinel (missing, no response, incoherent, etc.)

Usage:
  python scan_media_frequency_labels.py media_tv_frequency
  python scan_media_frequency_labels.py media_radio_frequency
  python scan_media_frequency_labels.py media_newspaper_frequency

Outputs (written to data/WM/):
  <varname>_label_scan.csv
  <varname>_harmonize_map.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

YAML_DIR = DATA_DIR / "WM" / "raw"
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

# ---------------------------------------------------------------------------
# Keyword classification
# ---------------------------------------------------------------------------

SENTINEL_CODES = {7, 8, 9, 98, 99}

SENTINEL_KEYWORDS = {
    "missing", "manquant", "non déclarée", "non déclaré", "non declaree",
    "no reportado", "omitido", "em falta", "no response", "non reponse",
    "non réponse", "incoherent", "incohérent",
    "no declarado", "not stated", "not reported", "nsp", "nd",
}

NEVER_KEYWORDS = {
    "not at all", "never", "nunca", "pas du tout", "jamais",
}

LESS_THAN_WEEKLY_KEYWORDS = {
    "less than once a week", "rarely",
    "moins d'une fois par semaine", "moins d?une fois par semaine",
    "menos de una vez por semana", "menos de uma vez por semana",
    "at least once a month", "au moins une fois par mois",
    "al menos una vez al mes", "pelo menos uma vez por mês",
}

AT_LEAST_WEEKLY_KEYWORDS = {
    "at least once a week",
    "au moins une fois par semaine",
    "al menos una vez por semana",
    "pelo menos uma vez por semana",
}

ALMOST_DAILY_KEYWORDS = {
    "almost every day", "every day",
    "presque chaque jour", "presque tous les jours",
    "casi todos los días", "casi todos los dias",
    "quase todos os dias",
    "todos los días", "todos los dias",
}


def _norm_code(x) -> str:
    try:
        return str(int(float(x)))
    except (ValueError, TypeError):
        return str(x).strip()


def classify_label(code, label: str) -> int | None:
    if code is not None:
        try:
            if int(float(code)) in SENTINEL_CODES:
                return -1
        except (ValueError, TypeError):
            pass

    if not label or str(label).lower().strip() in {"", "nan"}:
        return None

    low = str(label).lower().strip()
    if low in {"dk", "nsp", "ns", "nd", "nr", "na", "nk"}:
        return -1
    if any(kw in low for kw in SENTINEL_KEYWORDS):
        return -1
    if any(kw in low for kw in ALMOST_DAILY_KEYWORDS):
        return 3
    if any(kw in low for kw in AT_LEAST_WEEKLY_KEYWORDS):
        return 2
    if any(kw in low for kw in LESS_THAN_WEEKLY_KEYWORDS):
        return 1
    if any(kw in low for kw in NEVER_KEYWORDS):
        return 0
    return None


# ---------------------------------------------------------------------------
# Scan + map
# ---------------------------------------------------------------------------

def scan_yaml(rows: list[tuple[str, str]]) -> pd.DataFrame:
    records = []
    for dataset, col in rows:
        yaml_path = YAML_DIR / dataset / "wm.yaml"
        if not yaml_path.exists():
            continue
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cols = data.get("columns", data) if isinstance(data, dict) else data
        for entry in cols:
            if not isinstance(entry, dict):
                continue
            if entry.get("column_in_raw_sav", "").upper() != col.upper():
                continue
            vl = entry.get("value_labels") or {}
            if not vl:
                break
            for code, lbl in vl.items():
                level = classify_label(code, str(lbl) if lbl is not None else "")
                records.append({
                    "dataset_name": dataset,
                    "column_in_raw_sav": col,
                    "raw_code": code,
                    "raw_label": lbl,
                    "freq_level": level,
                })
            break
    return pd.DataFrame(records)


def build_map(scan: pd.DataFrame, varname: str) -> pd.DataFrame:
    scan_lookup = scan[["dataset_name", "raw_code", "freq_level"]].copy()
    scan_lookup["raw_code_str"] = scan_lookup["raw_code"].map(_norm_code)

    conn = psycopg2.connect(**DB_PARAMS)
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT dataset_name, "{varname}"::text AS val, COUNT(*) AS n_rows
            FROM "final_WM_MICS"
            WHERE "{varname}" IS NOT NULL
            GROUP BY dataset_name, "{varname}"
        """)
        db_rows = cur.fetchall()
    finally:
        conn.close()

    df_db = pd.DataFrame(db_rows, columns=["dataset_name", "raw_value", "n_rows"])
    df_db["raw_code_str"] = df_db["raw_value"].map(_norm_code)

    result = df_db.merge(
        scan_lookup[["dataset_name", "raw_code_str", "freq_level"]],
        on=["dataset_name", "raw_code_str"],
        how="left",
    )
    result = result.rename(columns={"freq_level": "harmonized"})
    return result[["dataset_name", "raw_value", "harmonized", "n_rows"]]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scan_media_frequency_labels.py <varname>")
        sys.exit(1)

    varname = sys.argv[1]
    out_scan = DATA_DIR / "WM" / f"{varname}_label_scan.csv"
    out_map  = DATA_DIR / "WM" / f"{varname}_harmonize_map.csv"

    conn = psycopg2.connect(**DB_PARAMS)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT dataset_name, column_in_raw_sav
            FROM "ind_que_WM_MICS"
            WHERE canonical_varname = %s
        """, (varname,))
        df_ind = pd.DataFrame(cur.fetchall(), columns=["dataset_name", "column_in_raw_sav"])
    finally:
        conn.close()

    print(f"[{varname}] Datasets in ind_que: {df_ind['dataset_name'].nunique()}")

    rows = list(df_ind.itertuples(index=False, name=None))
    scan = scan_yaml(rows)
    print(f"  Total label rows:  {len(scan)}")
    print(f"  Auto-classified:   {scan['freq_level'].notna().sum()}/{len(scan)}")

    unclassified = scan[scan["freq_level"].isna()]
    if len(unclassified):
        print(f"  Needs review:      {len(unclassified)}")
        print(unclassified[["dataset_name", "column_in_raw_sav", "raw_code", "raw_label"]].to_string(index=False))
    else:
        print("  Needs review:      0  ✅")

    scan.to_csv(out_scan, index=False)
    print(f"  Scan saved → {out_scan}")

    result = build_map(scan, varname)

    unmapped = result[result["harmonized"].isna()]
    if len(unmapped):
        print(f"\n  Unmapped DB pairs: {len(unmapped)}")
        print(unmapped[["dataset_name", "raw_value", "n_rows"]].to_string(index=False))
    else:
        print("  Unmapped DB pairs: 0  ✅")

    result.to_csv(out_map, index=False)
    print(f"  Harmonize map → {out_map}")

    print("\n  Distribution:")
    valid = result[result["harmonized"].notna() & (result["harmonized"] != -1)]
    sentinel = result[result["harmonized"] == -1]
    labels = {0: "0=Never", 1: "1=<weekly", 2: "2=≥weekly", 3: "3=~daily"}
    for v in [0, 1, 2, 3]:
        n = int(valid[valid["harmonized"] == v]["n_rows"].sum())
        print(f"    {labels[v]:<15} {n:>10,}")
    print(f"    {'sentinel':<15} {int(sentinel['n_rows'].sum() if len(sentinel) else 0):>10,}")


if __name__ == "__main__":
    main()
