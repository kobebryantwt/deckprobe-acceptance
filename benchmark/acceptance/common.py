from __future__ import annotations

import contextlib
import datetime as dt
try:
    import fcntl
except ImportError:  # Windows hosted runners
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
CODE = Path(__file__).resolve().parent
DEFAULT_HOME = ROOT / "benchmark" / "artifacts" / "acceptance"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def atomic(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if isinstance(value, str):
                f.write(value)
            else:
                json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def immutable(path, value):
    if Path(path).exists():
        if read(path) != value:
            raise ValueError("Immutable record already exists: " + str(path))
    else:
        atomic(path, value)


@contextlib.contextmanager
def locked(home):
    Path(home).mkdir(parents=True, exist_ok=True,mode=0o700)
    with (Path(home) / "execution.lock").open("a+") as f:
        if msvcrt is not None:
            f.seek(0);f.write("0");f.flush();f.seek(0)
            try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise RuntimeError("An acceptance command is already running")
        if fcntl is not None:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("An acceptance command is already running")
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(f, fcntl.LOCK_UN)
            if msvcrt is not None:
                f.seek(0);msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def process(argv, cwd=None, timeout=60, stdin=None, env=None):
    """No shell; kill the complete process group on timeout or interruption."""
    start = time.monotonic()
    clean = {k: v for k, v in os.environ.items() if k not in {
        "NODE_OPTIONS", "NODE_PATH", "DECKPROBE_MCP_BIN", "DECKPROBE_MCP_ROOTS",
        "DYLD_INSERT_LIBRARIES", "LD_PRELOAD", "GITHUB_TOKEN", "GH_TOKEN"}}
    clean.update(env or {})
    record = {"command": list(map(str, argv)), "cwd": str(cwd or ROOT), "startedAt": now()}
    p = None
    try:
        p = subprocess.Popen(record["command"], cwd=cwd or ROOT, env=clean,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        try:
            out, err = p.communicate(stdin, timeout=timeout)
            record.update(exitCode=p.returncode, stdout=out, stderr=err, timedOut=False)
        except subprocess.TimeoutExpired:
            if os.name == "nt": p.kill()
            else: os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate()
            record.update(exitCode=None, stdout=out, stderr=err, timedOut=True)
        except BaseException:
            if p.poll() is None:
                if os.name == "nt": p.kill()
                else: os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            raise
    except OSError as e:
        record.update(exitCode=None, stdout="", stderr=str(e), launchError=True, timedOut=False)
    record["durationMs"] = (time.monotonic() - start) * 1000
    return record


def code_files():
    files = sorted(p for p in CODE.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix in {".py", ".mjs", ".json", ".md", ".sh", ".txt", ".html", ".css"})
    values={str(p.relative_to(CODE)): p for p in files}
    for name in ['deck_benchmark.py','release_acceptance.py']:
        p=ROOT/'benchmark/scripts'/name
        if p.exists():values['entry/'+name]=p
    return values


def code_hash():
    return digest({name:sha(path) for name,path in code_files().items()})


def seal(folder):
    files = {str(p.relative_to(folder)): sha(p) for p in sorted(Path(folder).rglob("*"))
             if p.is_file() and p.name != "evidence-manifest.json"}
    atomic(Path(folder) / "evidence-manifest.json", {"algorithm": "sha256", "files": files})
    return digest(files)


def verify_seal(folder):
    manifest = read(Path(folder) / "evidence-manifest.json")
    if not manifest or not manifest.get("files"):
        return ["Missing evidence manifest"]
    errors = []
    base = Path(folder).resolve()
    for name, expected in manifest["files"].items():
        p = (base / name).resolve()
        if base not in p.parents or not p.is_file() or sha(p) != expected:
            errors.append("Evidence mismatch: " + name)
    actual={str(p.relative_to(base)) for p in base.rglob('*') if p.is_file() and p.name!='evidence-manifest.json'}
    if actual!=set(manifest['files']):errors.append('Evidence inventory differs from sealed manifest')
    return errors
