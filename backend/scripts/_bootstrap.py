"""Ensure backend imports use backend/.env regardless of process cwd."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def bootstrap_backend() -> Path:
    os.chdir(BACKEND_ROOT)
    root = str(BACKEND_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return BACKEND_ROOT
