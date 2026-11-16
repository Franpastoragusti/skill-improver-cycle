"""Locate local Node dependencies and logs independently of the Python imports."""

import os
from pathlib import Path

_source_root = Path(__file__).resolve().parents[2]
_default_root = _source_root if (_source_root / "pyproject.toml").is_file() else Path.cwd()
PROJECT_ROOT = Path(os.getenv("INVESTIGATION_PROJECT_ROOT", str(_default_root))).resolve()
