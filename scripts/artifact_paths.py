"""Shared seller-side artifact path resolution."""
from __future__ import annotations

import os
from pathlib import Path


def resolve_artifact_dir(default, environ=None):
    """Prefer isolated ICT_BUILD_DIR, then legacy ICT_SOURCE_DIR, then default."""
    env = os.environ if environ is None else environ
    return Path(env.get("ICT_BUILD_DIR") or env.get("ICT_SOURCE_DIR") or default)
