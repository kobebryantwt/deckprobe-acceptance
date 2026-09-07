#!/usr/bin/env python3
"""Run Node/WASM runtime parity scenarios after the JS package has been built."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def execute(command: list[str], cwd: Path) -> dict:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return {"exitCode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> None:
    node, binary, input_name, scenario = sys.argv[1:5]
    repo = Path.cwd()
    package = repo / "packages/deckprobe-js"
    dist = package / "dist/index.node.js"
    wasm = package / "wasm/deckprobe_wasm_bg.wasm"
    release = repo / binary
    prerequisites = {"nodeEntry": dist.is_file(), "wasm": wasm.is_file(), "releaseBinary": release.is_file()}
    if not all(prerequisites.values()):
        print(json.dumps({"scenario": scenario, "prerequisites": prerequisites, "ready": False}))
        return

    if scenario in {"node-file-parity", "node-byte-shapes"}:
        script = r'''
import { readFileSync } from "node:fs";
import { probe, probeFile } from "./packages/deckprobe-js/dist/index.node.js";
const [source, scenario] = process.argv.slice(1);
if (scenario === "node-file-parity") {
  const report = await probeFile(source, {targets:["pdf.page_count"], level:"metadata"});
  process.stdout.write(JSON.stringify({sourceKind:report.input.source_kind, report}));
} else {
  const bytes = readFileSync(source);
  const options = {name:"sample.pdf", targets:["pdf.page_count"], level:"metadata"};
  const a = await probe(bytes, options);
  const b = await probe(new Uint8Array(bytes), options);
  const c = await probe(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), options);
  process.stdout.write(JSON.stringify({equal:JSON.stringify(a)===JSON.stringify(b)&&JSON.stringify(a)===JSON.stringify(c), sourceKind:a.input.source_kind, pageCount:a.results["pdf.page_count"].value}));
}
'''
        api = execute([node, "--input-type=module", "-e", script, input_name, scenario], repo)
        observed = {"apiExitCode": api["exitCode"]}
        if api["exitCode"] == 0:
            value = json.loads(api["stdout"])
            if scenario == "node-file-parity":
                native = execute([str(release), "-t", "pdf.page_count", "-l", "metadata", input_name], repo)
                observed.update({"nativeExitCode": native["exitCode"], "sourceKind": value["sourceKind"],
                                 "reportsEqual": native["exitCode"] == 0 and value["report"] == json.loads(native["stdout"])})
            else:
                observed.update(value)
        runs = [api]
    elif scenario == "browser-worker-parity":
        smoke = execute([node, "./scripts/browser-smoke.mjs"], package)
        observed = {"exitCode": smoke["exitCode"], "passedMarker": "Browser smoke passed:" in smoke["stdout"]}
        runs = [smoke]
    else:
        raise SystemExit(f"unknown runtime scenario: {scenario}")
    print(json.dumps({"scenario": scenario, "prerequisites": prerequisites, "ready": True, "observed": observed, "runs": runs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
