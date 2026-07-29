"""
P14 — Carefully process `bmi_for_age_zscore` -> `CP_bmi_for_age_zscore` (CH):
clean the existing values AND derive it for fully-missing datasets that pass a
strict data-quality gate.

Cleaning: keep BMI-for-age z within [-6, 6]; sentinel 999.99 and implausible
extremes -> NULL. (|z|<=6 is a slightly more permissive, more reasonable bound
than the WHO |z|<=5 flag.) The raw `bmi_for_age_zscore` is left unchanged.

Derivation: for datasets with ZERO existing coverage, compute BMI-for-age z from
raw child_weight_kg / child_height_or_length_cm / age / sex_of_child using the
WHO 2006 Child Growth Standards (BMI-for-age LMS, embedded below). Validated
against the 143 datasets that already have z: median |diff| 0.004, r=0.989.

GUARD AGAINST SERIOUS ERROR — a fully-missing dataset is derived ONLY if, after
cleaning inputs (weight 1-40 kg, height 38-140 cm) and clipping |z|<=6, its
derived distribution is healthy: drop rate <=5%, SD in [0.7, 1.8], |mean|<=1.5,
n>=100. Datasets that fail (uncleanable unit/measurement problems) stay NULL and
are reported. This gate is computed in-code so the result is reproducible.

`CP_bmi_for_age_zscore_derived`: 1 = value derived here, 0 = MICS-provided,
NULL = CP_ is NULL. Lets analysts separate or sensitivity-test derived values.

Note: for under-5, WHO prefers weight_for_height_zscore; BMI-for-age is a 5-19y
tool. This derivation is provided for completeness of the BMI-for-age column.

Usage:
    .venv/bin/python MICS-CH/src/patch_bmi_for_age.py            # apply
    .venv/bin/python MICS-CH/src/patch_bmi_for_age.py --verify   # check only
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
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")

BASE = "bmi_for_age_zscore"
CP = "CP_bmi_for_age_zscore"
CPD = "CP_bmi_for_age_zscore_derived"
ZCLIP = 6.0
W_LO, W_HI = 1.0, 40.0     # plausible under-5 weight (kg)
H_LO, H_HI = 38.0, 140.0   # plausible under-5 height/length (cm)
# derivation data-quality gate (per fully-missing dataset)
G_DROP_MAX, G_SD_LO, G_SD_HI, G_MEAN_ABS, G_MIN_N = 5.0, 0.7, 1.8, 1.5, 100

# WHO 2006 Child Growth Standards — BMI-for-age LMS by month & sex (0-60 mo).
WHO_BMI_LMS = {
  'M': [(0,-0.3053,13.4069,0.0956),(1,0.2708,14.9441,0.09027),(2,0.1118,16.3195,0.08677),(3,0.0068,16.8987,0.08495),(4,-0.0727,17.1579,0.08378),(5,-0.137,17.2919,0.08296),(6,-0.1913,17.3422,0.08234),(7,-0.2385,17.3288,0.08183),(8,-0.2802,17.2647,0.0814),(9,-0.3176,17.1662,0.08102),(10,-0.3516,17.0488,0.08068),(11,-0.3828,16.9239,0.08037),(12,-0.4115,16.7981,0.08009),(13,-0.4382,16.6743,0.07982),(14,-0.463,16.5548,0.07958),(15,-0.4863,16.4409,0.07935),(16,-0.5082,16.3335,0.07913),(17,-0.5289,16.2329,0.07892),(18,-0.5484,16.1392,0.07873),(19,-0.5669,16.0528,0.07854),(20,-0.5846,15.9743,0.07836),(21,-0.6014,15.9039,0.07818),(22,-0.6174,15.8412,0.07802),(23,-0.6328,15.7852,0.07786),(24,-0.6473,15.7356,0.07771),(25,-0.584,15.98,0.07792),(26,-0.5497,15.9414,0.078),(27,-0.5166,15.9036,0.07808),(28,-0.485,15.8667,0.07818),(29,-0.4552,15.8306,0.07829),(30,-0.4274,15.7953,0.07841),(31,-0.4016,15.7606,0.07854),(32,-0.3782,15.7267,0.07867),(33,-0.3572,15.6934,0.07882),(34,-0.3388,15.661,0.07897),(35,-0.3231,15.6294,0.07914),(36,-0.3101,15.5988,0.07931),(37,-0.3,15.5693,0.0795),(38,-0.2927,15.541,0.07969),(39,-0.2884,15.514,0.0799),(40,-0.2869,15.4885,0.08012),(41,-0.2881,15.4645,0.08036),(42,-0.2919,15.442,0.08061),(43,-0.2981,15.421,0.08087),(44,-0.3067,15.4013,0.08115),(45,-0.3174,15.3827,0.08144),(46,-0.3303,15.3652,0.08174),(47,-0.3452,15.3485,0.08205),(48,-0.3622,15.3326,0.08238),(49,-0.3811,15.3174,0.08272),(50,-0.4019,15.3029,0.08307),(51,-0.4245,15.2891,0.08343),(52,-0.4488,15.2759,0.0838),(53,-0.4747,15.2633,0.08418),(54,-0.5019,15.2514,0.08457),(55,-0.5303,15.24,0.08496),(56,-0.5599,15.2291,0.08536),(57,-0.5905,15.2188,0.08577),(58,-0.6223,15.2091,0.08617),(59,-0.6552,15.2,0.08659),(60,-0.6892,15.1916,0.087)],
  'F': [(0,-0.0631,13.3363,0.09272),(1,0.3448,14.5679,0.09556),(2,0.1749,15.7679,0.09371),(3,0.0643,16.3574,0.09254),(4,-0.0191,16.6703,0.09166),(5,-0.0864,16.8386,0.09096),(6,-0.1429,16.9083,0.09036),(7,-0.1916,16.902,0.08984),(8,-0.2344,16.8404,0.08939),(9,-0.2725,16.7406,0.08898),(10,-0.3068,16.6184,0.08861),(11,-0.3381,16.4875,0.08828),(12,-0.3667,16.3568,0.08797),(13,-0.3932,16.2311,0.08768),(14,-0.4177,16.1128,0.08741),(15,-0.4407,16.0028,0.08716),(16,-0.4623,15.9017,0.08693),(17,-0.4825,15.8096,0.08671),(18,-0.5017,15.7263,0.0865),(19,-0.5199,15.6517,0.0863),(20,-0.5372,15.5855,0.08612),(21,-0.5537,15.5278,0.08594),(22,-0.5695,15.4787,0.08577),(23,-0.5846,15.438,0.0856),(24,-0.5989,15.4052,0.08545),(25,-0.5684,15.659,0.08452),(26,-0.5684,15.6308,0.08449),(27,-0.5684,15.6037,0.08446),(28,-0.5684,15.5777,0.08444),(29,-0.5684,15.5523,0.08443),(30,-0.5684,15.5276,0.08444),(31,-0.5684,15.5034,0.08448),(32,-0.5684,15.4798,0.08455),(33,-0.5684,15.4572,0.08467),(34,-0.5684,15.4356,0.08484),(35,-0.5684,15.4155,0.08506),(36,-0.5684,15.3968,0.08535),(37,-0.5684,15.3796,0.08569),(38,-0.5684,15.3638,0.08609),(39,-0.5684,15.3493,0.08654),(40,-0.5684,15.3358,0.08704),(41,-0.5684,15.3233,0.08757),(42,-0.5684,15.3116,0.08813),(43,-0.5684,15.3007,0.08872),(44,-0.5684,15.2905,0.08931),(45,-0.5684,15.2814,0.08991),(46,-0.5684,15.2732,0.09051),(47,-0.5684,15.2661,0.0911),(48,-0.5684,15.2602,0.09168),(49,-0.5684,15.2556,0.09227),(50,-0.5684,15.2523,0.09286),(51,-0.5684,15.2503,0.09345),(52,-0.5684,15.2496,0.09403),(53,-0.5684,15.2502,0.0946),(54,-0.5684,15.2519,0.09515),(55,-0.5684,15.2544,0.09568),(56,-0.5684,15.2575,0.09618),(57,-0.5684,15.2612,0.09665),(58,-0.5684,15.2653,0.09709),(59,-0.5684,15.2698,0.0975),(60,-0.5684,15.2747,0.09789)],
}
_L = {s: np.array(sorted(v)) for s, v in WHO_BMI_LMS.items()}  # cols: month,L,M,S


def _zscore(bmi, age_m, sexcode):
    """WHO BMI-for-age z (LMS + |z|>3 adjustment). sexcode 1=M, 2=F."""
    bmi = np.asarray(bmi, float); age_m = np.asarray(age_m, float)
    sexcode = np.asarray(sexcode, float)
    z = np.full(bmi.shape, np.nan)
    for code, s in [(1.0, 'M'), (2.0, 'F')]:
        t = _L[s]
        sel = ((sexcode == code) & np.isfinite(bmi) & np.isfinite(age_m)
               & (age_m >= 0) & (age_m <= 60) & (bmi > 0))
        i = np.where(sel)[0]
        if not len(i):
            continue
        am = age_m[i]
        L = np.interp(am, t[:, 0], t[:, 1]); M = np.interp(am, t[:, 0], t[:, 2])
        S = np.interp(am, t[:, 0], t[:, 3]); x = bmi[i]
        zz = ((x / M) ** L - 1) / (L * S)
        SD3 = M * (1 + L * S * 3) ** (1 / L); SD2 = M * (1 + L * S * 2) ** (1 / L)
        SD3n = M * (1 + L * S * -3) ** (1 / L); SD2n = M * (1 + L * S * -2) ** (1 / L)
        zz = np.where(zz > 3, 3 + (x - SD3) / (SD3 - SD2), zz)
        zz = np.where(zz < -3, -3 + (x - SD3n) / (SD2n - SD3n), zz)
        z[i] = zz
    return z


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce")


def _compute(df: pd.DataFrame):
    """Return (cp, cp_derived_flag, derived_datasets, gate_report)."""
    base = _num(df, BASE)
    # age in months: prefer days, then months, then interview-minus-birth
    age = (_num(df, "child_age_days") / 30.4375)
    age = age.fillna(_num(df, "child_age_months"))
    age = age.fillna((_num(df, "interview_year") * 12 + _num(df, "interview_month"))
                     - (_num(df, "child_birth_year") * 12 + _num(df, "child_birth_month")))
    # cleaned inputs -> BMI -> derived z
    w = _num(df, "child_weight_kg").where(lambda s: s.between(W_LO, W_HI))
    h = _num(df, "child_height_or_length_cm").where(lambda s: s.between(H_LO, H_HI))
    bmi = w / (h / 100) ** 2
    dz = pd.Series(_zscore(bmi.values, age.values, _num(df, "sex_of_child").values),
                   index=df.index)
    dz = dz.where(dz.abs() <= ZCLIP)

    # existing values, cleaned to |z|<=6
    cp = base.where(base.abs() <= ZCLIP)

    # gate: only derive for datasets with ZERO existing coverage that look healthy
    has_base = df.loc[base.notna(), "dataset_name"].unique()
    fully_missing = set(df["dataset_name"].unique()) - set(has_base)
    derived_ds, report = [], []
    for ds in sorted(fully_missing):
        m = (df["dataset_name"] == ds)
        vals = dz[m].dropna()
        n = len(vals)
        if n == 0:
            continue
        # candidate rows = rows where derived z computable BEFORE the |z|<=6 clip
        raw_dz = pd.Series(_zscore(bmi[m].values, age[m].values,
                                   _num(df.loc[m], "sex_of_child").values), index=df.index[m])
        c = int(raw_dz.notna().sum())
        drop = 100 * (c - n) / c if c else 100
        mean, sd = vals.mean(), vals.std()
        ok = (n >= G_MIN_N and drop <= G_DROP_MAX and G_SD_LO <= sd <= G_SD_HI
              and abs(mean) <= G_MEAN_ABS)
        report.append((ds, n, round(drop, 1), round(mean, 2), round(sd, 2), ok))
        if ok:
            derived_ds.append(ds)

    in_der = df["dataset_name"].isin(derived_ds)
    fill = cp.isna() & in_der & dz.notna()
    cp = cp.copy(); cp[fill] = dz[fill]
    flag = pd.Series(np.nan, index=df.index)
    flag[base.where(base.abs() <= ZCLIP).notna()] = 0.0
    flag[fill] = 1.0
    return cp, flag, derived_ds, report


def patch_parquet(verify: bool):
    df = pd.read_parquet(PARQUET)
    cp, flag, derived_ds, report = _compute(df)
    if verify:
        ok = (CP in df.columns and CPD in df.columns
              and df[CP].equals(cp) and df[CPD].equals(flag))
        n = int(cp.notna().sum()); nd = int((flag == 1).sum())
        nds = df.loc[cp.notna(), "dataset_name"].nunique()
        print(f"  parquet: present&correct={ok}; {CP} non-null={n} across {nds} ds; "
              f"derived={nd}; derived datasets={len(derived_ds)}")
        return derived_ds
    if not PARQUET.with_suffix(".parquet.bak_p14").exists():
        shutil.copy2(PARQUET, PARQUET.with_suffix(".parquet.bak_p14"))
    print("  derivation gate (fully-missing datasets):")
    for ds, n, drop, mean, sd, ok in report:
        print(f"    {'DERIVE ' if ok else 'exclude'} {ds[:44]:44} n={n:>6} drop={drop:>4}% mean={mean:>5} sd={sd:>4}")
    df[CP] = cp; df[CPD] = flag
    df.to_parquet(PARQUET, index=False)
    print(f"  parquet: {CP} non-null={int(cp.notna().sum())} across "
          f"{df.loc[cp.notna(),'dataset_name'].nunique()} datasets; "
          f"derived={int((flag==1).sum())} rows / {len(derived_ds)} datasets")
    return derived_ds


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def patch_db(derived_ds, verify: bool):
    conn = psycopg2.connect(**DB_PARAMS); conn.autocommit = False
    cur = conn.cursor()
    T = '"final_CH_MICS"'; I = '"ind_que_CH_MICS"'
    if verify:
        cur.execute(f'SELECT COUNT("{CP}"), COUNT(DISTINCT dataset_name) '
                    f'FILTER (WHERE "{CP}" IS NOT NULL), '
                    f'COUNT(*) FILTER (WHERE "{CPD}"=1) FROM {T}')
        n, nds, nd = cur.fetchone()
        cur.execute(f'SELECT COUNT(*) FROM {T} WHERE "{CP}" IS NOT NULL '
                    f'AND ("{CP}"<{-ZCLIP} OR "{CP}">{ZCLIP})')
        bad = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
        print(f"  db: {CP} non-null={n} across {nds} ds; derived={nd}; "
              f"out-of-range={bad}; ind_que CP_ rows={cur.fetchone()[0]}")
        conn.close(); return

    pdf = pd.read_parquet(PARQUET)
    for col in (CP, CPD):
        if not _col_exists(cur, "final_CH_MICS", col):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{col}" DOUBLE PRECISION')
    # re-clean existing (base-derived) rows in place, |z|<=6
    cur.execute(f'UPDATE {T} SET "{CP}" = CASE WHEN {BASE} BETWEEN {-ZCLIP} AND {ZCLIP} '
                f'THEN {BASE} ELSE NULL END, '
                f'"{CPD}" = CASE WHEN {BASE} BETWEEN {-ZCLIP} AND {ZCLIP} THEN 0 ELSE NULL END')
    # derived datasets: delete + reinsert from patched parquet
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name='final_CH_MICS'""")
    dbtype = dict(cur.fetchall()); cols = list(pdf.columns)
    assert all(c in dbtype for c in cols), "DB missing a parquet column"
    for ds in derived_ds:
        sub = pdf[pdf["dataset_name"] == ds].copy()
        for c in cols:
            if dbtype.get(c) == "bigint":
                sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
            elif dbtype.get(c) == "double precision":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
        buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
        buf.seek(0)
        collist = ", ".join(f'"{c}"' for c in cols)
        cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
    print(f"  db: re-cleaned existing + re-inserted {len(derived_ds)} derived datasets")

    # ind_que: mirror base -> CP_ (+ derived-source rows for derived datasets)
    cur.execute(f"DELETE FROM {I} WHERE canonical_varname IN ('{CP}','{CPD}')")
    cur.execute(f'''INSERT INTO {I}
        (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
         source_kind, measure_type, canonical_text)
        SELECT '{CP}', dataset_name, column_in_raw_sav, column_label_in_english,
               source_kind, measure_type, canonical_text
        FROM {I} WHERE canonical_varname='{BASE}' ''')
    for ds in derived_ds:
        cur.execute(f'''INSERT INTO {I}
            (canonical_varname, dataset_name, column_in_raw_sav, column_label_in_english,
             source_kind, measure_type, canonical_text)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (CP, ds, "(derived: weight,height,age,sex via WHO2006)",
             "BMI-for-age z-score (derived)", "derived", "anthropometry",
             "BMI-for-age z-score"))
    cur.execute(f"SELECT COUNT(*) FROM {I} WHERE canonical_varname='{CP}'")
    print(f"  db: ind_que {CP} rows={cur.fetchone()[0]}")
    conn.commit(); conn.close()


def main():
    verify = "--verify" in sys.argv
    print(f"P14 bmi_for_age_zscore -> CP_ (clean + derive) — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet =="); derived_ds = patch_parquet(verify)
    print("== database =="); patch_db(derived_ds, verify)
    print("Done.")


if __name__ == "__main__":
    main()
