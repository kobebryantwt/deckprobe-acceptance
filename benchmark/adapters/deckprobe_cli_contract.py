#!/usr/bin/env python3
"""Exercise one documented DeckProbe CLI scenario and emit normalized evidence."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(binary: str, args: list[str], stdin: bytes | None = None) -> dict[str, Any]:
    proc = subprocess.run([binary, *args], input=stdin, capture_output=True)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    parsed: Any = None
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        pass
    return {"exitCode": proc.returncode, "stdout": stdout, "stderr": stderr, "json": parsed}


def semantic_json_equal(left: str, right: str) -> bool:
    try:
        return json.loads(left) == json.loads(right)
    except json.JSONDecodeError:
        return False


def main() -> None:
    binary, input_name, scenario = sys.argv[1:4]
    source = Path(input_name)
    observed: dict[str, Any] = {}
    runs: list[dict[str, Any]] = []

    if scenario == "formats-discovery":
        item = run(binary, ["formats"]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "schemaVersion": data.get("schema_version"),
                    "status": data.get("status"), "drivers": [x.get("driver") for x in data.get("formats", [])]}
    elif scenario == "pdf-target-discovery":
        item = run(binary, ["targets", "pdf"]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "driver": data.get("driver"), "profile": data.get("profile"),
                    "hasTargets": bool(data.get("targets")), "hasSelectors": bool(data.get("selector_expansions")),
                    "hasFormatOptions": bool(data.get("format_options"))}
    elif scenario == "schema-discovery":
        item = run(binary, ["schema"]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "isObjectSchema": data.get("type") == "object",
                    "hasDefs": isinstance(data.get("$defs"), dict), "schemaVersionConst": data.get("$defs", {}).get("base", {}).get("properties", {}).get("schema_version", {}).get("const")}
    elif scenario == "raw-stdin":
        item = run(binary, ["-n", source.name, "-t", "page_count", "-"], source.read_bytes()); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "sourceKind": data.get("input", {}).get("source_kind"),
                    "driver": data.get("driver"), "pageCount": data.get("results", {}).get("pdf.page_count", {}).get("value")}
    elif scenario == "jsonl-continue":
        good = {"name": source.name, "data_base64": base64.b64encode(source.read_bytes()).decode("ascii")}
        payload = (json.dumps(good) + "\n" + "{bad json\n" + json.dumps(good) + "\n").encode()
        item = run(binary, ["--jsonl", "-t", "page_count"], payload); runs.append(item)
        lines = [line for line in item["stdout"].splitlines() if line.strip()]
        parsed = []
        for line in lines:
            try: parsed.append(json.loads(line))
            except json.JSONDecodeError: parsed.append(None)
        observed = {"exitCode": item["exitCode"], "lineCount": len(lines), "allLinesJson": all(x is not None for x in parsed),
                    "statuses": [x.get("status") if isinstance(x, dict) else None for x in parsed],
                    "lastPageCount": (parsed[-1] or {}).get("results", {}).get("pdf.page_count", {}).get("value") if parsed else None}
    elif scenario == "values-view":
        item = run(binary, ["-t", "page_count", "--view", "values", str(source)]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "view": data.get("view"), "pageCount": data.get("values", {}).get("pdf.page_count"),
                    "hasFullResults": "results" in data}
    elif scenario == "plan-only":
        item = run(binary, ["-P", "-t", "page_count", str(source)]); runs.append(item)
        data = item["json"] or {}; result = data.get("results", {}).get("pdf.page_count", {})
        observed = {"exitCode": item["exitCode"], "targetStatus": result.get("status"), "path": result.get("path"),
                    "physicalBytes": data.get("execution", {}).get("actual_cost", {}).get("physical_bytes_read")}
    elif scenario == "strict-unresolved":
        item = run(binary, ["-s", "-l", "deep", "-t", "@all", str(source)]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "status": data.get("status"),
                    "unresolvedCount": len(data.get("execution", {}).get("unresolved_targets", [])),
                    "hasUnresolved": bool(data.get("execution", {}).get("unresolved_targets", [])),
                    "hasReport": data.get("schema_version") == 2}
    elif scenario in {"optional-piggyback", "no-piggyback"}:
        args = ["-t", "page_count", "-o", "object_count"]
        if scenario == "no-piggyback": args.append("-N")
        item = run(binary, [*args, str(source)]); runs.append(item)
        data = item["json"] or {}; execution = data.get("execution", {})
        observed = {"exitCode": item["exitCode"], "resultKeys": sorted(data.get("results", {}).keys()),
                    "piggybackTargets": execution.get("piggyback_targets", [])}
    elif scenario == "aliases-equivalent":
        first = run(binary, ["--level", "metadata", "-t", "page_count", str(source)])
        second = run(binary, ["-l", "m", "-t", "page_count", str(source)])
        runs.extend([first, second])
        observed = {"bothExitZero": first["exitCode"] == second["exitCode"] == 0,
                    "semanticEqual": semantic_json_equal(first["stdout"], second["stdout"])}
    elif scenario == "input-format-mismatch":
        item = run(binary, ["--input-format", "pptx", str(source)]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "status": data.get("status"), "errorCode": data.get("error", {}).get("code")}
    elif scenario == "unknown-format-option":
        item = run(binary, ["-O", "pdf.no_such=1", str(source)]); runs.append(item)
        data = item["json"] or {}
        observed = {"exitCode": item["exitCode"], "status": data.get("status"), "errorCode": data.get("error", {}).get("code")}
    elif scenario == "pretty-semantic":
        compact = run(binary, ["-t", "page_count", str(source)])
        pretty = run(binary, ["-p", "-t", "page_count", str(source)])
        runs.extend([compact, pretty])
        observed = {"bothExitZero": compact["exitCode"] == pretty["exitCode"] == 0,
                    "semanticEqual": semantic_json_equal(compact["stdout"], pretty["stdout"]),
                    "prettyHasNewlines": pretty["stdout"].count("\n") > 2}
    elif scenario == "telemetry-opt-in":
        default = run(binary, ["-t", "page_count", str(source)])
        telemetry = run(binary, ["--telemetry", "-t", "page_count", str(source)])
        runs.extend([default, telemetry])
        d0, d1 = default["json"] or {}, telemetry["json"] or {}
        observed = {"bothExitZero": default["exitCode"] == telemetry["exitCode"] == 0,
                    "defaultHasElapsed": "elapsed_ms" in d0.get("execution", {}).get("actual_cost", {}),
                    "telemetryHasElapsed": "elapsed_ms" in d1.get("execution", {}).get("actual_cost", {})}
    elif scenario == "completion-generation":
        item = run(binary, ["completion", "zsh"]); runs.append(item)
        observed = {"exitCode": item["exitCode"], "nonEmpty": bool(item["stdout"].strip()), "mentionsDeckprobe": "deckprobe" in item["stdout"]}
    elif scenario == "man-generation":
        item = run(binary, ["generate", "man"]); runs.append(item)
        observed = {"exitCode": item["exitCode"], "nonEmpty": bool(item["stdout"].strip()),
                    "hasTitle": ".TH DECKPROBE" in item["stdout"].upper(), "hasSynopsis": "SYNOPSIS" in item["stdout"].upper()}
    else:
        raise SystemExit(f"unknown CLI contract scenario: {scenario}")

    print(json.dumps({"scenario": scenario, "observed": observed, "runs": runs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
