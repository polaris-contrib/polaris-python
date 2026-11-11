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

"""Run examples and manage only their local processes and artifacts."""

import argparse
import atexit
import json
import os
import runpy
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import psutil

EXAMPLES = Path(__file__).resolve().parent
REPO = EXAMPLES.parent
TERMINATE_GRACE_SECONDS = 30


def demo_directory(value):
    directory = (EXAMPLES / value).resolve()
    if not directory.is_relative_to(EXAMPLES) or not directory.is_dir():
        raise ValueError("choose a directory inside examples")
    return directory


def selected_directories(directory, only=None):
    scope = demo_directory(directory)
    directories = sorted({
        path.parent
        for path in scope.rglob("main.py")
        if path.is_file()
        and path.resolve().is_relative_to(EXAMPLES)
        and not any(part.startswith(".") for part in path.relative_to(scope).parts)
    })
    if not only:
        return directories
    selected = set()
    for item in only.split(","):
        if not item.strip():
            raise ValueError("--only must contain nonempty example paths")
        candidate = demo_directory(scope / item.strip())
        matches = [path for path in directories if path.is_relative_to(candidate)]
        if not matches:
            raise ValueError(f"no runnable example matches {item!r}")
        selected.update(matches)
    return sorted(selected)


def track_process(entry):
    entry = Path(entry).resolve()
    directory = demo_directory(entry.parent)
    records = directory / ".runtime" / "processes"
    if (
        (directory / ".runtime").is_symlink()
        or records.is_symlink()
        or not records.resolve().is_relative_to(directory)
    ):
        raise ValueError("example runtime directory must not be a symlink")
    records.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    record = records / f"{process.pid}.json"
    data = {
        "kind": "example",
        "pid": process.pid,
        "created": process.create_time(),
        "command": process.cmdline(),
        "entry": str(entry),
    }
    record.write_text(json.dumps(data), encoding="utf-8")
    atexit.register(record.unlink, missing_ok=True)
    return record


def run(directory, arguments, entry_name="main.py"):
    directory = demo_directory(directory)
    entry = (directory / entry_name).resolve()
    if not entry.is_relative_to(directory) or not entry.is_file():
        raise ValueError("choose an example directory containing the application entry point")
    log_root = directory / ".logs"
    if log_root.is_symlink() or not log_root.resolve().is_relative_to(directory):
        raise ValueError("example log directory must not be a symlink")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = log_root / f"run-{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True)
    env = os.environ.copy()
    env.update(POLARIS_DEMO_RUN_DIR=str(run_dir), PYTHONUNBUFFERED="1")
    env["PYTHONPATH"] = os.pathsep.join(filter(
        None, [str(REPO / "src"), str(REPO), env.get("PYTHONPATH", "")],
    ))
    print(f"Run: {run_dir}", flush=True)
    print(f"Logs: {run_dir / 'polaris' / 'log'}", flush=True)
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    record = track_process(entry)
    try:
        process = subprocess.Popen(
            [sys.executable, str(EXAMPLES / "_apps.py"), "__exec__", str(entry), *arguments],
            cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **options,
        )
    except BaseException:
        record.unlink(missing_ok=True)
        raise
    interrupted = None
    escalation = None

    def stop(force=False):
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            root = psutil.Process(process.pid)
            for target in root.children(recursive=True) + [root]:
                try:
                    target.kill() if force else target.terminate()
                except psutil.NoSuchProcess:
                    pass

    def interrupt(signum, _frame):
        nonlocal interrupted, escalation
        interrupted = signum
        stop()
        if escalation is None:
            escalation = threading.Timer(TERMINATE_GRACE_SECONDS, lambda: stop(True))
            escalation.daemon = True
            escalation.start()

    handlers = {
        value: signal.signal(value, interrupt)
        for value in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        with (run_dir / "console.log").open("w", encoding="utf-8") as logfile:
            for line in process.stdout:
                logfile.write(line)
                logfile.flush()
                print(line, end="", flush=True)
        code = process.wait()
    finally:
        if process.poll() is None:
            stop()
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                stop(True)
                process.wait()
        if escalation:
            escalation.cancel()
        process.stdout.close()
        for value, handler in handlers.items():
            signal.signal(value, handler)
        try:
            (run_dir / "result.json").write_text(json.dumps({
                "entry": str(entry), "exit_code": process.returncode,
                "interrupted": interrupted,
            }, indent=2) + "\n", encoding="utf-8")
        finally:
            record.unlink(missing_ok=True)
    return 128 + interrupted if interrupted else code if code >= 0 else 128 - code


def execute_entry(entry, arguments):
    """Track and execute one example in the child process created by run()."""
    entry = Path(entry).resolve()
    track_process(entry)
    sys.argv = [str(entry), *arguments]
    runpy.run_path(str(entry), run_name="__main__")


def owned_processes(directories):
    found = []
    for directory in directories:
        records = directory / ".runtime" / "processes"
        if (
            (directory / ".runtime").is_symlink()
            or records.is_symlink()
            or not records.resolve().is_relative_to(directory)
        ):
            continue
        for record in records.glob("*.json"):
            if record.is_symlink():
                continue
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                process = psutil.Process(data["pid"])
                if (
                    data.get("kind") == "example"
                    and process.pid not in (os.getpid(), os.getppid())
                    and Path(data["entry"]).resolve().parent == directory
                    and abs(process.create_time() - data["created"]) <= 0.01
                    and process.cmdline() == data["command"]
                ):
                    found.append(process)
            except (psutil.AccessDenied, PermissionError):
                raise
            except (OSError, ValueError, KeyError, TypeError, psutil.NoSuchProcess):
                continue
    return found


def wait_processes(processes, timeout):
    deadline = time.monotonic() + timeout
    while processes:
        _, processes = psutil.wait_procs(processes, timeout=0)
        alive = []
        for process in processes:
            try:
                if process.status() != psutil.STATUS_ZOMBIE:
                    alive.append(process)
            except psutil.NoSuchProcess:
                pass
        if not alive or time.monotonic() >= deadline:
            return alive
        processes = alive
        time.sleep(0.05)
    return []


def cleanup(directories, args):
    processes = owned_processes(directories)
    names = (".runtime",) if args.keep_logs else (
        ".logs", ".runtime", ".build", "bin", "x86-bin",
    )
    targets = [directory / name for directory in directories for name in names
               if (directory / name).exists() or (directory / name).is_symlink()]
    for process in processes:
        print(f"Process: {process.pid}")
    for path in targets:
        print(f"Artifact: {path}")
    if args.dry_run:
        print("Dry run; nothing changed.")
        return 0
    if not processes and not targets:
        print("Nothing to clean.")
        return 0
    if not args.force:
        try:
            confirmed = input("Stop these example processes and remove the listed artifacts? [y/N] ")
        except EOFError:
            confirmed = ""
        if confirmed.lower() not in ("y", "yes"):
            print("Cleanup cancelled. Use --force for noninteractive cleanup.")
            return 0
    children = []
    for process in processes:
        try:
            try:
                children.extend(process.children(recursive=True))
            except (psutil.AccessDenied, PermissionError):
                pass
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    alive = wait_processes(processes, TERMINATE_GRACE_SECONDS)
    for process in alive + children:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    alive = wait_processes(alive + children, 2)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    alive = wait_processes(alive, 2)
    if alive:
        print("Some example processes are still alive; artifacts were kept.", file=sys.stderr)
        return 1
    for path in targets:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)
        print(f"Removed: {path}")
    return 0


def log_files(directories, latest=False, category=None):
    files = []
    for directory in directories:
        root = directory / ".logs"
        if root.is_symlink() or not root.exists():
            continue
        runs = [path for path in root.iterdir() if path.is_dir() and not path.is_symlink()]
        if latest and runs:
            runs = [max(runs, key=lambda path: path.stat().st_mtime)]
        for run_dir in runs:
            for path in run_dir.rglob("*"):
                if not path.is_file() or not path.resolve().is_relative_to(root):
                    continue
                if path.suffix != ".log" and path.name != "result.json":
                    continue
                if category:
                    parts = path.relative_to(run_dir).parts
                    if parts[:2] != ("polaris", "log") or category not in parts[2:-1]:
                        continue
                files.append(path)
    return sorted(files)


def show_logs(directories, args):
    files = log_files(directories, args.latest, args.category)
    if not files:
        print("No example logs found.")
        return 0
    if args.follow:
        tail = shutil.which("tail")
        if tail is None:
            raise ValueError("--follow requires the tail command")
        return subprocess.call([tail, "-n", str(args.tail), "-f", *map(str, files)])
    for path in files:
        print(f"Log: {path}")
        if args.tail:
            with path.open(encoding="utf-8", errors="replace") as logfile:
                print("".join(deque(logfile, maxlen=args.tail)), end="")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["__exec__"]:
        if len(argv) < 2:
            raise SystemExit("__exec__ requires an example entry point")
        execute_entry(argv[1], argv[2:])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("run", help="run one example in the foreground")
    start.add_argument("--entry", default="main.py")
    start.add_argument("demo", type=Path, help="example path, such as quickstart/provider")
    start.add_argument("arguments", nargs=argparse.REMAINDER)
    logs = commands.add_parser("logs", help="inspect example logs")
    logs.add_argument("--latest", action="store_true")
    logs.add_argument("--tail", type=int, default=0)
    logs.add_argument("--category")
    logs.add_argument("--follow", "-f", action="store_true")
    clean = commands.add_parser("cleanup", help="stop example processes and remove local artifacts")
    clean.add_argument("--force", "-f", action="store_true")
    clean.add_argument("--dry-run", action="store_true")
    clean.add_argument("--keep-logs", "--processes-only", dest="keep_logs", action="store_true")
    for command in (logs, clean):
        command.add_argument("--directory", type=Path, default=EXAMPLES)
        command.add_argument("--only", help="comma-separated example or group paths")
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            return run(args.demo, arguments, args.entry)
        directories = selected_directories(args.directory, args.only)
        if args.action == "cleanup":
            return cleanup(directories, args)
        if args.tail < 0:
            raise ValueError("--tail must not be negative")
        return show_logs(directories, args)
    except (OSError, ValueError, psutil.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
