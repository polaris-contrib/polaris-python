# Local Instance Circuit Breaking

[中文](README-zh.md)

This example follows the Go `oldInstanceCircuitBreakerCaller` discovery / HTTP / reporting workflow.
It exercises only the Python SDK's existing local default instance rule, without remote rules
or service and method circuits. Active health detection is not supported. No rule needs to be created in the console.

## Offline Verification

From the repository root:

```bash
uv sync --group dev --locked
uv run --locked python examples/circuitbreaker/verify.py
```

The verifier replaces registry RPCs, starts two HTTP providers and a caller on temporary
`127.0.0.1` ports, and uses real SDK discovery caches, routing, result reporting and timers.
It never connects to an external registry, even if `POLARIS_E2E` is set. Cache and log files
remain in this demo's `.logs/` directory until `cleanup.sh` removes them. The final JSON reports `passed_scenarios: 10`:

1. HTTP 200 and 404 are successful circuit results; request IDs reach the provider.
2. Configured consecutive failures open only the faulty instance, and routing selects its healthy peer.
3. Half-open permits follow the configured success count; one failed probe reopens the circuit.
4. The actual sleep timer enters half-open and the configured success count closes it.
5. Configured error percentage and minimum requests drive the delayed sliding-window check.
6. All-down fallback can still call an open instance.
7. Async discovery and reporting work when the default rule is disabled.
8. Enabled async calls open and recover the circuit.
9. Transport failure reports `-1`; automatic heartbeat and deregistration are verified for both providers.
10. All contexts, timers, streams, HTTP listeners and cache writers are closed.

Only this verifier shortens the windows and thresholds through public code fields. The adjacent
`consumer/polaris.yaml` retains the default 10 consecutive failures / 60-second error-rate window /
30-second sleep window / 3 half-open successes. Pytest tests cover HTTP mapping and example helpers:

```bash
uv run --locked pytest -q tests/test_circuitbreaker_examples.py -W error::RuntimeWarning
```

## With A Registry

Both `main.py` entry points skip SDK construction unless `POLARIS_E2E=1` is set.
Prepare the service `default/CircuitBreakerCallee` in your registry if required, then export
the following in each of three terminals and run the respective command from the repository root:

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
```

Terminal A, healthy provider:

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18081 --status 200
```

Terminal B, faulty provider:

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18082 --status 500
```

Terminal C, caller:

```bash
uv run --locked python examples/circuitbreaker/consumer/main.py --port 18080
```

`POLARIS_TOKEN` authenticates SDK connections; `POLARIS_SERVICE_TOKEN` is used by the provider
registration request. Use `--config /path/to/polaris.yaml` to load another SDK configuration.
Provider `--host` explicitly sets the advertised business address, defaulting to `127.0.0.1`;
use a reachable address for callers on other machines. It is independent of SDK `bindIP`.
The caller is not registered as a provider because this local rule needs no caller resource.

## Observe And Recover

```bash
for i in $(seq 1 60); do curl -s http://127.0.0.1:18080/echo; printf '\n'; done
curl -s http://127.0.0.1:18080/instances
curl -s 'http://127.0.0.1:18082/switch?openError=false'
sleep 31
for i in $(seq 1 30); do curl -s http://127.0.0.1:18080/echo; printf '\n'; done
curl -s http://127.0.0.1:18080/instances
```

Weighted random selection means the number of total calls needed is not fixed; confirm the
faulty provider reaches `open` in `/instances`. After recovery and enough selected successes,
it becomes `closed` again. `/instances` reads the unfiltered cache without consuming permits.
Each `/echo` response contains `instance_id`, `ret_code`, `circuit_state`, `delay_ms` and the
provider body. The HTTP status is the upstream status, or 502 for a transport failure.
Forwarded `X-Request-ID` is preserved; an absent ID is generated locally.

Use `openError=true` to restore HTTP 500, or `/switch?status=404` to verify a client error
does not count as an instance failure. These unauthenticated controls are **test-only**;
do not expose the provider on an untrusted network.

Stop the three processes with Ctrl+C or SIGTERM. Providers explicitly deregister and destroy
their contexts; the caller drains HTTP handlers before destroying its context. SIGKILL cannot
perform this cleanup. Provider heartbeat TTL defaults to 5 seconds.

Each business call reports exactly once using the discovered object from its own context.
There is no additional remote circuit report. All-down fallback remains enabled, so this is
not a strict call-rejection API. See [local circuit behavior](../../docs/circuitbreaker.md).

## Verification, Logs And Cleanup

From the repository root:

```bash
./examples/verify.sh --only circuitbreaker
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category circuitbreaker --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

The verifier runs this demo, retaining output in this directory.
Every run preserves console output, caches and SDK category logs in its own `.logs/`
directory. Use `./examples/logs.sh --follow` to follow log files.
Cleanup previews and confirms by default; `--force` skips the prompt. It stops tracked
processes and removes only this directory's and its demos' `.logs/` and `.runtime/`.
See the [example overview](../README.md) for the execution and cleanup rules.
