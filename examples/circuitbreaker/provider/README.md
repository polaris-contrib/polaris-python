# Switchable Provider

[中文](README-zh.md)

From the repository root, set these variables in each terminal and run two copies
on separate ports:

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18081 --status 200'
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18082 --status 500'
```

Runs stay in the foreground; use separate terminals or `&`.

`/echo` responds with the configured status. `/switch?openError=true/false` selects 500/200;
`/switch?status=404` can select another code in 200..599. Invalid switches return 400 without
changing the existing state. These controls are unauthenticated and are intended only for
local demonstration.

The registered IP defaults to `get_local_host(POLARIS_SERVER_ADDRESS)`; `--host` can
override it and is independent of the SDK `bindIP`.
`--service-token` defaults to `POLARIS_SERVICE_TOKEN`. Registration uses `register_instance()`
with automatic heartbeats; `--ttl` defaults to 5 seconds. Ctrl+C / SIGTERM stops HTTP serving,
deregisters and destroys the context. `--port 0` picks a temporary port and prints it at startup.

See [the full scenario](../README.md).

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only circuitbreaker/provider --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker/provider --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker/provider --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker/provider'
```

Example output and SDK logs live in this demo's `.logs/run-<timestamp>-<id>/`;
direct `python main.py` runs use `.logs/manual/`. `make run ARGS='...'` in this
directory uses the same runner. Cleanup confirms by default; `--force` skips the
prompt. It stops only recorded demo PIDs and removes local generated artifacts,
without deleting remote services.
See the [example overview](../../README.md) for the execution and cleanup rules.

## Verify

From the repository root, run `./integration/verify.sh --only circuitbreaker/provider`,
or `./integration/verify_e2e.sh --only circuitbreaker/provider` against a real registry.
These run the associated scenario; test steps and integration test artifacts are documented in
[integration/scenarios/circuitbreaker/provider/test.md](../../../integration/scenarios/circuitbreaker/provider/test.md).
