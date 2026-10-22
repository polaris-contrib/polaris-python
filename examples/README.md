# Examples

[A2A metadata](a2a/README.md) uses ordinary Provider/Consumer APIs.
[Monitoring](monitoring/README.md) verifies real HTTP calls and Prometheus pull/push.
Both one-shot real-service examples explicitly deregister and destroy their context on exit.

[中文](README-zh.md)

The examples use public `polaris` APIs and cover these existing SDK capabilities:

- [quickstart](quickstart/README.md): synchronous provider registration, HTTP discovery and calls.
- [circuitbreaker](circuitbreaker/README.md): local instance failures, routing and half-open recovery.
- [sdkconfig/file](sdkconfig/file/README.md) and [sdkconfig/code](sdkconfig/code/README.md): YAML and code startup.
- [cache/expiry](cache/expiry/README.md): idle eviction, stream closure and reload.
- [cache/restart](cache/restart/README.md): interrupted writes and offline process restart.
- [loadbalancer/random](loadbalancer/random/README.md): asynchronous and synchronous uniform-random selection.
- [loadbalancer/wr](loadbalancer/wr/README.md): asynchronous and synchronous weighted-random selection.
- [servicerouter](servicerouter/test.md): Java-aligned before/core/after chains and optional metadata routing.
- [multicontext](multicontext/README.md): independent registration, heartbeat, discovery and shutdown.
- [mcp](mcp/README.md): MCP registration, discovery, explicit contracts and deregistration using Provider/Consumer.
- [skill](skill/README.md): published Skill queries, ZIP downloads and persistent fallback.

Install dependencies once from the repository root:

```bash
uv sync --group dev --locked
```

Every demo directory has a Makefile, following the Go examples. `build` writes `bin`, `run` executes it, and `package` writes `.build/<directory>.tar.gz`. Pass program arguments with `ARGS`. `build-x86` is for linux/amd64.

```bash
make -C examples/quickstart/provider build
make -C examples/quickstart/provider run ARGS="--help"
make -C examples/quickstart package
```

`examples/Makefile` runs the scripts beside it. Pass their arguments in `ARGS`:

```bash
make -C examples verify ARGS="--help"
make -C examples verify ARGS="--only cache/expiry"
make -C examples verify-e2e ARGS="--only cache/restart"
make -C examples logs ARGS="--latest --tail 30"
make -C examples cleanup ARGS="--dry-run"
```

The script name also works: `make -C examples verify_e2e.sh ARGS="--help"`.

Offline verification, real-service verification, logs and cleanup are entered from
`examples/` only. The scripts locate the repository from their own path.
`POLARIS_PYTHON` selects the interpreter; otherwise they use the repository `.venv`,
then `uv --project`.

```bash
./examples/verify.sh
./examples/verify.sh --only circuitbreaker,cache
./examples/verify.sh --only cache/expiry
make -C examples/circuitbreaker/consumer run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category circuitbreaker --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
  ./examples/cleanup.sh --keep-logs --delete-services --force
```

`make run` starts `main.py` in the demo directory, so relative `--config` paths resolve there.
Each scenario keeps its checks in `test.md`.

Real Polaris verification registers temporary providers, checks discovery and calls, and
keeps the processes and registrations running by default:

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh
./examples/verify_e2e.sh --only cache/expiry
```

Stop the retained processes later while keeping logs, and optionally delete the
test-created services:

```bash
./examples/cleanup.sh --keep-logs --force
./examples/cleanup.sh --keep-logs --delete-services --force
```

Environment variables and result files are documented in [中文](README-zh.md#真实服务验证).

Provider/consumer verification runs the complete associated quickstart or circuit scenario,
retaining its results in the directory from which that verification script was selected.
Group verifiers run each child once; `sdkconfig/code` and `sdkconfig/file` verify their own
startup cases. Offline verification never requires an external registry. Quickstart,
circuitbreaker and cache restart listen on temporary local ports.

Each invocation creates its own `<demo>/.logs/verify-<timestamp>-<id>/` or
`run-<timestamp>-<id>/` directory. Console output goes to `console.log`, verification output
to `verification.log`, and the exit status to `result.json`. SDK files are under `polaris/log/`
(or per-case `cases/<entry>-NN/polaris/log/`), split into `base`, `network`, `cache`, `route`, `circuitbreaker`
and other categories, with a client ID in each filename. Multiple providers or contexts
have their own component directories. Files remain available after success and failure.
Direct `python main.py` runs keep SDK logs under the demo's `.logs/manual/polaris/log/`.
`make run` also retains console output. `python verify.py` retains its artifacts.
Every demo keeps its cache files in `polaris/backup/`, beside the run's `polaris/log/` log directory.
Direct `python main.py` runs use `.logs/manual/polaris/backup/`; managed and verification runs use
`<run>/polaris/backup/`. Multiple providers and contexts get separate component directories.
The restart demo defaults `--persist-dir` to this directory, and the multiple-context demo
defaults its backup root there. `work/` is reserved for configuration and test scaffolding.

Cleanup is scoped to the chosen directory and its demos. It previews processes and the
`.logs`/`.runtime` directories, then asks for confirmation; `--dry-run` only previews,
`--force` runs without prompting. `--keep-logs` (alias `--processes-only`) stops tracked
processes only and preserves logs; process records are removed by the demos on normal exit.
`--delete-services` (alias `--remote`) deletes only `polaris-python-e2e-*` services in
`POLARIS_E2E_NAMESPACE`.
Only processes tracked by these demo entries with a matching PID, creation time and command are
stopped. Graceful shutdown lets providers
explicitly deregister and close their SDK contexts; a forced kill cannot guarantee remote
deregistration. Explicitly assigned custom cache directories, YAML and source files are kept.

Real registry demos retain their existing CLI and `POLARIS_E2E` opt-in behavior. Set the
Polaris endpoint and access token as described in each demo. `POLARIS_TOKEN` authenticates
SDK connections, while a service token authenticates provider registration.
