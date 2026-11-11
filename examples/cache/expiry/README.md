# Cache Idle Expiry

[中文](README-zh.md)

The SDK releases idle instance resources after
`consumer.localCache.serviceExpireTime`. Application reads renew the idle clock;
background refreshes do not. Each context scans every half of the idle threshold,
capped at one hour, and excludes configured system services.

Idle eviction stops the resource's refresh task and Discover stream. Channels
remain available for other resources. Corresponding disk backups are deleted
after earlier queued writes; a later discovery recreates the memory and disk
cache. Contexts sharing a directory also share file deletions. Use separate
`persistDir` values when contexts require independent backup lifecycles.

## Run

From the repository root, query an existing service on a real registry:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/expiry ARGS='default demo'
```

`--config path/to/polaris.yaml` selects file configuration. `--expire-ms` controls
the idle threshold for this example (minimum and default: 5000 ms). The example
does not register or deregister any business instance.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only cache/expiry --latest --tail 30'
make -C examples logs ARGS='--only cache/expiry --latest --category cache --follow'
make -C examples cleanup ARGS='--only cache/expiry --dry-run'
make -C examples cleanup ARGS='--only cache/expiry'
```

Example output, backups and SDK logs are saved in this demo's
`.logs/run-<timestamp>-<id>/`; direct `python main.py` runs use `.logs/manual/`.
`make -C examples/cache/expiry run ARGS='default demo'` uses the same runner.
Cleanup previews and confirms by default; `--force` skips the prompt. It stops only
recorded demo PIDs and removes local generated artifacts, without deleting remote services.
See the [example overview](../../README.md) for the execution and cleanup rules.

## Verify

From the repository root, run `./integration/verify.sh --only cache/expiry`, or
`./integration/verify_e2e.sh --only cache/expiry` against a real registry.
Test steps and integration test artifacts are documented in
[integration/scenarios/cache/expiry/test.md](../../../integration/scenarios/cache/expiry/test.md).
