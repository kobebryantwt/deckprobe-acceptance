#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pluggable document benchmark dispatcher and declarative evaluator."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SUITES = ROOT / "suites"
TARGETS = ROOT / "config" / "targets"
EVALUATORS = ROOT / "evaluators"
ARTIFACTS = ROOT / "artifacts"
CACHE = ROOT / "cache" / "sources"
CORE_VERSION = "2.1.0"
REPORT_CONTRACT_VERSION = "2"
CORE_CONTRACT_ID = "deck-benchmark-core-v2"
CORE_CAPABILITIES = (
    "decision_roles",
    "check_definition_enrichment",
    "macro_feature_scoring",
    "quality_policy_thresholds",
    "canonical_dual_reports",
    "human_answer_actual_evidence",
    "agent_repair_contract",
    "assertion_level_comparison",
    "comparison_compatibility_guards",
)
CHECK_ROLES = {"gate", "scored", "observation"}
SEVERITIES = {"critical", "major", "minor"}
ALLOWED_ASSERTIONS = {
    "exit_code", "json_path_exists", "json_path_equals", "json_path_contains",
    "json_path_regex", "json_path_count", "numeric_tolerance", "set_equals",
    "text_contains", "text_regex", "artifact_exists", "artifact_count", "ai_review",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at {path}:{number}")
        rows.append(value)
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_sha256(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in folder.rglob("*") if item.is_file() and "__pycache__" not in item.parts):
        digest.update(str(path.relative_to(folder)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def format_facts(path: Path) -> tuple[str, dict[str, Any]]:
    fmt = path.suffix.lower().lstrip(".")
    facts: dict[str, Any] = {}
    header = path.read_bytes()[:8]
    if fmt in {"pptx", "docx", "xlsx"}:
        if header.startswith(b"PK\x03\x04"):
            facts = {"container": "ooxml-zip", "encryptedContainer": False}
        elif header == bytes.fromhex("d0cf11e0a1b11ae1"):
            facts = {"container": "ole-compound-file", "encryptedContainer": True}
    return fmt, facts


def document_row(path: Path, *, display_path: str | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    digest = sha256(path)
    fmt, facts = format_facts(path)
    base_id = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return {
        "documentId": f"{base_id}-{fmt or 'unknown'}-{digest[:10]}",
        "path": display_path or path.name,
        "format": fmt,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "facts": facts,
        "source": source or {"type": "local", "uri": str(path.resolve())},
    }


def default_corpus_source() -> Path:
    preferred = ROOT / "corpus" / "inputs"
    return preferred if preferred.exists() else ROOT / "cases" / "inputs"


def corpus_scan(source_value: str | None = None, source_spec_value: str | None = None) -> dict[str, Any]:
    if source_spec_value:
        spec_path = Path(source_spec_value).expanduser().resolve()
        spec = read_json(spec_path)
        if spec.get("type") != "command-catalog":
            raise SystemExit(f"Unsupported corpus catalog type: {spec.get('type')}")
        command = expand_tokens(spec.get("command", []), {"uri": str(spec.get("uri", "")), "repo": str(REPO)})
        proc = run_process(command, spec_path.parent, int(spec.get("timeoutSeconds", 300)), {str(k): str(v) for k, v in spec.get("env", {}).items()})
        if proc.get("exitCode") != 0:
            raise SystemExit(proc.get("stderr") or "Corpus catalog command failed")
        payload = parse_payload(proc.get("stdout", ""))
        documents = payload.get("documents") if isinstance(payload, dict) else payload
        if not isinstance(documents, list) or not all(isinstance(item, dict) for item in documents):
            raise SystemExit("Corpus catalog must return a JSON array or an object containing documents")
        hashes: dict[str, list[str]] = {}
        for item in documents:
            source = item.get("source", item)
            if source.get("type") != "local" and not source.get("sha256"):
                raise SystemExit(f"Remote catalog item requires sha256: {source.get('uri')}")
            digest = source.get("sha256") or item.get("sha256")
            if digest:
                hashes.setdefault(str(digest), []).append(str(source.get("uri")))
        return {"source": {"type": "command-catalog", "uri": spec.get("uri"), "spec": str(spec_path)}, "documentCount": len(documents), "duplicates": [items for items in hashes.values() if len(items) > 1], "documents": documents}
    inputs = Path(source_value).expanduser().resolve() if source_value else default_corpus_source()
    if not inputs.exists():
        raise SystemExit(f"Corpus source does not exist: {inputs}")
    paths = [inputs] if inputs.is_file() else sorted(item for item in inputs.rglob("*") if item.is_file() and not item.name.startswith("."))
    documents = []
    hashes: dict[str, list[str]] = {}
    base = inputs if inputs.is_dir() else inputs.parent
    for path in paths:
        relative = str(path.relative_to(base))
        row = document_row(path, display_path=relative)
        documents.append(row)
        hashes.setdefault(row["sha256"], []).append(relative)
    return {"source": {"type": "local", "uri": str(inputs)}, "documentCount": len(documents), "duplicates": [items for items in hashes.values() if len(items) > 1], "documents": documents}


def suite_dir(suite_id: str) -> Path:
    path = SUITES / suite_id
    if not path.is_dir():
        raise SystemExit(f"Suite does not exist: {path}")
    return path


def load_suite(suite_id: str) -> tuple[Path, dict[str, Any]]:
    folder = suite_dir(suite_id)
    suite = read_json(folder / "suite.json")
    if suite.get("id") != suite_id:
        raise SystemExit(f"Suite id mismatch: requested {suite_id}, found {suite.get('id')}")
    return folder, suite


def load_target(target_id: str) -> dict[str, Any]:
    path = TARGETS / f"{target_id}.json"
    if not path.exists():
        raise SystemExit(f"Target does not exist: {path}")
    target = read_json(path)
    if target.get("id") != target_id:
        raise SystemExit(f"Target id mismatch: requested {target_id}, found {target.get('id')}")
    return target


def load_evaluator(reference: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    evaluator_id, version = reference.get("id"), str(reference.get("version", ""))
    if not evaluator_id or not version:
        raise ValueError("Suite evaluator requires id and version")
    folder = EVALUATORS / str(evaluator_id) / version
    path = folder / "evaluator.json"
    if not path.exists():
        raise ValueError(f"Evaluator does not exist: {path}")
    evaluator = read_json(path)
    if evaluator.get("id") != evaluator_id or str(evaluator.get("version")) != version:
        raise ValueError(f"Evaluator identity mismatch: {path}")
    return folder, evaluator


def suite_files(folder: Path, suite: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    features_payload = read_json(folder / suite.get("features", "features.json"))
    features = features_payload.get("features", [])
    cases = read_jsonl(folder / suite.get("cases", "cases.jsonl"))
    questions_path = folder / suite.get("questions", "questions.jsonl")
    questions = read_jsonl(questions_path) if questions_path.exists() else []
    return features, cases, questions


def quality_policy(suite: dict[str, Any]) -> dict[str, Any]:
    supplied = suite.get("qualityPolicy", {})
    scoring = supplied.get("scoring", {})
    return {
        "version": str(supplied.get("version", "1")),
        "gate": {"blockedDecision": "INCOMPLETE", **supplied.get("gate", {})},
        "scoring": {
            "scale": float(scoring.get("scale", 100)),
            "aggregation": scoring.get("aggregation", "macro_feature"),
            "passThreshold": scoring.get("passThreshold"),
            "reviewThreshold": scoring.get("reviewThreshold"),
        },
    }


def policy_hash(policy: dict[str, Any]) -> str:
    payload = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def core_contract_sha256() -> str:
    payload = {"contractId": CORE_CONTRACT_ID, "reportContractVersion": REPORT_CONTRACT_VERSION, "capabilities": list(CORE_CAPABILITIES)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def check_role(check: dict[str, Any]) -> str:
    if check.get("role") in CHECK_ROLES:
        return str(check["role"])
    return "gate" if check.get("required", True) else "observation"


def check_severity(check: dict[str, Any], role: str) -> str:
    if check.get("severity") in SEVERITIES:
        return str(check["severity"])
    return "major" if role == "gate" else "minor"


def enrich_assertions(case: dict[str, Any], assertions: list[dict[str, Any]], evaluator_type: str, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = case.get("assertions", []) if evaluator_type == "declarative" else case.get("evaluation", {}).get("checks", [])
    by_id = {str(item.get("id")): item for item in definitions}
    bindings: dict[str, dict[str, Any]] = {}
    for question in questions:
        if question.get("caseId") != case.get("id"):
            continue
        for assertion_id in question.get("assertionIds", []):
            bindings[str(assertion_id)] = {"featureId": question.get("featureId"), "questionId": question.get("questionId")}
    enriched = []
    for assertion in assertions:
        definition = by_id.get(str(assertion.get("id")), {})
        merged = {**definition, **assertion}
        role = check_role(merged)
        score_mode = str(merged.get("scoreMode", "binary"))
        score = merged.get("score")
        if role == "scored" and score is None and score_mode == "binary":
            score = 1.0 if merged.get("status") == "passed" else 0.0 if merged.get("status") == "failed" else None
        if score is not None:
            score = max(0.0, min(1.0, float(score)))
        enriched.append({
            **definition,
            **assertion,
            "type": assertion.get("type", definition.get("type", "unknown")),
            "role": role,
            "required": role == "gate",
            "severity": check_severity(merged, role),
            "weight": float(merged.get("weight", 1)),
            "scoreMode": score_mode,
            "score": score,
            **bindings.get(str(assertion.get("id")), {}),
        })
    return enriched


def validate_suite(suite_id: str, require_approved: bool = False) -> dict[str, Any]:
    folder, suite = load_suite(suite_id)
    errors: list[str] = []
    warnings: list[str] = []
    if suite.get("compatibility", {}).get("engine") == "legacy-render":
        try:
            _, evaluator = load_evaluator(suite.get("evaluator", {}))
            if evaluator.get("type") != "compatibility" or evaluator.get("engine") != "legacy-render":
                errors.append("Legacy render suite must bind the legacy-render compatibility evaluator")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
        if require_approved and suite.get("reviewStatus") != "approved":
            errors.append("Suite is not approved")
        manifest = (folder / suite["compatibility"].get("manifest", "../../cases/manifest.jsonl")).resolve()
        try:
            cases = read_jsonl(manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "suiteId": suite_id, "profile": "render", "evaluator": suite.get("evaluator"), "compatibility": True, "errors": errors + [str(exc)]}
        with tempfile.TemporaryDirectory(prefix="deck-benchmark-legacy-validation-") as tmp:
            staged = Path(tmp)
            rewritten = []
            for case in cases:
                source = case_source(case)
                source_type = source.get("type", "local")
                uri = str(source.get("uri", ""))
                suffix = source_extension(source) or Path(str(case.get("input", ""))).suffix
                if source_type == "local":
                    parsed = urllib.parse.urlparse(uri)
                    value = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else uri
                    if not Path(value).expanduser().is_file():
                        errors.append(f"Missing local input for {case.get('id')}: {value}")
                elif source_type not in {"http", "https", "command"}:
                    errors.append(f"Unsupported source type for {case.get('id')}: {source_type}")
                elif require_approved and not (source.get("sha256") or case.get("sha256")):
                    errors.append(f"Approved remote source requires sha256 for {case.get('id')}")
                name = f"{case.get('id')}{suffix}"
                (staged / name).write_bytes(b"validation-placeholder")
                rewritten.append({**case, "input": name})
            staged_manifest = staged / "manifest.jsonl"
            staged_manifest.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in rewritten), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "benchmark.py"), "validate", "--inputs", str(staged), "--manifest", str(staged_manifest)],
                text=True,
                capture_output=True,
            )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {"ok": False, "errors": [proc.stderr.strip()]}
        errors.extend(payload.get("errors", []))
        return {"ok": proc.returncode == 0 and not errors, "suiteId": suite_id, "profile": "render", "evaluator": suite.get("evaluator"), "compatibility": True, "legacy": payload, "errors": errors}
    try:
        _, evaluator = load_evaluator(suite.get("evaluator", {}))
        if evaluator.get("profile") not in {"*", suite.get("profile")}:
            errors.append(f"Evaluator profile mismatch: suite={suite.get('profile')} evaluator={evaluator.get('profile')}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        evaluator = {}
        errors.append(str(exc))
    try:
        features, cases, questions = suite_files(folder, suite)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "suiteId": suite_id, "errors": [str(exc)], "warnings": []}
    feature_ids = [item.get("id") for item in features]
    case_ids = [item.get("id") for item in cases]
    question_ids = [item.get("questionId") for item in questions]
    for label, values in (("feature", feature_ids), ("case", case_ids), ("question", question_ids)):
        duplicates = sorted({value for value in values if value and values.count(value) > 1})
        if duplicates:
            errors.append(f"Duplicate {label} ids: {', '.join(duplicates)}")
    feature_set, case_set = set(feature_ids), set(case_ids)
    assertion_ids: dict[str, set[str]] = {}
    assertion_bindings: dict[str, set[str]] = {}
    covered: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        try:
            source = case_source(case)
            if source.get("type", "local") == "local":
                parsed = urllib.parse.urlparse(str(source.get("uri", "")))
                value = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else str(source.get("uri", ""))
                if not Path(value).expanduser().is_file():
                    errors.append(f"Missing local input for {case_id}: {value}")
            elif source.get("type") not in {"http", "https", "command"}:
                errors.append(f"Unsupported source type for {case_id}: {source.get('type')}")
            elif require_approved and not (source.get("sha256") or case.get("sha256")):
                errors.append(f"Approved remote source requires sha256 for {case_id}")
        except ValueError as exc:
            errors.append(str(exc))
        unknown = sorted(set(case.get("covers", [])) - feature_set)
        if unknown:
            errors.append(f"Unknown features for {case_id}: {', '.join(unknown)}")
        covered.update(case.get("covers", []))
        checks = case.get("assertions", []) if evaluator.get("type") == "declarative" else case.get("evaluation", {}).get("checks", [])
        ids: list[str] = []
        for assertion in checks:
            assertion_id = assertion.get("id")
            if not assertion_id:
                errors.append(f"Assertion without id in {case_id}")
            elif assertion_id in ids:
                errors.append(f"Duplicate assertion id {assertion_id} in {case_id}")
            ids.append(assertion_id)
            if evaluator.get("type") == "declarative" and assertion.get("type") not in ALLOWED_ASSERTIONS:
                errors.append(f"Unknown assertion type in {case_id}/{assertion_id}: {assertion.get('type')}")
            role = check_role(assertion)
            if assertion.get("role") is not None and assertion.get("role") not in CHECK_ROLES:
                errors.append(f"Invalid role in {case_id}/{assertion_id}: {assertion.get('role')}")
            if assertion.get("severity") is not None and assertion.get("severity") not in SEVERITIES:
                errors.append(f"Invalid severity in {case_id}/{assertion_id}: {assertion.get('severity')}")
            try:
                if float(assertion.get("weight", 1)) <= 0:
                    errors.append(f"Weight must be positive in {case_id}/{assertion_id}")
            except (TypeError, ValueError):
                errors.append(f"Weight must be numeric in {case_id}/{assertion_id}")
            if role == "observation" and assertion.get("finding", False):
                errors.append(f"Observation cannot be actionable finding in {case_id}/{assertion_id}")
            if role == "scored" and assertion.get("scoreMode", "binary") not in {"binary", "evaluator"}:
                errors.append(f"Invalid scoreMode in {case_id}/{assertion_id}: {assertion.get('scoreMode')}")
        assertion_ids[str(case_id)] = set(ids)
        assertion_bindings[str(case_id)] = set()
    missing_features = sorted(feature_set - covered)
    if missing_features:
        errors.append(f"Uncovered features: {', '.join(missing_features)}")
    for question in questions:
        qid = question.get("questionId")
        case_id = question.get("caseId")
        required_question_fields = {"questionId", "caseId", "featureId", "question", "answer", "assertionIds", "evidence", "reviewStatus"}
        missing_question_fields = sorted(required_question_fields - set(question))
        if missing_question_fields:
            errors.append(f"Missing fields in question {qid}: {', '.join(missing_question_fields)}")
        if case_id not in case_set:
            errors.append(f"Unknown case in question {qid}: {case_id}")
        if question.get("featureId") not in feature_set:
            errors.append(f"Unknown feature in question {qid}: {question.get('featureId')}")
        unknown_assertions = sorted(set(question.get("assertionIds", [])) - assertion_ids.get(str(case_id), set()))
        if unknown_assertions:
            errors.append(f"Unknown assertions in question {qid}: {', '.join(unknown_assertions)}")
        assertion_bindings.setdefault(str(case_id), set()).update(question.get("assertionIds", []))
        if question.get("reviewStatus") not in {"draft", "approved", "rejected"}:
            errors.append(f"Invalid reviewStatus in question {qid}")
        if not question.get("evidence"):
            errors.append(f"Question has no answer evidence: {qid}")
    if not suite.get("allowUnquestionedAssertions", False):
        for case_id, ids in assertion_ids.items():
            unbound = sorted(ids - assertion_bindings.get(case_id, set()))
            if unbound:
                errors.append(f"Assertions not bound to reviewed questions in {case_id}: {', '.join(unbound)}")
    if require_approved:
        if suite.get("reviewStatus") != "approved":
            errors.append("Suite is not approved")
        drafts = [str(q.get("questionId")) for q in questions if q.get("reviewStatus") != "approved"]
        if drafts:
            errors.append(f"Questions not approved: {', '.join(drafts)}")
    elif suite.get("reviewStatus") != "approved":
        warnings.append("Suite is draft; approve questions and answers before running")
    policy = quality_policy(suite)
    scoring = policy["scoring"]
    if scoring["aggregation"] != "macro_feature":
        errors.append("qualityPolicy.scoring.aggregation must be macro_feature")
    for field in ("passThreshold", "reviewThreshold"):
        value = scoring.get(field)
        if value is not None and (not isinstance(value, (int, float)) or not 0 <= float(value) <= float(scoring["scale"])):
            errors.append(f"qualityPolicy.scoring.{field} must be within 0..scale")
    if scoring.get("passThreshold") is not None and scoring.get("reviewThreshold") is not None and float(scoring["reviewThreshold"]) > float(scoring["passThreshold"]):
        errors.append("qualityPolicy scoring reviewThreshold cannot exceed passThreshold")
    return {
        "ok": not errors,
        "suiteId": suite_id,
        "profile": suite.get("profile"),
        "evaluator": suite.get("evaluator"),
        "caseCount": len(cases),
        "featureCount": len(features),
        "questionCount": len(questions),
        "coveredFeatureCount": len(covered & feature_set),
        "reviewStatus": suite.get("reviewStatus"),
        "qualityPolicy": policy,
        "errors": errors,
        "warnings": warnings,
    }


def legacy_input_source(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("input") or case.get("path")
    if not value:
        return {"type": "missing", "uri": ""}
    candidate = Path(str(value))
    if candidate.is_absolute():
        return {"type": "local", "uri": str(candidate)}
    corpus = ROOT / "corpus" / "inputs" / candidate
    if corpus.exists():
        return {"type": "local", "uri": str(corpus)}
    return {"type": "local", "uri": str(ROOT / "cases" / "inputs" / candidate)}


def case_source(case: dict[str, Any]) -> dict[str, Any]:
    source = case.get("source")
    if source is None:
        return legacy_input_source(case)
    if isinstance(source, str):
        return {"type": "local", "uri": source}
    if not isinstance(source, dict):
        raise ValueError(f"Invalid source for case {case.get('id')}")
    return source


def source_extension(source: dict[str, Any]) -> str:
    uri = str(source.get("uri", ""))
    return Path(urllib.parse.urlparse(uri).path).suffix


class MaterializedSource:
    def __init__(self, path: Path, provenance: dict[str, Any], cleanup: Any = None):
        self.path = path
        self.provenance = provenance
        self._cleanup = cleanup

    def __enter__(self) -> "MaterializedSource":
        return self

    def __exit__(self, *_: Any) -> None:
        if self._cleanup:
            self._cleanup.cleanup()


def materialize_source(case: dict[str, Any], cache_policy: str = "session") -> MaterializedSource:
    if cache_policy not in {"session", "persistent"}:
        raise ValueError(f"Unsupported source cache policy: {cache_policy}")
    source = case_source(case)
    source_type, uri = source.get("type", "local"), str(source.get("uri", ""))
    expected_sha = source.get("sha256") or case.get("sha256")
    temporary = None
    if source_type == "local":
        parsed = urllib.parse.urlparse(uri)
        value = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else uri
        path = Path(value).expanduser().resolve()
    elif source_type in {"http", "https"}:
        if source_type != urllib.parse.urlparse(uri).scheme:
            raise ValueError(f"Source type and URI scheme disagree: {source_type} {uri}")
        cache_key = str(expected_sha or hashlib.sha256(uri.encode()).hexdigest())
        filename = f"{cache_key}{source_extension(source)}"
        if cache_policy == "persistent":
            CACHE.mkdir(parents=True, exist_ok=True)
            path = CACHE / filename
        else:
            temporary = tempfile.TemporaryDirectory(prefix="deck-benchmark-source-")
            path = Path(temporary.name) / (Path(urllib.parse.urlparse(uri).path).name or filename)
        if not path.exists():
            request = urllib.request.Request(uri, headers={str(k): str(v) for k, v in source.get("headers", {}).items()})
            with urllib.request.urlopen(request, timeout=int(source.get("timeoutSeconds", 300))) as response, path.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
    elif source_type == "command":
        temporary = tempfile.TemporaryDirectory(prefix="deck-benchmark-source-") if cache_policy != "persistent" else None
        base = Path(temporary.name) if temporary else CACHE
        base.mkdir(parents=True, exist_ok=True)
        cache_key = str(expected_sha or hashlib.sha256(uri.encode()).hexdigest())
        path = base / f"{cache_key}{source_extension(source)}"
        if not path.exists():
            command = expand_tokens(source.get("command", []), {"uri": uri, "output": str(path), "repo": str(REPO)})
            proc = run_process(command, REPO, int(source.get("timeoutSeconds", 300)), {str(k): str(v) for k, v in source.get("env", {}).items()})
            if proc.get("exitCode") != 0 or not path.is_file():
                raise OSError(proc.get("stderr") or f"Source command did not create {path}")
    else:
        raise ValueError(f"Unsupported source type: {source_type}")
    if not path.is_file():
        if temporary:
            temporary.cleanup()
        raise FileNotFoundError(f"Source is not a file: {path}")
    actual_sha = sha256(path)
    if expected_sha and actual_sha != expected_sha:
        if temporary:
            temporary.cleanup()
        raise ValueError(f"Source SHA-256 mismatch for {uri}: expected {expected_sha}, got {actual_sha}")
    provenance = {"type": source_type, "uri": uri, "sha256": actual_sha, "bytes": path.stat().st_size, "cachePolicy": cache_policy}
    for key in ("versionId", "etag"):
        if source.get(key) is not None:
            provenance[key] = source[key]
    return MaterializedSource(path, provenance, temporary)


def expand_tokens(tokens: list[str], values: dict[str, str]) -> list[str]:
    expanded = []
    for token in tokens:
        value = str(token)
        for key, replacement in values.items():
            value = value.replace("{" + key + "}", replacement)
        if re.search(r"\{[a-z_]+\}", value):
            raise ValueError(f"Unresolved command placeholder: {value}")
        expanded.append(value)
    return expanded


def parse_payload(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for start in reversed([match.start() for match in re.finditer(r"[\[{]", text)]):
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                continue
    return None


def json_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    if path in {"", "$"}:
        return True, current
    for part in path.removeprefix("$.").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def normalize(proc: dict[str, Any], result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    result_type = result.get("type", "stdout_json")
    if result_type == "stdout_json":
        data = parse_payload(proc["stdout"])
    elif result_type == "output_json":
        path = output_dir / result["path"]
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    elif result_type == "stdout_text":
        data = {"text": proc["stdout"]}
    elif result_type == "output_text":
        path = output_dir / result["path"]
        text = path.read_text(encoding=result.get("encoding", "utf-8")) if path.exists() else ""
        data = {"text": text}
        return {"data": data, "text": text, "artifacts": sorted(str(item.relative_to(output_dir)) for item in output_dir.rglob("*") if item.is_file())}
    elif result_type == "artifacts":
        data = {"artifacts": sorted(str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file())}
    else:
        raise ValueError(f"Unsupported result type: {result_type}")
    return {"data": data, "text": proc["stdout"], "artifacts": sorted(str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file())}


def evaluate_assertion(assertion: dict[str, Any], normalized: dict[str, Any], proc: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    kind = assertion["type"]
    expected = assertion.get("expected")
    required = assertion.get("required", True)
    exists, actual = json_path(normalized.get("data"), assertion.get("path", "$"))
    passed = False
    details: dict[str, Any] = {}
    if kind == "exit_code":
        actual, passed = proc["exitCode"], proc["exitCode"] == expected
    elif kind == "json_path_exists":
        actual, passed = exists, exists is bool(expected if expected is not None else True)
    elif kind == "json_path_equals":
        passed = exists and actual == expected
    elif kind == "json_path_contains":
        passed = exists and ((isinstance(actual, str) and str(expected) in actual) or (isinstance(actual, (list, dict)) and expected in actual))
    elif kind == "json_path_regex":
        passed = exists and re.search(str(expected), str(actual)) is not None
    elif kind == "json_path_count":
        actual = len(actual) if exists and hasattr(actual, "__len__") else None
        passed = actual == expected
    elif kind == "numeric_tolerance":
        if exists and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            absolute = float(assertion.get("absoluteTolerance", 0))
            relative = float(assertion.get("relativeTolerance", 0)) * abs(float(expected))
            passed = abs(float(actual) - float(expected)) <= max(absolute, relative)
    elif kind == "set_equals":
        passed = exists and isinstance(actual, list) and set(map(json.dumps, actual)) == set(map(json.dumps, expected or []))
    elif kind == "text_contains":
        actual, passed = normalized.get("text", ""), str(expected) in normalized.get("text", "")
    elif kind == "text_regex":
        actual = normalized.get("text", "")
        passed = re.search(str(expected), actual) is not None
    elif kind == "artifact_exists":
        actual = str(assertion.get("path", ""))
        passed = (output_dir / actual).is_file()
    elif kind == "artifact_count":
        pattern = str(assertion.get("glob", "*"))
        actual = sum(fnmatch.fnmatch(str(path.relative_to(output_dir)), pattern) for path in output_dir.rglob("*") if path.is_file())
        passed = actual == expected
    elif kind == "ai_review":
        details = {"rubric": assertion.get("rubric"), "evidence": assertion.get("evidence", [])}
        return {"id": assertion["id"], "type": kind, "status": "review", "required": required, "expected": expected, "actual": actual, **details}
    return {"id": assertion["id"], "type": kind, "status": "passed" if passed else "failed", "required": required, "expected": expected, "actual": actual, **details}


def run_process(command: list[str], cwd: Path, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, env={**os.environ, **env, "NO_COLOR": "1"})
        return {"exitCode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "timedOut": False, "durationMs": round((time.monotonic() - started) * 1000)}
    except subprocess.TimeoutExpired as exc:
        return {"exitCode": None, "stdout": str(exc.stdout or ""), "stderr": str(exc.stderr or ""), "timedOut": True, "durationMs": round((time.monotonic() - started) * 1000)}
    except OSError as exc:
        return {"exitCode": None, "stdout": "", "stderr": str(exc), "timedOut": False, "launchError": True, "durationMs": round((time.monotonic() - started) * 1000)}


def grade_case(
    evaluator_folder: Path,
    evaluator: dict[str, Any],
    case: dict[str, Any],
    normalized: dict[str, Any],
    proc: dict[str, Any],
    output_dir: Path,
    source: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    if evaluator.get("type") == "declarative":
        assertions = [evaluate_assertion(item, normalized, proc, output_dir) for item in case.get("assertions", [])]
        return {"assertions": assertions, "metrics": {}, "evidence": [], "summary": None}
    if evaluator.get("type") != "command":
        raise ValueError(f"Unsupported evaluator type: {evaluator.get('type')}")
    context_path = output_dir / "benchmark-evaluator-input.json"
    payload = {
        "contractVersion": "1",
        "runId": run_id,
        "case": case,
        "source": source,
        "targetProcess": proc,
        "normalizedTargetOutput": normalized,
        "outputDir": str(output_dir),
    }
    context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    command = expand_tokens(
        evaluator.get("command", []),
        {"context": str(context_path), "output_dir": str(output_dir), "evaluator_dir": str(evaluator_folder), "repo": str(REPO)},
    )
    grade_proc = run_process(command, evaluator_folder, int(evaluator.get("timeoutSeconds", 300)), {str(k): str(v) for k, v in evaluator.get("env", {}).items()})
    if grade_proc.get("exitCode") != 0:
        raise OSError(grade_proc.get("stderr") or "Evaluator command failed")
    result = parse_payload(grade_proc.get("stdout", ""))
    if not isinstance(result, dict) or not isinstance(result.get("assertions"), list):
        raise ValueError("Evaluator must return a JSON object containing assertions")
    for assertion in result["assertions"]:
        if assertion.get("status") not in {"passed", "failed", "review"}:
            raise ValueError(f"Evaluator returned invalid assertion status: {assertion.get('status')}")
        assertion.setdefault("required", True)
    return {
        "assertions": result["assertions"],
        "metrics": result.get("metrics", {}),
        "evidence": result.get("evidence", []),
        "summary": result.get("summary"),
        "evaluatorProcess": grade_proc,
    }


def summarize_quality(results: list[dict[str, Any]], cases: list[dict[str, Any]], suite: dict[str, Any], evaluator_type: str) -> dict[str, Any]:
    policy = quality_policy(suite)
    result_by_case = {item["caseId"]: item for item in results}
    gate = {"total": 0, "passed": 0, "failed": 0, "review": 0, "blocked": 0}
    observation_total = 0
    scored_total = 0
    scored_evaluated = 0
    feature_buckets: dict[str, dict[str, float]] = {}
    for case in cases:
        result = result_by_case.get(case.get("id"), {})
        actual = {str(item.get("id")): item for item in result.get("assertions", [])}
        definitions = case.get("assertions", []) if evaluator_type == "declarative" else case.get("evaluation", {}).get("checks", [])
        for definition in definitions:
            role = check_role(definition)
            assertion = actual.get(str(definition.get("id")))
            if role == "gate":
                gate["total"] += 1
                if result.get("status") == "blocked":
                    gate["blocked"] += 1
                elif assertion is None:
                    gate["failed"] += 1
                else:
                    gate[str(assertion.get("status", "review"))] += 1
            elif role == "observation":
                observation_total += 1
            else:
                scored_total += 1
                if assertion is None or assertion.get("score") is None:
                    continue
                scored_evaluated += 1
                feature_id = str(assertion.get("featureId") or (case.get("covers") or ["unbound"])[0])
                bucket = feature_buckets.setdefault(feature_id, {"weightedScore": 0.0, "weight": 0.0, "checks": 0.0})
                weight = float(assertion.get("weight", 1))
                bucket["weightedScore"] += float(assertion["score"]) * weight
                bucket["weight"] += weight
                bucket["checks"] += 1
    scale = float(policy["scoring"]["scale"])
    by_feature = {}
    for feature_id, bucket in sorted(feature_buckets.items()):
        value = bucket["weightedScore"] / bucket["weight"] * scale if bucket["weight"] else None
        by_feature[feature_id] = {"score": round(value, 2) if value is not None else None, "evaluatedChecks": int(bucket["checks"]), "weight": bucket["weight"]}
    score = round(sum(item["score"] for item in by_feature.values() if item["score"] is not None) / len(by_feature), 2) if by_feature else None
    completion = round(sum(item.get("status") != "blocked" for item in results) / len(results) * 100, 2) if results else 0.0
    if gate["failed"]:
        decision = "FAIL"
        reason = "gate_failed"
    elif gate["blocked"] or any(item.get("status") == "blocked" for item in results):
        decision = "INCOMPLETE"
        reason = "gate_or_run_blocked"
    elif score is not None and policy["scoring"].get("reviewThreshold") is not None and score < float(policy["scoring"]["reviewThreshold"]):
        decision = "FAIL"
        reason = "quality_below_review_threshold"
    elif score is not None and policy["scoring"].get("passThreshold") is not None and score < float(policy["scoring"]["passThreshold"]):
        decision = "REVIEW"
        reason = "quality_below_pass_threshold"
    elif scored_total and scored_evaluated < scored_total:
        decision = "REVIEW"
        reason = "scored_coverage_incomplete"
    elif any(item.get("role") == "scored" and item.get("status") != "passed" for result in results for item in result.get("assertions", [])):
        decision = "REVIEW"
        reason = "scored_checks_need_review"
    else:
        decision = "PASS"
        reason = "policy_satisfied"
    return {
        "policy": policy,
        "policySha256": policy_hash(policy),
        "releaseDecision": decision,
        "decisionReason": reason,
        "gate": {**gate, "passRate": round(gate["passed"] / gate["total"] * 100, 2) if gate["total"] else None},
        "scored": {"score": score, "scale": scale, "totalChecks": scored_total, "evaluatedChecks": scored_evaluated, "coverage": round(scored_evaluated / scored_total * 100, 2) if scored_total else None, "byFeature": by_feature},
        "observation": {"totalChecks": observation_total},
        "completionRate": completion,
    }


def run_declarative(suite_id: str, target_id: str, run_id: str, selected: set[str] | None) -> Path:
    validation = validate_suite(suite_id, require_approved=True)
    if not validation["ok"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    folder, suite = load_suite(suite_id)
    target = load_target(target_id)
    evaluator_folder, evaluator = load_evaluator(suite["evaluator"])
    evaluator_record = {**evaluator, "codeSha256": directory_sha256(evaluator_folder)}
    if target.get("profile") != suite.get("profile") and target.get("evaluationProfile") != suite.get("profile"):
        raise SystemExit(f"Profile mismatch: suite={suite.get('profile')} target={target.get('profile') or target.get('evaluationProfile')}")
    adapter = target.get("adapter", {})
    if adapter.get("type") != "command":
        raise SystemExit(f"Generic engine requires a command adapter: {target_id}")
    _, cases, questions = suite_files(folder, suite)
    cases = [case for case in cases if not selected or case["id"] in selected]
    if not cases:
        raise SystemExit("No cases selected")
    run_dir = ARTIFACTS / "runs" / suite_id / target_id / run_id
    raw_dir, output_root = run_dir / "raw", run_dir / "outputs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        output_dir = output_root / case["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        command: list[str] = []
        proc = {"exitCode": None, "stdout": "", "stderr": "", "timedOut": False, "launchError": False, "durationMs": 0}
        normalized = {"data": None, "text": "", "artifacts": []}
        source_provenance = {**case_source(case)}
        materialized_ok = False
        target_completed = False
        try:
            with materialize_source(case, suite.get("sourceCache", "session")) as materialized:
                input_path = materialized.path.resolve()
                source_provenance = materialized.provenance
                materialized_ok = True
                values = {"input": str(input_path), "output_dir": str(output_dir), "case_id": case["id"], "run_id": run_id, "repo": str(REPO)}
                command = expand_tokens(adapter["command"], values)
                cwd_value = expand_tokens([adapter.get("cwd", "{repo}")], values)[0]
                proc = run_process(command, Path(cwd_value), int(adapter.get("timeoutSeconds", 300)), {str(k): str(v) for k, v in adapter.get("env", {}).items()})
                normalized = normalize(proc, adapter.get("result", {}), output_dir)
                target_completed = True
                evaluator_source = {**materialized.provenance, "materializedPath": str(input_path)}
                grade = grade_case(evaluator_folder, evaluator, case, normalized, proc, output_dir, evaluator_source, run_id)
                normalization_error = None
                evaluator_error = None
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            grade = {"assertions": [], "metrics": {}, "evidence": [], "summary": None}
            if not materialized_ok:
                source_provenance["materializationError"] = str(exc)
                proc = {**proc, "stderr": str(exc), "launchError": True}
                normalization_error, evaluator_error = None, None
            elif not target_completed:
                normalization_error, evaluator_error = str(exc), None
            else:
                normalization_error, evaluator_error = None, str(exc)
        assertions = enrich_assertions(case, grade["assertions"], str(evaluator.get("type")), questions)
        if proc.get("timedOut") or proc.get("launchError"):
            status = "blocked"
        elif evaluator_error:
            status = "blocked"
        elif normalization_error:
            status = "failed"
        elif any(item["status"] == "failed" and item["role"] == "gate" for item in assertions):
            status = "failed"
        elif any(item["status"] in {"failed", "review"} and item["role"] == "scored" for item in assertions):
            status = "review"
        else:
            status = "passed"
        result = {
            "caseId": case["id"],
            "source": source_provenance,
            "inputSha256": source_provenance.get("sha256"),
            "command": command,
            **proc,
            "normalized": normalized,
            "normalizationError": normalization_error,
            "evaluatorError": evaluator_error,
            "evaluator": {"id": evaluator["id"], "version": str(evaluator["version"]), "codeSha256": evaluator_record["codeSha256"]},
            "assertions": assertions,
            "metrics": grade.get("metrics", {}),
            "evidence": grade.get("evidence", []),
            "evaluationSummary": grade.get("summary"),
            "status": status,
        }
        (raw_dir / f"{case['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
    findings = build_findings(results, suite, target, run_id)
    quality = summarize_quality(results, cases, suite, str(evaluator.get("type")))
    envelope = {"contractVersion": REPORT_CONTRACT_VERSION, "benchmarkCoreVersion": CORE_VERSION, "runId": run_id, "suite": suite, "target": target, "evaluator": evaluator_record, "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(), "results": results, "findings": findings, "qualitySummary": quality, "counts": {status: sum(item["status"] == status for item in results) for status in ("passed", "review", "failed", "blocked")}}
    (run_dir / "run.json").write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    build_reports(envelope, run_dir, questions)
    return run_dir


def build_findings(results: list[dict[str, Any]], suite: dict[str, Any], target: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    findings = []
    for result in results:
        for assertion in result.get("assertions", []):
            if assertion["status"] == "passed" or assertion.get("role") == "observation" or assertion.get("finding") is False:
                continue
            findings.append({
                "findingId": f"FINDING-{len(findings) + 1:03d}",
                "fingerprint": f"{suite['profile']}.{assertion['type']}.{assertion['id']}",
                "category": assertion["type"],
                "severity": assertion.get("severity", "major" if assertion.get("role") == "gate" else "minor"),
                "status": assertion["status"],
                "role": assertion.get("role", "gate" if assertion.get("required", True) else "observation"),
                "assertionId": assertion.get("id"),
                "questionId": assertion.get("questionId"),
                "featureId": assertion.get("featureId"),
                "score": assertion.get("score"),
                "suiteId": suite["id"],
                "targetId": target["id"],
                "runId": run_id,
                "caseId": result["caseId"],
                "expected": assertion.get("expected"),
                "actual": assertion.get("actual"),
                "evidence": assertion.get("evidence", []),
                "details": assertion.get("details"),
                "command": result["command"],
            })
        if result.get("status") == "blocked":
            evaluator_error = result.get("evaluatorError")
            findings.append({
                "findingId": f"FINDING-{len(findings) + 1:03d}",
                "fingerprint": f"environment.{target['id']}.{'evaluator' if evaluator_error else 'execution'}",
                "category": "environment_evaluator" if evaluator_error else "environment_execution",
                "severity": "major",
                "status": "blocked",
                "role": "gate",
                "suiteId": suite["id"],
                "targetId": target["id"],
                "runId": run_id,
                "caseId": result["caseId"],
                "expected": "evaluator available and returns its contract" if evaluator_error else "source and target executable available and complete within timeout",
                "actual": evaluator_error or result.get("stderr") or "timeout",
                "command": result["command"],
            })
    return findings


def compare_runs(suite_id: str, target_id: str, baseline_id: str, candidate_id: str) -> dict[str, Any]:
    base_path = ARTIFACTS / "runs" / suite_id / target_id / baseline_id / "run.json"
    candidate_path = ARTIFACTS / "runs" / suite_id / target_id / candidate_id / "run.json"
    if not base_path.exists() or not candidate_path.exists():
        raise SystemExit(f"Missing run envelope: {base_path if not base_path.exists() else candidate_path}")
    baseline, candidate = read_json(base_path), read_json(candidate_path)
    base_evaluator = baseline.get("evaluator", {})
    candidate_evaluator = candidate.get("evaluator", {})
    evaluator_compatible = (
        base_evaluator.get("id"), str(base_evaluator.get("version")), base_evaluator.get("codeSha256")
    ) == (
        candidate_evaluator.get("id"), str(candidate_evaluator.get("version")), candidate_evaluator.get("codeSha256")
    )
    baseline_policy = baseline.get("qualitySummary", {}).get("policySha256")
    candidate_policy = candidate.get("qualitySummary", {}).get("policySha256")
    policy_compatible = bool(baseline_policy and baseline_policy == candidate_policy)
    baseline_cohort = sorted((item["caseId"], item.get("inputSha256")) for item in baseline.get("results", []))
    candidate_cohort = sorted((item["caseId"], item.get("inputSha256")) for item in candidate.get("results", []))
    cohort_compatible = baseline_cohort == candidate_cohort
    old = {item["caseId"]: item for item in baseline["results"]}
    new = {item["caseId"]: item for item in candidate["results"]}
    rank = {"passed": 0, "review": 1, "failed": 2, "blocked": 3}
    case_changes = []
    for case_id in sorted(set(old) | set(new)):
        before, after = old.get(case_id), new.get(case_id)
        if before is None:
            kind = "added"
        elif after is None:
            kind = "removed"
        elif before["status"] == "blocked" and after["status"] != "blocked":
            kind = "newly_evaluated"
        elif before["status"] != "blocked" and after["status"] == "blocked":
            kind = "newly_blocked"
        elif rank.get(after["status"], 9) > rank.get(before["status"], 9):
            kind = "regression"
        elif rank.get(after["status"], 9) < rank.get(before["status"], 9):
            kind = "improvement"
        else:
            kind = "unchanged"
        case_changes.append({"caseId": case_id, "kind": kind, "baselineStatus": before.get("status") if before else None, "candidateStatus": after.get("status") if after else None})
    assertion_changes = []
    for case_id in sorted(set(old) & set(new)):
        before_items = {str(item.get("id")): item for item in old[case_id].get("assertions", [])}
        after_items = {str(item.get("id")): item for item in new[case_id].get("assertions", [])}
        for assertion_id in sorted(set(before_items) | set(after_items)):
            before, after = before_items.get(assertion_id), after_items.get(assertion_id)
            if before is None:
                kind = "added"
            elif after is None:
                kind = "removed"
            elif before.get("score") is not None and after.get("score") is not None and float(after["score"]) != float(before["score"]):
                kind = "improvement" if float(after["score"]) > float(before["score"]) else "regression"
            elif rank.get(str(after.get("status")), 9) > rank.get(str(before.get("status")), 9):
                kind = "regression"
            elif rank.get(str(after.get("status")), 9) < rank.get(str(before.get("status")), 9):
                kind = "improvement"
            else:
                kind = "unchanged"
            assertion_changes.append({
                "caseId": case_id, "assertionId": assertion_id, "role": (after or before).get("role"), "featureId": (after or before).get("featureId"), "kind": kind,
                "baselineStatus": before.get("status") if before else None, "candidateStatus": after.get("status") if after else None,
                "baselineScore": before.get("score") if before else None, "candidateScore": after.get("score") if after else None,
            })
    kinds = ("regression", "improvement", "newly_evaluated", "newly_blocked", "added", "removed", "unchanged")
    warnings = []
    if not evaluator_compatible:
        warnings.append("Evaluator id/version/code changed; deltas are not attributable to the target alone")
    if not policy_compatible:
        warnings.append("Quality policy changed or is missing; score deltas are not directly comparable")
    if not cohort_compatible:
        warnings.append("Case ids or source hashes changed; cohort deltas are not directly comparable")
    baseline_score = baseline.get("qualitySummary", {}).get("scored", {}).get("score")
    candidate_score = candidate.get("qualitySummary", {}).get("scored", {}).get("score")
    score_delta = round(float(candidate_score) - float(baseline_score), 2) if baseline_score is not None and candidate_score is not None else None
    result = {
        "contractVersion": REPORT_CONTRACT_VERSION, "suiteId": suite_id, "targetId": target_id, "baseline": baseline_id, "candidate": candidate_id,
        "comparable": evaluator_compatible and policy_compatible and cohort_compatible,
        "evaluatorCompatible": evaluator_compatible,
        "compatibility": {"evaluator": evaluator_compatible, "qualityPolicy": policy_compatible, "sourceCohort": cohort_compatible},
        "baselineEvaluator": base_evaluator, "candidateEvaluator": candidate_evaluator,
        "releaseDecision": {"baseline": baseline.get("qualitySummary", {}).get("releaseDecision"), "candidate": candidate.get("qualitySummary", {}).get("releaseDecision")},
        "qualityScore": {"baseline": baseline_score, "candidate": candidate_score, "delta": score_delta},
        "caseCounts": {kind: sum(item["kind"] == kind for item in case_changes) for kind in kinds},
        "assertionCounts": {kind: sum(item["kind"] == kind for item in assertion_changes) for kind in ("regression", "improvement", "added", "removed", "unchanged")},
        "newGateRegressions": [item for item in assertion_changes if item["role"] == "gate" and item["kind"] == "regression"],
        "resolvedGateFailures": [item for item in assertion_changes if item["role"] == "gate" and item["kind"] == "improvement"],
        "caseChanges": case_changes, "assertionChanges": assertion_changes, "warnings": warnings,
    }
    candidate_dir = candidate_path.parent
    (candidate_dir / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(f"<tr><td>{html.escape(item['kind'])}</td><td>{html.escape(item['caseId'])}</td><td>{html.escape(item['assertionId'])}</td><td>{html.escape(str(item.get('role') or '—'))}</td><td>{html.escape(str(item.get('baselineStatus')))} → {html.escape(str(item.get('candidateStatus')))}</td><td>{html.escape(str(item.get('baselineScore')))} → {html.escape(str(item.get('candidateScore')))}</td></tr>" for item in assertion_changes if item["kind"] != "unchanged") or '<tr><td colspan="6">没有断言级变化</td></tr>'
    comparison_page = f'''<!doctype html><meta charset="utf-8"><title>Benchmark comparison</title><style>body{{font:14px system-ui;max-width:1200px;margin:36px auto;padding:0 18px}}.cards{{display:flex;gap:12px}}.card{{border:1px solid #ddd;border-radius:9px;padding:14px;min-width:180px}}strong{{font-size:23px;display:block}}table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{border:1px solid #ddd;padding:9px;text-align:left}}.warn{{background:#fff4e5;padding:10px}}</style><h1>{html.escape(baseline_id)} → {html.escape(candidate_id)}</h1>{''.join(f'<p class="warn">{html.escape(w)}</p>' for w in warnings)}<div class="cards"><div class="card"><strong>{html.escape(str(result['releaseDecision']['candidate']))}</strong>候选发布结论</div><div class="card"><strong>{html.escape(str(score_delta if score_delta is not None else '—'))}</strong>质量分变化</div><div class="card"><strong>{len(result['newGateRegressions'])}</strong>新增门禁回归</div><div class="card"><strong>{len(result['resolvedGateFailures'])}</strong>已修复门禁</div></div><table><thead><tr><th>变化</th><th>Case</th><th>检查点</th><th>角色</th><th>状态</th><th>分数</th></tr></thead><tbody>{rows}</tbody></table>'''
    (candidate_dir / "comparison.html").write_text(comparison_page, encoding="utf-8")
    agent_path = candidate_dir / "agent-report.json"
    if agent_path.exists():
        agent = read_json(agent_path)
        change_by_assertion = {(item["caseId"], item["assertionId"]): item["kind"] for item in assertion_changes}
        for finding in agent.get("actionableFindings", []):
            change = change_by_assertion.get((finding.get("caseId"), str(finding.get("assertionId"))))
            finding["regressionState"] = {"regression": "new_regression", "unchanged": "persistent", "added": "new_check"}.get(change, "unknown")
        agent["comparison"] = {"baseline": baseline_id, "candidate": candidate_id, "comparable": result["comparable"], "artifact": "comparison.json"}
        agent_path.write_text(json.dumps(agent, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def suspected_component(assertion: dict[str, Any], finding: dict[str, Any]) -> str:
    if assertion.get("component"):
        return str(assertion["component"])
    kind = str(assertion.get("type") or finding.get("category") or "unknown")
    return {
        "exit_code": "target execution contract",
        "artifact_exists": "artifact writer",
        "artifact_count": "artifact writer",
    }.get(kind, f"{kind} evaluator or target implementation")


def html_value(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_agent_report(envelope: dict[str, Any], run_dir: Path, questions: list[dict[str, Any]]) -> dict[str, Any]:
    bindings = {(item["caseId"], str(assertion_id)): item for item in questions for assertion_id in item.get("assertionIds", [])}
    results = {item["caseId"]: item for item in envelope["results"]}
    actionable = []
    for finding in envelope["findings"]:
        result = results.get(finding["caseId"], {})
        assertion = next((item for item in result.get("assertions", []) if item.get("id") == finding.get("assertionId")), {})
        question = bindings.get((finding["caseId"], str(finding.get("assertionId"))), {})
        actionable.append({
            **finding,
            "question": question.get("question"),
            "approvedAnswer": question.get("answer"),
            "answerEvidence": question.get("evidence"),
            "suspectedComponent": suspected_component(assertion, finding),
            "confidence": "high" if finding.get("status") in {"failed", "blocked"} else "medium",
            "regressionState": "unknown",
            "rawEvidence": f"raw/{finding['caseId']}.json",
            "reproduction": {"cwd": str(REPO), "command": finding.get("command", [])},
            "recommendedAction": "Reproduce from raw evidence, fix the target or evaluator implementation, and keep the approved oracle unchanged.",
        })
    observations = []
    for result in envelope["results"]:
        for assertion in result.get("assertions", []):
            if assertion.get("role") != "observation":
                continue
            question = bindings.get((result["caseId"], str(assertion.get("id"))), {})
            observations.append({
                "caseId": result["caseId"], "assertionId": assertion.get("id"), "featureId": assertion.get("featureId"),
                "question": question.get("question"), "approvedAnswer": question.get("answer"),
                "status": assertion.get("status"), "expected": assertion.get("expected"), "actual": assertion.get("actual"),
                "details": assertion.get("details"), "rawEvidence": f"raw/{result['caseId']}.json",
            })
    clusters = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in actionable:
        grouped.setdefault(str(finding["suspectedComponent"]), []).append(finding)
    for component, findings in sorted(grouped.items()):
        clusters.append({
            "clusterId": f"CLUSTER-{len(clusters) + 1:03d}", "suspectedComponent": component,
            "findingIds": [item["findingId"] for item in findings], "caseIds": sorted({item["caseId"] for item in findings}),
            "rootSignal": f"{len(findings)} non-pass checks share the same suspected component",
        })
    payload = {
        "schemaVersion": REPORT_CONTRACT_VERSION, "benchmarkCoreVersion": CORE_VERSION,
        "audience": "developer-agent", "purpose": "Repair-oriented benchmark evidence; approved answers are immutable oracles.",
        "run": {key: envelope[key] for key in ("runId", "createdAt", "suite", "target", "evaluator")},
        "qualitySummary": envelope["qualitySummary"], "counts": envelope["counts"],
        "failureClusters": clusters, "actionableFindings": actionable, "reviewObservations": observations,
        "cases": [{
            "caseId": result["caseId"], "status": result["status"], "source": result.get("source"), "rawEvidence": f"raw/{result['caseId']}.json",
            "assertions": [{key: assertion.get(key) for key in ("id", "type", "role", "severity", "status", "featureId", "score", "expected", "actual")} for assertion in result.get("assertions", [])],
        } for result in envelope["results"]],
        "artifacts": {"humanReport": "report.html", "runEnvelope": "run.json", "rawCaseDirectory": "raw/"},
    }
    (run_dir / "agent-report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_reports(envelope: dict[str, Any], run_dir: Path, questions: list[dict[str, Any]]) -> None:
    agent = build_agent_report(envelope, run_dir, questions)
    bindings = {(item["caseId"], str(assertion_id)): item for item in questions for assertion_id in item.get("assertionIds", [])}
    quality = envelope["qualitySummary"]
    gate, scored = quality["gate"], quality["scored"]
    score_text = "—" if scored["score"] is None else f"{scored['score']:.2f} / {scored['scale']:.0f}"
    cards = [
        (quality["releaseDecision"], "发布结论", quality["decisionReason"]),
        (f"{gate['passed']} / {gate['total']}", "门禁通过", f"失败 {gate['failed']} · 阻塞 {gate['blocked']}"),
        (score_text, "质量分", f"评分覆盖 {scored['coverage'] if scored['coverage'] is not None else '—'}%"),
        (f"{quality['completionRate']:.2f}%", "完成率", f"观察项 {quality['observation']['totalChecks']}"),
    ]
    cards_html = "".join(f'<div class="card"><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span><small>{html.escape(str(note))}</small></div>' for value, label, note in cards)
    feature_rows = "".join(f"<tr><td>{html.escape(feature)}</td><td>{value['score'] if value['score'] is not None else '—'}</td><td>{value['evaluatedChecks']}</td><td>{value['weight']}</td></tr>" for feature, value in scored["byFeature"].items()) or '<tr><td colspan="4">本套件没有 scored 检查点</td></tr>'
    findings = []
    for finding in agent["actionableFindings"]:
        findings.append(f'''<article class="finding {html.escape(str(finding["status"]))}"><header><b>{html.escape(finding["findingId"])} · {html.escape(finding["caseId"])} / {html.escape(str(finding.get("assertionId") or "运行环境"))}</b><span>{html.escape(str(finding["role"]).upper())} · {html.escape(str(finding["severity"]))}</span></header><p class="question">{html.escape(str(finding.get("question") or "未绑定审批问题"))}</p><p><b>标准答案：</b>{html.escape(str(finding.get("approvedAnswer") or "—"))}</p><div class="diff"><section><h4>预期</h4><pre>{html_value(finding.get("expected"))}</pre></section><section><h4>实际</h4><pre>{html_value(finding.get("actual"))}</pre></section></div><p><b>疑似归属：</b>{html.escape(str(finding["suspectedComponent"]))} · <a href="{html.escape(finding["rawEvidence"])}">原始证据</a></p></article>''')
    case_blocks = []
    for result in envelope["results"]:
        assertions = []
        for assertion in result.get("assertions", []):
            question = bindings.get((result["caseId"], str(assertion.get("id"))), {})
            assertions.append(f'''<article class="assertion {html.escape(str(assertion["status"]))}"><header><code>{html.escape(str(assertion["id"]))}</code><span>{html.escape(str(assertion["role"]))} · {html.escape(str(assertion["status"]))}</span></header><p class="question">{html.escape(str(question.get("question") or "未绑定审批问题"))}</p><p><b>标准答案：</b>{html.escape(str(question.get("answer") or "—"))}</p><div class="diff"><section><h4>预期</h4><pre>{html_value(assertion.get("expected"))}</pre></section><section><h4>实际</h4><pre>{html_value(assertion.get("actual"))}</pre></section></div></article>''')
        opened = " open" if result["status"] != "passed" else ""
        assertion_content = "".join(assertions) or "<p>没有可用断言（通常表示执行被阻塞）。</p>"
        case_blocks.append(f'''<details class="case"{opened}><summary><b>{html.escape(result["caseId"])}</b><span>{html.escape(result["status"].upper())} · {result.get("durationMs", 0)} ms</span></summary><p><a href="raw/{html.escape(result["caseId"])}.json">查看原始运行证据</a></p>{assertion_content}</details>''')
    findings_content = "".join(findings) or '<div class="card">没有可执行的产品缺陷。</div>'
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(envelope["suite"]["displayName"])} · {html.escape(envelope["runId"])}</title><style>
    :root{{--ink:#17202a;--muted:#667085;--line:#dfe3e8;--bg:#f6f7f9;--panel:#fff;--pass:#137a4b;--review:#9a6700;--fail:#b42318}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:34px 22px 70px}}h1{{margin:0}}h2{{margin-top:36px}}a{{color:#175cd3}}.sub,.hint{{color:var(--muted)}}.toolbar{{display:flex;gap:16px;margin:16px 0}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card,.finding,.assertion,.case{{background:var(--panel);border:1px solid var(--line);border-radius:10px}}.card{{padding:16px;border-top:4px solid #175cd3}}.card strong,.card span,.card small{{display:block}}.card strong{{font-size:25px}}.card span{{font-weight:650}}.card small{{color:var(--muted)}}table{{width:100%;border-collapse:collapse;background:var(--panel)}}th,td{{padding:10px;border:1px solid var(--line);text-align:left}}.finding,.assertion{{padding:16px;margin:12px 0}}.finding.failed,.assertion.failed{{border-left:5px solid var(--fail)}}.finding.review,.assertion.review{{border-left:5px solid var(--review)}}.assertion.passed{{border-left:5px solid var(--pass)}}header,.case summary{{display:flex;justify-content:space-between;gap:12px}}.question{{font-size:16px;font-weight:650}}.diff{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}pre{{white-space:pre-wrap;overflow:auto;max-height:320px;background:#f8fafc;border:1px solid var(--line);padding:10px;border-radius:7px}}.case{{margin:12px 0;padding:0 16px 16px}}.case summary{{cursor:pointer;padding:16px 0}}@media(max-width:760px){{.cards,.diff{{grid-template-columns:1fr}}}}</style></head><body><main><h1>{html.escape(envelope["suite"]["displayName"])}</h1><div class="sub">目标：{html.escape(envelope["target"]["displayName"])} · 运行：{html.escape(envelope["runId"])} · Core {CORE_VERSION}</div><div class="toolbar"><a href="agent-report.json">Agent 修复报告</a><a href="run.json">完整运行数据</a></div><div class="cards">{cards_html}</div><h2>质量分解</h2><p class="hint">质量分按特性宏平均；门禁、评分和观察项分别统计，不用简单 case 通过率代替质量。</p><table><thead><tr><th>特性</th><th>得分</th><th>已评分检查</th><th>权重</th></tr></thead><tbody>{feature_rows}</tbody></table><h2>需要修复的差异</h2>{"".join(findings) or '<div class="card">没有可执行的产品缺陷。</div>'}<h2>逐案例：标准答案与实际结果</h2><p class="hint">所有检查点均保留，失败案例默认展开；观察项不触发产品失败。</p>{"".join(case_blocks)}</main></body></html>'''
    (run_dir / "report.html").write_text(page, encoding="utf-8")


def core_conformance() -> dict[str, Any]:
    """Exercise semantic Core behavior so a version string cannot impersonate compatibility."""
    probes: dict[str, dict[str, Any]] = {}
    try:
        suite = {
            "id": "core-conformance", "displayName": "Core conformance", "profile": "probe",
            "qualityPolicy": {"version": "1", "scoring": {"aggregation": "macro_feature", "scale": 100, "passThreshold": 80, "reviewThreshold": 60}},
        }
        cases = [
            {"id": "case-a", "covers": ["feature-a"], "assertions": [
                {"id": "gate", "type": "json_path_equals", "role": "gate", "severity": "critical", "expected": True},
                {"id": "score-a1", "type": "json_path_equals", "role": "scored", "scoreMode": "binary", "weight": 1, "expected": True},
                {"id": "score-a2", "type": "json_path_equals", "role": "scored", "scoreMode": "binary", "weight": 1, "expected": True},
                {"id": "note", "type": "ai_review", "role": "observation", "finding": False},
            ]},
            {"id": "case-b", "covers": ["feature-b"], "assertions": [
                {"id": "score-b", "type": "json_path_equals", "role": "scored", "scoreMode": "binary", "weight": 1, "expected": True},
            ]},
        ]
        questions = [
            {"questionId": f"q-{assertion['id']}", "caseId": case["id"], "featureId": case["covers"][0], "question": f"Check {assertion['id']}", "answer": assertion.get("expected", "observe"), "assertionIds": [assertion["id"]], "evidence": {"type": "conformance"}, "reviewStatus": "approved"}
            for case in cases for assertion in case["assertions"]
        ]
        raw_a = [
            {"id": "gate", "type": "json_path_equals", "status": "passed", "expected": True, "actual": True},
            {"id": "score-a1", "type": "json_path_equals", "status": "passed", "expected": True, "actual": True},
            {"id": "score-a2", "type": "json_path_equals", "status": "passed", "expected": True, "actual": True},
            {"id": "note", "type": "ai_review", "status": "review", "actual": "diagnostic"},
        ]
        raw_b = [{"id": "score-b", "type": "json_path_equals", "status": "failed", "expected": True, "actual": False}]
        enriched_a = enrich_assertions(cases[0], raw_a, "declarative", questions)
        enriched_b = enrich_assertions(cases[1], raw_b, "declarative", questions)
        results = [
            {"caseId": "case-a", "status": "passed", "durationMs": 1, "command": ["core-check"], "source": {"uri": "synthetic://case-a"}, "inputSha256": "a", "assertions": enriched_a},
            {"caseId": "case-b", "status": "review", "durationMs": 1, "command": ["core-check"], "source": {"uri": "synthetic://case-b"}, "inputSha256": "b", "assertions": enriched_b},
        ]
        quality = summarize_quality(results, cases, suite, "declarative")
        probes["checkDefinitionEnrichment"] = {"ok": enriched_a[1].get("role") == "scored" and enriched_a[1].get("featureId") == "feature-a", "actual": {"role": enriched_a[1].get("role"), "featureId": enriched_a[1].get("featureId")}}
        probes["binaryScoring"] = {"ok": enriched_a[1].get("score") == 1.0 and enriched_b[0].get("score") == 0.0, "actual": [enriched_a[1].get("score"), enriched_b[0].get("score")]}
        probes["macroFeatureScoring"] = {"ok": quality["scored"]["score"] == 50.0 and set(quality["scored"]["byFeature"]) == {"feature-a", "feature-b"}, "actual": quality["scored"]}
        probes["roleIsolation"] = {"ok": quality["gate"]["failed"] == 0 and quality["observation"]["totalChecks"] == 1, "actual": {"gate": quality["gate"], "observation": quality["observation"]}}
        probes["qualityThresholds"] = {"ok": quality["releaseDecision"] == "FAIL" and quality["decisionReason"] == "quality_below_review_threshold", "actual": {"decision": quality["releaseDecision"], "reason": quality["decisionReason"]}}
        target = {"id": "core", "displayName": "Core"}
        findings = build_findings(results, suite, target, "core-check")
        envelope = {
            "contractVersion": REPORT_CONTRACT_VERSION, "benchmarkCoreVersion": CORE_VERSION, "runId": "core-check", "suite": suite,
            "target": target, "evaluator": {"id": "core-conformance", "version": "1", "codeSha256": core_contract_sha256()},
            "createdAt": "1970-01-01T00:00:00+00:00", "results": results, "findings": findings, "qualitySummary": quality,
            "counts": {status: sum(item["status"] == status for item in results) for status in ("passed", "review", "failed", "blocked")},
        }
        with tempfile.TemporaryDirectory(prefix="deck-benchmark-core-check-") as tmp:
            run_dir = Path(tmp)
            build_reports(envelope, run_dir, questions)
            human = (run_dir / "report.html").read_text(encoding="utf-8")
            agent = read_json(run_dir / "agent-report.json")
            probes["canonicalDualReports"] = {"ok": (run_dir / "report.html").is_file() and (run_dir / "agent-report.json").is_file(), "actual": sorted(item.name for item in run_dir.iterdir())}
            probes["humanReportPresentation"] = {"ok": all(label in human for label in ("门禁通过", "质量分", "标准答案")) and "Gate {" not in human, "actual": {"hasGateCard": "门禁通过" in human, "hasQualityCard": "质量分" in human, "hasApprovedAnswer": "标准答案" in human, "rawGateJson": "Gate {" in human}}
            probes["agentRepairContract"] = {"ok": str(agent.get("schemaVersion")) == REPORT_CONTRACT_VERSION and isinstance(agent.get("actionableFindings"), list) and agent.get("qualitySummary", {}).get("scored", {}).get("score") == 50.0, "actual": {"schemaVersion": agent.get("schemaVersion"), "findingCount": len(agent.get("actionableFindings", []))}}
    except Exception as exc:  # self-check must report failures as data
        probes["internalError"] = {"ok": False, "actual": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": bool(probes) and all(item.get("ok") is True for item in probes.values()),
        "benchmarkCoreVersion": CORE_VERSION,
        "reportContractVersion": REPORT_CONTRACT_VERSION,
        "contractId": CORE_CONTRACT_ID,
        "contractSha256": core_contract_sha256(),
        "capabilities": {name: True for name in CORE_CAPABILITIES},
        "probes": probes,
    }


def run_suite(suite_id: str, target_id: str, run_id: str, selected: set[str] | None) -> Path:
    folder, suite = load_suite(suite_id)
    if suite.get("compatibility", {}).get("engine") == "legacy-render":
        manifest = (folder / suite["compatibility"].get("manifest", "../../cases/manifest.jsonl")).resolve()
        cases = read_jsonl(manifest)
        cases = [case for case in cases if not selected or case["id"] in selected]
        if not cases:
            raise SystemExit("No cases selected")
        with tempfile.TemporaryDirectory(prefix="deck-benchmark-legacy-cases-") as tmp:
            staged = Path(tmp)
            rewritten = []
            for case in cases:
                with materialize_source(case, suite.get("sourceCache", "session")) as materialized:
                    original = Path(str(case.get("input", "")))
                    if case.get("input") and not original.is_absolute() and ".." not in original.parts:
                        staged_name = original
                    else:
                        uri_name = Path(urllib.parse.urlparse(str(case_source(case).get("uri", ""))).path).name
                        staged_name = Path(uri_name or f"{case['id']}{materialized.path.suffix}")
                    destination = staged / staged_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(materialized.path, destination)
                    rewritten.append({**case, "input": str(staged_name), "sha256": materialized.provenance["sha256"], "bytes": materialized.provenance["bytes"]})
            staged_manifest = staged / "manifest.jsonl"
            staged_manifest.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in rewritten), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "benchmark.py"), "all", "--run-id", run_id, "--inputs", str(staged), "--manifest", str(staged_manifest)]
            proc = subprocess.run(command, cwd=REPO)
            if proc.returncode:
                raise SystemExit(proc.returncode)
        return ROOT / "reports" / run_id
    return run_declarative(suite_id, target_id, run_id, selected)


def doctor(target_id: str) -> dict[str, Any]:
    target = load_target(target_id)
    adapter = target.get("adapter")
    if not adapter:
        return {"ok": True, "targetId": target_id, "compatibility": True, "message": "Target uses its profile compatibility engine"}
    command = adapter.get("command", [])
    executable = command[0] if command else None
    if executable and not os.path.isabs(executable):
        import shutil
        resolved = shutil.which(executable)
    else:
        resolved = executable if executable and Path(executable).exists() else None
    return {"ok": bool(resolved), "targetId": target_id, "adapterType": adapter.get("type"), "executable": executable, "resolvedExecutable": resolved}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    sub.add_parser("core-check")
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--suite", required=True)
    validate_parser.add_argument("--approved", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--suite", required=True)
    run_parser.add_argument("--target", required=True)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--case", action="append")
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--target", required=True)
    corpus_parser = sub.add_parser("corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_command", required=True)
    corpus_scan_parser = corpus_sub.add_parser("scan")
    corpus_scan_parser.add_argument("--json", action="store_true")
    corpus_scan_parser.add_argument("--source", help="Local file or directory to scan; defaults to the compatibility corpus")
    corpus_scan_parser.add_argument("--source-spec", help="JSON command-catalog descriptor for a remote collection")
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--suite", required=True)
    compare_parser.add_argument("--target", required=True)
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    if args.command == "version":
        print(json.dumps({
            "benchmarkCoreVersion": CORE_VERSION,
            "reportContractVersion": REPORT_CONTRACT_VERSION,
            "contractId": CORE_CONTRACT_ID,
            "contractSha256": core_contract_sha256(),
            "capabilities": {name: True for name in CORE_CAPABILITIES},
        }, indent=2))
        return
    if args.command == "core-check":
        result = core_conformance()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    if args.command == "validate":
        result = validate_suite(args.suite, args.approved)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    if args.command == "doctor":
        result = doctor(args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    if args.command == "corpus":
        if args.source and args.source_spec:
            raise SystemExit("Use either --source or --source-spec, not both")
        print(json.dumps(corpus_scan(args.source, args.source_spec), ensure_ascii=False, indent=2))
        return
    if args.command == "compare":
        print(json.dumps(compare_runs(args.suite, args.target, args.baseline, args.candidate), ensure_ascii=False, indent=2))
        return
    output = run_suite(args.suite, args.target, args.run_id, set(args.case or []))
    print(f"Report: {output / 'report.html'}")


if __name__ == "__main__":
    main()
