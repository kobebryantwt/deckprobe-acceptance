"""Linux x64 fail-closed network/process/file monitoring for GitHub-hosted runs."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from .common import atomic, now, process, read, seal, sha
from .github_ci import job_result, prepare_locked

TOOLS = ["ip", "nft", "strace"]


def _nft_packets(namespace):
    result = process(["ip", "netns", "exec", namespace, "nft", "-j", "list", "chain", "inet", "acceptance", "output"])
    if result["exitCode"] != 0:
        raise ValueError("cannot read nftables counters: " + result["stderr"])
    values = [int(value) for value in re.findall(r'"packets"\s*:\s*(\d+)', result["stdout"])]
    if not values:
        raise ValueError("nftables drop counter is not visible")
    return max(values), result


def run_security(lock_path, snapshot, home, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    lock = read(lock_path); checks = []
    missing = [name for name in TOOLS if not shutil.which(name)]
    if sys.platform != "linux" or os.geteuid() != 0 or missing:
        checks.append({"id": "linux_live_isolation", "requirement": "PRO-R02", "title": "Ubuntu x64 独立隔离与监控",
                       "status": "blocked", "expected": "root + ip/nft/strace", "actual": {"missing": missing, "euid": os.geteuid()}})
    else:
        try:
            lock, targets = prepare_locked(lock_path, snapshot, home, include_previous=False)
            binary = targets["candidate"]["release"]["binary"]
            samples = read(Path(home) / "corpus/manifest.json")["sources"]
            input_hashes = {sample["id"]: sha(sample["path"]) for sample in samples}
            namespace = "deckprobe-accept-" + lock["runId"][-8:]
            suffix = re.sub(r"[^a-z0-9]", "", lock["runId"].lower())[-6:] or "accept"
            host_veth, namespace_veth = "dp" + suffix + "h", "dp" + suffix + "n"
            trace = output / "trace"
            marker = output / "marker"
            setup = process(["ip", "netns", "add", namespace])
            if setup["exitCode"] != 0: raise ValueError("network namespace setup failed: " + setup["stderr"])
            try:
                for command in (["ip", "link", "add", host_veth, "type", "veth", "peer", "name", namespace_veth],
                                ["ip", "link", "set", namespace_veth, "netns", namespace],
                                ["ip", "addr", "add", "192.0.2.1/30", "dev", host_veth],
                                ["ip", "-6", "addr", "add", "2001:db8:1::1/64", "dev", host_veth],
                                ["ip", "link", "set", host_veth, "up"],
                                ["ip", "-n", namespace, "link", "set", "lo", "up"],
                                ["ip", "-n", namespace, "addr", "add", "192.0.2.2/30", "dev", namespace_veth],
                                ["ip", "-n", namespace, "-6", "addr", "add", "2001:db8:1::2/64", "dev", namespace_veth],
                                ["ip", "-n", namespace, "link", "set", namespace_veth, "up"],
                                ["ip", "-n", namespace, "route", "add", "default", "via", "192.0.2.1"],
                                ["ip", "-n", namespace, "-6", "route", "add", "default", "via", "2001:db8:1::1"],
                                ["ip", "netns", "exec", namespace, "nft", "add", "table", "inet", "acceptance"],
                                ["ip", "netns", "exec", namespace, "nft", "add", "chain", "inet", "acceptance", "output", "{", "type", "filter", "hook", "output", "priority", "0", ";", "policy", "drop", ";", "}"],
                                ["ip", "netns", "exec", namespace, "nft", "add", "rule", "inet", "acceptance", "output", "oifname", "lo", "accept"],
                                ["ip", "netns", "exec", namespace, "nft", "add", "rule", "inet", "acceptance", "output", "counter", "drop"]):
                    result = process(command)
                    if result["exitCode"] != 0: raise ValueError("isolation rule failed: " + result["stderr"])
                control_code = ("import os,socket,subprocess,sys,pathlib\n"
                    "p=pathlib.Path(sys.argv[1]);p.write_text('marker')\n"
                    "subprocess.run([sys.executable,'-c','pass'])\n"
                    "tests=[(socket.AF_INET,('1.1.1.1',53)),(socket.AF_INET6,('2606:4700:4700::1111',53)),(socket.AF_INET,('127.0.0.1',9)),(socket.AF_INET,('192.0.2.1',8080))]\n"
                    "for family,address in tests:\n"
                    " s=socket.socket(family,socket.SOCK_STREAM);s.settimeout(.2)\n"
                    " try:s.connect(address)\n"
                    " except OSError:pass\n"
                    "try:socket.getaddrinfo('deckprobe-control.invalid',443)\n"
                    "except OSError:pass\n")
                def control(phase):
                    phase_marker = marker.with_name(marker.name + "-" + phase)
                    packets_before, _ = _nft_packets(namespace)
                    result = process(["ip", "netns", "exec", namespace, "strace", "-ff", "-o", str(trace)+"-control-"+phase,
                        "-e", "trace=network,process,file", sys.executable, "-c", control_code, str(phase_marker)], timeout=30,
                        env={"HTTP_PROXY":"http://192.0.2.1:8080","HTTPS_PROXY":"http://192.0.2.1:8080","NO_PROXY":"127.0.0.1"})
                    packets_after, counter_record = _nft_packets(namespace)
                    text = "\n".join(p.read_text(errors="ignore") for p in output.glob("trace-control-"+phase+"*"))
                    trace_files=list(output.glob("trace-control-"+phase+"*"))
                    complete_logs=bool(trace_files) and all("+++ exited with" in p.read_text(errors="ignore") for p in trace_files)
                    observed = {"ipv4": "1.1.1.1" in text, "ipv6": "2606:4700:4700::1111" in text,
                                "dns": ":53" in text or "htons(53)" in text, "loopback": "127.0.0.1" in text,
                                "proxy": "192.0.2.1" in text, "child_exec": len(list(output.glob("trace-control-"+phase+"*"))) > 1,
                                "marker_file": phase_marker.is_file() and phase_marker.name in text,
                                "proxy_environment": "192.0.2.1" in text,
                                "nft_drop_counter": packets_after > packets_before,
                                "complete_logs": complete_logs}
                    if result["exitCode"] != 0 or not all(observed.values()):
                        raise ValueError("positive control incomplete: " + json.dumps(observed))
                    return {"process": result, "observed": observed, "nftPacketsBefore": packets_before,
                            "nftPacketsAfter": packets_after, "counterRecord": counter_record}
                preflight = control("pre")
                product_packets_before, _ = _nft_packets(namespace)
                product_runs = []
                for index, sample in enumerate(samples):
                    command = ["ip", "netns", "exec", namespace, "strace", "-ff", "-o", str(trace)+"-product-"+str(index),
                               "-e", "trace=network,process,file", binary, "-l", "deep", "-t", "@all", sample["path"]]
                    product_runs.append(process(command, timeout=180))
                postflight = control("post")
                product_packets_after = postflight["nftPacketsBefore"]
                product_drop_packets = product_packets_after - product_packets_before
                traces = "\n".join(p.read_text(errors="ignore") for p in output.glob("trace-product*"))
                forbidden = [line for line in traces.splitlines() if "connect(" in line
                             and ("AF_INET" in line or "AF_INET6" in line)]
                execs=[line for line in traces.splitlines() if "execve(" in line]
                unexpected_execs = [line for line in execs if not re.search(r'execve\("'+re.escape(str(binary))+r'"',line)]
                write_events=[line for line in traces.splitlines() if re.search(r'\b(open|openat|creat|unlink|unlinkat|rename|renameat)\(',line)
                              and re.search(r'O_(?:WRONLY|RDWR|CREAT|TRUNC)|\b(unlink|unlinkat|rename|renameat)\(',line)]
                modified_inputs = [sample["id"] for sample in samples if sha(sample["path"]) != input_hashes[sample["id"]]]
                product_trace_files=list(output.glob("trace-product*"))
                complete = (bool(product_trace_files) and all(p.stat().st_size>0 for p in product_trace_files)
                            and all(not r.get('timedOut') and not r.get('launchError') for r in product_runs))
                status = "failed" if forbidden or unexpected_execs or write_events or modified_inputs or product_drop_packets else ("passed" if complete else "blocked")
                checks.append({"id": "linux_live_isolation", "requirement": "PRO-R02", "title": "Ubuntu x64 网络、进程及文件边界",
                    "status": status, "expected": "positive controls visible; no product IPv4/IPv6 connect attempts",
                    "actual": {"controlsVisible": complete, "forbiddenConnects": forbidden,
                               "unexpectedExecutions": unexpected_execs, "modifiedInputs": modified_inputs, "runs": len(product_runs),
                               "writeEvents": write_events,
                               "productDropPackets": product_drop_packets,
                               "scope": "Ubuntu x64 hosted runner and exported public fixtures"}})
                rules = process(["ip", "netns", "exec", namespace, "nft", "list", "ruleset"])
                session = {"runId": lock["runId"], "createdAt": now(), "preflight": preflight, "postflight": postflight,
                           "rules": rules, "productRuns": product_runs, "forbiddenConnects": forbidden,
                           "unexpectedExecutions": unexpected_execs, "modifiedInputs": modified_inputs,
                           "writeEvents": write_events,
                           "captureIntegrity": {"productTraceFiles":len(product_trace_files),"complete":complete},
                           "droppedEvents": 0 if complete else None,
                           "productDropPackets": product_drop_packets}
            finally:
                cleanup = process(["ip", "netns", "delete", namespace])
                process(["ip", "link", "delete", host_veth])
            session["rulesCleaned"] = cleanup["exitCode"] == 0
            atomic(output / "security-session.json", session)
            if not session["rulesCleaned"]:
                checks[-1]["status"] = "blocked"; checks[-1]["actual"]["cleanup"] = cleanup
        except (OSError, ValueError, RuntimeError) as error:
            checks.append({"id": "linux_live_isolation", "requirement": "PRO-R02", "title": "Ubuntu x64 独立隔离与监控",
                           "status": "blocked", "expected": "complete live monitoring", "actual": str(error)})
    result = job_result(lock, "security-linux", checks)
    atomic(output / "job-result.json", result)
    seal(output)
    return result
