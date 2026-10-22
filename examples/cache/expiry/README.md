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

Run from the repository root without a Polaris server:

```bash
uv run --locked python examples/cache/expiry/verify.py
```

The verification takes about eight seconds. It checks actual periodic eviction,
stream closure, backup deletion, reload and context cleanup, replacing only the
server boundary.

To query an existing service on a real registry:

```bash
POLARIS_E2E=1 POLARIS_SERVER=127.0.0.1:8091 \
  uv run --locked python examples/cache/expiry/main.py default demo
```

`--config path/to/polaris.yaml` selects file configuration. `--expire-ms` controls
the idle threshold for this example (minimum and default: 5000 ms). The example
does not register or deregister any business instance.

## Verification, Logs And Cleanup

From the repository root:

```bash
./examples/verify.sh --only cache/expiry
make -C examples/cache/expiry run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category cache --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

The verifier runs this demo, retaining output in this directory.
Every run preserves console output, caches and SDK category logs in its own `.logs/`
directory. Use `./examples/logs.sh --follow` to follow log files. `make run` passes `ARGS` to `main.py`.
Cleanup previews and confirms by default; `--force` skips the prompt. It stops tracked
processes and removes only this directory's and its demos' `.logs/` and `.runtime/`.
See the [example overview](../../README.md) for the execution and cleanup rules.
