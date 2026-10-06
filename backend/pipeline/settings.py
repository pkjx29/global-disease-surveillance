"""Runtime settings for the data pipeline (environment-driven)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://localhost:5432/disease_surveillance")
DATA_DIR = Path(os.environ.get("DATA_DIR", BACKEND_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", BACKEND_ROOT / "models"))
SCHEMA_FILE = BACKEND_ROOT / "sql" / "schema.sql"

# Modelling
HORIZON_WEEKS = 4                 # predict a surge over the next four weeks
SURGE_RATIO = 2.0                 # ... defined as cases at least doubling
TRAIN_END = os.environ.get("TRAIN_END", "2022-12-31")     # everything after this date is held out

# Minimum size of the following 4 weeks for a doubling to count as an outbreak
# (stops "1 case -> 2 cases" from being labelled a surge).
MIN_SURGE_CASES = {"covid19": 100, "dengue": 50, "mpox": 10}
MIN_SURGE_INCIDENCE = {"covid19": 1.0, "dengue": 0.5, "mpox": 0.0}    # per 100k over 4 weeks

RISK_LEVELS = [("Critical", 0.60), ("High", 0.35), ("Moderate", 0.15), ("Low", 0.0)]


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S")
