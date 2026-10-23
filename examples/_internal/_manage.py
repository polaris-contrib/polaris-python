# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
#
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Run, verify, inspect and clean the repository's example directories."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import urllib.request
import urllib.parse
from pathlib import Path

import psutil

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]
from examples._internal._runtime import new_run_directory, track_process

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"
TERMINATE_GRACE_SECONDS = 10
E2E_SERVICE_PREFIX = "polaris-python-e2e-"
VERIFIERS = {
    "quickstart": ("quickstart/verify.py", []),
    "quickstart/provider": ("quickstart/verify.py", []),
    "quickstart/consumer": ("quickstart/verify.py", []),
    "circuitbreaker": ("circuitbreaker/verify.py", []),
    "circuitbreaker/provider": ("circuitbreaker/verify.py", []),
    "circuitbreaker/consumer": ("circuitbreaker/verify.py", []),
    "sdkconfig/code": ("sdkconfig/verify.py", ["--only", "code"]),
    "sdkconfig/file": ("sdkconfig/verify.py", ["--only", "file"]),
    "cache/expiry": ("cache/expiry/verify.py", []),
    "cache/restart": ("cache/restart/verify.py", []),
    "loadbalancer/random": ("loadbalancer/random/verify.py", []),
    "loadbalancer/wr": ("loadbalancer/wr/verify.py", []),
    "servicerouter": ("servicerouter/verify.py", []),
    "multicontext": ("multicontext/verify.py", []),
    "mcp": ("mcp/verify.py", []),
    "skill": ("skill/verify.py", []),
    "a2a": ("a2a/verify.py", []),
    "monitoring": ("monitoring/verify.py", []),
    "events": ("events/verify.py", []),
}
GROUPS = {
    "": ["quickstart", "circuitbreaker", "sdkconfig/code", "sdkconfig/file",
         "cache/expiry", "cache/restart", "loadbalancer/random", "loadbalancer/wr",
         "servicerouter", "multicontext", "mcp", "skill", "a2a", "monitoring", "events"],
    "sdkconfig": ["sdkconfig/code", "sdkconfig/file"],
    "cache": ["cache/expiry", "cache/restart"],
    "loadbalancer": ["loadbalancer/random", "loadbalancer/wr"],
}
REAL_VERIFIERS = {
    name: ("_internal/_real_verify.py", ["--demo", name])
    for name in VERIFIERS
}
REAL_GROUPS = GROUPS


def contained(path, root):
    return path.is_relative_to(root)


def directories(scope):
    return [EXAMPLES / name for name in sorted(set(VERIFIERS) | set(GROUPS))
            if contained(EXAMPLES / name, scope)]


def verification_targets(name, only, groups=None):
    groups = GROUPS if groups is None else groups
    available = groups.get(name, [name])
    if not only:
        return available
    selected = []
    for item in only.split(","):
        candidate = f"{name}/{item}" if name else item
        matches = [value for value in available if value == item or value == candidate
                   or value.startswith(candidate + "/")]
        if not matches:
            raise ValueError(f"Unknown demo {item!r}; choose from {', '.join(available)}")
        selected.extend(matches)
    return list(dict.fromkeys(selected))


def run_process(directory, entry, arguments, action, timeout):
    run = new_run_directory(directory, action)
    work = run / "work"
    work.mkdir()
    env = os.environ.copy()
    env.update(POLARIS_DEMO_RUN_DIR=str(run), POLARIS_DEMO_DIRECTORY=str(directory),
               PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO / "src"), str(REPO), env.get("PYTHONPATH", "")]))
    print(f"{action.upper()} {directory.relative_to(EXAMPLES) or '.'}", flush=True)
    print(f"Run: {run}", flush=True)
    print(f"Logs: {run / 'polaris' / 'log'}", flush=True)
    print(f"Backups: {run / 'polaris' / 'backup'}", flush=True)
    command = [sys.executable, str(entry), *arguments]
    if action == "run":
        # The wrapper tees output and tracks identity in the same PID as main.py.
        command = [sys.executable, str(EXAMPLES / "_internal" / "_run.py"), str(entry), *arguments]
    process = subprocess.Popen(command, cwd=directory if action == "run" else work,
                               env=env, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    timed_out = False
    interrupted = None
    finished = threading.Event()
    escalation = None

    def signal_group(signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def force_stop():
        if not finished.is_set():
            signal_group(signal.SIGKILL)

    def terminate_group():
        nonlocal escalation
        signal_group(signal.SIGTERM)
        if escalation is None:
            escalation = threading.Timer(TERMINATE_GRACE_SECONDS, force_stop)
            escalation.daemon = True
            escalation.start()

    def interrupt(signum, frame):
        nonlocal interrupted
        interrupted = signum
        terminate_group()

    old_handlers = {value: signal.signal(value, interrupt) for value in (signal.SIGINT, signal.SIGTERM)}
    # A timer can interrupt a blocked stdout read as well as a quiet child.
    def expire():
        nonlocal timed_out
        if not finished.is_set():
            timed_out = True
            terminate_group()

    timer = threading.Timer(timeout, expire) if timeout else None
    if timer:
        timer.start()
    try:
        with (run / "console.log").open("w", encoding="utf-8") as logfile:
            for line in process.stdout:
                logfile.write(line)
                logfile.flush()
                print(line, end="", flush=True)
        code = process.wait()
    finally:
        finished.set()
        if timer:
            timer.cancel()
        if escalation:
            escalation.cancel()
        if process.poll() is None:
            signal_group(signal.SIGTERM)
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                signal_group(signal.SIGKILL)
                process.wait()
        process.stdout.close()
        for value, handler in old_handlers.items():
            signal.signal(value, handler)
    result = {"entry": str(entry.relative_to(REPO)), "exit_code": code,
              "timed_out": timed_out, "interrupted": interrupted, "action": action}
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if code == 0 and not timed_out and not interrupted else 'FAIL'} {directory.relative_to(EXAMPLES)}", flush=True)
    return 128 + interrupted if interrupted else 124 if timed_out else code


def log_files(scope):
    files = []
    for directory in directories(scope):
        root = directory / ".logs"
        if root.is_symlink() or not root.exists():
            continue
        files.extend(path for path in root.rglob("*") if path.is_file() and contained(path.resolve(), root.resolve())
                     and (".log" in path.name or path.name == "result.json"))
    return sorted(set(files))


def console_address():
    configured = os.getenv("POLARIS_CONSOLE_ADDRESS")
    if configured:
        return configured.rstrip("/")
    registry = (os.getenv("POLARIS_SERVER_ADDRESS")
                or os.getenv("POLARIS_SERVER_ADDRESSES", "")).split(",", 1)[0].strip()
    if not registry:
        raise ValueError("POLARIS_CONSOLE_ADDRESS or POLARIS_SERVER_ADDRESS is required to delete services")
    host = registry.rsplit(":", 1)[0] if ":" in registry else registry
    return f"http://{host}:8090"


def e2e_namespace():
    return os.getenv("POLARIS_E2E_NAMESPACE", "python-integration")


def test_services():
    """List only services created by this repository's real-service tests."""
    address = console_address()
    namespace = e2e_namespace()
    token = os.getenv("POLARIS_E2E_SERVICE_TOKEN") or os.getenv("POLARIS_SERVICE_TOKEN", "")
    url = f"{address}/naming/v1/services?namespace={urllib.parse.quote(namespace)}"
    request = urllib.request.Request(url, headers={"X-Polaris-Token": token} if token else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("code") != 200000:
        raise RuntimeError(f"Polaris service query failed: {body}")
    return address, namespace, [
        item["name"] for item in body.get("services", [])
        if item.get("namespace") == namespace and item.get("name", "").startswith(E2E_SERVICE_PREFIX)
    ]


def delete_test_services(address, namespace, names):
    """Delete only the named services created by real-service tests."""
    if not names:
        return []
    token = os.getenv("POLARIS_E2E_SERVICE_TOKEN") or os.getenv("POLARIS_SERVICE_TOKEN", "")
    request = urllib.request.Request(
        f"{address}/naming/v1/services/delete",
        data=json.dumps([
            {"namespace": namespace, "name": name} for name in names
        ]).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Polaris-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("code") != 200000:
        raise RuntimeError(f"Polaris service deletion failed: {body}")
    failures = [item for item in body.get("responses", []) if item.get("code") != 200000]
    if failures:
        raise RuntimeError(f"Polaris service deletion partially failed: {failures}")
    return names


def show_logs(scope, args):
    files = log_files(scope)
    if args.latest:
        roots = {}
        for path in files:
            parts = path.relative_to(EXAMPLES).parts
            index = parts.index(".logs")
            key = parts[:index]
            run = EXAMPLES.joinpath(*parts[:index + 2])
            if key not in roots or run.stat().st_mtime > roots[key].stat().st_mtime:
                roots[key] = run
        files = [path for path in files if any(contained(path, root) for root in roots.values())]
    if args.category:
        files = [path for path in files if args.category in path.parts[path.parts.index(".logs") + 1:-1]]
    if not files:
        print("No logs found.")
        return 0
    if args.follow:
        print("Following logs; Ctrl+C stops viewing.", flush=True)
        return subprocess.call(["tail", "-n", str(args.tail or 50), "-f", *map(str, files)])
    for path in files:
        print(f"{path} ({path.stat().st_size} bytes)")
        if args.tail:
            from collections import deque
            with path.open(encoding="utf-8", errors="replace") as stream:
                print("".join(deque(stream, maxlen=args.tail)), end="")
    return 0


def owned_processes(scope):
    found, stale = {}, []
    for directory in directories(scope):
        records = directory / ".runtime" / "processes"
        if (records.is_symlink() or not records.exists()
                or not contained(records.resolve(), directory.resolve())):
            continue
        for record in records.glob("*.json"):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                process = psutil.Process(data["pid"])
                entry = Path(data["entry"])
                if (process.pid in (os.getpid(), os.getppid()) or not contained(entry, EXAMPLES)
                        or abs(process.create_time() - data["created"]) > 0.01
                        or process.cmdline() != data["command"]):
                    stale.append(record)
                    continue
                found[process.pid] = (process, record)
            except (OSError, ValueError, KeyError, TypeError, psutil.Error):
                stale.append(record)
    return list(found.values()), stale


def cleanup(scope, args):
    processes, _ = owned_processes(scope)
    keep_logs = getattr(args, "keep_logs", False)
    delete_services = getattr(args, "delete_services", False)
    services = test_services() if delete_services else None
    targets = [directory / name for directory in directories(scope) for name in (".logs", ".runtime")
               if (directory / name).exists() or (directory / name).is_symlink()]
    if keep_logs:
        targets = []
    for process, record in processes:
        print(f"Process: {process.pid} ({record.parent.parent.parent.relative_to(EXAMPLES)})")
    for path in targets:
        print(f"Directory: {path}")
    if services is not None:
        address, namespace, names = services
        print(f"Services: {address} {namespace}/{E2E_SERVICE_PREFIX}* ({len(names)})")
    if args.dry_run:
        print("Dry run; nothing changed.")
        return 0
    if not targets and not processes and not delete_services:
        print("Nothing to clean.")
        return 0
    if not args.force:
        try:
            prompt = ("Stop these demo processes, delete listed services, and keep logs?"
                      if keep_logs and delete_services else
                      "Stop these demo processes and delete listed services?"
                      if delete_services else
                      "Stop these demo processes and keep logs?"
                      if keep_logs else
                      "Stop these demo processes and remove these logs/runtime files?")
            response = input(prompt + " [y/N] ")
        except EOFError:
            response = ""
        if response.lower() not in ("y", "yes"):
            print("Cleanup cancelled. Use --force for noninteractive cleanup.")
            return 0
    children = []
    for process, record in processes:
        try:
            try:
                children.extend(process.children(recursive=True))
            except (psutil.AccessDenied, PermissionError):
                # PID records still allow direct cleanup in a restricted shell.
                pass
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs([process for process, _ in processes], timeout=10)
    for process in alive + children:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive + children, timeout=2)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=2)
    if services is not None:
        address, namespace, names = services
        for name in delete_test_services(address, namespace, names):
            print(f"Deleted service: {namespace}/{name}")
    if keep_logs:
        print("Kept logs.")
        return 0
    for path in targets:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
        print(f"Removed: {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    verify = commands.add_parser("verify", help="run offline verification; no external registry")
    verify.add_argument("--only", help="comma-separated child demos (group directories)")
    verify.add_argument("--timeout", type=float, default=180, help="seconds per demo; default 180")
    verify_e2e = commands.add_parser("verify-e2e", help="run verification against a real Polaris service")
    verify_e2e.add_argument("--only", help="comma-separated child demos (group directories)")
    verify_e2e.add_argument("--timeout", type=float, default=300, help="seconds per demo; default 300")
    run = commands.add_parser("run", help="run this demo with its original main.py arguments")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    logs = commands.add_parser("logs", help="list retained console and SDK logs")
    logs.add_argument("--tail", type=int, default=0, help="show the last N lines of each file")
    logs.add_argument("--follow", "-f", action="store_true")
    logs.add_argument("--latest", action="store_true")
    logs.add_argument("--category", help="filter by SDK category, e.g. base/network/cache/circuitbreaker")
    clean = commands.add_parser("cleanup", help="stop owned demo processes and delete logs/runtime files")
    clean.add_argument("--force", "-f", action="store_true")
    clean.add_argument("--dry-run", action="store_true")
    clean.add_argument("--keep-logs", "--processes-only", dest="keep_logs", action="store_true",
                       help="stop owned demo processes and keep logs")
    clean.add_argument("--delete-services", "--remote", dest="delete_services", action="store_true",
                       help="delete only polaris-python-e2e services in POLARIS_E2E_NAMESPACE")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not contained(directory, EXAMPLES):
        parser.error("directory must be inside examples")
    name = directory.relative_to(EXAMPLES).as_posix()
    name = "" if name == "." else name
    if name not in VERIFIERS and name not in GROUPS:
        parser.error("unknown example directory")
    try:
        if args.action == "logs":
            if args.tail < 0:
                parser.error("--tail must not be negative")
            return show_logs(directory, args)
        if args.action == "cleanup":
            return cleanup(directory, args)
        track_process(directory, __file__)
        if args.action == "run":
            entry = directory / "main.py"
            if not entry.exists():
                parser.error("choose a child demo with main.py to run")
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            return run_process(directory, entry, arguments, "run", None)
        if not 0 < args.timeout <= 3600:
            parser.error("--timeout must be between 0 and 3600 seconds")
        if args.action == "verify-e2e":
            targets = verification_targets(name, args.only, groups=REAL_GROUPS)
            failed = []
            for target in targets:
                script, arguments = REAL_VERIFIERS[target]
                code = run_process(EXAMPLES / target, EXAMPLES / script, arguments, "verify-e2e", args.timeout)
                if code:
                    failed.append(target)
                if code in (128 + signal.SIGINT, 128 + signal.SIGTERM):
                    print("Verification interrupted; remaining demos were not started.")
                    return code
            print(f"Real-service verification: {len(targets) - len(failed)} passed, {len(failed)} failed.")
            return bool(failed)
        targets = verification_targets(name, args.only)
        failed = []
        for target in targets:
            script, arguments = VERIFIERS[target]
            code = run_process(EXAMPLES / target, EXAMPLES / script, arguments, "verify", args.timeout)
            if code:
                failed.append(target)
            if code in (128 + signal.SIGINT, 128 + signal.SIGTERM):
                print("Verification interrupted; remaining demos were not started.")
                return code
        print(f"Verification: {len(targets) - len(failed)} passed, {len(failed)} failed.")
        return bool(failed)
    except (OSError, ValueError, psutil.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
