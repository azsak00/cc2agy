"""Unit tests for cc2agy."""

import sys
from pathlib import Path

# Ensure src/ takes precedence over root directory to avoid module collision with cc2agy.py
ROOT_DIR = str(Path(__file__).resolve().parent.parent)
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")

while ROOT_DIR in sys.path:
    sys.path.remove(ROOT_DIR)
while "" in sys.path:
    sys.path.remove("")

if SRC_DIR in sys.path:
    sys.path.remove(SRC_DIR)
sys.path.insert(0, SRC_DIR)
