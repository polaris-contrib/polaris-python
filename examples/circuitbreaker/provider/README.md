# Switchable Provider

[中文](README-zh.md)

From the repository root, opt in with `POLARIS_E2E=1` and run two copies on separate ports:

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18081 --status 200
uv run --locked python examples/circuitbreaker/provider/main.py --port 18082 --status 500
```

`/echo` responds with the configured status. `/switch?openError=true/false` selects 500/200;
`/switch?status=404` can select another code in 200..599. Invalid switches return 400 without
changing the existing state. These controls are unauthenticated and must remain test-only.

The registered IP defaults to `get_local_host(POLARIS_SERVER_ADDRESS)`; `--host` can
override it and is independent of the SDK `bindIP`.
`--service-token` defaults to `POLARIS_SERVICE_TOKEN`. Registration uses `register_instance()`
with automatic heartbeats; `--ttl` defaults to 5 seconds. Ctrl+C / SIGTERM stops HTTP serving,
deregisters and destroys the context. `--port 0` picks a temporary port and prints it at startup.

See [the full scenario and offline verifier](../README.md).

## Verification, Logs And Cleanup

From the repository root:

```bash
./examples/verify.sh --only circuitbreaker/provider
make -C examples/circuitbreaker/provider run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category circuitbreaker --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

The verifier runs the complete associated scenario, retaining output in this directory.
Every run preserves console output, caches and SDK category logs in its own `.logs/`
directory. Use `./examples/logs.sh --follow` to follow log files. `make run` passes `ARGS` to `main.py`.
Cleanup previews and confirms by default; `--force` skips the prompt. It stops tracked
processes and removes only this directory's and its demos' `.logs/` and `.runtime/`.
See the [example overview](../../README.md) for the execution and cleanup rules.
