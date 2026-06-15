from pathlib import Path

from dotenv import load_dotenv
import os

_PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

RAW_DATA_DIR = Path(os.environ["DATA_RAW_DIR"])

_MICS_HL_DIR = Path(__file__).parent.parent
DOCS_DIR = _MICS_HL_DIR / "docs"
DATA_DIR = _MICS_HL_DIR / "data"
