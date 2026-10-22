# Cache Restart Recovery

[中文](README-zh.md)

Run from the repository root without an external Polaris server:

```bash
uv run --locked python examples/cache/restart/verify.py
```

The verifier starts a temporary loopback gRPC server and an SDK subprocess.
After the subprocess discovers a service and persists the instance response,
the verifier terminates it with SIGKILL while another snapshot is being written.
The server is then stopped. New SDK processes reuse the same `persistDir`.
Synchronous and asynchronous discovery return the last complete backup after the
initial remote wait times out, both for a fresh backup and a 120-second-old backup.
The verifier then starts the server again with a new revision and checks that
both calls return that remote revision. Temporary files are not loaded; the last
complete snapshot survives the interrupted write. All files belong to this
verifier and remain in `.logs/` for inspection; child processes stop on exit.

Backups use the Go SDK's
`svc#<namespace>#<service>#instance.json` naming and indented JSON, so the
discovered instances can be inspected directly.

The instance backup is loaded into memory without checking its modification time,
and `remote_updated` stays false. The default read keeps waiting for the remote
update. `global.api.timeout` bounds that first wait. Remote failure or timeout
returns the usable snapshot as fallback without marking it remotely updated. Background discovery continues
and replaces it after the server recovers. This is separate from
`serviceExpireTime`, which controls idle memory eviction and deletes the
corresponding backup.

`persistMaxReadRetry` and `persistMaxWriteRetry` count additional attempts after
the initial read or write. `persistRetryInterval` is the delay between failed
attempts. Lock contention, I/O failures and JSON parsing failures are retried;
missing or expired files are immediate cache misses. Deletions use the write
retry budget. Reads run on a context-owned reader, writes and deletions use its
FIFO writer. Shutdown interrupts read retry delays and drains accepted writes,
so large write retry budgets can extend shutdown time.

To populate backups from a real registry, opt in explicitly:

```bash
POLARIS_E2E=1 POLARIS_SERVER=127.0.0.1:8091 \
  uv run --locked python examples/cache/restart/main.py default demo \
  --persist-dir examples/cache/restart/.logs/manual/polaris/backup/restart
```

`--persist-dir` defaults to `.logs/manual/polaris/backup/restart`, beside the SDK log
directory. `--config path/to/polaris.yaml` selects YAML startup configuration. Re-running
with the same directory while the registry is unavailable returns the saved
instances after the initial wait. Instance loading does not enforce a file age limit.
The example only discovers an existing service; it does not register or
deregister instances. Use distinct directories for independent contexts or
registries. Process restart recovery requires an already completed backup; it
does not guarantee recovery of queued writes or survival of an operating-system
crash, power loss, disk loss or an ephemeral container filesystem.

## Verification, Logs And Cleanup

From the repository root:

```bash
./examples/verify.sh --only cache/restart
make -C examples/cache/restart run ARGS="--help"
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
