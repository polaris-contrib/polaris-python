# Circuit Breaker Demo

[中文](README-zh.md)

Demonstrates the local Python SDK `composite` instance rule: consecutive failures,
error rate, half-open permits, routing, and all-down fallback.

## Offline Verification

```bash
./verify.sh
```

The verifier starts local HTTP providers and uses real SDK routing, reporting,
circuit timers, cache, and discovery. It does not need an external registry.
Scenarios cover:

- HTTP success and failure classification
- consecutive failures and healthy-peer routing
- half-open failure, recovery, and permit limits
- error-rate window and minimum request count
- all-down fallback
- sync and async flows
- heartbeat, deregistration, and resource cleanup

## Real Registry

Set `POLARIS_E2E=1`, then start two providers and one caller:

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=

./provider/run.sh --port 18081 --status 200
./provider/run.sh --port 18082 --status 500
./consumer/run.sh --port 18080
```

The caller is not registered. Provider `--host` is the advertised business address,
independent of SDK `bindIP`.

Observe:

```bash
curl http://127.0.0.1:18080/instances
curl 'http://127.0.0.1:18082/switch?openError=false'
```

Provider controls are test-only and unauthenticated. Do not expose them publicly.

## Logs And Cleanup

```bash
./logs.sh --latest --tail 30
./logs.sh --latest --category circuitbreaker --follow
./cleanup.sh --force
```

See [local circuit behavior](../../docs/circuitbreaker.md).
