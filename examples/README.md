# Examples

[中文](README-zh.md)

The examples use the public `polaris` API.

| Demo | Purpose |
| --- | --- |
| [quickstart](quickstart/README.md) | Synchronous registration, discovery, HTTP call and result report |
| [circuitbreaker](circuitbreaker/README.md) | Local instance failure, routing and half-open recovery |
| [sdkconfig/file](sdkconfig/file/README.md) | Start from YAML |
| [sdkconfig/code](sdkconfig/code/README.md) | Configure from code |
| [cache/expiry](cache/expiry/README.md) | Idle eviction and reload |
| [cache/restart](cache/restart/README.md) | Process interruption and offline recovery |
| [loadbalancer/random](loadbalancer/random/README.md) | Uniform random selection |
| [loadbalancer/wr](loadbalancer/wr/README.md) | Weighted random selection |
| [multicontext](multicontext/README.md) | Independent contexts and lifecycle |
| [mcp](mcp/README.md) | MCP registration and discovery |
| [a2a](a2a/README.md) | A2A metadata |
| [skill](skill/README.md) | Skill query and download |
| [monitoring](monitoring/README.md) | Prometheus pull and push |
| [events](events/README.md) | Instance cache and local circuit-breaker events |

## Run And Verify

Install once from the repository root:

```bash
uv sync --group dev --locked
```

Verify all offline demos:

```bash
./examples/verify_all.sh
```

Verify selected demos:

```bash
cd examples
./verify.sh --only quickstart,loadbalancer
```

Each demo directory provides:

```text
run.sh       start main.py
verify.sh    run offline verification
logs.sh      inspect retained logs
cleanup.sh   stop tracked processes and remove local artifacts
```

Scripts work from any current directory.

## Output

Each run creates a new directory under the demo:

```text
.logs/verify-<time>-<id>/
.logs/run-<time>-<id>/
```

It retains:

- `console.log`
- `verification.log`
- `result.json`
- SDK logs under `sdk/`
- runtime data under `work/` or `.runtime/`

Inspect and clean:

```bash
./logs.sh --latest --tail 30
./logs.sh --latest --category circuitbreaker --follow
./cleanup.sh --dry-run
./cleanup.sh --force
```

Cleanup only affects tracked demo processes and demo-local artifacts.

## Real Registry

Most real-registry entry points require:

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
```

`POLARIS_TOKEN` authenticates the SDK connection. A service token is used when
registering a Provider.
