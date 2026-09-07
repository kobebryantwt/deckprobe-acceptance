"""Acquire published artifacts only. Network access is confined to check/prepare."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .common import CODE, atomic, digest, immutable, now, process, read, sha

HEADERS = {"User-Agent": "deckprobe-release-acceptance/1", "Accept": "application/vnd.github+json"}


def fetch(url, limit=268435456):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("Acquisition requires HTTPS")
    headers = dict(HEADERS)
    if urllib.parse.urlparse(url).hostname != "api.github.com":
        headers["Accept"] = "*/*"
    if urllib.parse.urlparse(url).hostname == "api.github.com" and os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as f:
        if urllib.parse.urlparse(f.url).scheme != "https":
            raise ValueError("Insecure redirect")
        data = f.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Download exceeds configured limit")
        return data


def api(url):
    return json.loads(fetch(url))


def tag_commit(repo, tag):
    obj = api(f"https://api.github.com/repos/{repo}/git/ref/tags/{urllib.parse.quote(tag, safe='')}")["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = api(f"https://api.github.com/repos/{repo}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Tag does not resolve to a commit")


def release_record(repo, value):
    return {"repository": repo, "tag": value["tag_name"], "releaseId": value["id"],
            "commit": tag_commit(repo, value["tag_name"]), "publishedAt": value["published_at"],
            "url": value["html_url"], "notes": value.get("body", ""),
            "assets": [{k: a.get(k) for k in ("id", "name", "size", "updated_at", "digest", "browser_download_url")}
                       for a in sorted(value["assets"], key=lambda a: a["name"])]}


def npm_record(name, version="latest"):
    value = api("https://registry.npmjs.org/" + name + "/" + version)
    if "-" in value["version"]:
        raise ValueError("Prerelease npm package is not a stable acceptance target")
    return {"name": name, "version": value["version"], "license": value.get("license"),
            "dependencies": value.get("dependencies", {}), "dist": value["dist"]}


def discover(home):
    repo = read(CODE / "config/policy.json")["repository"]
    values = api(f"https://api.github.com/repos/{repo}/releases?per_page=100")
    stable = sorted((r for r in values if not r["draft"] and not r["prerelease"]),
                    key=lambda r: r["published_at"], reverse=True)
    if not stable:
        raise ValueError("No stable release available")
    # GitHub's explicit latest release wins; the comparison release is older by publication time.
    latest = api(f"https://api.github.com/repos/{repo}/releases/latest")
    if latest["draft"] or latest["prerelease"]:
        raise ValueError("GitHub latest is not stable")
    older = next((r for r in stable if r["published_at"] < latest["published_at"]), None)
    candidate = release_record(repo, latest)
    mcp = npm_record("@deckflow/deckprobe-mcp")
    value = {"candidate": candidate, "previous": release_record(repo, older) if older else None,
             "js": npm_record("@deckflow/deckprobe", candidate["tag"].lstrip("v")),
             "latestJs": npm_record("@deckflow/deckprobe"), "mcp": mcp}
    identity = digest(value)
    immutable(Path(home) / "discoveries" / (identity + ".json"), value)
    atomic(Path(home) / "discovery.json", {"id": identity, "checkedAt": now(), "data": value})
    return identity, value


def safe_extract(data, target, max_bytes=1073741824):
    """Reject traversal, symlinks, devices, duplicates and decompression bombs."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    seen, total = set(), 0

    def output(name, size):
        nonlocal total
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name or not p.parts:
            raise ValueError("Unsafe archive member: " + name)
        relative = str(p)
        if relative in seen:
            raise ValueError("Duplicate archive member: " + name)
        seen.add(relative)
        total += size
        if total > max_bytes:
            raise ValueError("Archive exceeds expansion limit")
        dest = target.joinpath(*p.parts)
        if target.resolve() not in dest.resolve().parents:
            raise ValueError("Archive member escapes destination")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive symlink")
                dest = output(item.filename, item.file_size)
                with z.open(item) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            for item in t:
                if item.isdir():
                    continue
                if not item.isfile():
                    raise ValueError("Archive contains non-regular member")
                dest = output(item.name, item.size)
                with t.extractfile(item) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                dest.chmod(0o755 if item.mode & 0o111 else 0o644)


def verify_sri(data, integrity):
    for token in integrity.split():
        alg, _, expected = token.partition("-")
        if alg in {"sha256", "sha384", "sha512"}:
            if base64.b64encode(hashlib.new(alg, data).digest()).decode() == expected:
                return True
    return False


def download_release(home, release, native_platform=None):
    policy = read(CODE / "config/policy.json")
    native_platform = native_platform or policy["nativePlatform"]
    folder = Path(home) / "releases" / digest({"release": release, "nativePlatform": native_platform})
    existing = read(folder / "prepared.json")
    if existing:
        for asset in existing["assets"]:
            if sha(folder / asset["name"]) != asset["sha256"]:
                raise ValueError("Cached release artifact was modified")
        return existing
    folder.mkdir(parents=True, exist_ok=True)
    assets = []
    for asset in release["assets"]:
        name = asset["name"]
        if Path(name).name != name:
            raise ValueError("Unsafe release asset name")
        p = folder / name
        data = fetch(asset["browser_download_url"], policy["maxDownloadBytes"])
        if len(data) != asset["size"]:
            raise ValueError("Release asset size changed during acquisition: " + name)
        h = hashlib.sha256(data).hexdigest()
        if asset.get("digest") and asset["digest"] != "sha256:" + h:
            raise ValueError("GitHub digest mismatch: " + name)
        p.write_bytes(data)
        assets.append({**asset, "sha256": h})
    checksums = {}
    for p in folder.glob("*.sha256"):
        for line in p.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                checksums[parts[-1].lstrip("*")] = parts[0]
    consolidated = folder / "sha256.sum"
    if consolidated.exists():
        for line in consolidated.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name, h = parts[-1].lstrip("*"), parts[0]
                if name in checksums and checksums[name] != h:
                    raise ValueError("Per-asset and consolidated checksum disagree")
                checksums[name] = h
    archives = [a for a in assets if a["name"].startswith("deckprobe-") and a["name"].endswith((".tar.gz", ".zip"))]
    for asset in archives:
        if checksums.get(asset["name"]) != asset["sha256"]:
            raise ValueError("Missing or invalid release checksum: " + asset["name"])
    extracted = {}
    for asset in archives:
        dest = folder / "unpacked" / asset["name"]
        safe_extract((folder / asset["name"]).read_bytes(), dest, policy["maxArchiveExpandedBytes"])
        extracted[asset["name"]] = {str(p.relative_to(dest)): sha(p) for p in dest.rglob("*") if p.is_file()}
    native_name = "deckprobe-" + native_platform + (".zip" if native_platform.endswith("windows-msvc") else ".tar.gz")
    native_root = folder / "unpacked" / native_name
    binaries = list(native_root.rglob("deckprobe.exe" if native_platform.endswith("windows-msvc") else "deckprobe"))
    if len(binaries) != 1:
        raise ValueError("Expected exactly one published native binary")
    binary = binaries[0]
    snapshots = {}
    for name in ["README.md", "SECURITY.md", "LICENSE", "NOTICE", "docs/deckprobe-report.schema.json"]:
        try:
            content = fetch(f"https://raw.githubusercontent.com/{release['repository']}/{release['commit']}/{name}")
            path = folder / "source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            snapshots[name] = {"sha256": sha(path), "path": str(path)}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            snapshots[name] = {"missing": True}
    provenance = []
    gh = shutil.which("gh")
    for asset in archives:
        if gh:
            result = process([gh, "attestation", "verify", str(folder / asset["name"]),
                              "--repo", release["repository"], "--source-digest", release["commit"],
                              "--format", "json"], timeout=120)
            result["status"] = "passed" if result["exitCode"] == 0 else "blocked"
        else:
            result = {"status": "blocked", "reason": "gh is not installed; checksum is not build provenance"}
        provenance.append({"asset": asset["name"], **result})
    record = {"identity": digest({"release": release, "nativePlatform": native_platform}), "release": release,
              "nativePlatform": native_platform, "folder": str(folder), "assets": assets,
              "extracted": extracted, "binary": str(binary), "binarySha256": sha(binary),
              "sourceSnapshots": snapshots, "provenance": provenance}
    immutable(folder / "prepared.json", record)
    return record


def prepare_packages(home, discovery, release):
    engine = release["release"]["tag"].lstrip("v")
    js = npm_record("@deckflow/deckprobe", engine)
    mcp = discovery["mcp"]
    identity = digest({"js": js, "mcp": mcp, "harness": "1"})
    folder = Path(home) / "packages" / identity
    existing = read(folder / "prepared.json")
    if existing:
        if sha(folder / "package-lock.json") != existing["lockSha256"]:
            raise ValueError("Dependency lock was modified")
        return existing
    folder.mkdir(parents=True, exist_ok=True)
    archives = {}
    for package in [js, mcp]:
        data = fetch(package["dist"]["tarball"])
        if not verify_sri(data, package["dist"]["integrity"]):
            raise ValueError("npm integrity mismatch: " + package["name"])
        name = package["name"].split("/")[-1] + ".tgz"
        (folder / name).write_bytes(data)
        archives[name] = sha(folder / name)
    package_json = {"name": "deckprobe-acceptance-install", "version": "1.0.0", "private": True,
                    "type": "module", "dependencies": {"@deckflow/deckprobe": js["version"],
                    "@deckflow/deckprobe-mcp": mcp["version"], "playwright": "1.62.1"},
                    "overrides": {"@deckflow/deckprobe": js["version"]}}
    atomic(folder / "package.json", package_json)
    prep = process(["npm", "install", "--ignore-scripts", "--package-lock-only", "--no-audit", "--no-fund"], folder, 240)
    atomic(folder / "npm-resolve.json", prep)
    if prep["exitCode"] != 0:
        raise RuntimeError("npm dependency resolution failed; see " + str(folder / "npm-resolve.json"))
    install = process(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], folder, 300)
    atomic(folder / "npm-install.json", install)
    if install["exitCode"] != 0:
        raise RuntimeError("npm ci failed; see " + str(folder / "npm-install.json"))
    env = {"PLAYWRIGHT_BROWSERS_PATH": str(Path(home) / "browsers")}
    browser = process(["node", str(folder / "node_modules/playwright/cli.js"), "install", "chromium"], folder, 300, env=env)
    atomic(folder / "browser-install.json", browser)
    audit = process(["npm", "audit", "signatures"], folder, 180)
    atomic(folder / "npm-signatures.json", audit)
    listing = process(["npm", "ls", "--all", "--json"], folder, 90)
    atomic(folder / "dependency-tree.json", listing)
    # Freeze every runtime file, including per-platform binaries and WASM; no later network install.
    files = {str(p.relative_to(folder)): sha(p) for p in (folder / "node_modules").rglob("*")
             if p.is_file() and not p.is_symlink()}
    record = {"id": identity, "folder": str(folder), "engine": engine, "js": js, "mcp": mcp,
              "lockSha256": sha(folder / "package-lock.json"), "archives": archives,
              "runtimeFiles": files, "browserReady": browser["exitCode"] == 0,
              "signatureAudit": audit["exitCode"], "browserEnv": env}
    immutable(folder / "prepared.json", record)
    return record
