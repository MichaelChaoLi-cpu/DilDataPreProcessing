"""
P11 — Introduce the CP_ ("carefully processed") column-name convention.

Every canonical variable that has been touched by a post-hoc patch (P01-P10) is
NOT a raw pass-through of the SPSS source: it was cleaned, split, harmonized,
derived, or backfilled. Going forward such columns carry a ``CP_`` prefix so an
analyst can tell at a glance that the values are the product of deliberate
post-processing rather than a coarse rename of the raw questionnaire column.

To avoid breaking prior projects (and their reproducibility), this patch does
NOT rename anything. It DUPLICATES each processed column into a ``CP_<name>``
copy while leaving the original column in place. New work should prefer the
``CP_`` columns; old code that references the original names keeps working.

Scope: the 20 columns touched by P01-P10, across all four modules.

Idempotent: skips columns whose CP_ copy already exists. Safe to re-run.

Going forward (convention, see CLAUDE.md): a NEW post-processed variable should
be created with a CP_ name directly, so no retrofit copy is ever needed. This
one-off retrofit is only for the P01-P10 columns that predate the convention.

Performance notes for any future bulk CP_ work:
  * DB: this script issues one full-table ``UPDATE`` per column. Each UPDATE
    rewrites every row (Postgres MVCC), so N columns = N full-table rewrites +
    N x WAL. For many columns at once, prefer a single
    ``ALTER TABLE ADD COLUMN a ..., ADD COLUMN b ...`` followed by ONE
    ``UPDATE ... SET a = ..., b = ...`` — one rewrite instead of N. The mass
    UPDATE also bloats the table and triggers (throttled) autovacuum; run a
    manual ``VACUUM (ANALYZE)`` afterwards so later table scans stay fast.
  * parquet: to_parquet rewrites the WHOLE file regardless of how many columns
    were added, so batch all new columns into a single write (as done here).

Usage:
    .venv/bin/python src/patch_cp_prefix.py            # apply to parquet + DB
    .venv/bin/python src/patch_cp_prefix.py --verify   # verify only, no writes
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import psycopg2

REPO = Path(__file__).resolve().parent.parent
DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")
CP = "CP_"

# module -> (final_* table, ind_que_* table, parquet path, [processed columns])
MODULES = {
    "WM": (
        "final_WM_MICS", "ind_que_WM_MICS",
        REPO / "MICS-WM/data/WM/processed_data/wm_merged.parquet",
        [
            "woman_age", "woman_age_group",
            "education_level_harmonized",
            "media_tv_frequency_harmonized",
            "media_radio_frequency_harmonized",
            "media_newspaper_frequency_harmonized",
            "education_grade", "education_grade_completed",
            "education_years", "education_years_estimated",
        ],
    ),
    "HL": (
        "final_HL_MICS", "ind_que_HL_MICS",
        REPO / "MICS-HL/data/HL/processed_data/hl_merged.parquet",
        [
            "highest_grade_completed", "ever_completed_grade",
            "education_years", "education_years_estimated",
        ],
    ),
    "CH": (
        "final_CH_MICS", "ind_que_CH_MICS",
        REPO / "MICS-CH/data/CH/processed_data/ch_merged.parquet",
        [
            "mother_education_harmonized",
            "child_age_months", "child_age_years",
            "mother_education_years", "mother_education_years_estimated",
        ],
    ),
    "HH": (
        "final_HH_MICS", "ind_que_HH_MICS",
        REPO / "MICS-HH/data/HH/processed_data/hh_merged.parquet",
        ["sex_of_household_head"],
    ),
}


# ---------------------------------------------------------------------------
# Parquet
# ---------------------------------------------------------------------------

def patch_parquet(verify: bool) -> None:
    for mod, (_, _, path, cols) in MODULES.items():
        df = pd.read_parquet(path)
        present = [c for c in cols if c in df.columns]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            print(f"  [{mod}] WARNING missing source columns: {missing}")

        if verify:
            ok = all(
                CP + c in df.columns and df[CP + c].equals(df[c]) for c in present
            )
            print(f"  [{mod}] parquet CP_ copies present & equal: {ok}")
            continue

        to_add = [c for c in present if CP + c not in df.columns]
        if not to_add:
            print(f"  [{mod}] parquet already patched, skip")
            continue

        bak = path.with_suffix(path.suffix + ".bak_p11")
        if not bak.exists():
            shutil.copy2(path, bak)
            print(f"  [{mod}] backup -> {bak.name}")

        for c in to_add:
            df[CP + c] = df[c]
        df.to_parquet(path, index=False)
        print(f"  [{mod}] parquet: added {len(to_add)} CP_ columns {to_add}")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _col_type(cur, table: str, col: str) -> str | None:
    cur.execute(
        """SELECT data_type FROM information_schema.columns
           WHERE table_name = %s AND column_name = %s""",
        (table, col),
    )
    row = cur.fetchone()
    return row[0] if row else None


def patch_db(verify: bool) -> None:
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    for mod, (table, ind, _, cols) in MODULES.items():
        present = [c for c in cols if _col_type(cur, table, c) is not None]

        if verify:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = %s AND column_name LIKE 'CP\\_%%'""",
                (table,),
            )
            have = {r[0] for r in cur.fetchall()}
            mismatch = []
            for c in present:
                if CP + c not in have:
                    mismatch.append(c)
                    continue
                cur.execute(
                    f'SELECT COUNT(*) FROM "{table}" '
                    f'WHERE "{CP + c}" IS DISTINCT FROM "{c}"'
                )
                if cur.fetchone()[0]:
                    mismatch.append(c)
            print(f"  [{mod}] {table}: {len(have)} CP_ cols; mismatches: {mismatch or 'none'}")
            # ind_que provenance mirror check
            cur.execute(
                f'SELECT COUNT(DISTINCT canonical_varname) FROM "{ind}" '
                f"WHERE canonical_varname LIKE 'CP\\_%%'"
            )
            print(f"  [{mod}] {ind}: {cur.fetchone()[0]} CP_ provenance varnames")
            continue

        existing_cp = {r[0] for r in _existing_cp(cur, table)}
        added = 0
        for c in present:
            if CP + c in existing_cp:
                continue
            dtype = _col_type(cur, table, c)
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{CP + c}" {dtype}')
            cur.execute(f'UPDATE "{table}" SET "{CP + c}" = "{c}"')
            added += 1
        print(f"  [{mod}] {table}: added {added} CP_ columns")

        # Mirror ind_que provenance rows: CP_<name> rows = copy of <name> rows.
        cur.execute(
            f"DELETE FROM \"{ind}\" WHERE canonical_varname LIKE 'CP\\_%%'"
        )
        cur.execute(f'SELECT * FROM "{ind}" LIMIT 0')
        colnames = [d[0] for d in cur.description]
        vn_idx = colnames.index("canonical_varname")
        cur.execute(
            f'SELECT * FROM "{ind}" WHERE canonical_varname = ANY(%s)', (present,)
        )
        rows = cur.fetchall()
        placeholders = ",".join(["%s"] * len(colnames))
        collist = ",".join(f'"{c}"' for c in colnames)
        n_ins = 0
        for row in rows:
            row = list(row)
            row[vn_idx] = CP + row[vn_idx]
            cur.execute(
                f'INSERT INTO "{ind}" ({collist}) VALUES ({placeholders})', row
            )
            n_ins += 1
        print(f"  [{mod}] {ind}: mirrored {n_ins} provenance rows")

    if not verify:
        conn.commit()
    conn.close()


def _existing_cp(cur, table: str):
    cur.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_name = %s AND column_name LIKE 'CP\\_%%'""",
        (table,),
    )
    return cur.fetchall()


def main() -> None:
    verify = "--verify" in sys.argv
    print(f"P11 CP_ prefix — {'VERIFY' if verify else 'APPLY'}")
    print("== parquet ==")
    patch_parquet(verify)
    print("== database ==")
    patch_db(verify)
    print("Done.")


if __name__ == "__main__":
    main()
