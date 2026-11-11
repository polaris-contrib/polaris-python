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

"""Own integration run artifacts and retained process identities."""

import atexit
import json
import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psutil

INTEGRATION = Path(__file__).resolve().parent
REPO = INTEGRATION.parent
EXAMPLES = REPO / "examples"
SCENARIOS = INTEGRATION / "scenarios"
LOG_ROOT = INTEGRATION / ".logs"
RUNTIME_ROOT = INTEGRATION / ".runtime"
DEFAULT_E2E_NAMESPACE = "python-integration"

_tracked = set()


def resolve_e2e_namespace():
    """Return the isolated namespace used for real integration resources."""
    namespace = os.getenv("POLARIS_E2E_NAMESPACE", DEFAULT_E2E_NAMESPACE).strip()
    if not namespace:
        raise ValueError("POLARIS_E2E_NAMESPACE must not be empty")
    if namespace == "default":
        raise ValueError(
            "POLARIS_E2E_NAMESPACE must not be default; use python-integration "
            "or another isolated E2E namespace"
        )
    return namespace


def new_run_directory(directory, action):
    """Create a unique run directory directly below the requested artifact root."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path(directory) / f"{action}-{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    return path


def scenario_artifact_directory(demo):
    relative = Path(str(demo))
    if relative.is_absolute():
        try:
            relative = relative.relative_to(EXAMPLES)
        except ValueError:
            relative = Path(relative.name)
    return relative


def process_owner_directory(demo):
    return RUNTIME_ROOT / scenario_artifact_directory(demo)


def track_process(directory, entry):
    """Record process identity so cleanup cannot signal a reused PID."""
    directory = Path(directory).resolve()
    if directory in _tracked:
        return
    process = psutil.Process()
    records = directory / "processes"
    records.mkdir(parents=True, exist_ok=True)
    record = records / f"{process.pid}.json"
    data = {
        "pid": process.pid,
        "created": process.create_time(),
        "command": process.cmdline(),
        "entry": str(Path(entry).resolve()),
    }
    record.write_text(json.dumps(data), encoding="utf-8")
    _tracked.add(directory)
    atexit.register(record.unlink, missing_ok=True)


def record_external_process(directory, process, entry):
    """Record a retained child process for explicit cleanup."""
    directory = Path(directory).resolve()
    records = directory / "processes"
    records.mkdir(parents=True, exist_ok=True)
    record = records / f"{process.pid}.json"
    data = {
        "pid": process.pid,
        "created": process.create_time(),
        "command": process.cmdline(),
        "entry": str(Path(entry).resolve()),
    }
    record.write_text(json.dumps(data), encoding="utf-8")
    return record


class _Tee:
    def __init__(self, stream, logfile):
        self.stream = stream
        self.logfile = logfile

    def write(self, value):
        self.logfile.write(value)
        self.logfile.flush()
        return self.stream.write(value)

    def flush(self):
        self.logfile.flush()
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _scenario_name(entry):
    entry = Path(entry).resolve()
    try:
        relative = entry.relative_to(SCENARIOS)
    except ValueError:
        return entry.stem
    return relative.parent.as_posix() if relative.parent != Path(".") else relative.stem


@contextmanager
def verification_directory(entry):
    """Retain console output, SDK logs and backups below integration/.logs."""
    configured = os.getenv("POLARIS_DEMO_RUN_DIR")
    scenario = _scenario_name(entry)
    run = (
        Path(configured)
        if configured
        else new_run_directory(LOG_ROOT / scenario, "verify")
    )
    work = run / "work"
    work.mkdir(parents=True, exist_ok=True)
    owner = Path(os.getenv("POLARIS_DEMO_DIRECTORY", str(process_owner_directory(scenario))))
    previous = {
        name: os.environ.get(name)
        for name in ("POLARIS_DEMO_RUN_DIR", "POLARIS_DEMO_DIRECTORY")
    }
    os.environ["POLARIS_DEMO_RUN_DIR"] = str(run)
    os.environ["POLARIS_DEMO_DIRECTORY"] = str(owner)
    track_process(owner, entry)
    output, errors = sys.stdout, sys.stderr
    try:
        with (run / "verification.log").open("a", encoding="utf-8") as logfile:
            sys.stdout = _Tee(output, logfile)
            sys.stderr = _Tee(errors, logfile)
            try:
                yield work
            except BaseException:
                traceback.print_exc(file=logfile)
                raise
            finally:
                sys.stdout, sys.stderr = output, errors
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        print(f"Logs: {run / 'polaris' / 'log'}", file=sys.stderr)
        print(f"AI logs: {run / 'polaris' / 'log' / 'ai'}", file=sys.stderr)
        print(f"Backups: {run / 'polaris' / 'backup'}", file=sys.stderr)
