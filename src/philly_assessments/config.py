"""Project configuration."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path("data")


def data_dir() -> Path:
    """Root of the local data lake (raw/, staged/, marts/).

    Defaults to ./data; override with the PHILLY_DATA_DIR environment variable.
    """
    return Path(os.environ.get("PHILLY_DATA_DIR", str(DEFAULT_DATA_DIR)))
