# Restart Recovery

[中文](README-zh.md)

Demonstrates disk backup recovery after a process is killed during a cache write.

Only complete backups are loaded. Temporary files from interrupted writes are ignored.

Backup naming is compatible with Go:

```text
svc#<namespace>#<service>#instance.json
```

## Real Registry

From the repository root:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/restart ARGS='default demo --persist-dir $PWD/examples/cache/restart/.logs/manual/polaris/backup/restart'
```

The demo only discovers an existing service. Reuse this `--persist-dir` across runs
to inspect restart recovery; without it each managed run uses its own backup directory.
Use separate directories for different registries or contexts.

`global.api.timeout` bounds the initial remote wait. A network failure or timeout can
return a complete backup; background discovery continues until the remote recovers.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only cache/restart --latest --category cache --tail 30'
make -C examples cleanup ARGS='--only cache/restart --dry-run'
make -C examples cleanup ARGS='--only cache/restart'
```

Example logs live in `.logs/run-<timestamp>-<id>/` in this demo; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not
delete remote services.

## Verify

From the repository root, run `./integration/verify.sh --only cache/restart`, or
`./integration/verify_e2e.sh --only cache/restart` against a real registry.
Test steps and integration test artifacts are documented in
[integration/scenarios/cache/restart/test.md](../../../integration/scenarios/cache/restart/test.md).
