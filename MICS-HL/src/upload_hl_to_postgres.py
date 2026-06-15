"""
Upload HL data to PostgreSQL (localhost:5432, database: mda).

Tables created (drop + recreate if they exist):
  final_HL_MICS2MICS6  -- merged person-level data from hl_merged.parquet
  ind_que_HL_MICSMICS  -- index of canonical variables with original SAV column
                          names and English labels, one row per dataset × variable

Usage:
  python upload_hl_to_postgres.py
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

_MICS_HL_DIR = Path(__file__).parent.parent
ALIGNMENT_FILE = _MICS_HL_DIR / "data" / "HL" / "alignment_v2.yaml"
PARQUET_FILE   = DATA_DIR / "HL" / "processed_data" / "hl_merged.parquet"
LOG_FILE       = _MICS_HL_DIR / "logs" / "upload_hl.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

DB_PARAMS = dict(host="localhost", port=5432, dbname="mda", user="lichao")


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False
    return conn


def _pg_type(dtype) -> str:
    kind = dtype.kind
    if kind in ("i", "u"):
        return "BIGINT"
    if kind == "f":
        return "DOUBLE PRECISION"
    return "TEXT"


def _drop_and_create(cur, table: str, df: pd.DataFrame) -> None:
    cur.execute(f'DROP TABLE IF EXISTS "{table}"')
    cols_ddl = ",\n  ".join(
        f'"{col}" {_pg_type(df[col].dtype)}' for col in df.columns
    )
    cur.execute(f'CREATE TABLE "{table}" (\n  {cols_ddl}\n)')
    logger.info("Created table %s (%d columns)", table, len(df.columns))


def _copy_upload(conn, cur, table: str, df: pd.DataFrame) -> None:
    logger.info("Uploading %d rows to %s via COPY ...", len(df), table)
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)
    col_list = ", ".join(f'"{c}"' for c in df.columns)
    cur.copy_expert(
        f"COPY \"{table}\" ({col_list}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
        buffer,
    )
    conn.commit()
    logger.info("Committed %s", table)


def upload_final(conn) -> None:
    logger.info("Reading parquet: %s", PARQUET_FILE)
    df = pd.read_parquet(PARQUET_FILE)
    logger.info("Parquet loaded: %d rows x %d cols", len(df), len(df.columns))

    with conn.cursor() as cur:
        _drop_and_create(cur, "final_HL_MICS2MICS6", df)
        conn.commit()
        _copy_upload(conn, cur, "final_HL_MICS2MICS6", df)


def _build_index(alignment: dict) -> pd.DataFrame:
    rows = []
    for canonical_varname, entries in alignment.items():
        for e in entries:
            rows.append(
                {
                    "canonical_varname": canonical_varname,
                    "dataset_name": e["dataset_name"],
                    "column_in_raw_sav": e.get("column_in_raw_sav", ""),
                    "column_label_in_english": e.get("column_label_in_english") or "",
                    "source_kind": e.get("source_kind", ""),
                    "measure_type": e.get("measure_type") or "",
                    "canonical_text": e.get("canonical_text") or "",
                }
            )
    return pd.DataFrame(rows)


def upload_index(conn) -> None:
    logger.info("Reading alignment: %s", ALIGNMENT_FILE)
    with open(ALIGNMENT_FILE, encoding="utf-8") as f:
        alignment = yaml.safe_load(f) or {}

    df = _build_index(alignment)
    logger.info("Index built: %d rows", len(df))

    with conn.cursor() as cur:
        _drop_and_create(cur, "ind_que_HL_MICSMICS", df)
        conn.commit()
        _copy_upload(conn, cur, "ind_que_HL_MICSMICS", df)


def main() -> None:
    logger.info("Connecting to %s/%s", DB_PARAMS["host"], DB_PARAMS["dbname"])
    conn = _connect()
    try:
        upload_final(conn)
        upload_index(conn)
    except Exception as exc:
        conn.rollback()
        logger.error("Upload failed: %s", exc)
        raise
    finally:
        conn.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
