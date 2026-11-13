# Service Router

[中文](README-zh.md)

This example demonstrates Polaris metadata and circuit-breaker router chains
through the public `polaris` API.

From the repository root, query an existing service:

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=servicerouter ARGS='default demo 3 --mode default --interval 0'
make -C examples run DEMO=servicerouter ARGS='default demo 3 --mode metadata --metadata env=prod --failover none --interval 0'
```

Each run selects instances asynchronously, then synchronously, and prints each
`host` and `port`. `--metadata KEY=VALUE` is repeatable; `--failover` accepts
`none`, `all` or `others` for metadata matching. This selection demo reports a
fixed successful result without invoking a downstream service. In this directory,
`make run ARGS='default demo 3 --mode default --interval 0'` uses the same runner.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only servicerouter --latest --category route --tail 30'
make -C examples cleanup ARGS='--only servicerouter --dry-run'
make -C examples cleanup ARGS='--only servicerouter'
```

Example logs live in this demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only servicerouter`, or
`./integration/verify_e2e.sh --only servicerouter` against a real registry. Test steps
and integration test artifacts are documented in
[`integration/scenarios/servicerouter/test.md`](../../integration/scenarios/servicerouter/test.md).
