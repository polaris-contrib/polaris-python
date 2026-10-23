# Polaris Python SDK

[中文](README-zh.md)

Python client for Polaris service discovery, registration, service governance,
AI Registry resources, observability, and TLS.

The distribution is `polaris-python`; import it as `polaris`.

## Install

Requires Python 3.12+.

```bash
uv sync --group dev --locked
uv run pytest
```

The project uses a `src` layout. `uv sync` installs `src/polaris/` in editable mode,
so source changes take effect immediately.

## Configure

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
    token: ${POLARIS_TOKEN:}
```

Use `Configuration.from_file()` for YAML, `Configuration.from_env()` for environment
variables, or `Configuration.from_dict()` for code-owned mappings. Python durations
are integer milliseconds; YAML also accepts values such as `500ms`, `1s`, and `1m30s`.

See:

- [Configuration parameters](docs/config/configuration-reference.md)
- [Minimal YAML example](docs/config/polaris.yaml)
- [Environment variables and precedence](docs/config/environment-variables.md)
- [Minimal file example](examples/sdkconfig/file/polaris.yaml)

## Context

Each `SDKContext` owns its configuration snapshot, client ID, plugins, connections,
caches, tasks, and logs. Reuse one context for APIs that should share that client.

```python
from polaris import Configuration, init_context_by_config

config = Configuration()
config.set_default()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]

context = init_context_by_config(config)
try:
    ...
finally:
    context.destroy()
```

API calls after `destroy()` raise `SDKError`.

## Provider

`ProviderAPI` supports synchronous methods and `async_` counterparts.
`register_instance()` enables SDK-managed heartbeats by default.

```python
from polaris.pkg.model.server import InstanceRegisterRequest

response = provider.register_instance(InstanceRegisterRequest(
    service="demo",
    service_token="service-token",
    namespace="default",
    host="127.0.0.1",
    port=8080,
    ttl=5,
))
```

The service token authorizes register, heartbeat, and deregister. It is different
from `POLARIS_TOKEN`, which authenticates the SDK connection.

Automatic re-registration runs after two consecutive `400202` responses and
`provider.minRegisterInterval`.
Deregistration stops heartbeat tasks before the RPC. Context destruction does not
implicitly deregister instances.

## Consumer

Reuse one `ConsumerAPI` per context. Synchronous calls are `get_one_instance()`,
`get_instances()`, `get_all_instances()`, and `get_healthy_instances()`; every method
has an `async_` form.

```python
from polaris.pkg.model.service import GetOneInstanceRequest

instance = consumer.get_one_instance(GetOneInstanceRequest(
    namespace="default",
    service="demo",
))
```

After invoking the downstream service, report the result with
`update_service_call_result()` or `async_update_service_call_result()`.

Local cache behavior, idle eviction, disk retries, and restart recovery are covered by
the examples and [configuration reference](docs/config/configuration-reference.md).

## AI Registry

- MCP and A2A use ordinary `Instance` registration and discovery.
- Service contracts use `report_service_contract()` and `get_service_contract()`.
- `SkillAPI` provides read-only get/list/download operations over an independent connector.
- Skill downloads can fall back to versioned local backups after network errors.

See [AI Registry APIs](docs/ai-registry.md) and:

- [MCP example](examples/mcp/README.md)
- [A2A example](examples/a2a/README.md)
- [Skill example](examples/skill/README.md)

## Plugins

| Kind | Names |
| --- | --- |
| Server connector | `grpc` |
| Local cache | `inmemory`, `file` |
| Service router | `isolatedRouter`, `metadataRouter`, `recoverRouter` |
| Load balancer | `weightedRandom`, `random` |
| Circuit breaker | `composite` |
| Stat reporter | `prometheus` (`pushgateway` chain alias for push mode) |
| Event reporter | `pushgateway` |

Legacy names `wr` and `err_count` normalize to `weightedRandom` and `composite`.
Remote governance rules and active health detection are not enabled.

## Observability And Security

Public cloud currently uses Pushgateway as the default supported export path.
Prometheus pull remains available for self-hosted or custom scraping setups.
See [Observability](docs/observability.md).

Each context has an isolated event center for implemented instance-cache and local
circuit-breaker events, with an optional Pushgateway reporter. See
[Events](docs/events.md).

The registry and Skill connectors support independent TLS and mTLS certificates.
Invalid certificate configuration fails startup instead of falling back to plaintext.
See [TLS](docs/tls.md).

## Examples

Run all offline verifications:

```bash
./examples/verify_all.sh
```

Run or inspect a single demo:

```bash
cd examples/quickstart
./run.sh --help
./verify.sh
./logs.sh --latest --tail 30
./cleanup.sh --force
```

Start with [examples/README.md](examples/README.md). Real registry examples require
`POLARIS_E2E=1`.

## License

[BSD 3-Clause](LICENSE)
