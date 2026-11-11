# Monitoring

[中文](README-zh.md)

The example starts a loopback HTTP echo endpoint, registers it with Polaris, discovers
it and reports three actual HTTP calls (200, 503, 200). It exports the invocation
metrics through Prometheus pull or Pushgateway push.

From the repository root:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=monitoring ARGS='--mode pull'
```

Pull prints an allocated local `/metric` URL. Default duration is 31 seconds to allow
the first 30-second aggregation. `--keep-running` keeps the listener, context, process,
and instance registered until SIGINT/SIGTERM cleanup; the default mode deregisters on exit.

Push to an explicit gateway:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=monitoring ARGS='--mode push --push-address 127.0.0.1:9091'
```

Push mode prints the number of successful Pushgateway requests as `pushes` after the
configured interval.
An empty push address list discovers `Polaris/polaris.pushgateway`.
This example reports with `async_update_service_call_result`. No business request
interception is automatic.
See [observability](../../docs/guides/observability.md).

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only monitoring --latest --tail 30'
make -C examples cleanup ARGS='--only monitoring --dry-run'
make -C examples cleanup ARGS='--only monitoring'
```

Example logs live in this demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only monitoring`, or
`./integration/verify_e2e.sh --only monitoring` against a real registry. Test steps
and integration test artifacts are documented in
[integration/scenarios/monitoring/test.md](../../integration/scenarios/monitoring/test.md).
