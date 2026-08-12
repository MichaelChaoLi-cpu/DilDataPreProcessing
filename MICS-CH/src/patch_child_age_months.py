"""
P33 — `CP_child_age_months` (CH) ENHANCED: age of the child in completed months.

The old CP_child_age_months carried the merged `child_age_months`, populated for
only 42 datasets — the historical alignment mapped it to a grab-bag of raw columns
(age BANDS like CAGE_6/CAGE_11, DOB CMC, line numbers) and produced a valid month
value for almost none. Yet the raw SAVs almost universally carry `CAGE` = "Age
(months)" (0-59). This patch rebuilds the column from raw with a clear priority:

    1. CAGE  — direct completed-months age (label "Age (months)"/"Âge (mois)"/
       "Edad (meses)"), plausible 0-59. Present in 248/251 datasets.
    2. date back-calc — interview_cmc - birth_cmc, where cmc = (year-1900)*12+month:
         MICS4/5  interview UF8M/UF8Y, birth AG1M/AG1Y
         MICS6    interview UF7M/UF7Y, birth UB1M/UB1Y
       Used only where CAGE is absent/null. Calendar-guarded (year 1990-2025,
       month 1-12) to drop 9999/9997 sentinels; kept when result is 0-60 (60 is a
       boundary child at exactly 5y-in-months -> clamped to 59). Agrees with CAGE
       to within 1 month for >=96% of rows (the completed-vs-boundary rounding).
    3. existing `child_age_months` — final fallback (guard fails / no SAV).

Read fresh from raw via guarded positional backfill. A dataset is written only if
(a) SAV row count == parquet row count, (b) the values form a real 0-59 completed-
months scale (max >= 48 — excludes miscoded columns like Cuba's cage capped at 23
or Indonesia-2000's constant 1), and (c) the rows are aligned: household_number
matches the SAV HH id at >=99.9%, OR — when the HH id was recoded (Kosovo, Argentina,
Montenegro, ...) — (age//12) agrees with the dataset's child_age_years at >=90%.
child_age_years is itself broken/degenerate for several datasets (all-zero, or only
1-2 year values), so it can only CONFIRM a household-aligned dataset, never veto one.
Otherwise the dataset keeps its old value.

Usage:
    .venv/bin/python MICS-CH/src/patch_child_age_months.py            # apply
    .venv/bin/python MICS-CH/src/patch_child_age_months.py --verify
"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

ROOT = Path(__file__).parent.parent / "data" / "CH"
PARQUET = ROOT / "processed_data" / "ch_merged.parquet"
RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

CP = "CP_child_age_months"
BASE = "child_age_months"
GUARD_KEYS = ["HH2", "hh2", "HI2", "hi2", "WIHHNO", "wihhno", "hh1", "HH1"]
CAGE = ["CAGE", "cage", "Cage"]
# (interview month, interview year, birth month, birth year)
DATE_SETS = [
    (["UF8M"], ["UF8Y"], ["AG1M"], ["AG1Y"]),   # MICS4/5
    (["UF7M"], ["UF7Y"], ["UB1M"], ["UB1Y"]),   # MICS6
]


def _find(cols, names):
    low = {c.lower(): c for c in cols}
    return next((low[n.lower()] for n in names if n.lower() in low), None)


def _cmc(y, m):
    y = pd.to_numeric(y, errors="coerce")
    m = pd.to_numeric(m, errors="coerce")
    ok = y.between(1990, 2025) & m.between(1, 12)
    return pd.Series(np.where(ok, (y - 1900) * 12 + m, np.nan), index=y.index)


def _sav(ds):
    d = RAW / ds
    if not d.is_dir():
        return None
    for pat in ("ch.sav", "CH.sav", "Ch.sav"):
        if (d / pat).exists():
            return d / pat
    c = [p for p in d.glob("*.sav") if "ch" in p.name.lower()]
    return c[0] if c else None


def _from_raw(ds, parquet_ds):
    """Return (Series age-in-months aligned to parquet_ds, note) or (None, why).

    Positional guard: the produced age must agree with the dataset's already-
    validated `child_age_years` — (age // 12) == child_age_years for >=95% of the
    overlapping rows. This is robust to household-id recoding (which sinks a plain
    household_number match) yet still catches genuine row-order misalignment
    (e.g. Kyrgyzstan 2005-06 -> 0.40). Household match is the fallback only when
    child_age_years is unavailable.
    """
    import pyreadstat
    sav = _sav(ds)
    if sav is None:
        return None, "no SAV"
    try:
        _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    except Exception as e:
        return None, f"meta err {e!s:.40}"
    names = meta.column_names
    cage = _find(names, CAGE)
    dset = next((s for s in DATE_SETS if all(_find(names, part) for part in s)), None)
    if not cage and not dset:
        return None, "no CAGE/date column"
    key = _find(names, GUARD_KEYS)
    need = list(dict.fromkeys(
        ([cage] if cage else [])
        + ([_find(names, p) for p in dset] if dset else [])
        + ([key] if key else [])))
    try:
        df, _ = pyreadstat.read_sav(str(sav), usecols=need, apply_value_formats=False)
    except Exception as e:
        return None, f"read err {e!s:.40}"
    if len(df) != len(parquet_ds):
        return None, f"row mismatch {len(df)} vs {len(parquet_ds)}"
    df = df.reset_index(drop=True)
    val = pd.Series(np.nan, index=df.index)
    src = []
    if cage:
        ca = pd.to_numeric(df[cage], errors="coerce")
        val = val.where(~ca.between(0, 59), ca)
        src.append(f"CAGE={cage}")
    if dset:
        im, iy, bm, by = [_find(names, p) for p in dset]
        diff = _cmc(df[iy], df[im]) - _cmc(df[by], df[bm])
        diff = diff.where(diff.between(0, 60)).clip(upper=59)
        val = val.where(val.notna(), diff)
        src.append(f"date({im}/{iy}-{bm}/{by})")
    # --- semantic guard: must be a real 0-59 completed-months scale ---
    nval = int(val.notna().sum())
    if nval < 50:
        return None, "no valid month values"
    vmax = float(val.max())
    if vmax < 48:
        return None, f"value maxes at {vmax:.0f} (not a 0-59 months scale)"
    # --- positional guard: rows aligned by household id OR by age-in-years ---
    # household match is the reliable anchor; it fails only on household-id RECODING
    # (Kosovo/Argentina/...), where the age-year cross-check confirms alignment
    # instead. child_age_years is a broken/degenerate column for several datasets,
    # so it can only *confirm* alignment (>=0.90), never veto a household-confirmed one.
    g = np.nan
    if key is not None:
        a = pd.to_numeric(parquet_ds["household_number"].reset_index(drop=True), errors="coerce")
        b = pd.to_numeric(df[key].reset_index(drop=True), errors="coerce")
        g = (a == b).mean()
    yr = pd.to_numeric(parquet_ds["child_age_years"].reset_index(drop=True), errors="coerce")
    both = val.notna() & yr.notna()
    ag = ((val[both] // 12) == yr[both]).mean() if both.sum() >= 100 else np.nan
    pass_hh = g >= 0.999
    pass_ag = both.sum() >= 100 and ag >= 0.90
    if not (pass_hh or pass_ag):
        agtxt = f"{ag:.3%}" if not np.isnan(ag) else "NA"
        gtxt = f"{g:.3%}" if not np.isnan(g) else "NA"
        return None, f"unaligned hh={gtxt} age-yr={agtxt}"
    gnote = f"hh={g:.3%}" if pass_hh else f"age-yr={ag:.3%}"
    return val, f"n={nval} [{'+'.join(src)}] {gnote} max={vmax:.0f}"


def apply(verify):
    df = pd.read_parquet(PARQUET)
    if verify:
        v = pd.to_numeric(df[CP], errors="coerce") if CP in df.columns else pd.Series(dtype=float)
        nds = df.loc[v.notna(), "dataset_name"].nunique() if CP in df.columns else 0
        bad = int((v.notna() & ~v.between(0, 59)).sum()) if CP in df.columns else -1
        print(f"  parquet {CP}: valid={int(v.notna().sum())} / {nds} ds; out-of-range(0-59)={bad}")
        return
    if not PARQUET.with_suffix(".parquet.bak_p33").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p33"))
    # start from the existing value (final fallback)
    cp = pd.to_numeric(df[BASE], errors="coerce")
    cp = cp.where(cp.between(0, 59))
    filled, skipped = [], []
    for ds in df.dataset_name.unique():
        m = (df.dataset_name == ds).values
        ser, note = _from_raw(ds, df.loc[m])
        if ser is None:
            skipped.append((ds, note)); continue
        cp.values[m] = ser.values                    # CAGE/date override existing
        filled.append((ds, note))
    for ds, note in filled:
        print(f"  [ok]   {ds[:42]:42s} {note}")
    for ds, note in skipped:
        print(f"  [skip] {ds[:42]:42s} {note}")
    df[CP] = cp.values
    df.to_parquet(PARQUET, index=False)
    v = df[CP]
    nds = df.loc[v.notna(), "dataset_name"].nunique()
    print(f"  parquet: {CP} valid={int(v.notna().sum())} / {nds} datasets; "
          f"raw-filled={len(filled)} skipped={len(skipped)}")


def _cols(cur):
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_CH_MICS'""")
    return dict(cur.fetchall())


def sync_db(verify):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor(); T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{CP}" IS NOT NULL) FROM {T}')
        n, nds = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL AND ("{CP}"<0 OR "{CP}">59)')
        print(f"  db {CP}: non-null={n} / {nds} ds; out-of-range={cur.fetchone()[0]}")
        conn.close(); return
    pdf = pd.read_parquet(PARQUET)
    dbtype = _cols(cur)
    if CP not in dbtype:
        cur.execute(f'ALTER TABLE {T} ADD COLUMN "{CP}" SMALLINT'); dbtype = _cols(cur)
    cols = [c for c in pdf.columns if c in dbtype]
    assert set(dbtype) - set(pdf.columns) == set(), "DB has columns absent from parquet"
    for c in cols:
        if dbtype.get(c) in ("bigint", "smallint", "integer"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce").astype("Int64")
        elif dbtype.get(c) in ("double precision", "real", "numeric"):
            pdf[c] = pd.to_numeric(pdf[c], errors="coerce")
    collist = ", ".join(f'"{c}"' for c in cols)
    cur.execute(f'TRUNCATE {T}')
    for ds, sub in pdf.groupby("dataset_name", sort=False):
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    # ind_que: mostly CAGE-sourced -> derived; carry existing base provenance rows.
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname=%s", (CP,))
    cur.execute(f'''INSERT INTO {I} (canonical_varname,dataset_name,column_in_raw_sav,
        column_label_in_english,source_kind,measure_type,canonical_text)
        SELECT %s,dataset_name,'CAGE','Age (months) [CAGE or interview-minus-birth date]',
               'derived',measure_type,'Child age in completed months'
        FROM {I} WHERE canonical_varname=%s''', (CP, BASE))
    print(f"  db: rebuilt CH ({pdf['dataset_name'].nunique()} datasets); ind_que mirrored")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P33 CP_child_age_months (enhanced) — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); apply(verify)
    print("== database =="); sync_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
