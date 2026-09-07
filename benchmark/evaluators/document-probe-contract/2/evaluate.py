#!/usr/bin/env python3
"""Evaluate DeckProbe-style document facts without coupling to its invocation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


CONFIDENCE_SCORES = {
    "none": 0.0,
    "low": 0.4,
    "medium": 0.7,
    "high": 0.95,
    "exact": 1.0,
}


def assertion(check: dict[str, Any], passed: bool, actual: Any, details: str | None = None) -> dict[str, Any]:
    role = check["role"]
    value = {
        "id": check["id"],
        "type": check["type"],
        "status": "passed" if passed else "failed",
        "role": role,
        "featureId": check["featureId"],
        "severity": check["severity"],
        "expected": check.get("expected"),
        "actual": actual,
    }
    if role == "scored":
        value.update({
            "weight": float(check["weight"]),
            "scoreMode": check["scoreMode"],
            "score": 1.0 if passed else 0.0,
        })
    if details:
        value["details"] = details
    return value


def observation(check: dict[str, Any], actual: Any) -> dict[str, Any]:
    """Return evidence for a non-gating observation without declaring success."""
    return {
        "id": check["id"],
        "type": check["type"],
        "status": "review",
        "role": "observation",
        "featureId": check["featureId"],
        "severity": check.get("severity", "minor"),
        "finding": False,
        "expected": None,
        "actual": actual,
        "details": "观察项：仅记录实际值，不参与通过/失败判定。",
    }


def target(report: Any, target_id: str) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    value = report.get("results", {}).get(target_id)
    return value if isinstance(value, dict) else None


def probe_contract(report: Any, process: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    issues: list[str] = []
    if not isinstance(report, dict):
        return False, {"issues": ["stdout is not a JSON object"]}
    if report.get("schema_version") != 2:
        issues.append("schema_version is not 2")
    if report.get("status") not in {"ok", "partial", "error"}:
        issues.append("invalid top-level status")
    if not isinstance(report.get("tool_version"), str):
        issues.append("tool_version is absent")
    if report.get("status") == "error":
        error = report.get("error")
        if not isinstance(error, dict):
            issues.append("error envelope is absent")
        else:
            if not isinstance(error.get("code"), str) or not error.get("code"):
                issues.append("stable error code is absent")
            if error.get("exit_code") != process.get("exitCode"):
                issues.append("reported and process exit codes disagree")
    else:
        for field in ("input", "driver", "results", "execution", "diagnostics"):
            if field not in report:
                issues.append(f"missing top-level field: {field}")
        results = report.get("results", {})
        if not isinstance(results, dict):
            issues.append("results is not an object")
            results = {}
        unresolved = []
        for target_id, value in results.items():
            if not isinstance(value, dict):
                issues.append(f"result {target_id} is not an object")
                continue
            if value.get("target") != target_id:
                issues.append(f"result {target_id} does not retain canonical target id")
            status = value.get("status")
            if status not in {"resolved", "estimated", "planned", "unknown", "unsupported", "invalid", "budget_exceeded", "failed"}:
                issues.append(f"result {target_id} has invalid status")
            if status in {"resolved", "estimated"}:
                confidence = value.get("confidence")
                if confidence not in CONFIDENCE_SCORES:
                    issues.append(f"result {target_id} has invalid confidence")
                elif value.get("confidence_score") != CONFIDENCE_SCORES[confidence]:
                    issues.append(f"result {target_id} confidence score disagrees")
                if not value.get("path") or not value.get("source"):
                    issues.append(f"result {target_id} lacks path/source evidence")
                if "value" not in value:
                    issues.append(f"result {target_id} lacks value")
            else:
                unresolved.append(target_id)
        execution = report.get("execution", {})
        actual_unresolved = sorted(execution.get("unresolved_targets", [])) if isinstance(execution, dict) else []
        if sorted(unresolved) != actual_unresolved:
            issues.append("execution.unresolved_targets disagrees with results")
        expected_status = "partial" if unresolved else "ok"
        if report.get("status") != expected_status:
            issues.append("top-level status disagrees with target statuses")
        actual_cost = execution.get("actual_cost", {}) if isinstance(execution, dict) else {}
        for field in ("physical_bytes_read", "expanded_bytes", "random_reads"):
            if not isinstance(actual_cost.get(field), int) or actual_cost.get(field, -1) < 0:
                issues.append(f"actual_cost.{field} is not a non-negative integer")
        if "elapsed_ms" in actual_cost:
            issues.append("default deterministic output contains elapsed_ms")
    return not issues, {"issues": issues}


def run_check(check: dict[str, Any], data: Any, process: dict[str, Any]) -> dict[str, Any]:
    kind = check["type"]
    expected = check.get("expected")
    if kind == "probe_observation":
        report = data if isinstance(data, dict) else {}
        value = target(report, check["target"])
        return observation(check, {
            "processExitCode": process.get("exitCode"),
            "schemaVersion": report.get("schema_version"),
            "reportStatus": report.get("status"),
            "driver": report.get("driver"),
            "target": check["target"],
            "targetResult": value,
            "actualCost": report.get("execution", {}).get("actual_cost"),
        })
    if kind == "probe_contract":
        passed, actual = probe_contract(data, process)
        return assertion(check, passed, actual)
    if kind == "driver_equals":
        actual = data.get("driver") if isinstance(data, dict) else None
        return assertion(check, actual == expected, actual)
    if kind == "target_equals":
        value = target(data, check["target"])
        actual = value.get("value") if value else None
        return assertion(check, value is not None and actual == expected, actual)
    if kind == "target_confidence":
        value = target(data, check["target"])
        actual = value.get("confidence") if value else None
        return assertion(check, actual == expected, actual)
    if kind == "target_status_equals":
        value = target(data, check["target"])
        actual = value.get("status") if value else None
        return assertion(check, value is not None and actual == expected, actual)
    if kind == "target_path_equals":
        value = target(data, check["target"])
        actual = value.get("path") if value else None
        return assertion(check, actual == expected, actual)
    if kind == "cost_ceiling":
        cost = data.get("execution", {}).get("actual_cost", {}) if isinstance(data, dict) else {}
        exceeded = {key: cost.get(key) for key, ceiling in expected.items() if not isinstance(cost.get(key), int) or cost[key] > ceiling}
        return assertion(check, not exceeded, cost, f"exceeded: {exceeded}" if exceeded else None)
    if kind == "error_equals":
        actual = {
            "code": data.get("error", {}).get("code") if isinstance(data, dict) else None,
            "exit_code": process.get("exitCode"),
        }
        return assertion(check, actual == expected, actual)
    if kind == "byte_identical":
        actual = data.get("byteIdentical") if isinstance(data, dict) else None
        return assertion(check, actual is expected, actual)
    if kind == "repeat_report_contract":
        if not isinstance(data, dict):
            return assertion(check, False, None)
        first_ok, first = probe_contract(data.get("first"), {"exitCode": data.get("firstExit")})
        second_ok, second = probe_contract(data.get("second"), {"exitCode": data.get("secondExit")})
        actual = {"first": first, "second": second}
        return assertion(check, first_ok and second_ok, actual)
    return assertion(check, False, f"unsupported check type: {kind}")


def main() -> None:
    context = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    data = context["normalizedTargetOutput"].get("data")
    process = context["targetProcess"]
    checks = context["case"].get("evaluation", {}).get("checks", [])
    assertions = [run_check(check, data, process) for check in checks]
    print(json.dumps({
        "assertions": assertions,
        "metrics": {
            "checkCount": len(assertions),
            "passedCount": sum(item["status"] == "passed" for item in assertions),
            "gateCount": sum(item["role"] == "gate" for item in assertions),
            "scoredCount": sum(item["role"] == "scored" for item in assertions),
            "observationCount": sum(item["role"] == "observation" for item in assertions),
            "scoredWeight": sum(item.get("weight", 0.0) for item in assertions if item["role"] == "scored"),
        },
        "evidence": [],
        "summary": "版本化文档事实探测业务评估",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
