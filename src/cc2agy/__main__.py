"""Entrypoint for executing cc2agy as a module: python -m cc2agy."""

import sys
from cc2agy.cli import main

if __name__ == "__main__":
    sys.exit(main())
