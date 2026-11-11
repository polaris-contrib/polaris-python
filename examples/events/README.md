# SDK Events

[中文](README-zh.md)

Subscribe to events emitted by capabilities actually implemented by this SDK:
instance cache add/update/delete and local instance circuit-breaker transitions.
The optional Pushgateway reports `InstanceThreadEnd` and circuit-breaker
transitions. The example does not emit
rate-limit, lossless, configuration, or watch events.

From the repository root, run against a real registry:

```bash
make -C examples run DEMO=events ARGS='--server 127.0.0.1:8091 --namespace default --service DiscoverEchoServer'
```

See [event documentation](../../docs/guides/events.md) for listener APIs and event fields.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only events --latest --tail 30'
make -C examples cleanup ARGS='--only events --dry-run'
make -C examples cleanup ARGS='--only events'
```

Example logs live in this demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only events`, or
`./integration/verify_e2e.sh --only events` against a real registry. Test steps and
integration test artifacts are documented in
[integration/scenarios/events/test.md](../../integration/scenarios/events/test.md).
