from pathlib import Path

RAW_DATA_DIR = Path("/Volumes/MikesDataBackup/MICS/raw")
PROCESSED_DATA_DIR = Path("/Volumes/MikesDataBackup/MICS/processed")

OUTPUT_FORMAT = "parquet"

MODULES = ["hh", "hl", "wm", "ch", "bh", "fs", "gm"]

MICS_ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]
