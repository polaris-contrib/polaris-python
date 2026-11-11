# Examples

[中文](README-zh.md)

The examples demonstrate the public `polaris` API. They contain runnable
applications, configuration, expected behavior, and scripts to run and clean up
manual demos. Verification and test-owned resources live in
[`../integration/`](../integration/README.md).

Each application stays focused on one public capability. Stubs, fault injection,
multi-step assertions and test-specific fixture applications belong to
`integration/`; examples do not import integration code and do not require test-only
environment flags.

| Demo | Purpose |
| --- | --- |
| [quickstart](quickstart/README.md) | Synchronous registration, discovery, HTTP call, and result reporting |
| [lossless](lossless/README.md) | Lossless registration, warmup, and deregistration |
| [circuitbreaker](circuitbreaker/README.md) | Local instance failure, routing, and half-open recovery |
| [sdkconfig/file](sdkconfig/file/README.md) | Start from YAML |
| [sdkconfig/code](sdkconfig/code/README.md) | Configure from code |
| [cache/expiry](cache/expiry/README.md) | Idle eviction and reload |
| [cache/restart](cache/restart/README.md) | Process interruption and offline recovery |
| [loadbalancer/random](loadbalancer/random/README.md) | Uniform random selection |
| [loadbalancer/wr](loadbalancer/wr/README.md) | Weighted random selection |
| [servicerouter](servicerouter/README.md) | Router chains |
| [multicontext](multicontext/README.md) | Independent contexts and lifecycle |
| [mcp](mcp/README.md) | MCP registration and discovery |
| [a2a](a2a/README.md) | A2A metadata |
| [skill](skill/README.md) | Skill query and download |
| [monitoring](monitoring/README.md) | Prometheus pull and push |
| [events](events/README.md) | Cache and circuit-breaker events |

## Install

From the repository root:

```bash
uv sync --group dev --locked
```

## Run

Run one demo from the repository root. Use separate terminals for a provider and consumer:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=quickstart/provider ARGS='--service-token "" --port 18081'
```

Each demo Makefile supports:

```text
build       create a local launcher
run         run main.py
package     package the example directory
clean       remove local build artifacts
logs        inspect this demo's logs
cleanup     stop tracked demo processes and remove local artifacts
```

Use `make -C examples run DEMO=quickstart/provider ARGS='...'` to select one
application from the examples root. A group directory accepts a relative child,
such as `make -C examples/quickstart run DEMO=provider ARGS='...'`.

## Logs And Cleanup

```bash
make -C examples logs ARGS='--only quickstart/provider --latest --tail 30'
make -C examples cleanup ARGS='--only quickstart/provider --dry-run'
make -C examples cleanup ARGS='--only quickstart/provider --force --keep-logs'
```

Each run retains console output, the exit result, SDK logs, and backups under
`examples/<demo>/.logs/run-<time>-<id>/`. Cleanup verifies recorded process identities,
allows graceful shutdown, and removes only the selected demo's local artifacts.
It asks for confirmation unless `--force` is supplied. `--keep-logs` stops processes
and removes runtime records while retaining logs and build artifacts. It never
deletes remote services or integration resources. Direct `python main.py` runs are
not tracked by these scripts and must be stopped separately.

## Integration

```bash
./integration/verify.sh --only quickstart
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 ./integration/verify_e2e.sh --only quickstart
```

Test assertions, process retention, and test cleanup belong to `integration/`.
