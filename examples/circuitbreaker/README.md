# Circuit Breaker Demo

[中文](README-zh.md)

Demonstrates the local Python SDK `composite` instance rule: consecutive failures,
error rate, half-open permits, routing, and all-down fallback.

## Real Registry

From the repository root, set these variables in each terminal, then start two
providers and one caller in separate terminals or with `&`:

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=

# Terminal 1
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18081 --status 200'
# Terminal 2
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18082 --status 500'
# Terminal 3
make -C examples run DEMO=circuitbreaker/consumer ARGS='--port 18080'
```

Runs stay in the foreground. The caller is not registered. Provider defaults its advertised address to
`get_local_host(POLARIS_SERVER_ADDRESS)`; an explicit `--host` overrides it. SDK `bindIP`
is independent of the registered instance IP.

Observe:

```bash
curl http://127.0.0.1:18080/instances
curl 'http://127.0.0.1:18082/switch?openError=false'
```

Provider controls are demo-only and unauthenticated. Do not expose them publicly.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only circuitbreaker --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker'
```

Example logs live in each child demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only circuitbreaker`, or
`./integration/verify_e2e.sh --only circuitbreaker` against a real registry.
Test coverage and integration test artifacts are documented in
[integration/scenarios/circuitbreaker/test.md](../../integration/scenarios/circuitbreaker/test.md).

See [local circuit behavior](../../docs/guides/circuitbreaker.md).
