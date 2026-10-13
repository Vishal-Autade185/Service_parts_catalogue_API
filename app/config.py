"""Runtime configuration, read from environment variables (PRODUCT.md section 11.2)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_PN: str = os.environ.get("ROOT_PN") or "AS-40000"

# Resolved relative to this file, never the current working directory (PRODUCT.md section 2).
DATA_DIR: Path = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data")

PATHS_PRECOMPUTE_LIMIT: int = int(os.environ.get("PATHS_PRECOMPUTE_LIMIT") or 200_000)
MAX_PATHS_WARN: int = int(os.environ.get("MAX_PATHS_WARN") or 100_000)
LOG_LEVEL: str = os.environ.get("LOG_LEVEL") or "INFO"
