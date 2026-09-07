"""GitHub-hosted orchestration contracts for released DeckProbe artifacts."""
from __future__ import annotations

import html
import json
import os
import platform
import re
import shutil
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .ci_snapshot import _portable, materialize_snapshot, validate_snapshot
from .common import CODE, ROOT, atomic, code_hash, digest, now, process, read, seal, sha, verify_seal
from .contracts import compare_assertions, decision
from .releases import api, download_release, npm_record, prepare_packages, release_record, safe_extract, fetch
from .reporting import publish
from .runner import paired_performance, run
from .supply_evidence import refresh_signature_audit

JOB_SCHEMA = 1
PLATFORMS = {
    "macos-arm64": ("aarch64-apple-darwin", "deckprobe-aarch64-apple-darwin.tar.gz"),
    "macos-x64": ("x86_64-apple-darwin", "deckprobe-x86_64-apple-darwin.tar.gz"),
    "linux-arm64-gnu": ("aarch64-unknown-linux-gnu", "deckprobe-aarch64-unknown-linux-gnu.tar.gz"),
    "linux-arm64-musl": ("aarch64-unknown-linux-musl", "deckprobe-aarch64-unknown-linux-musl.tar.gz"),
    "linux-x64-gnu": ("x86_64-unknown-linux-gnu", "deckprobe-x86_64-unknown-linux-gnu.tar.gz"),
    "linux-x64-musl": ("x86_64-unknown-linux-musl", "deckprobe-x86_64-unknown-linux-musl.tar.gz"),
    "windows-x64": ("x86_64-pc-windows-msvc", "deckprobe-x86_64-pc-windows-msvc.zip"),
}


def _release(repo, tag=None):
    if tag:
        value = api(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        if value.get("draft") or value.get("prerelease"): raise ValueError("release is not stable")
        candidate = release_record(repo, value)
        all_releases = api(f"https://api.github.com/repos/{repo}/releases?per_page=100")
    else:
        value = api(f"https://api.github.com/repos/{repo}/releases/latest")
        candidate = release_record(repo, value)
        all_releases = api(f"https://api.github.com/repos/{repo}/releases?per_page=100")
    stable = sorted((r for r in all_releases if not r["draft"] and not r["prerelease"]),
                    key=lambda r: r["published_at"], reverse=True)
    previous = next((r for r in stable if r["published_at"] < candidate["publishedAt"]), None)
    return candidate, release_record(repo, previous) if previous else None


def freeze(snapshot, output, release_tag=None, history=None, force=False):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    created_at = now()
    errors = validate_snapshot(snapshot)
    policy = read(Path(snapshot) / "policy.json", {}).get("policy", read(CODE / "config/policy.json"))
    blocked = None; blockers=[]
    try:
        if errors:
            blockers=[{'stage':'snapshot-validation','message':x} for x in errors]
            raise ValueError(f"CI snapshot validation failed with {len(errors)} issue(s)")
        candidate, previous = _release(policy["repository"], release_tag)
        version = candidate["tag"].lstrip("v")
        packages = {"js": npm_record("@deckflow/deckprobe", version),
                    "mcp": npm_record("@deckflow/deckprobe-mcp")}
    except Exception as error:  # network/registry failures are modeled evidence
        candidate = previous = None; packages = {}; blocked = str(error)
        if not blockers:blockers=[{'stage':'release-freeze','message':blocked}]
    snapshot_digest = sha(Path(snapshot) / "SHA256SUMS") if (Path(snapshot) / "SHA256SUMS").is_file() else None
    binding = {"release": candidate, "previous": previous, "packages": packages,
               "snapshotDigest": snapshot_digest, "codeSha256": code_hash(), "policyHash": digest(policy)}
    input_digest = digest(binding)
    base_run_id = ((candidate or {}).get("tag", "blocked") + "-" + input_digest[:20]).replace("/", "-")
    latest = read(Path(history) / "history.json", {}) if history else {}
    last = latest.get("runs", [{}])[-1] if latest.get("runs") else {}
    retry_failed = bool(last and last.get("inputDigest") == input_digest and last.get("decision") != "PASS")
    changed = bool(force or blocked or last.get("inputDigest") != input_digest or retry_failed)
    rerun_suffix = created_at.replace("-", "").replace(":", "").replace("+", "").replace(".", "") if force or retry_failed else None
    run_id = base_run_id + ("-rerun-" + rerun_suffix if rerun_suffix else "")
    record = {"schemaVersion": 1, "runId": run_id, "combinationId": base_run_id, "createdAt": created_at, "inputDigest": input_digest,
              "snapshotDigest": snapshot_digest, "codeSha256": code_hash(), "policyHash": digest(policy),
              "candidate": candidate, "previous": previous, "packages": packages, "policy": policy,
              "changed": changed, "force": force, "status": "BLOCKED" if blocked else ("READY" if changed else "NO_CHANGE"),
              "blocker": blocked,"blockers":blockers}
    atomic(output / "run-lock.json", record)
    atomic(output / "freeze-blockers.json",blockers)
    atomic(output / "freeze-result.json", job_result(record, "freeze", [], "BLOCKED" if blocked else record["status"]))
    seal(output)
    return record


def _platform_for_host():
    key = (platform.system(), platform.machine().lower())
    values = {("Linux", "x86_64"): "x86_64-unknown-linux-gnu", ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
              ("Darwin", "arm64"): "aarch64-apple-darwin", ("Darwin", "x86_64"): "x86_64-apple-darwin",
              ("Windows", "amd64"): "x86_64-pc-windows-msvc"}
    if key not in values: raise ValueError("unsupported hosted runner: " + repr(key))
    return values[key]


def prepare_locked(lock_path, snapshot, home, include_previous=True):
    lock = read(lock_path); home = Path(home)
    if lock.get("status") == "BLOCKED": raise ValueError(lock.get("blocker", "freeze blocked"))
    materialize_snapshot(snapshot, home)
    targets = {}
    discovery = {"candidate": lock["candidate"], "previous": lock.get("previous"), **lock.get("packages", {})}
    for label in (["candidate", "previous"] if include_previous else ["candidate"]):
        release = lock.get(label)
        if not release: continue
        prepared_release = download_release(home, release, _platform_for_host())
        packages = prepare_packages(home, discovery, prepared_release)
        refresh_signature_audit(packages)
        targets[label] = {"release": prepared_release, "packages": packages}
    atomic(home / "prepared.json", {"discovery": discovery, "targets": targets})
    security_entry = {"checkedAt": now(), "repository": lock["policy"]["repository"],
                      "identity": "GITHUB_TOKEN" if os.getenv("GITHUB_TOKEN") else "anonymous"}
    try:
        security_entry["privateReporting"] = api("https://api.github.com/repos/" + lock["policy"]["repository"] + "/private-vulnerability-reporting")
    except Exception as error:
        security_entry["blocked"] = str(error)
    atomic(home / "security-entry.json", security_entry)
    return lock, targets


def job_result(lock, job, checks, status=None, **extra):
    status = status or decision(checks)
    return {"schemaVersion": JOB_SCHEMA, "runId": lock["runId"], "inputDigest": lock["inputDigest"],
            "release": (lock.get("candidate") or {}).get("tag"), "job": job, "status": status,
            "createdAt": now(), "environment": {"system": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "runner": os.getenv("RUNNER_NAME")}, "checks": checks, **extra}


def run_main(lock_path, snapshot, home, output):
    lock, targets = prepare_locked(lock_path, snapshot, home, include_previous=True)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    candidate = run(home, "candidate", diagnostic=False, performance=False)
    previous = run(home, "previous", diagnostic=False, performance=False) if lock.get("previous") else None
    envelope = read(Path(home) / "runs" / candidate["runId"] / "run.json")
    excluded = {"PRO-R02", "PRO-R06"}
    original_checks = envelope["acceptance"]["checks"]
    checks = [c for c in envelope["acceptance"]["checks"] if c["requirement"] not in excluded | {"PRO-R09"}
              and c["id"] not in {"platform_matrix", "native_install", "npm_native_install"}]
    release_comparison=[]
    if previous:
        previous_envelope=read(Path(home) / "runs" / previous["runId"] / "run.json")
        previous_checks=[c for c in previous_envelope["acceptance"]["checks"] if c["requirement"] not in excluded | {"PRO-R09"}]
        release_comparison=compare_assertions(previous_checks,checks,True)
        regressions=[x for x in release_comparison if x['classification']=='regression']
        checks.append({"id":"candidate_previous_compatibility","requirement":"PRO-R04",
            "title":"候选版与前一正式版在同一冻结输入下的契约差异","status":"failed" if regressions else "passed",
            "expected":"no previously passing contract regresses","actual":{"regressions":regressions,"changes":release_comparison}})
    # Linux x64 GNU is the main job's R08 evidence.
    install_checks = [c for c in original_checks if c["id"] in {"release_version", "native_install", "npm_native_install"}]
    install_ok = len(install_checks) == 3 and all(c["status"] == "passed" for c in install_checks)
    checks.append({"id": "platform_linux-x64-gnu", "requirement": "PRO-R08",
                   "title": "Linux x64 GNU 发布包安装运行", "status": "passed" if install_ok else "failed",
                   "expected": "published x86_64 GNU binary and npm launcher", "actual": install_checks})
    security = read(Path(home) / "security-entry.json", {})
    enabled = security.get("privateReporting", {}).get("enabled") is True
    security_policy = targets["candidate"]["release"].get("sourceSnapshots", {}).get("SECURITY.md", {})
    policy_present = not security_policy.get("missing") and bool(security_policy.get("sha256"))
    policy_text = ""
    if policy_present and security_policy.get("path"):
        policy_text = Path(security_policy["path"]).read_text(errors="replace")
    expected_entry = "https://github.com/" + lock["policy"]["repository"] + "/security/advisories/new"
    declared_entries = sorted(set(re.findall(r"https://github\.com/[^\s)>]+/security/advisories/new", policy_text)))
    entry_matches = expected_entry in declared_entries
    form_access={"url":expected_entry,"authenticated":bool(os.getenv('GITHUB_TOKEN'))}
    try:
        request=urllib.request.Request(expected_entry,headers={'User-Agent':'deckprobe-acceptance',
            **({'Authorization':'Bearer '+os.environ['GITHUB_TOKEN']} if os.getenv('GITHUB_TOKEN') else {})})
        with urllib.request.urlopen(request,timeout=20) as response:
            form_access.update(status=response.status,finalUrl=response.url,accessible=response.status==200 and '/security/advisories/new' in response.url)
    except (OSError,urllib.error.HTTPError) as error:
        form_access.update(accessible=False,error=str(error),status=getattr(error,'code',None))
    checks.extend([
        {"id": "private_reporting_enabled", "requirement": "PRO-R09", "title": "GitHub 私密漏洞报告设置开启",
         "status": "passed" if enabled else ("blocked" if security.get("blocked") else "failed"), "expected": True, "actual": security},
        {"id": "security_policy_entry", "requirement": "PRO-R09", "title": "发布提交包含可访问的 SECURITY 策略入口",
         "status": "passed" if policy_present and entry_matches else "failed",
         "expected": {"SECURITY.md": "bound to release commit", "privateReportUrl": expected_entry},
         "actual": {"sha256": security_policy.get("sha256"), "missing": security_policy.get("missing", False),
                    "declaredEntries": declared_entries, "matchesRepository": entry_matches}},
        {"id":"security_private_entry_access","requirement":"PRO-R09","title":"以当前 GitHub 身份访问私密报告表单",
         "status":"passed" if form_access.get('accessible') else "blocked",
         "expected":{"authenticated":True,"status":200,"path":"/security/advisories/new"},"actual":form_access},
    ])
    inventory=read(Path(home)/"facts/index.json",{"facts":[]})
    for row in inventory.get("facts",[]):
        if row.get("scope",{}).get("mode")=="reference" or row.get("mapping",{}).get("status")=="mapped":continue
        fact=row["fact"];mapping=row.get("mapping",{})
        checks.append({"id":"fact-gap-"+fact["id"],"requirement":"PRO-R03","title":fact["question"],
            "status":"review","role":"observation","expected":fact.get("expected"),
            "actual":{"mappingStatus":mapping.get("status"),"reason":mapping.get("note"),"executed":False},
            "approval":fact.get("status","pending"),"evidence":["facts.json"]})
    result = job_result(lock, "main-functional", checks, candidateRun=candidate, previousRun=previous,
                        releaseComparison=release_comparison)
    atomic(output / "job-result.json", result)
    source = Path(home) / "runs" / candidate["runId"]
    shutil.copytree(source, output / "run", dirs_exist_ok=True)
    atomic(output / "run/facts.json",inventory)
    seal(output)
    return result


def _asset(lock, asset_name):
    assets = {a["name"]: a for a in lock["candidate"]["assets"]}
    if asset_name not in assets: raise ValueError("published asset missing: " + asset_name)
    return assets[asset_name]


def _platform_environment(platform_id):
    machine = platform.machine().lower()
    expected_machine = "arm" if "arm64" in platform_id else "x64"
    machine_ok = machine in ({"arm64", "aarch64"} if expected_machine == "arm" else {"x86_64", "amd64"})
    system_ok = ((platform_id.startswith("macos-") and platform.system() == "Darwin") or
                 (platform_id.startswith("linux-") and platform.system() == "Linux") or
                 (platform_id.startswith("windows-") and platform.system() == "Windows"))
    libc = platform.libc_ver()
    musl_files = list(Path("/lib").glob("ld-musl-*.so.1")) if platform.system() == "Linux" else []
    musl_ok = bool(musl_files) if platform_id.endswith("musl") else True
    return {"system": platform.system(), "machine": machine, "libc": libc, "muslLoader": [str(p) for p in musl_files],
            "matches": machine_ok and system_ok and musl_ok}


def _binary_arch(path):
    data=Path(path).read_bytes()[:4096]
    if data[:4]==b'\x7fELF':
        endian='little' if data[5]==1 else 'big';machine=int.from_bytes(data[18:20],endian)
        return {'format':'ELF','arch':{62:'x86_64',183:'aarch64'}.get(machine,'machine-'+str(machine))}
    magic=int.from_bytes(data[:4],'big')
    if magic in {0xfeedface,0xfeedfacf,0xcefaedfe,0xcffaedfe}:
        endian='big' if magic in {0xfeedface,0xfeedfacf} else 'little';cpu=int.from_bytes(data[4:8],endian)
        return {'format':'Mach-O','arch':{0x01000007:'x86_64',0x0100000c:'arm64'}.get(cpu,'cpu-'+hex(cpu))}
    if data[:2]==b'MZ' and len(data)>=64:
        offset=int.from_bytes(data[60:64],'little')
        full=Path(path).read_bytes()[offset:offset+8]
        if full[:4]==b'PE\0\0':
            machine=int.from_bytes(full[4:6],'little')
            return {'format':'PE','arch':{0x8664:'x86_64',0xaa64:'arm64'}.get(machine,'machine-'+hex(machine))}
    return {'format':'unknown','arch':'unknown'}


def platform_smoke(lock_path, snapshot, platform_id, output):
    lock = read(lock_path); output = Path(output); output.mkdir(parents=True, exist_ok=True)
    target, asset_name = PLATFORMS[platform_id]
    checks = []
    try:
        errors = validate_snapshot(snapshot)
        if errors: raise ValueError("; ".join(errors))
        environment = _platform_environment(platform_id)
        if not environment["matches"]: raise ValueError("runner environment does not match platform: " + json.dumps(environment))
        asset = _asset(lock, asset_name); data = fetch(asset["browser_download_url"])
        actual_hash = __import__("hashlib").sha256(data).hexdigest()
        if asset.get("digest") and asset["digest"] != "sha256:" + actual_hash:
            raise ValueError("GitHub release digest mismatch")
        checksum_asset = _asset(lock, asset_name + ".sha256")
        checksum_text = fetch(checksum_asset["browser_download_url"]).decode("utf-8").strip().split()[0]
        if checksum_text != actual_hash: raise ValueError("published checksum mismatch")
        archive = output / asset_name; archive.write_bytes(data)
        unpacked = output / "unpacked"; safe_extract(data, unpacked)
        binary_name = "deckprobe.exe" if platform_id == "windows-x64" else "deckprobe"
        binaries = list(unpacked.rglob(binary_name))
        if len(binaries) != 1: raise ValueError("expected exactly one executable")
        binary = binaries[0]; binary.chmod(binary.stat().st_mode | 0o100)
        binary_identity=_binary_arch(binary)
        version = process([str(binary), "--version"], timeout=30)
        sample = read(Path(snapshot) / "samples.json")["samples"][0]
        smoke = process([str(binary), "-l", "header", "-t", "document.format", str(Path(snapshot) / sample["object"])], timeout=60)
        expected = "deckprobe " + lock["candidate"]["tag"].lstrip("v")
        expected_arch='arm64' if 'aarch64' in target else 'x86_64'
        ok = (version.get("exitCode") == 0 and version.get("stdout", "").strip() == expected and smoke.get("exitCode") == 0
              and binary_identity.get('arch')==expected_arch)
        if ok:
            try: ok = isinstance(json.loads(smoke["stdout"]), dict)
            except ValueError: ok = False
        checks.append({"id": "platform_" + platform_id, "requirement": "PRO-R08",
                       "title": platform_id + " 发布资产安装、版本和 schema smoke", "status": "passed" if ok else "failed",
                       "expected": {"target": target, "version": expected,"binaryArch":expected_arch},
                       "actual": {"asset": asset_name, "sha256": actual_hash, "environment": environment,
                                  "binaryIdentity":binary_identity,"version": version, "smoke": smoke}})
    except (OSError, ValueError, RuntimeError) as error:
        checks.append({"id": "platform_" + platform_id, "requirement": "PRO-R08", "title": platform_id + " 平台 smoke",
                       "status": "blocked", "expected": target, "actual": str(error)})
    result = job_result(lock, "platform-smoke", checks, platformId=platform_id, targetTriple=target)
    atomic(output / "job-result.json", result); seal(output)
    return result


def run_performance(lock_path, snapshot, home, output):
    lock, targets = prepare_locked(lock_path, snapshot, home, include_previous=True)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    if not lock.get("previous"):
        checks = [{"id": "performance_pair", "requirement": "PRO-R06", "title": "新旧版本配对趋势",
                   "status": "blocked", "role": "observation", "expected": "two stable releases", "actual": None}]
        record = None
    else:
        pair = paired_performance(home); record = read(pair.get("path"), {})
        incomplete = [g for g in record.get("groups", []) if g.get("status") == "blocked"]
        comparisons = []
        policy = lock["policy"]["performance"]
        for group in record.get("groups", []):
            if group.get("status") == "blocked": continue
            durations = {label: sorted(x["durationMs"] for x in group["samples"][label] if x.get("exitCode") == 0)
                         for label in ("candidate", "previous")}
            if any(len(values) != policy["samples"] for values in durations.values()):
                incomplete.append(group); continue
            for metric, index in [("p50", None), ("p95", max(0, int(.95 * policy["samples"] + .999) - 1))]:
                before = statistics.median(durations["previous"]) if index is None else durations["previous"][index]
                after = statistics.median(durations["candidate"]) if index is None else durations["candidate"][index]
                delta = after - before; relative = delta / before if before else None
                comparisons.append({"caseId": group["caseId"], "level": group["level"], "mode": group["mode"],
                    "metric": metric, "previousMs": before, "candidateMs": after, "absoluteDeltaMs": delta,
                    "relativeDelta": relative, "status": "review" if relative is not None and relative >= policy["relativeAlert"] and delta >= policy["absoluteAlertMs"] else "observation"})
        # Exercise JS/WASM/browser/Worker surfaces on both frozen versions in the same runner.
        runtime_records = []
        sources = {s['id']:s for s in read(Path(home) / "corpus/manifest.json")["sources"]}
        for case_id in policy.get('cases',[]):
            sample=sources.get(case_id)
            if not sample or sample.get('private'):
                incomplete.append({'runtimeCase':case_id,'reason':'missing or private'});continue
            for level in policy.get('levels',[]):
                result=process(["node",str(CODE/"adapters/paired-performance.mjs"),
                    targets['candidate']['packages']['folder'],targets['previous']['packages']['folder'],sample['path'],
                    targets['candidate']['release']['binary'],targets['previous']['release']['binary'],level,
                    str(policy['warmup']),str(policy['samples'])],targets['candidate']['packages']['folder'],3600,
                    env=targets['candidate']['packages'].get('browserEnv',{}))
                entry={'caseId':case_id,'level':level,'process':result};runtime_records.append(entry)
                try:parsed=json.loads(result.get('stdout',''))
                except (ValueError,TypeError):parsed={}
                if result.get('exitCode')!=0 or not parsed.get('modes'):
                    incomplete.append({'runtimeCase':case_id,'level':level});continue
                entry['measurement']=parsed
                for mode in parsed['modes']:
                    runtime_times={label:sorted(p['durationMs'] for p in mode.get('samples',{}).get(label,[]) if not p.get('error')) for label in ['previous','candidate']}
                    if any(len(x)!=policy['samples'] for x in runtime_times.values()):
                        incomplete.append({'runtimeCase':case_id,'level':level,'mode':mode.get('mode')});continue
                    for metric,index in [('p50',None),('p95',max(0,int(.95*policy['samples']+.999)-1))]:
                        before=statistics.median(runtime_times['previous']) if index is None else runtime_times['previous'][index]
                        after=statistics.median(runtime_times['candidate']) if index is None else runtime_times['candidate'][index]
                        delta=after-before;relative=delta/before if before else None
                        comparisons.append({'caseId':case_id,'level':level,'mode':mode['mode'],'metric':metric,
                            'previousMs':before,'candidateMs':after,'absoluteDeltaMs':delta,'relativeDelta':relative,
                            'status':'review' if relative is not None and relative>=policy['relativeAlert'] and delta>=policy['absoluteAlertMs'] else 'observation'})
        atomic(output / "runtime-pairs.json", runtime_records)
        record["comparisons"] = comparisons; record["runtimePairs"] = runtime_records
        review = any(c["status"] == "review" for c in comparisons)
        checks = [{"id": "performance_pair", "requirement": "PRO-R06", "title": "GitHub runner 新旧版本配对趋势",
                   "status": "blocked" if incomplete else ("review" if review else "passed"), "role": "observation",
                   "expected": {"warmup": policy['warmup'], "samples": policy['samples'], "claim": "trend only"},
                   "actual": {"groups": len(record.get("groups", [])), "comparisons": len(comparisons),
                              "runtimeVersions": len(runtime_records), "blocked": len(incomplete), "alerts": sum(c["status"] == "review" for c in comparisons)}}]
        if record: atomic(output / "paired.json", record)
    result = job_result(lock, "performance", checks, "BLOCKED" if checks[0]["status"] == "blocked" else ("REVIEW" if checks[0]["status"] == "review" else "PASS"))
    atomic(output / "job-result.json", result); seal(output)
    return result


def aggregate(lock_path, inputs, output):
    lock = read(lock_path); output = Path(output); output.mkdir(parents=True, exist_ok=True)
    results = []; seen = set(); main_context = None
    for path in sorted(Path(inputs).rglob("job-result.json")):
        integrity = verify_seal(path.parent)
        if integrity: raise ValueError("job result evidence mismatch: " + "; ".join(integrity))
        value = read(path)
        if value.get("job") == "freeze": continue
        if value.get("schemaVersion") != JOB_SCHEMA: raise ValueError("unsupported job result schema: " + str(path))
        if value.get("runId") != lock["runId"] or value.get("inputDigest") != lock["inputDigest"]:
            raise ValueError("job result binding mismatch: " + str(path))
        if value.get("release") != (lock.get("candidate") or {}).get("tag"):
            raise ValueError("job release binding mismatch: " + str(path))
        identity = (value.get("job"), value.get("platformId") if value.get("job") == "platform-smoke" else None)
        if identity in seen: raise ValueError("duplicate job result: " + repr(identity))
        seen.add(identity)
        evidence_key = value.get("job", "job") + ("-" + value["platformId"] if value.get("platformId") else "")
        evidence_root = output / "job-evidence" / evidence_key
        if value.get("job") == "main-functional" and (path.parent / "run").is_dir():
            archived_context = read(path.parent / "run" / "report-context.json", {})
            if archived_context:
                main_context = _portable(archived_context)
            for check in value.get("checks", []):
                rewritten = []
                for item in check.get("evidence", []):
                    source = path.parent / "run" / item
                    if not source.is_file():
                        check["status"]="blocked"
                        check.setdefault("missingEvidence",[]).append(item)
                        continue
                    destination = evidence_root / "run" / item; destination.parent.mkdir(parents=True, exist_ok=True)
                    if source.suffix == ".json": atomic(destination, _portable(read(source)))
                    else: shutil.copyfile(source, destination)
                    rewritten.append("job-evidence/" + evidence_key + "/run/" + item)
                check["evidence"] = rewritten
        elif value.get("job") == "performance":
            evidence_root.mkdir(parents=True, exist_ok=True)
            for name in ["paired.json", "runtime-pairs.json"]:
                if (path.parent / name).is_file(): atomic(evidence_root / name, _portable(read(path.parent / name)))
        elif value.get("job") == "security-linux" and (path.parent / "security-session.json").is_file():
            evidence_root.mkdir(parents=True, exist_ok=True)
            atomic(evidence_root / "security-session.json", _portable(read(path.parent / "security-session.json")))
        results.append(_portable(value))
    checks = [_portable(check) for result in results for check in result.get("checks", [])]
    if lock.get("status") == "BLOCKED":
        checks.append({"id": "freeze_blocked", "requirement": "PRO-R01", "title": "冻结正式发布与验收输入",
                       "status": "blocked", "expected": "READY snapshot and reachable published release",
                       "actual": lock.get("blocker")})
    expected_platforms = set(PLATFORMS)
    present = {r.get("platformId") for r in results if r.get("job") == "platform-smoke"}
    present.add("linux-x64-gnu" if any(c["id"] == "platform_linux-x64-gnu" for c in checks) else None)
    for missing in sorted(expected_platforms - present):
        checks.append({"id": "platform_" + missing, "requirement": "PRO-R08", "title": missing + " 平台结果",
                       "status": "blocked", "expected": "bound platform smoke result", "actual": "job result missing"})
    required_jobs = {"main-functional", "security-linux", "performance"}
    jobs = {r.get("job") for r in results}
    for missing in sorted(required_jobs - jobs):
        requirements = (["PRO-R01","PRO-R03","PRO-R04","PRO-R05","PRO-R07","PRO-R09"] if missing=="main-functional"
                        else ["PRO-R02"] if missing=="security-linux" else ["PRO-R06"])
        for requirement in requirements:
            checks.append({"id": "missing_" + missing + "_" + requirement.lower(), "requirement": requirement,
                           "title": missing + " 的 " + requirement + " 结果缺失", "status": "blocked",
                           "expected": "bound job result", "actual": None,
                           "role": "observation" if missing == "performance" else "gate"})
    if "main-functional" in jobs:
        represented={c.get("requirement") for r in results if r.get("job")=="main-functional" for c in r.get("checks",[])}
        for requirement in sorted({"PRO-R01","PRO-R03","PRO-R04","PRO-R05","PRO-R07","PRO-R09"}-represented):
            checks.append({"id":"empty_main_"+requirement,"requirement":requirement,
                "title":requirement+" 必需检查未提交","status":"blocked","expected":"nonempty checks","actual":None})
    if lock.get("status") == "NO_CHANGE":
        checks = [{"id": "no_change", "requirement": "PRO-R01", "title": "发布与验收输入无变化",
                   "status": "passed", "expected": lock["inputDigest"], "actual": lock["inputDigest"]}]
    record = {"runId": lock["runId"], "createdAt": now(), "targetVersion": (lock.get("candidate") or {}).get("tag", "unknown"),
              "codeSha256": lock["codeSha256"], "policyHash": lock["policyHash"], "cohortHash": lock["snapshotDigest"],
              "answersHash": lock["snapshotDigest"], "declarationsHash": lock["snapshotDigest"], "mode": "formal",
              "target": {"lock": lock}, "checks": checks, "inputDigest": lock["inputDigest"], "jobResults": results}
    if main_context:
        main_context.update({"runId": record["runId"], "cohortHash": record["cohortHash"],
                             "answersHash": record["answersHash"], "corpusBound": True, "answersBound": True,
                             "note": "来自同一冻结输入的 main-functional 归档上下文；路径已脱敏。"})
        atomic(output / "report-context.json", main_context)
    envelope = publish(output, record)
    seal(output)
    return {"runId": lock["runId"], "decision": envelope["qualitySummary"]["releaseDecision"], "checks": len(checks),
            "report": str(output / "report.html")}


def sanitize_publication(folder):
    from .ci_snapshot import SENSITIVE
    errors = []
    for path in Path(folder).rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".zip", ".gz", ".pdf"}: continue
        text = path.read_text(errors="ignore")
        for pattern in SENSITIVE:
            if pattern.search(text): errors.append(str(path))
    return sorted(set(errors))


def publish_history(run_folder, site, comparison=None):
    run_folder, site = Path(run_folder), Path(site)
    envelope = read(run_folder / "run.json")
    run_id = envelope["runId"]
    history = read(site / "history.json", {"schemaVersion": 1, "runs": [], "checks": []})
    history.setdefault("runs", []); history.setdefault("checks", [])
    lock_status = envelope.get("acceptance", {}).get("target", {}).get("lock", {}).get("status")
    if lock_status == "NO_CHANGE":
        history["checks"].append({"checkedAt": envelope["createdAt"], "status": "NO_CHANGE",
                                  "inputDigest": envelope["acceptance"]["inputDigest"]})
        atomic(site / "history.json", history)
        return {"runId": run_id, "runs": len(history["runs"]), "site": str(site), "noChange": True}
    destination = site / "runs" / run_id
    if destination.exists():
        old = read(destination / "run.json")
        if old.get("acceptance", {}).get("inputDigest") != envelope.get("acceptance", {}).get("inputDigest"):
            raise ValueError("run id collision")
    else: shutil.copytree(run_folder, destination)
    entry = {"runId": run_id, "createdAt": envelope["createdAt"],
            "release": envelope["acceptance"]["targetVersion"], "inputDigest": envelope["acceptance"]["inputDigest"],
            "decision": envelope["qualitySummary"]["releaseDecision"], "url": f"runs/{run_id}/report.html"}
    if comparison:
        comparison = Path(comparison)
        data = read(comparison / "comparison.json", {})
        name = data.get("before", "previous") + "--" + data.get("after", run_id)
        comparison_dest = site / "comparisons" / name
        if not comparison_dest.exists(): shutil.copytree(comparison, comparison_dest)
        entry["comparisonUrl"] = f"comparisons/{name}/comparison.html"
    if not any(r["runId"] == run_id for r in history["runs"]):
        history["runs"].append(entry)
    if envelope["qualitySummary"]["releaseDecision"] == "PASS":
        history["lastPassedRunId"] = run_id
    atomic(site / "history.json", history)
    latest = site / "latest"
    if latest.exists(): shutil.rmtree(latest)
    shutil.copytree(run_folder, latest)
    if history.get("lastPassedRunId") == run_id:
        passed = site / "last-passed"
        if passed.exists(): shutil.rmtree(passed)
        shutil.copytree(run_folder, passed)
    rows = "".join(f'<tr><td>{html.escape(r["createdAt"])}</td><td>{html.escape(r["release"])}</td><td>{r["decision"]}</td><td><a href="{r["url"]}">报告</a>' + (f' · <a href="{r["comparisonUrl"]}">差异</a>' if r.get("comparisonUrl") else '') + '</td></tr>' for r in reversed(history["runs"]))
    passed_link = ' · <a href="last-passed/report.html">最近通过基线</a>' if history.get("lastPassedRunId") else ''
    atomic(site / "index.html", '<!doctype html><meta charset="utf-8"><title>DeckProbe 验收历史</title><style>body{font:15px system-ui;margin:40px;max-width:1100px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:10px}</style><h1>DeckProbe 每周发布验收</h1><p><a href="latest/report.html">查看最新报告</a>'+passed_link+'</p><table><tr><th>时间</th><th>版本</th><th>结论</th><th>报告</th></tr>'+rows+'</table>')
    leaks = sanitize_publication(site)
    if leaks: raise ValueError("publication contains sensitive paths or values: " + ", ".join(leaks))
    return {"runId": run_id, "runs": len(history["runs"]), "site": str(site)}


def verdict(run_folder):
    value = read(Path(run_folder) / "run.json")
    result = value["qualitySummary"]["releaseDecision"]
    return {"decision": result, "success": result == "PASS"}
