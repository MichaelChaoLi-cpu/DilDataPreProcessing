"""
Upload WM alignment summary to PostgreSQL (localhost:5432, database: mda).

Table created (drop + recreate):
  align_summary_WM_MICS  -- variable coverage summary from alignment_summary_v2.csv

Usage:
  python upload_align_summary_to_postgres.py
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import psycopg2

_MODULE_DIR = Path(__file__).parent.parent
CSV_FILE = _MODULE_DIR / "data" / "WM" / "alignment_summary_v2.csv"
TABLE = "align_summary_WM_MICS"

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")


def main() -> None:
    df = pd.read_csv(CSV_FILE)
    print(f"Read {len(df)} rows from {CSV_FILE.name}")

    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
            cur.execute(f"""
                CREATE TABLE "{TABLE}" (
                    varname          TEXT,
                    dataset_count    BIGINT,
                    source_count     BIGINT,
                    explicit_count   BIGINT,
                    derived_count    BIGINT,
                    measure_type     TEXT,
                    canonical_text   TEXT
                )
            """)
            conn.commit()

            buf = io.StringIO()
            df.to_csv(buf, index=False, header=False, na_rep="\\N")
            buf.seek(0)
            col_list = ", ".join(f'"{c}"' for c in df.columns)
            cur.copy_expert(
                f"COPY \"{TABLE}\" ({col_list}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                buf,
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Uploaded {len(df)} rows to {TABLE}")


if __name__ == "__main__":
    main()
