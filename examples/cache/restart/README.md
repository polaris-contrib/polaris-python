# Restart Recovery

[中文](README-zh.md)

Demonstrates disk backup recovery after a process is killed during a cache write.

## Verify

```bash
./verify.sh
```

The verifier:

1. Starts a temporary local gRPC server.
2. Discovers an instance and persists the response.
3. Kills the SDK subprocess during the next write.
4. Stops the server and restarts discovery from the same cache directory.
5. Checks synchronous and asynchronous fallback.
6. Restarts the server and verifies that a new remote revision replaces the backup.

Only complete backups are loaded. Temporary files from interrupted writes are ignored.

Backup naming is compatible with Go:

```text
svc#<namespace>#<service>#instance.json
```

## Real Registry

```bash
POLARIS_E2E=1 ./run.sh default demo \
  --persist-dir .logs/manual/polaris/backup/restart
```

The demo only discovers an existing service. Use separate directories for different
registries or contexts.

`global.api.timeout` bounds the initial remote wait. A network failure or timeout can
return a complete backup; background discovery continues until the remote recovers.

## Logs And Cleanup

```bash
./logs.sh --latest --category cache --tail 30
./cleanup.sh --force
```
