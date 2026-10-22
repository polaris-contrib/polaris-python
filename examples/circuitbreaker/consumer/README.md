# Circuit Caller

[中文](README-zh.md)

From the repository root, opt in with `POLARIS_E2E=1` and run:

```bash
uv run --locked python examples/circuitbreaker/consumer/main.py --port 18080
```

`/echo` discovers an instance, performs HTTP and reports exactly once.
`/instances` returns all cached instance states without spending half-open permits.
The adjacent `polaris.yaml` lists the seven local default rule parameters.
Use `--config`, `--namespace`, `--service` and `--call-timeout` to override the example settings.
Ctrl+C / SIGTERM drains HTTP handlers before destroying the owned SDK context.

See [the full scenario and offline verifier](../README.md).

## Verification, Logs And Cleanup

From the repository root:

```bash
./examples/verify.sh --only circuitbreaker/consumer
make -C examples/circuitbreaker/consumer run ARGS="--help"
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
