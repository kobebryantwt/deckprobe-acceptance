#!/usr/bin/env python3
"""Apply the user's approval of DeckProbe quality policy v1."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITES = ROOT / "suites"
PENDING_SUITES = {"deckprobe-runtime-parity-v1"}
PENDING_SUFFIX = "（评分政策待审批）"


def main() -> None:
    approved: list[str] = []
    pending: list[str] = []
    for suite_path in sorted(SUITES.glob("*/suite.json")):
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        policy = suite.get("qualityPolicy")
        if not isinstance(policy, dict):
            raise ValueError(f"Missing qualityPolicy: {suite_path}")
        policy["reviewStatus"] = "approved"
        suite_id = str(suite["id"])
        if suite_id in PENDING_SUITES:
            suite["reviewStatus"] = "draft"
            pending.append(suite_id)
        else:
            suite["reviewStatus"] = "approved"
            suite["displayName"] = str(suite.get("displayName", suite_id)).removesuffix(PENDING_SUFFIX)
            approved.append(suite_id)
        suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"approvedSuites": approved, "pendingSuites": pending}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
