#!/usr/bin/env python3
"""One-command entry point, independent of the current working directory."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmark.acceptance.cli import main

if __name__=='__main__':
    raise SystemExit(main())
