# Lossless Online/Offline

[中文](README-zh.md)

From the repository root, set these variables in each terminal. Start the consumer
first, then one or more providers in separate terminals or with `&`:

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
# Terminal 1
make -C examples run DEMO=lossless/consumer
# Terminal 2
make -C examples run DEMO=lossless/provider ARGS='--port 18081 --admin-port 28080'
# Terminal 3
make -C examples run DEMO=lossless/provider ARGS='--port 18082 --admin-port 28081'
```

Runs stay in the foreground. Both programs read their adjacent `polaris.yaml`.

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
[docs/guides/lossless.md](../../docs/guides/lossless.md) for all options.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only lossless --latest --tail 30'
make -C examples cleanup ARGS='--only lossless --dry-run'
make -C examples cleanup ARGS='--only lossless'
```

Example logs live in each child demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only lossless`, or
`./integration/verify_e2e.sh --only lossless` against a real registry. Test steps and
integration test artifacts are documented in
[integration/scenarios/lossless/test.md](../../integration/scenarios/lossless/test.md).
