#!/usr/bin/env python3
"""Run one deterministic DeckProbe request twice and expose both raw reports."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: deckprobe_repeat.py DECKPROBE INPUT")
    command = [sys.argv[1], "-c", "exact", "-t", "slide_count", sys.argv[2]]
    first = subprocess.run(command, capture_output=True)
    second = subprocess.run(command, capture_output=True)
    payload = {
        "first": json.loads(first.stdout),
        "second": json.loads(second.stdout),
        "firstExit": first.returncode,
        "secondExit": second.returncode,
        "byteIdentical": first.stdout == second.stdout,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
