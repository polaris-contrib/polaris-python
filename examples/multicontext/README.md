# Multiple Contexts

[中文](README-zh.md)

Creates two independent SDK contexts with separate:

- addresses and tokens
- client IDs and event loops
- registration and heartbeat tasks
- cache and log directories

The first context is deregistered and destroyed while the second continues heartbeats
and discovery. The second context is then cleaned up.

## Real Registry

From the repository root:

```bash
export export POLARIS_FIRST_SERVER=127.0.0.1:8091
export POLARIS_SECOND_SERVER=127.0.0.1:8091
export POLARIS_FIRST_SERVICE_TOKEN=service-token
export POLARIS_SECOND_SERVICE_TOKEN=service-token

make -C examples run DEMO=multicontext ARGS='--namespace default --service multicontext-example'
```

Both contexts in this process use their own `consumer.localCache.persistDir` and log directory.
Destroying one context does not close the other.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only multicontext --latest --tail 30'
make -C examples cleanup ARGS='--only multicontext --dry-run'
make -C examples cleanup ARGS='--only multicontext'
```

Example logs live in `.logs/run-<timestamp>-<id>/` in this demo; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not
delete remote services.

## Verify

From the repository root, run `./integration/verify.sh --only multicontext`, or
`./integration/verify_e2e.sh --only multicontext` against a real registry.
Test coverage and integration test artifacts are documented in
[integration/scenarios/multicontext/test.md](../../integration/scenarios/multicontext/test.md).
