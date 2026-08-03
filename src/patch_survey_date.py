"""
P25 — `CP_survey_year` + `CP_survey_month`: harmonized (Gregorian) interview
year and month, in all four tables (HH / WM / CH / HL).

Sources per row: `interview_year` / `interview_month` (broad coverage), with
`interview_date_cmc` (WM only) filling datasets that have no year/month field.
Two survey calendars need conversion to Gregorian:
- **Thailand** — `interview_year` is Buddhist Era: Gregorian = year − 543. The
  month is unchanged (BE months == Gregorian months).
- **Nepal** — `interview_year`/`month`/`day` are Bikram Sambat; converted to the
  Gregorian date with an embedded BS calendar (month lengths + per-year Baishakh-1
  Gregorian anchor, so month-length error never compounds across years).

Everything else is already Gregorian (verified: cmc-derived year matches
`interview_year` 100 % and month 99.9 % on 2.05 M non-Thai/Nepal rows).

Clean range: Gregorian year 1998–2025, month 1–12; sentinels (9999 / 99 / 0 /
negatives) → NULL. Each table uses its OWN interview date (household / woman /
child interviews happen on different days) — no cross-table propagation.

Usage:
    .venv/bin/python src/patch_survey_date.py --validate   # cmc cross-check
    .venv/bin/python src/patch_survey_date.py              # apply all tables
    .venv/bin/python src/patch_survey_date.py --verify
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
CPY, CPM = "CP_survey_year", "CP_survey_month"
YEAR_LO, YEAR_HI = 1998, 2025

TABLES = {
    "final_HH_MICS": "MICS-HH/data/HH/processed_data/hh_merged.parquet",
    "final_WM_MICS": "MICS-WM/data/WM/processed_data/wm_merged.parquet",
    "final_CH_MICS": "MICS-CH/data/CH/processed_data/ch_merged.parquet",
    "final_HL_MICS": "MICS-HL/data/HL/processed_data/hl_merged.parquet",
}

# Bikram Sambat month lengths (Baishakh..Chaitra) + Gregorian date of Baishakh 1,
# per BS year. Per-year anchors keep any month-length error from compounding.
BS_CAL = {
    2070: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30],
    2071: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30],
    2072: [31, 32, 31, 32, 31, 30, 30, 29, 30, 29, 30, 30],
    2073: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30],
    2074: [31, 31, 31, 32, 31, 31, 30, 29, 30, 30, 29, 31],
    2075: [31, 32, 31, 32, 31, 30, 30, 29, 30, 29, 30, 30],
    2076: [31, 32, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30],
    2077: [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 31],
    2078: [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30],
}
BS_ANCHOR = {
    2070: date(2013, 4, 14), 2071: date(2014, 4, 14), 2072: date(2015, 4, 14),
    2073: date(2016, 4, 13), 2074: date(2017, 4, 14), 2075: date(2018, 4, 14),
    2076: date(2019, 4, 14), 2077: date(2020, 4, 13), 2078: date(2021, 4, 14),
}


def _bs_to_ad(y, m, d):
    if y not in BS_CAL or not (1 <= m <= 12):
        return None
    dd = int(d) if 1 <= int(d) <= BS_CAL[y][m - 1] + 1 else 1
    return BS_ANCHOR[y] + timedelta(days=sum(BS_CAL[y][:m - 1]) + (dd - 1))


def _is_thailand(ds):
    return "thailand" in ds.lower()


def _is_nepal(ds):
    return "nepal" in ds.lower()


def _clean_year(y):
    y = pd.to_numeric(y, errors="coerce")
    return y.where((y >= YEAR_LO) & (y <= YEAR_HI))


def _clean_month(m):
    m = pd.to_numeric(m, errors="coerce")
    return m.where((m >= 1) & (m <= 12))


def derive(df):
    """Return (cp_year, cp_month) Gregorian Series for one table's dataframe."""
    iy = pd.to_numeric(df["interview_year"], errors="coerce")
    im = pd.to_numeric(df["interview_month"], errors="coerce")
    cpy = pd.Series(np.nan, index=df.index)
    cpm = pd.Series(np.nan, index=df.index)

    thai = df["dataset_name"].map(_is_thailand).to_numpy()
    nepal = df["dataset_name"].map(_is_nepal).to_numpy()
    other = ~thai & ~nepal

    # normal Gregorian datasets
    cpy[other] = _clean_year(iy[other]).values
    cpm[other] = _clean_month(im[other]).values

    # WM: fill from interview_date_cmc where year/month absent (Gregorian datasets only)
    if "interview_date_cmc" in df.columns:
        cmc = pd.to_numeric(df["interview_date_cmc"], errors="coerce")
        cy = 1900 + np.floor((cmc - 1) / 12)
        cm = ((cmc - 1) % 12) + 1
        need = other & cpy.isna() & cmc.notna()
        cpy[need] = _clean_year(pd.Series(cy[need], index=df.index[need])).values
        cpm[need] = _clean_month(pd.Series(cm[need], index=df.index[need])).values

    # Thailand: Buddhist Era -> Gregorian (year - 543, month unchanged)
    cpy[thai] = _clean_year(iy[thai] - 543).values
    cpm[thai] = _clean_month(im[thai]).values

    # Nepal: Bikram Sambat -> Gregorian date (needs the day)
    if nepal.any():
        d = pd.to_numeric(df["interview_day"], errors="coerce")
        idx = df.index[nepal]
        yy, mm, dd = iy[nepal], im[nepal], d[nepal]
        ny = np.full(len(idx), np.nan)
        nm = np.full(len(idx), np.nan)
        for i, (a, b, c) in enumerate(zip(yy, mm, dd)):
            if pd.notna(a) and pd.notna(b) and pd.notna(c):
                ad = _bs_to_ad(int(a), int(b), int(c))
                if ad is not None:
                    ny[i], nm[i] = ad.year, ad.month
        cpy[idx] = ny
        cpm[idx] = nm
        cpy[idx] = _clean_year(cpy[idx]).values
        cpm[idx] = _clean_month(cpm[idx]).values

    return cpy, cpm


# ---------------------------------------------------------------------------

def validate():
    """cmc cross-check: CP_survey_year/month vs the cmc-derived date on WM
    (excluding Thailand/Nepal, whose cmc is in-calendar)."""
    df = pd.read_parquet(TABLES["final_WM_MICS"],
                         columns=["dataset_name", "interview_year", "interview_month",
                                  "interview_day", "interview_date_cmc"])
    cpy, cpm = derive(df)
    cmc = pd.to_numeric(df["interview_date_cmc"], errors="coerce")
    cy = 1900 + np.floor((cmc - 1) / 12)
    cm = ((cmc - 1) % 12) + 1
    greg = ~df["dataset_name"].map(_is_thailand) & ~df["dataset_name"].map(_is_nepal)
    m = greg & cpy.notna() & cmc.notna() & (cy >= YEAR_LO) & (cy <= YEAR_HI)
    print(f"  cmc cross-check on {int(m.sum())} WM rows (non-Thai/Nepal):")
    print(f"    year match:  {(cpy[m] == cy[m]).mean():.4f}")
    mm = m & cpm.notna() & (cm >= 1) & (cm <= 12)
    print(f"    month match: {(cpm[mm] == cm[mm]).mean():.4f}")
    for ds in ["Thailand 2005-06 MICS_Datasets", "Thailand MICS6 Datasets",
               "Nepal_MICS5_Datasets", "Nepal MICS6 Datasets"]:
        s = df["dataset_name"] == ds
        if s.any():
            print(f"    {ds[:38]:38} year {sorted(cpy[s].dropna().unique())} "
                  f"months {sorted(int(x) for x in cpm[s].dropna().unique())}")


def _reinsert_datasets(df, cpy):
    """Datasets whose CP is NOT a clean function of (interview_year, interview_month):
    Nepal (depends on day) + cmc-derived rows (year/month field absent)."""
    iy = pd.to_numeric(df["interview_year"], errors="coerce")
    rs = set(df.loc[df["dataset_name"].map(_is_nepal), "dataset_name"].unique())
    rs |= set(df.loc[cpy.notna() & iy.isna(), "dataset_name"].unique())
    return rs


def process_table(table, verify):
    path = Path(TABLES[table])
    df = pd.read_parquet(path)
    if verify:
        for c in (CPY, CPM):
            n = int(df[c].notna().sum()) if c in df.columns else 0
            nds = df.loc[df[c].notna(), "dataset_name"].nunique() if c in df.columns else 0
            print(f"  [{table}] {c} valid={n} / {nds} ds")
        if CPY in df.columns:
            bad = int(df.loc[df[CPY].notna() & ~df[CPY].between(YEAR_LO, YEAR_HI)].shape[0])
            badm = int(df.loc[df[CPM].notna() & ~df[CPM].between(1, 12)].shape[0])
            print(f"  [{table}] out-of-range year={bad} month={badm}")
        return set()

    bak = path.with_suffix(".parquet.bak_p25")
    if not bak.exists():
        shutil.copy2(path, bak)
    cpy, cpm = derive(df)
    reinsert = _reinsert_datasets(df, cpy)
    df[CPY] = cpy.values
    df[CPM] = cpm.values
    df.to_parquet(path, index=False)
    print(f"  [{table}] {CPY} valid={int(cpy.notna().sum())} / {df.loc[cpy.notna(),'dataset_name'].nunique()} ds; "
          f"{CPM} valid={int(cpm.notna().sum())}; special(reinsert)={len(reinsert)}")
    return reinsert


def _col_exists(cur, table, col):
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""", (table, col))
    return cur.fetchone() is not None


def sync_db(table, reinsert, verify):
    path = TABLES[table]
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    cur = conn.cursor()
    T = f'"{table}"'
    if verify:
        for c in (CPY, CPM):
            cur.execute(f'SELECT COUNT("{c}"), COUNT(DISTINCT dataset_name) FILTER (WHERE "{c}" IS NOT NULL) FROM {T}')
            n, nds = cur.fetchone()
            print(f"  [{table}] db {c} non-null={n} / {nds} ds")
        conn.close(); return

    df = pd.read_parquet(path, columns=["dataset_name", "interview_year", "interview_month", CPY, CPM])
    existed = _col_exists(cur, table, CPY)
    for c in (CPY, CPM):
        if not _col_exists(cur, table, c):
            cur.execute(f'ALTER TABLE {T} ADD COLUMN "{c}" SMALLINT')
    if existed:
        cur.execute(f'UPDATE {T} SET "{CPY}"=NULL, "{CPM}"=NULL')

    # non-special datasets: CP is a function of (dataset, interview_year, interview_month)
    simple = df[~df.dataset_name.isin(reinsert)].copy()
    simple["_iy"] = pd.to_numeric(simple["interview_year"], errors="coerce")
    simple["_im"] = pd.to_numeric(simple["interview_month"], errors="coerce")
    # keep rows where year OR month is set (a sentinel year can coexist with a valid month)
    lut = (simple.dropna(subset=[CPY, CPM], how="all").drop_duplicates(["dataset_name", "_iy", "_im"])
           [["dataset_name", "_iy", "_im", CPY, CPM]].copy())
    lut[CPY] = lut[CPY].astype("Int64"); lut[CPM] = lut[CPM].astype("Int64")
    cur.execute("CREATE TEMP TABLE _sd(dataset text, iy double precision, im double precision, "
                "cy smallint, cm smallint) ON COMMIT DROP")
    buf = io.StringIO(); lut.to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
    cur.copy_expert("COPY _sd(dataset,iy,im,cy,cm) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", buf)
    cur.execute("CREATE INDEX ON _sd(dataset,iy,im)")
    cur.execute("""SELECT data_type FROM information_schema.columns
                   WHERE table_name=%s AND column_name='interview_year'""", (table,))
    yt = cur.fetchone()[0]
    if yt in ("double precision", "real", "numeric", "integer", "bigint", "smallint"):
        iyx, imx = "f.interview_year", "f.interview_month"
    else:
        iyx = "(CASE WHEN f.interview_year ~ '^-?[0-9.]+$' THEN f.interview_year::double precision END)"
        imx = "(CASE WHEN f.interview_month ~ '^-?[0-9.]+$' THEN f.interview_month::double precision END)"
    cur.execute(f'UPDATE {T} f SET "{CPY}"=m.cy, "{CPM}"=m.cm FROM _sd m '
                f'WHERE f.dataset_name=m.dataset AND {iyx} IS NOT DISTINCT FROM m.iy '
                f'AND {imx} IS NOT DISTINCT FROM m.im')
    print(f"  [{table}] db: mapped {len(lut)} (dataset,iy,im) combos")

    # special datasets (Nepal / cmc-derived): reinsert full rows from patched parquet
    if reinsert:
        full = pd.read_parquet(path)
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name=%s""", (table,))
        dbtype = dict(cur.fetchall())
        cols = [c for c in full.columns if c in dbtype]
        for ds in reinsert:
            sub = full[full.dataset_name == ds].copy()
            for c in cols:
                if dbtype.get(c) == "bigint":
                    sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
                elif dbtype.get(c) in ("smallint", "integer"):
                    sub[c] = pd.to_numeric(sub[c], errors="coerce").astype("Int64")
                elif dbtype.get(c) in ("double precision", "real", "numeric"):
                    sub[c] = pd.to_numeric(sub[c], errors="coerce")
            cur.execute(f'DELETE FROM {T} WHERE dataset_name=%s', (ds,))
            buf = io.StringIO(); sub[cols].to_csv(buf, index=False, header=False, na_rep="\\N"); buf.seek(0)
            collist = ", ".join(f'"{c}"' for c in cols)
            cur.copy_expert(f'COPY {T} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')', buf)
        print(f"  [{table}] db: reinserted {len(reinsert)} special datasets")

    conn.commit(); conn.close()


def main():
    if "--validate" in sys.argv:
        print("P25 survey date — VALIDATE"); validate(); return
    verify = "--verify" in sys.argv
    print(f"P25 CP_survey_year/CP_survey_month — {'VERIFY' if verify else 'APPLY'}")
    for table in TABLES:
        rec = process_table(table, verify)
        sync_db(table, rec, verify)
    print("Done.")


if __name__ == "__main__":
    main()
