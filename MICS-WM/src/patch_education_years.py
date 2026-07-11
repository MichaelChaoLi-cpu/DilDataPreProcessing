"""
P09 step 3 — Construct years-of-schooling variables.

  WM: education_years, education_years_estimated
  HL: education_years, education_years_estimated
  CH: mother_education_years, mother_education_years_estimated
      (WM-linked first, HL fallback, coarse 4-level midpoint last resort)

Formula
-------
  years = base(fine_level, durations at school-entry year) + grade_within_level

  fine_level (education_level_fine_map.csv): 0 none/pre · 1 primary ·
    2 secondary-combined · 21 lower sec · 22 upper sec · 3 higher · -1 sentinel
  base: 0/1→0 · 2/21→prim · 22→prim+lowsec · 3→prim+lowsec+upsec
  durations: World Bank series (school_durations.csv) looked up at
    entry_year = survey_year − age + 6 (dataset median age when missing);
    nearest year fallback, then (6,3,3).

Per-dataset grade semantics
---------------------------
  attended-coding (label says "attended"): grade−1 when the completion flag
    (education_grade_completed / ever_completed_grade) == 2 (No)
  cumulative-coding (>=10% of primary-level grades exceed prim_dur+1):
    years = grade directly

Missing grade with known level → midpoint estimate (base + level_dur/2;
higher → base+2), flagged *_estimated = 1. "Never attended school" → 0, exact.
Years capped at 25.

Usage:
  python patch_education_years.py wm|hl|ch [--dry-run]
  (run wm and hl before ch — ch links to their parquet outputs)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

_PROJECT_ROOT = Path(__file__).parent.parent.parent
WM_ROOT = _PROJECT_ROOT / "MICS-WM" / "data" / "WM"
HL_ROOT = _PROJECT_ROOT / "MICS-HL" / "data" / "HL"
CH_ROOT = _PROJECT_ROOT / "MICS-CH" / "data" / "CH"

WM_PARQUET = WM_ROOT / "processed_data" / "wm_merged.parquet"
HL_PARQUET = HL_ROOT / "processed_data" / "hl_merged.parquet"
CH_PARQUET = CH_ROOT / "processed_data" / "ch_merged.parquet"

DUR_CSV = WM_ROOT / "school_durations.csv"
ISO_CSV = WM_ROOT / "dataset_iso3_map.csv"

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
GRADE_SENTINELS = {77, 88, 90, 94, 95, 96, 97, 98, 99}
ATTENDED_PAT = re.compile(r"attend|fr[ée]quent|atteinte|asisti|asiste|frequentou", re.I)
COMPLETED_PAT = re.compile(r"complet|achev|termin|aprobado|completou|r[ée]ussie", re.I)
CAP_YEARS = 25.0


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------

def load_durations() -> dict[str, pd.DataFrame]:
    dur = pd.read_csv(DUR_CSV)
    out = {}
    for iso3, g in dur.groupby("iso3"):
        s = (g.set_index("year")[["prim_dur", "lowsec_dur", "upsec_dur"]]
              .reindex(range(1970, 2024)).ffill().bfill())
        out[iso3] = s
    return out


def load_iso_map() -> pd.DataFrame:
    return pd.read_csv(ISO_CSV).set_index("dataset_name")


def load_fine_candidates(csv_path: Path) -> dict[str, dict[str, dict[float, float]]]:
    """Per dataset, per raw column: {code: fine_level}.

    Some datasets carry several level columns with incompatible codings; the
    right one is chosen in build_years by matching observed parquet codes.
    """
    fm = pd.read_csv(csv_path)
    fm = fm.dropna(subset=["fine_level", "raw_code"])
    out: dict[str, dict[str, dict[float, float]]] = {}
    for _, r in fm.iterrows():
        col = str(r.get("column_in_raw_sav") or "?")
        (out.setdefault(r.dataset_name, {})
            .setdefault(col, {}))[float(r.raw_code)] = float(r.fine_level)
    return out


def pick_fine_map(candidates: dict[str, dict[float, float]],
                  observed: set[float]) -> dict[float, float]:
    """Choose the candidate column whose code set best matches the data."""
    if not candidates:
        return {}
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    best, best_score = None, -1.0
    for col, mapping in candidates.items():
        codes = set(mapping)
        union = codes | observed
        score = len(codes & observed) / len(union) if union else 0.0
        if score > best_score:
            best, best_score = mapping, score
    return best or {}


def load_grade_semantics(ind_que_table: str, grade_canonical: str) -> dict[str, str]:
    """Per dataset: 'attended' or 'completed' coding of the grade variable."""
    conn = psycopg2.connect(**DB_PARAMS)
    with conn.cursor() as cur:
        cur.execute(f'''
            SELECT dataset_name, column_label_in_english
            FROM "{ind_que_table}"
            WHERE canonical_varname = %s
        ''', (grade_canonical,))
        rows = cur.fetchall()
    conn.close()
    result: dict[str, str] = {}
    for ds, label in rows:
        lab = label or ""
        kind = None
        if COMPLETED_PAT.search(lab):
            kind = "completed"
        elif ATTENDED_PAT.search(lab):
            kind = "attended"
        prev = result.get(ds)
        if prev == "completed" or kind is None:
            continue
        result[ds] = kind if prev is None or kind == "completed" else prev
    return result


# ---------------------------------------------------------------------------
# Core construction
# ---------------------------------------------------------------------------

def build_years(
    df: pd.DataFrame,
    *,
    level_col: str,
    grade_col: str,
    completed_col: str | None,
    ever_col: str | None,
    age_col: str | None,
    fine_candidates: dict[str, dict[str, dict[float, float]]],
    grade_semantics: dict[str, str],
    durations: dict[str, pd.DataFrame],
    iso_map: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Return (years, estimated_flag) aligned to df.index."""
    n = len(df)
    years = np.full(n, np.nan)
    est = np.full(n, np.nan)

    level = pd.to_numeric(df[level_col], errors="coerce").values
    grade = pd.to_numeric(df[grade_col], errors="coerce").values
    grade = np.where(np.isin(grade, list(GRADE_SENTINELS)) | (grade < 0) | (grade > 30),
                     np.nan, grade)
    completed = (pd.to_numeric(df[completed_col], errors="coerce").values
                 if completed_col else np.full(n, np.nan))
    ever = (pd.to_numeric(df[ever_col], errors="coerce").values
            if ever_col else np.full(n, np.nan))
    age = (pd.to_numeric(df[age_col], errors="coerce").values
           if age_col else np.full(n, np.nan))

    ds_arr = df["dataset_name"].values
    flagged: dict[str, list[str]] = {"compound": [], "cumulative": []}
    for ds in pd.unique(ds_arr):
        m = ds_arr == ds
        idx = np.where(m)[0]
        try:
            iso3 = iso_map.loc[ds, "iso3"]
            survey_year = int(iso_map.loc[ds, "survey_year"])
        except KeyError:
            continue
        dur_tbl = durations.get(iso3)

        ds_age = age[idx]
        med_age = np.nanmedian(ds_age) if np.isfinite(ds_age).any() else 25.0
        entry = survey_year - (np.where(np.isfinite(ds_age), ds_age, med_age) - 6)
        entry = np.clip(entry, 1970, 2023).astype(int)

        if dur_tbl is not None:
            p = dur_tbl["prim_dur"].reindex(entry).values
            ls = dur_tbl["lowsec_dur"].reindex(entry).values
            us = dur_tbl["upsec_dur"].reindex(entry).values
        else:
            p = ls = us = np.full(len(idx), np.nan)
        p = np.where(np.isfinite(p), p, 6.0)
        ls = np.where(np.isfinite(ls), ls, 3.0)
        us = np.where(np.isfinite(us), us, 3.0)

        observed = {float(v) for v in level[idx] if np.isfinite(v)}
        fine_map = pick_fine_map(fine_candidates.get(ds, {}), observed)
        fl = np.array([fine_map.get(v, np.nan) if np.isfinite(v) else np.nan
                       for v in level[idx]])
        g = grade[idx].copy()

        # attended-coding: grade-1 when completion flag says No
        if grade_semantics.get(ds) == "attended":
            notdone = completed[idx] == 2
            g = np.where(notdone & np.isfinite(g), np.maximum(g - 1, 0), g)

        # compound coding (level*10+grade, e.g. 11-16/21-26): decode grade = g % 10
        finite_g = g[np.isfinite(g)]
        if len(finite_g) >= 50:
            decade_share = ((finite_g >= 10) & (finite_g <= 39)).mean()
            if decade_share >= 0.5:
                g = np.where(np.isfinite(g) & (g >= 10) & (g <= 39), g % 10, g)
                flagged["compound"].append(ds)

        base = np.select(
            [np.isin(fl, [0.0, 1.0]), np.isin(fl, [2.0, 21.0]), fl == 22.0, fl == 3.0],
            [0.0, p, p + ls, p + ls + us],
            default=np.nan,
        )
        level_dur = np.select(
            [fl == 0.0, fl == 1.0, fl == 2.0, fl == 21.0, fl == 22.0, fl == 3.0],
            [0.0, p, ls + us, ls, us, 4.0],
            default=np.nan,
        )

        # cumulative-coding detection: within-level grades must not exceed the
        # level duration; run over all school levels (higher excluded — its
        # grades legitimately run past the nominal duration)
        school = np.isin(fl, [1.0, 2.0, 21.0, 22.0]) & np.isfinite(g) & np.isfinite(level_dur)
        cumulative = False
        if school.sum() >= 50:
            exceed = (g[school] > level_dur[school] + 1).mean()
            cumulative = exceed >= 0.10
            if cumulative:
                flagged["cumulative"].append(ds)

        y = np.full(len(idx), np.nan)
        e = np.full(len(idx), np.nan)

        known = np.isfinite(fl) & (fl >= 0)
        with_g = known & np.isfinite(g)
        if cumulative:
            # grade is a cumulative class count → years = grade for school levels;
            # school grade says nothing about tertiary years → midpoint estimate
            sch_g = with_g & (fl != 3.0)
            y[sch_g] = g[sch_g]
            e[sch_g] = 0
            higher = known & (fl == 3.0)
            y[higher] = base[higher] + 2.0
            e[higher] = 1
        else:
            y[with_g] = base[with_g] + g[with_g]
            e[with_g] = 0

        # level 0: zero years regardless of grade
        zero = known & (fl == 0.0)
        y[zero] = 0.0
        e[zero] = 0

        # level known, grade missing → midpoint estimate
        no_g = known & ~np.isfinite(g) & (fl != 0.0)
        y[no_g] = base[no_g] + np.where(fl[no_g] == 3.0, 2.0,
                                        np.round(level_dur[no_g] / 2))
        e[no_g] = 1

        # never attended school → 0, exact
        never = ~np.isfinite(y) & (ever[idx] == 2)
        y[never] = 0.0
        e[never] = 0

        y = np.clip(y, 0, CAP_YEARS)
        years[idx] = y
        est[idx] = e

    print(f"compound-coded datasets ({len(flagged['compound'])}): {flagged['compound']}")
    print(f"cumulative-coded datasets ({len(flagged['cumulative'])}): {flagged['cumulative']}")
    return (pd.Series(years, index=df.index, dtype="Float64"),
            pd.Series(est, index=df.index, dtype="Float64"))


# ---------------------------------------------------------------------------
# Module runners
# ---------------------------------------------------------------------------

def run_wm(dry: bool) -> None:
    print(f"loading {WM_PARQUET} ...")
    df = pd.read_parquet(WM_PARQUET)
    years, est = build_years(
        df,
        level_col="education_level",
        grade_col="education_grade",
        completed_col="education_grade_completed",
        ever_col="ever_attended_school",
        age_col="woman_age",
        fine_candidates=load_fine_candidates(WM_ROOT / "education_level_fine_map.csv"),
        grade_semantics=load_grade_semantics("ind_que_WM_MICS", "education_grade"),
        durations=load_durations(),
        iso_map=load_iso_map(),
    )
    df["education_years"] = years
    df["education_years_estimated"] = est
    _summary("WM education_years", df, "education_years", "education_years_estimated")
    if not dry:
        df.to_parquet(WM_PARQUET, index=False)
        print(f"saved {WM_PARQUET}")


def run_hl(dry: bool) -> None:
    print(f"loading {HL_PARQUET} ...")
    df = pd.read_parquet(HL_PARQUET)
    years, est = build_years(
        df,
        level_col="highest_education_level",
        grade_col="highest_grade_completed",
        completed_col="ever_completed_grade",
        ever_col="ever_attended_school",
        age_col="age",
        fine_candidates=load_fine_candidates(HL_ROOT / "education_level_fine_map.csv"),
        grade_semantics=load_grade_semantics("ind_que_HL_MICS", "highest_grade_completed"),
        durations=load_durations(),
        iso_map=load_iso_map(),
    )
    df["education_years"] = years
    df["education_years_estimated"] = est
    _summary("HL education_years", df, "education_years", "education_years_estimated")
    if not dry:
        df.to_parquet(HL_PARQUET, index=False)
        print(f"saved {HL_PARQUET}")


def _numeric_keys(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Coerce join-key columns to float (they are TEXT in some modules)."""
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def run_ch(dry: bool) -> None:
    print(f"loading {CH_PARQUET} ...")
    ch = pd.read_parquet(CH_PARQUET)

    keys_ch = ["dataset_name", "cluster_number", "household_number",
               "mother_caretaker_line_number"]
    ch_keys = _numeric_keys(ch[keys_ch].copy(),
                            keys_ch[1:])
    print("linking WM ...")
    wm = pd.read_parquet(WM_PARQUET, columns=[
        "dataset_name", "cluster_number", "hh_number", "line_number",
        "woman_line_number", "education_years", "education_years_estimated"])
    wm = _numeric_keys(wm, ["cluster_number", "hh_number", "line_number", "woman_line_number"])
    wm["_line"] = wm["woman_line_number"].fillna(wm["line_number"])
    wm_l = (wm.dropna(subset=["cluster_number", "hh_number", "_line", "education_years"])
              .drop_duplicates(subset=["dataset_name", "cluster_number", "hh_number", "_line"]))
    merged = ch_keys.merge(
        wm_l[["dataset_name", "cluster_number", "hh_number", "_line",
              "education_years", "education_years_estimated"]],
        how="left",
        left_on=keys_ch,
        right_on=["dataset_name", "cluster_number", "hh_number", "_line"],
    )
    years = merged["education_years"].to_numpy(dtype=float, na_value=np.nan)
    est = merged["education_years_estimated"].to_numpy(dtype=float, na_value=np.nan)
    print(f"  WM-linked: {np.isfinite(years).sum():,}")

    print("linking HL fallback ...")
    hl = pd.read_parquet(HL_PARQUET, columns=[
        "dataset_name", "cluster_number", "household_number", "line_number",
        "education_years", "education_years_estimated"])
    hl = _numeric_keys(hl, ["cluster_number", "household_number", "line_number"])
    hl_l = (hl.dropna(subset=["cluster_number", "household_number", "line_number",
                              "education_years"])
              .drop_duplicates(subset=["dataset_name", "cluster_number",
                                       "household_number", "line_number"]))
    merged_hl = ch_keys.merge(
        hl_l,
        how="left",
        left_on=keys_ch,
        right_on=["dataset_name", "cluster_number", "household_number", "line_number"],
    )
    hl_years = merged_hl["education_years"].to_numpy(dtype=float, na_value=np.nan)
    hl_est = merged_hl["education_years_estimated"].to_numpy(dtype=float, na_value=np.nan)
    take = ~np.isfinite(years) & np.isfinite(hl_years)
    years[take] = hl_years[take]
    est[take] = hl_est[take]
    print(f"  +HL fallback: {take.sum():,}  (total {np.isfinite(years).sum():,})")

    print("coarse midpoint fallback from mother_education_harmonized ...")
    iso_map = load_iso_map()
    durations = load_durations()
    harm = pd.to_numeric(ch["mother_education_harmonized"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    m_age = (pd.to_numeric(ch["age_of_mother"], errors="coerce")
             .to_numpy(dtype=float, na_value=np.nan)
             if "age_of_mother" in ch.columns else np.full(len(ch), np.nan))
    need = ~np.isfinite(years) & np.isfinite(harm)
    ds_arr = ch["dataset_name"].values
    for ds in pd.unique(ds_arr[need]):
        m = need & (ds_arr == ds)
        try:
            iso3 = iso_map.loc[ds, "iso3"]
            survey_year = int(iso_map.loc[ds, "survey_year"])
        except KeyError:
            continue
        dur_tbl = durations.get(iso3)
        a = m_age[m]
        med = np.nanmedian(a) if np.isfinite(a).any() else 27.0
        entry = np.clip(survey_year - (np.where(np.isfinite(a), a, med) - 6),
                        1970, 2023).astype(int)
        if dur_tbl is not None:
            p = dur_tbl["prim_dur"].reindex(entry).values
            ls = dur_tbl["lowsec_dur"].reindex(entry).values
            us = dur_tbl["upsec_dur"].reindex(entry).values
        else:
            p = ls = us = np.full(m.sum(), np.nan)
        p = np.where(np.isfinite(p), p, 6.0)
        ls = np.where(np.isfinite(ls), ls, 3.0)
        us = np.where(np.isfinite(us), us, 3.0)
        h = harm[m]
        y = np.select(
            [h == 0, h == 1, h == 2, h == 3],
            [0.0, np.round(p / 2), p + np.round((ls + us) / 2), p + ls + us + 2],
            default=np.nan,
        )
        years[m] = np.clip(y, 0, CAP_YEARS)
        est[m] = np.where(h == 0, 0, 1)  # "None" is exact even in coarse scale
    print(f"  +coarse fallback: total {np.isfinite(years).sum():,}")

    ch["mother_education_years"] = pd.array(years, dtype="Float64")
    ch["mother_education_years_estimated"] = pd.array(est, dtype="Float64")
    _summary("CH mother_education_years", ch,
             "mother_education_years", "mother_education_years_estimated")
    if not dry:
        ch.to_parquet(CH_PARQUET, index=False)
        print(f"saved {CH_PARQUET}")


def _summary(tag: str, df: pd.DataFrame, ycol: str, ecol: str) -> None:
    y = df[ycol]
    print(f"\n=== {tag} ===")
    print(f"non-null: {y.notna().sum():,} / {len(df):,} "
          f"({y.notna().mean():.1%}) across "
          f"{df.loc[y.notna(), 'dataset_name'].nunique()} datasets")
    print(f"estimated share: {(df[ecol] == 1).sum():,} "
          f"({(df[ecol] == 1).sum() / max(y.notna().sum(), 1):.1%} of non-null)")
    print(f"mean: {y.mean():.2f}  p50: {y.median():.1f}  "
          f"p90: {y.quantile(0.9):.1f}  max: {y.max():.1f}")


if __name__ == "__main__":
    mode = sys.argv[1].lower()
    dry = "--dry-run" in sys.argv
    {"wm": run_wm, "hl": run_hl, "ch": run_ch}[mode](dry)
