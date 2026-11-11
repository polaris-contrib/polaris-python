# Quickstart

[中文](README-zh.md)

Synchronous Provider / Consumer example:

1. Provider serves `/echo` and registers with automatic heartbeats.
2. Consumer discovers one instance, calls it, and reports the result.
3. Provider deregisters on Ctrl-C or SIGTERM.

Both processes read the adjacent `polaris.yaml`.

## Run

From the repository root, set these variables in each terminal:

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=

# Terminal 1
make -C examples run DEMO=quickstart/provider ARGS='--service-token "" --port 0'
# Terminal 2
make -C examples run DEMO=quickstart/consumer ARGS='--port 18080'
```

Runs stay in the foreground; use separate terminals or `&`. `--service-token` is
required for registration, heartbeat, and deregistration; an empty string works
when service authentication is disabled. `POLARIS_TOKEN` authenticates the SDK
connection. The provider prints its allocated port.

The group Makefile selects one child demo:

```bash
make -C examples/quickstart run DEMO=provider ARGS='--service-token "" --port 0'
```

Call:

```bash
curl http://127.0.0.1:18080/echo
```

## Verify

From the repository root:

```bash
./integration/verify.sh --only quickstart
./integration/verify_e2e.sh --only quickstart
```

Test steps and integration test artifacts are documented in
[integration/scenarios/quickstart/test.md](../../integration/scenarios/quickstart/test.md).

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only quickstart --latest --tail 30'
make -C examples cleanup ARGS='--only quickstart --dry-run'
make -C examples cleanup ARGS='--only quickstart'
```

Example logs live in each child demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not
delete remote services. See the [example overview](../README.md).
