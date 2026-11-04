# Lossless Online/Offline

[中文](README-zh.md)

Start the consumer first, then one or more providers:

```bash
POLARIS_E2E=1 uv run --locked python examples/lossless/consumer/main.py
POLARIS_E2E=1 uv run --locked python examples/lossless/provider/main.py --port 18081 --admin-port 28080
POLARIS_E2E=1 uv run --locked python examples/lossless/provider/main.py --port 18082 --admin-port 28081
```

The provider starts `/ready` and `/echo` before it invokes `lossless_register()`. With the
default `DELAY_BY_HEALTH_CHECK` strategy, the SDK polls `http://127.0.0.1:provider_port/ready`;
only after that succeeds does it register the instance. During this period, the SDK's admin
endpoint returns `503 UNREGISTERED`:

```bash
curl http://127.0.0.1:28080/readiness
```

After registration it returns `200 REGISTERED`. The consumer enables warmup, so a newly
registered instance receives a gradually increasing share of `get_one_instance()` selections.
Its final summary prints the call count per instance ID.

For lossless offline, send SIGTERM to the provider or call the loopback-only admin endpoint:

```bash
curl -X POST http://127.0.0.1:28080/offline
```

The SDK deregisters the instance immediately so consumers can remove it from discovery.

Server-declared lossless rules take precedence over the local values in `polaris.yaml`.
`--service-token` defaults to `POLARIS_SERVICE_TOKEN`. See
[docs/lossless.md](../../docs/lossless.md) for all options.
