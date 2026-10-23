# Quickstart

Synchronous Provider / Consumer example:

1. Provider serves `/echo` and registers with automatic heartbeats.
2. Consumer discovers one instance, calls it, and reports the result.
3. Provider deregisters on Ctrl-C or SIGTERM.

Both processes read the adjacent `polaris.yaml`.

## Run

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=

./provider/run.sh --service-token service-token --port 0
./consumer/run.sh --port 18080
```

`--service-token` is used for registration, heartbeat, and deregistration.
`POLARIS_TOKEN` authenticates the SDK connection.

Call:

```bash
curl http://127.0.0.1:18080/echo
```

## Verify

```bash
./verify.sh
```

The offline verifier replaces registry RPCs and checks registration, heartbeat,
discovery, HTTP call, result reporting, deregistration, and cleanup.

## Logs And Cleanup

```bash
./logs.sh --latest --tail 30
./cleanup.sh --force
```
