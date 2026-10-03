#!/usr/bin/env python3
"""cc2agy standalone runner for immediate zero-config execution."""

import sys
from pathlib import Path

# Ensure src/ is on Python module search path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cc2agy.cli import main

if __name__ == "__main__":
    sys.exit(main())
