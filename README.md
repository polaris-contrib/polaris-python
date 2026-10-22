# Polaris Python SDK

[中文](README-zh.md)

Polaris Python SDK is a Python client for Polaris service governance. It talks to
Polaris over gRPC and uses the protocol stubs from
[`polarismesh-specification`](https://github.com/polarismesh/specification).

The distribution name is `polaris-python`. The import package is `polaris`.

MCP registration/discovery and read-only published Skill APIs are described in
[AI registry APIs](docs/ai-registry.md). MCP servers reuse the ordinary `Instance`
cache; Skill RPCs have an independent connection and persistent network-error fallback.
Ordinary A2A metadata is demonstrated in [examples/a2a](examples/a2a/README.md).
[Observability](docs/observability.md) supports invocation reporting and Prometheus
pull / Pushgateway push. Registry and Skill transports independently support [TLS](docs/tls.md).

## Requirements

- Python 3.12 or newer
- `grpcio>=1.84.0`
- `protobuf>=7.35.1,<8`
- `polarismesh-specification==1.9.0.dev4`
- `PyYAML>=6.0.2,<7`

This repository does not vendor `.proto` files or generated `*_pb2.py` modules.
Those come from `polarismesh-specification`.

## Install

From a checkout of this repository:

```bash
uv sync --group dev --locked
uv run pytest
```

This project uses a `src` layout. Run `uv sync` first to install `src/polaris/`
as an editable package in the project environment; source edits then take effect
immediately. Applications continue to use `import polaris`.

## Layout

```text
src/polaris/
├── api/                 # SDKContext, ProviderAPI, ConsumerAPI
├── pkg/
│   ├── common/          # shared plugin conventions
│   ├── config/          # Configuration, defaults, YAML and environment loading
│   ├── flow/            # engine and call flow
│   ├── model/           # requests, responses, instances, rules, and errors
│   └── version/         # SDK version
├── plugin/
│   ├── circuit_breaker/  # circuit breaking contract and implementation
│   ├── load_balancer/    # load balancing contract and implementations
│   ├── local_registry/   # in-memory and file cache registry
│   ├── server_connector/ # gRPC connector
│   └── service_router/   # service routing
└── plugin_manager.py
```

SDK defaults match Go: logs use `./polaris/log/` and backups use `./polaris/backup/`,
relative to the current working directory. Pytest runs each test in a system temporary
directory, where relative default files are retained. Demo logs remain in their own
`.logs/` directories. Test and demo runtime files are isolated from source files.
Source files live in `src/polaris/`. When run from the repository root,
the default `polaris/log/` and `polaris/backup/` paths are separate from source files.
The source package remains `polaris`, imported with `import polaris`.

Applications run from the source checkout can explicitly set
`LogOptions(log_dir="./.polaris/log")` and
`config.get_consumer().get_local_cache().persist_dir = "./.polaris/backup"`.
These are application-specific paths; SDK defaults continue to follow Go semantics.

## SDK context

A process can create more than one `SDKContext`. Each context owns a unique
client ID, a startup copy of its configuration, plugin instances and subscriptions,
connections, caches, rules, background tasks, and logging. Create the APIs from
one context when they should share that client. Destroying one context does not
close another context's resources, even when both connect to the same endpoint.

`create_provider_by_config()`, `create_consumer_by_config()`, and
`create_skill_by_config()` each create a new context. Call `context.destroy()`
when the client is no longer needed. `ConsumerAPI.destroy()` destroys the
context it holds. After `destroy()`, later API calls raise `SDKError`.

Other entry points:

- `init_context()` loads the default YAML file, or environment variables when no file is found.
- `init_context_by_file(path)` loads one YAML file.
- `init_context_by_stream(text)` loads YAML text or bytes.
- `create_*_by_file(path)` and `create_*_by_default_config_file()` build an API from those sources.

## Configuration

Timeouts set in Python are milliseconds. A YAML file may use duration strings
such as `1000ms` or `3s`. The connector protocol defaults to `grpc`, and the
built-in server address is `127.0.0.1:8091`.

See [`docs/config/polaris.yaml`](docs/config/polaris.yaml) for the complete
annotated configuration, defaults, and current implementation limitations.
See [environment variables and precedence](docs/config/environment-variables.md)
for the full variable list, alias priority, entry-point behavior, and independent logging options.
[`examples/sdkconfig/file/polaris.yaml`](examples/sdkconfig/file/polaris.yaml)
remains the minimal startup example; the reference is not auto-loaded.

Configuration structure follows the Java and Go SDKs. `discoverCluster`,
`healthCheckCluster`, and `monitorCluster` are direct children of `global.system`,
without a `serverClusters` wrapper. Code uses `system.discover_cluster`,
`system.health_check_cluster`, and `system.monitor_cluster`.
Discover and heartbeat clusters are resolved through bootstrap discovery when
configured; push metrics without an explicit address use `monitorCluster`.
`serverConnector.serverSwitchInterval` periodically rotates multiple server
addresses and rebuilds affected discovery streams.
Defaults follow the Go SDK's `pkg/config` implementation where Java and Go
differ: API retries `1`, client reporting `60s`, service refresh `2s`, connect
timeout `500ms`, message timeout `1500ms`, and circuit checks `10s`.
Active health detection is a P2 capability and is not supported.
Namespaces belong to register/discovery requests, not the root SDK configuration.
The internal Python SDK is an implementation reference, not the compatibility standard.

`Configuration.from_file()` applies `POLARIS_` environment variables on top of
the file. Pass `apply_env=False` to keep the file values. `Configuration.from_env()`
uses environment variables alone.

The Go provider configuration format is supported. With a `${POLARIS_SERVER}`
placeholder in an address, `POLARIS_SERVER` contains only the hostname or IP;
the port stays in the YAML file. `POLARIS_SERVER_ADDRESS` and
`POLARIS_SERVER_ADDRESSES` always override with complete `host:port` endpoints.
Without the placeholder, `POLARIS_SERVER` also accepts complete endpoints.
Overrides preserve other fields in the file. `${ENV}` placeholders expand unset
or empty variables to empty strings. `${ENV:default}` placeholders use the
variable when it is set to a non-empty value and use `default` when it is unset
or empty; the default may contain colons, as in
`${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}`.

For code-only setup, create `Configuration()`, call `set_default()`, and assign
the fields on its nested configuration objects. `init_context_by_config()` and
`create_*_by_config()` copy that object without reading files or automatically
applying environment variables. All file configuration fields are also
available as Python object fields; durations in Python are integer milliseconds.

Only `.yaml` files are accepted. The default lookup order is:

1. The file named by `POLARIS_CONFIG_FILE`.
2. `./polaris.yaml`.
3. `~/.config/polaris/polaris.yaml`.

Common environment variables:

| Variable | Effect |
| --- | --- |
| `POLARIS_SERVER` | Host for `${POLARIS_SERVER}:8091`; complete gRPC address otherwise |
| `POLARIS_SERVER_ADDRESSES` | Comma-separated gRPC addresses |
| `POLARIS_TOKEN` | Access token |
| `POLARIS_PROTOCOL` | Connector protocol |
| `POLARIS_TIMEOUT` | API timeout in milliseconds |
| `POLARIS_MAX_RETRY_TIMES` | API retry count |
| `POLARIS_RETRY_INTERVAL` | Retry interval in milliseconds |
| `POLARIS_CACHE_PERSIST_DIR` | Local cache directory |
| `POLARIS_SERVICE_REFRESH_INTERVAL` | Service refresh interval in milliseconds |
| `POLARIS_STAT_REPORTER_ENABLE` | Enable the stat reporter |

`POLARIS_SERVER_ADDRESS`, `POLARIS_API_TIMEOUT`, `POLARIS_API_MAX_RETRY_TIMES`,
`POLARIS_API_RETRY_INTERVAL`, and `POLARIS_LOCAL_CACHE_PERSIST_DIR` are accepted
aliases.

Logging is independent of SDK YAML. Every context has its own category files and level;
all context and API creation entry points accept keyword-only `log_options`:

```python
from polaris import Configuration, LogOptions, init_context_by_config

context = init_context_by_config(
    Configuration(), log_options=LogOptions(level="warn", log_dir="./logs/client-a")
)
try:
    print(context.get_client_id())
finally:
    context.destroy()
```

Unspecified options capture `POLARIS_LOG_LEVEL` / `POLARIS_LOG_PATH` at creation.
The default level is `info`; logs use the same categories as polaris-go under
`./polaris/log/`: `base`, `network`, `cache`, `route`, `circuitbreaker`, `stat`,
`statReport`, `detect`, `event`, `lossless`, and `auth`.
Base logs go to `base/polaris-<clientId>.log`, and network logs to
`network/polaris-network-<clientId>.log`. Category files open on first use;
available categories do not enable the corresponding SDK features.
`LogOptions.log_dir` sets the root directory. `POLARIS_LOG_PATH` accepts a directory
or a legacy base filename; directory paths without an extension or with a trailing
slash are recognized even before they exist. A legacy environment filename is
also suffixed with the client ID. An explicit `LogOptions.file_path` is used exactly
for base logs, with other categories in adjacent subdirectories using the same
filename stem. Do not set both `log_dir` and `file_path`; active contexts must not
share any category file, including across processes. Conflicts fail immediately with
`SDKError`; SDK process logs follow the same exclusive ownership rule.
The base filename and its numbered backups share ownership, so `client.log` and
an explicit `client.log.1` cannot be used by different active loggers.
Each category rotates independently at 50 MB with five backups retained for 30 days
(24 hours per day), without midnight rotation. Numbered backups retain their existing
names; their modification time records rollover age. Startup and hourly maintenance
remove expired backups and inactive UUID-named context logs with the same filename
prefix, while leaving active owners and unrelated files untouched. Stable hidden
sidecar lock files must not be deleted while applications are running.
Destruction stops maintenance, closes handlers and releases OS locks, including after
abnormal process exit. `init_log(log_dir=...)`
and `set_logger()` remain process logging
entry points outside context-bound SDK operations. `apply_env=False` does not
disable the independent logging environment variables.
`LogOptions` supports constructor arguments or direct assignment to `level`,
`log_dir`, `file_path`, `max_bytes`, `backup_count`, and `max_age_days` before creation.
Setting `max_age_days=0` disables age cleanup. Rotation options also apply to
`init_log()` / `create_log()` and have no YAML fields or environment variables. Later changes to
the options object do not reconfigure an existing context's logger.
See [logging options and retention](docs/config/environment-variables.md#日志环境变量与优先级)
for cleanup scope and filesystem limitations.

Disk backups use `consumer.localCache.persistDir` (default: `./polaris/backup`).
Each context has its own writer and queue, but contexts can intentionally share
files and deletions when configured with the same directory.
Backup names match the Go SDK:
`svc#<namespace>#<service>#<resource>.json`. Namespace and service are URL-encoded;
resource is currently `instance` only. Contents use protobuf canonical JSON and
can be inspected directly.
Idle resources expire after `consumer.localCache.serviceExpireTime` (default:
24 hours), stopping their
Discover streams and deleting backups. Application reads renew the idle clock;
background refreshes do not. Scans run every half of the threshold, capped at one
hour, excluding configured system services. Use different directories for different
registries or independent backup lifecycles. See the [idle expiry example](examples/cache/expiry/README.md).
Disk read/write retries use `persistMaxReadRetry`, `persistMaxWriteRetry` and
`persistRetryInterval`; counts exclude the initial attempt. Writes are synced
to a temporary file and atomically replace the backup. On restart, an instance
backup is loaded into memory without using its modification time, and it does
not immediately satisfy a default read. That read waits for the remote update;
network failure or timeout returns the usable backup. Background discovery continues and
replaces the snapshot after the server recovers. See the
[restart recovery example](examples/cache/restart/README.md), which verifies
forced process termination, successful offline reads, and a later remote revision.
SERVICE_NOT_FOUND (400301) removes memory, Discover and the backup rather than falling back.
Same revision / DATA_NO_CHANGE keeps the snapshot; a successful empty response replaces it.
Configuration is copied at startup; changing the original
object or `get_config()` is not a runtime hot-update mechanism.
The removed `namespace`, `global.system.logPath/logLevel`,
`global.statReporter.addresses`, and derived `global.api.bindIPValue` fields
are rejected as unknown configuration keys.

`global.api.bindIP` identifies the SDK client, not a business instance. It takes
precedence over `bindIf`, which strictly resolves an IP from the named interface
and fails startup if that interface has no IP. With both unset, startup probes
the first registry address over TCP within `connectTimeout`, reads the local IP,
and closes the probe connection. Failure logs a warning and keeps the SDK IP
empty without preventing startup. The resolved value is available through
`context.get_config().get_global().get_api().get_bind_ip()`; it is not copied
into registration requests. Always specify `InstanceRegisterRequest.host`.

## Register an instance

`ProviderAPI.register()`, `deregister()`, and `heartbeat()` are synchronous.
Their awaitable counterparts are `async_register()`, `async_deregister()`, and
`async_heartbeat()`; migrate existing `await provider.register(...)` calls to
`await provider.async_register(...)`. Synchronous RPC APIs reject calls from an
active event loop with `SDKError`; use the `async_` form there.

`register_instance()` and `async_register_instance()` also enable SDK-managed
heartbeats. The TTL defaults to 5 seconds when unspecified (`None`); an explicit
TTL must be positive integer seconds. `register()` only enables automatic
heartbeats when the request sets `auto_heartbeat=True`.

Automatic re-registration follows Java: two consecutive instance-not-found
responses (`400202`) after `provider.minRegisterInterval` (default: 30 seconds).
Other failures leave heartbeats running. Failed re-registrations back off with
jitter up to 60 seconds. Deregistration stops heartbeat and re-registration tasks
before sending the RPC, even when the RPC fails. `provider.destroy()` or
`context.destroy()` stops tasks and closes the runtime without implicitly
deregistering instances. See the [automatic-heartbeat example](examples/quickstart/README.md).

The service token authorizes register, heartbeat, and deregister. It is separate
from `POLARIS_TOKEN`, which authorizes the connection to Polaris.

## Discover an instance

Reuse one `ConsumerAPI` inside a process. It keeps the instance discovery
cache. `get_one_instance()` and `get_instances()` block and return
concrete values.
`async_get_one_instance()` and `async_get_instances()` are the awaitable forms.
Both paths use the same engine. Report a call result with
`update_service_call_result()` (synchronous) or `async_update_service_call_result()`
(awaitable) for invocation metrics and the existing local circuit breaker.
`get_instances()` returns filtered candidates, `get_all_instances()` the complete
snapshot, and `get_healthy_instances()` isolation/recovery candidates without the
middle metadata chain, including circuit-open instances by default. Their list results
expose `.instances`; candidate queries do not consume half-open permits.

## Built-in plugins

| Kind | Names |
| --- | --- |
| Server connector | `grpc` |
| Local cache | `inmemory`, `file` |
| Service router | `isolatedRouter`, `metadataRouter`, `recoverRouter` |
| Load balance | `weightedRandom`, `random` |
| Circuit breaker | `composite` (local instance error count, error rate, and half-open recovery) |

Legacy configuration names `wr` and `err_count` normalize to `weightedRandom`
and `composite` when defaults are applied. Remote governance rules are not fetched.
The `prometheus` stat reporter supports pull and push export.
See [local instance circuit breaking](docs/circuitbreaker.md) for reporting,
the default rules, half-open permits, and the all-down fallback.
Local default rule thresholds and recovery settings can be set in YAML or code;
the half-open permit count follows `successCountAfterHalfOpen`.

## Examples

See [`examples/`](examples/), including the
[multi-context lifecycle verifier](examples/multicontext/README.md).

## License

[BSD 3-Clause](LICENSE).
