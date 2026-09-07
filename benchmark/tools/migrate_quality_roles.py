#!/usr/bin/env python3
"""Apply the reviewed DeckProbe Core 2 role and scoring policy to suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUITES = ROOT / "suites"
PURE_GATE_SUITES = {
    "deckprobe-budget-v1",
    "deckprobe-cli-contract-v1",
    "deckprobe-determinism-v1",
    "deckprobe-runtime-parity-v1",
}
GATE_TYPES = {
    "probe_contract",
    "driver_equals",
    "error_equals",
    "cost_ceiling",
    "byte_identical",
    "repeat_report_contract",
    "target_status_equals",
}
IDENTITY_TARGETS = {
    "document.format",
    "document.format_profile",
    "document.mime_type",
    "document.extension",
    "document.extension_matches",
    "office.document_kind",
    "office.legacy_kind",
    "office.cfb_container",
    "office.content_probe_supported",
    "iwork.document_kind",
    "iwork.has_external_or_missing_data",
}
QUALITY_POLICY = {
    "version": "1",
    "reviewStatus": "draft",
    "scoring": {
        "aggregation": "macro_feature",
        "scale": 100,
        "passThreshold": 95,
        "reviewThreshold": 80,
    },
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def role_for(suite_id: str, check: dict[str, Any]) -> str:
    check_id = str(check.get("id", ""))
    check_type = str(check.get("type", ""))
    target = str(check.get("target", ""))
    if check_type == "probe_observation" or check.get("required") is False or "observation" in check_id:
        return "observation"
    if suite_id in PURE_GATE_SUITES or check_type in GATE_TYPES:
        return "gate"
    if target.startswith("security.") or target.startswith("quality."):
        return "gate"
    if target in IDENTITY_TARGETS or target.endswith(".ooxml_conformance") or target == "pdf.repaired":
        return "gate"
    return "scored"


def main() -> None:
    totals = {"gate": 0, "scored": 0, "observation": 0}
    for suite_path in sorted(SUITES.glob("*/suite.json")):
        suite_dir = suite_path.parent
        suite = read_json(suite_path)
        suite_id = str(suite["id"])
        questions_path = suite_dir / suite.get("questions", "questions.jsonl")
        feature_by_assertion: dict[tuple[str, str], str] = {}
        if questions_path.exists():
            for question in read_jsonl(questions_path):
                for assertion_id in question.get("assertionIds", []):
                    key = (str(question["caseId"]), str(assertion_id))
                    feature = str(question["featureId"])
                    previous = feature_by_assertion.get(key)
                    if previous and previous != feature:
                        raise ValueError(f"Assertion belongs to multiple features: {suite_id}/{key}")
                    feature_by_assertion[key] = feature

        cases_path = suite_dir / suite.get("cases", "cases.jsonl")
        if not cases_path.exists():
            continue
        cases = read_jsonl(cases_path)
        for case in cases:
            checks = case.get("evaluation", {}).get("checks", case.get("assertions", []))
            for check in checks:
                key = (str(case["id"]), str(check["id"]))
                feature_id = feature_by_assertion.get(key)
                if not feature_id:
                    raise ValueError(f"No reviewed feature binding: {suite_id}/{case['id']}/{check['id']}")
                role = role_for(suite_id, check)
                check["role"] = role
                check["featureId"] = feature_id
                check["severity"] = "major" if role == "gate" else "minor"
                check.pop("required", None)
                check.pop("finding", None)
                if role == "scored":
                    check["weight"] = 1.0
                    check["scoreMode"] = "binary"
                else:
                    check.pop("weight", None)
                    check.pop("scoreMode", None)
                totals[role] += 1
        cases_path.write_text("".join(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n" for case in cases), encoding="utf-8")

        suite["qualityPolicy"] = QUALITY_POLICY
        suite["evaluator"] = {**suite["evaluator"], "version": "2"}
        if suite.get("reviewStatus") == "approved":
            suite["reviewStatus"] = "draft"
            if "（评分政策待审批）" not in str(suite.get("displayName", "")):
                suite["displayName"] = f"{suite['displayName']}（评分政策待审批）"
        suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
