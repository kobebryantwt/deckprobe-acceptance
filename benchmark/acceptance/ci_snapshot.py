"""Public, path-independent execution snapshots for GitHub acceptance."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .common import CODE, atomic, digest, now, read, sha
from .corpus import approved

SCHEMA_VERSION = 1
SENSITIVE = [
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\", re.I),
    re.compile(r"(?i)(?:authorization|x-api-key|token|secret|password)\s*[:=]\s*[^\s,}\]]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
]


def _portable(value):
    """Remove cache locations while retaining a reviewable evidence label."""
    if isinstance(value, dict): return {k: _portable(v) for k, v in value.items()}
    if isinstance(value, list): return [_portable(v) for v in value]
    if isinstance(value, str):
        if SENSITIVE[0].search(value) or SENSITIVE[1].search(value):
            name = Path(value.replace("\\", "/")).name
            return "local-evidence://" + (name or "redacted")
        if any(x in value for x in ("http://", "https://", "mailto:")):
            value = re.sub(r"(?i)[?&](?:authType|authToken|token|secret|password|key|authorization|x-api-key)=[^&\"\'\s,}\]]+", "", value)
        if SENSITIVE[2].search(value):
            value = SENSITIVE[2].sub("redacted_credential", value)
    return value


def _scan_text(value, location="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _scan_text(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _scan_text(child, f"{location}[{index}]")
    elif isinstance(value, str):
        for pattern in SENSITIVE:
            if pattern.search(value):
                yield f"sensitive value at {location}"


def _public_source(source, objects):
    path = Path(source["path"])
    if source.get("private"):
        raise ValueError(f"Private sample cannot be exported: {source['id']}")
    if not path.is_file() or sha(path) != source["sha256"]:
        raise ValueError(f"Sample missing or hash changed: {source['id']}")
    name = source.get("maintenance", {}).get("inputName") or path.name
    destination = objects / source["sha256"] / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, destination)
    provenance = source.get("provenance", {})
    return {
        "id": source["id"], "format": source["format"], "sha256": source["sha256"],
        "bytes": path.stat().st_size, "object": str(destination.relative_to(objects.parent)),
        "inputName": name, "active": bool(source.get("active", True)), "private": False,
        "purpose": source.get("purpose"),
        "provenance": {k: provenance.get(k) for k in ("type", "project", "generator", "version", "parameters", "url",
            "upstreamPath", "preparation", "license", "redistributable") if provenance.get(k) is not None},
    }


def export_snapshot(home, output, allow_draft=False):
    home, output = Path(home), Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    objects = output / "objects"
    corpus = read(home / "corpus/manifest.json", {"sources": []})
    index = read(home / "answers/index.json", {"answers": []})
    active = [s for s in corpus.get("sources", []) if s.get("active", True)]
    public = [s for s in active if not s.get("private")]
    samples = [_public_source(s, objects) for s in public]
    sample_ids = {s["id"] for s in samples}
    answers, pending = [], []
    for answer in index.get("answers", []):
        if answer.get("caseId") not in sample_ids:
            continue
        if not approved(home, answer):
            pending.append(answer["id"])
            if not allow_draft:
                continue
        exported = _portable({k: answer.get(k) for k in (
            "id", "caseId", "sourceSha256", "format", "question", "expected", "evidence",
            "check", "options", "requirement", "reviewStatus", "factReference")})
        exported["sourceAnswerDigest"] = answer.get("answerDigest")
        exported["reviewStatus"] = "approved" if approved(home, answer) else "draft"
        exported["answerDigest"] = digest(exported)
        exported["approval"] = "approved" if approved(home, answer) else "draft"
        answers.append(exported)
    # Preserve the full public fact inventory, including unsupported mappings.
    facts=[]
    for row in read(home / "facts/index.json", {}).get("facts", []):
        if row.get("sampleId") not in sample_ids:continue
        exported=_portable(row)
        exported["recordDigest"]=digest(exported)
        facts.append(exported)
    atomic(output / "facts.json", {"schemaVersion": SCHEMA_VERSION, "facts": facts})
    claims = read(home / "declarations.json", {})
    policy = read(CODE / "config/policy.json", {})
    performance_cases = policy.get("performance", {}).get("cases", [])
    missing_performance_cases = sorted(set(performance_cases) - sample_ids)
    gaps = list(corpus.get("gaps", []))
    claims_approved = claims.get("reviewStatus") == "approved"
    claim_rows=claims.get('rows',[])
    required_scenarios=policy.get('requiredScenarios',[])
    scenario_rows={x.get('id'):x for x in claims.get('scenarioCoverage',[])}
    claims_complete=(bool(claim_rows) and all(x.get('reviewStatus')=='approved' for x in claim_rows) and
                     all(scenario_rows.get(x,{}).get('reviewStatus')=='approved' and scenario_rows[x].get('answerIds')
                         for x in required_scenarios))
    status = "approved" if public and not pending and answers and not gaps and claims_approved and claims_complete and not missing_performance_cases else "draft"
    atomic(output / "samples.json", {"schemaVersion": SCHEMA_VERSION, "samples": samples, "gaps": gaps,
                                     "omittedPrivateSamples": sum(bool(s.get("private")) for s in active)})
    atomic(output / "answers.json", {"schemaVersion": SCHEMA_VERSION, "answers": answers, "pending": pending})
    atomic(output / "claims.json", {"schemaVersion": SCHEMA_VERSION, "claims": claims})
    atomic(output / "policy.json", {"schemaVersion": SCHEMA_VERSION, "policy": policy})
    snapshot = {"schemaVersion": SCHEMA_VERSION, "createdAt": now(), "status": status,
                "counts": {"samples": len(samples), "answers": len(answers), "pending": len(pending), "gaps": len(gaps)},
                "factInventoryVersion": 1, "factCount": len(facts),
                "claimsApproved": claims_approved,
                "claimsComplete": claims_complete,
                "missingPerformanceCases": missing_performance_cases,
                "sourceCohort": corpus.get("cohortHash"), "contentDigest": None}
    atomic(output / "snapshot.json", snapshot)
    errors = validate_snapshot(output, require_ready=False, require_checksums=False)
    if errors:
        raise ValueError("; ".join(errors))
    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name not in {"SHA256SUMS", "READY"})
    sums = "".join(f"{sha(p)}  {p.relative_to(output).as_posix()}\n" for p in files)
    atomic(output / "SHA256SUMS", sums)
    snapshot["contentDigest"] = digest({str(p.relative_to(output)): sha(p) for p in files})
    atomic(output / "snapshot.json", snapshot)
    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name not in {"SHA256SUMS", "READY"})
    atomic(output / "SHA256SUMS", "".join(f"{sha(p)}  {p.relative_to(output).as_posix()}\n" for p in files))
    if status == "approved":
        atomic(output / "READY", sha(output / "SHA256SUMS") + "\n")
    elif not allow_draft:
        reasons=[]
        if pending: reasons.append(f"{len(pending)} answers still require approval")
        if gaps: reasons.append(f"{len(gaps)} declared coverage gaps remain")
        if not claims_approved: reasons.append("the product declaration matrix is not approved")
        if not claims_complete: reasons.append("the declaration rows or required scenario bindings are incomplete")
        if missing_performance_cases: reasons.append("performance cases are missing from the public cohort: " + ", ".join(missing_performance_cases))
        if not public or not answers: reasons.append("the public execution cohort is empty")
        raise ValueError("CI snapshot is not ready: " + "; ".join(reasons) + "; use --allow-draft only for review")
    return {"status": status, **snapshot["counts"], "output": str(output), "ready": status == "approved"}


def validate_snapshot(folder, require_ready=True, require_checksums=True):
    folder = Path(folder)
    errors = []
    required = ["snapshot.json", "samples.json", "answers.json", "claims.json", "policy.json", "SHA256SUMS"]
    for name in required:
        if not (folder / name).is_file() and (name != "SHA256SUMS" or require_checksums):
            errors.append("missing " + name)
    snapshot = read(folder / "snapshot.json", {})
    samples = read(folder / "samples.json", {})
    answers = read(folder / "answers.json", {})
    claims = read(folder / "claims.json", {}).get("claims", {})
    policy = read(folder / "policy.json", {}).get("policy", {})
    policy_envelope = read(folder / "policy.json", {})
    claims_envelope = read(folder / "claims.json", {})
    for value, name in [(snapshot, "snapshot"), (samples, "samples"), (answers, "answers"),
                        (claims_envelope, "claims"), (policy_envelope, "policy")]:
        if value.get("schemaVersion") != SCHEMA_VERSION:
            errors.append("unsupported schema: " + name)
        errors.extend(_scan_text(value, name))
    fact_inventory=read(folder / "facts.json", {})
    if snapshot.get("factInventoryVersion") == 1 and not (folder / "facts.json").is_file():
        errors.append("missing facts.json")
    errors.extend(_scan_text(fact_inventory,"facts"))
    fact_ids=set()
    sources_by_id={s.get("id"):s for s in samples.get("samples",[])}
    for row in fact_inventory.get("facts",[]):
        fact=row.get("fact",{});source=sources_by_id.get(row.get("sampleId"))
        if fact.get("id") in fact_ids:errors.append("duplicate fact id: "+str(fact.get("id")))
        fact_ids.add(fact.get("id"))
        if not source or fact.get("binding",{}).get("sha256")!=source.get("sha256"):
            errors.append("fact source mismatch: "+str(fact.get("id")))
        if row.get("recordDigest")!=digest({k:v for k,v in row.items() if k!="recordDigest"}):
            errors.append("fact record digest mismatch: "+str(fact.get("id")))
    ids = set()
    for sample in samples.get("samples", []):
        if sample.get("id") in ids: errors.append("duplicate sample id: " + str(sample.get("id")))
        ids.add(sample.get("id"))
        path = folder / sample.get("object", "")
        if not path.is_file() or sha(path) != sample.get("sha256"):
            errors.append("sample object mismatch: " + str(sample.get("id")))
        if sample.get("private"): errors.append("private sample in public snapshot: " + str(sample.get("id")))
    answer_ids = set()
    for answer in answers.get("answers", []):
        if answer.get("id") in answer_ids: errors.append("duplicate answer id: " + str(answer.get("id")))
        answer_ids.add(answer.get("id"))
        if answer.get("caseId") not in ids: errors.append("answer without sample: " + str(answer.get("id")))
        source = next((sample for sample in samples.get("samples", []) if sample.get("id") == answer.get("caseId")), None)
        if source and answer.get("sourceSha256") != source.get("sha256"):
            errors.append("answer source mismatch: " + str(answer.get("id")))
        expected_digest = digest({k: v for k, v in answer.items() if k not in {"answerDigest", "approval"}})
        if answer.get("answerDigest") != expected_digest:
            errors.append("answer digest mismatch: " + str(answer.get("id")))
        if require_ready and answer.get("approval") != "approved": errors.append("unapproved answer: " + str(answer.get("id")))
    if require_ready and not samples.get("samples"): errors.append("public sample cohort is empty")
    if require_ready and not answers.get("answers"): errors.append("approved answer set is empty")
    if require_ready and answers.get("pending"): errors.append("pending answers remain")
    if require_ready and samples.get("gaps"): errors.append("declared coverage gaps remain")
    if require_ready and claims.get("reviewStatus") != "approved": errors.append("product declaration matrix is not approved")
    if require_ready:
        rows=claims.get('rows',[])
        if not rows: errors.append('product declaration matrix is empty')
        if any(x.get('reviewStatus')!='approved' for x in rows): errors.append('unapproved declaration rows remain')
        required=policy.get('requiredScenarios',[]); scenarios={x.get('id'):x for x in claims.get('scenarioCoverage',[])}
        for scenario in required:
            row=scenarios.get(scenario,{})
            if row.get('reviewStatus')!='approved' or not row.get('answerIds'):
                errors.append('required scenario is not approved and bound: '+scenario)
    if require_ready:
        missing_performance_cases = sorted(set(policy.get("performance", {}).get("cases", [])) - ids)
        if missing_performance_cases:
            errors.append("missing performance cases: " + ", ".join(missing_performance_cases))
    sums = folder / "SHA256SUMS"
    if sums.is_file():
        listed = set()
        for line in sums.read_text().splitlines():
            expected, separator, name = line.partition("  ")
            listed.add(name)
            path = folder / name
            if not separator or not path.is_file() or sha(path) != expected:
                errors.append("checksum mismatch: " + name)
        actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and p.name not in {"SHA256SUMS", "READY"}}
        if listed != actual:
            errors.append("checksum inventory mismatch")
    if require_ready and (snapshot.get("status") != "approved" or not (folder / "READY").is_file()):
        errors.append("snapshot is not READY")
    if require_ready and (folder / "READY").is_file() and sums.is_file():
        if (folder / "READY").read_text().strip() != sha(sums): errors.append("READY binding mismatch")
    return sorted(set(errors))


def materialize_snapshot(snapshot, home):
    snapshot, home = Path(snapshot), Path(home)
    errors = validate_snapshot(snapshot)
    if errors: raise ValueError("; ".join(errors))
    sample_data = read(snapshot / "samples.json")
    sources = []
    for item in sample_data["samples"]:
        source = dict(item)
        source["path"] = str((snapshot / item["object"]).resolve())
        sources.append(source)
    atomic(home / "corpus/manifest.json", {"version": "ci-1", "sources": sources, "gaps": sample_data.get("gaps", []),
           "cohortHash": digest(sorted((s["id"], s["sha256"]) for s in sources))})
    answers = []
    for exported in read(snapshot / "answers.json")["answers"]:
        answer = {k: v for k, v in exported.items() if k != "approval"}
        if digest({k: v for k, v in answer.items() if k != "answerDigest"}) != answer.get("answerDigest"):
            raise ValueError("answer digest mismatch: " + str(answer.get("id")))
        answers.append(answer)
    atomic(home / "facts/index.json", read(snapshot / "facts.json", {"schemaVersion":1,"facts":[]}))
    atomic(home / "answers/index.json", {"version": "ci-1", "answers": answers})
    for answer in answers:
        atomic(home / "answers/decisions" / (answer["answerDigest"] + ".json"), {
            "answerDigest": answer["answerDigest"], "decision": "approved", "reviewer": "CI snapshot"})
    atomic(home / "declarations.json", read(snapshot / "claims.json").get("claims", {}))
    atomic(home / "policy.json", read(snapshot / "policy.json").get("policy", {}))
    return {"samples": len(sources), "answers": len(answers)}
