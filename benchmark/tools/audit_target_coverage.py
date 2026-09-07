#!/usr/bin/env python3
"""Compare DeckProbe catalogs with designed, approved, run, and passed checks."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


PROFILES = ("pdf", "docx", "xlsx", "pptx", "doc", "ppt", "key", "numbers", "pages")
EXTENSION_PROFILE = {f".{profile}": profile for profile in PROFILES}
DETERMINISTIC_CHECKS = {"target_equals", "target_confidence", "target_path_equals", "target_status_equals"}
LAYERS = ("designed", "approved", "run", "passed")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest_run(benchmark: Path, suite_id: str) -> dict[str, Any] | None:
    candidates = list((benchmark / "artifacts" / "runs" / suite_id).glob("*/*/run.json"))
    if not candidates:
        return None
    payloads = [(read_json(path), path) for path in candidates]
    payload, _ = max(payloads, key=lambda item: (str(item[0].get("createdAt", "")), item[1].stat().st_mtime_ns))
    return payload


def coverage_layers(benchmark: Path) -> dict[str, dict[str, set[str]]]:
    coverage = {profile: {layer: set() for layer in LAYERS} for profile in PROFILES}
    for suite_path in benchmark.glob("suites/*/suite.json"):
        suite = read_json(suite_path)
        suite_dir = suite_path.parent
        cases_path = suite_dir / suite.get("cases", "cases.jsonl")
        if not cases_path.exists():
            continue
        questions_path = suite_dir / suite.get("questions", "questions.jsonl")
        questions = read_jsonl(questions_path) if questions_path.exists() else []
        approved_assertions: dict[str, set[str]] = {}
        for question in questions:
            if question.get("reviewStatus") != "approved":
                continue
            approved_assertions.setdefault(str(question.get("caseId")), set()).update(str(value) for value in question.get("assertionIds", []))
        suite_approved = suite.get("reviewStatus") == "approved" and suite.get("qualityPolicy", {}).get("reviewStatus") == "approved"
        run = latest_run(benchmark, str(suite.get("id"))) if suite_approved else None
        run_results = {str(item.get("caseId")): item for item in run.get("results", [])} if run else {}

        for case in read_jsonl(cases_path):
            case_id = str(case.get("id"))
            profile = EXTENSION_PROFILE.get(Path(case.get("source", {}).get("uri", "")).suffix.lower())
            if not profile or case_id.startswith("encrypted-"):
                continue
            checks = case.get("evaluation", {}).get("checks", case.get("assertions", []))
            run_result = run_results.get(case_id)
            expected_sha = case.get("source", {}).get("sha256") or case.get("sha256")
            run_matches_source = bool(run_result) and (not expected_sha or run_result.get("inputSha256") == expected_sha)
            assertion_results = {str(item.get("id")): item for item in run_result.get("assertions", [])} if run_matches_source else {}
            for check in checks:
                target = check.get("target")
                assertion_id = str(check.get("id"))
                if not target or check.get("type") not in DETERMINISTIC_CHECKS:
                    continue
                coverage[profile]["designed"].add(str(target))
                if not suite_approved or assertion_id not in approved_assertions.get(case_id, set()):
                    continue
                coverage[profile]["approved"].add(str(target))
                assertion_result = assertion_results.get(assertion_id)
                if not assertion_result:
                    continue
                coverage[profile]["run"].add(str(target))
                if assertion_result.get("status") == "passed":
                    coverage[profile]["passed"].add(str(target))
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path("target/debug/deckprobe"))
    parser.add_argument("--benchmark", type=Path, default=Path("benchmark"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    coverage = coverage_layers(args.benchmark)
    rows = []
    for profile in PROFILES:
        output = subprocess.check_output([str(args.binary), "targets", "--format", profile], text=True)
        report = json.loads(output)
        catalog = {target["id"] for target in report["targets"] if target.get("applicable")}
        layer_summary = {}
        for layer in LAYERS:
            covered = catalog & coverage[profile][layer]
            layer_summary[layer] = {
                "targetCount": len(covered),
                "coveragePercent": round(100 * len(covered) / len(catalog), 1),
            }
        rows.append({
            "profile": profile,
            "catalogTargetCount": len(catalog),
            "coverage": layer_summary,
            "missingDesignedTargets": sorted(catalog - coverage[profile]["designed"]),
            "designedButMissingFromCatalog": sorted(coverage[profile]["designed"] - catalog),
        })
    rendered = json.dumps({
        "contractVersion": 2,
        "definitions": {
            "designed": "A deterministic target check exists in any suite.",
            "approved": "The suite and the question binding that check are approved.",
            "run": "The approved check appears in the latest suite run and the source SHA matches.",
            "passed": "The latest matching run reports that approved check as passed.",
        },
        "profiles": rows,
    }, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
