# Circuit Caller

[中文](README-zh.md)

After starting the [providers](../provider/README.md), run from the repository root:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=circuitbreaker/consumer ARGS='--port 18080'
```

The runner stays in the foreground; use another terminal for the providers.

`/echo` discovers an instance, performs HTTP and reports exactly once.
`/instances` returns all cached instance states without spending half-open permits.
The adjacent `polaris.yaml` lists the seven local default rule parameters.
Use `--config`, `--namespace`, `--service` and `--call-timeout` to override the example settings.
Ctrl+C / SIGTERM drains HTTP handlers before destroying the owned SDK context.

See [the full scenario](../README.md).

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only circuitbreaker/consumer --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker/consumer --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker/consumer --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker/consumer'
```

Example output and SDK logs live in this demo's `.logs/run-<timestamp>-<id>/`;
direct `python main.py` runs use `.logs/manual/`. `make run ARGS='...'` in this
directory uses the same runner. Cleanup confirms by default; `--force` skips the
prompt. It stops only recorded demo PIDs and removes local generated artifacts,
without deleting remote services.
See the [example overview](../../README.md) for the execution and cleanup rules.

## Verify

From the repository root, run `./integration/verify.sh --only circuitbreaker/consumer`,
or `./integration/verify_e2e.sh --only circuitbreaker/consumer` against a real registry.
These run the associated scenario; test steps and integration test artifacts are documented in
[integration/scenarios/circuitbreaker/consumer/test.md](../../../integration/scenarios/circuitbreaker/consumer/test.md).
