"""Unit tests for cc2agy."""

import sys
from pathlib import Path

# Ensure src/ is on sys.path for test discovery and runners
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
