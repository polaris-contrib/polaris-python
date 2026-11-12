# A2A Metadata

[中文](README-zh.md)

This example starts a real local A2A Provider, generates an instance-level
AgentCard from the bound host and port, registers one ordinary Polaris Instance,
then discovers and validates the same Instance and card. It provides three
callable interfaces:

| Interface | Path | Message binding |
| --- | --- | --- |
| A2A JSON-RPC 1.0 | `/a2a/v1` | `message/send` |
| A2A JSON-RPC 0.3 | `/a2a/legacy` | `message/send` |
| A2A HTTP+JSON 1.0 | `/rest` | message-send JSON body |

All three interfaces use the same IP and listening port, proving that multiple
transports remain in one AgentCard and produce one Polaris instance. The card is
also available at `/.well-known/agent-card.json`.

Start and register the generated Provider from the repository root:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=a2a ARGS="--namespace default --duration 60"
```

The process binds `--host` and `--port` (default `127.0.0.1:0`), rewrites the
three canonical interfaces to the actual address, and prints the callable
endpoints. One AgentCard registers one instance: `service` comes from
`AgentCard.name`, `host` comes from the interfaces, `version` comes from
`AgentCard.version`, and `protocol` stays empty. The instance identity port
defaults to `registration_port=1`; use `--registration-port` when separate
versions need to coexist.

Invoke the JSON-RPC 1.0 interface:

```bash
curl -sS http://127.0.0.1:<业务端口>/a2a/v1 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"ROLE_USER","parts":[{"text":"hello"}]}}}'
```

JSON-RPC 0.3 uses the same method at `/a2a/legacy`, with legacy text parts:

```json
{"role":"user","parts":[{"type":"text","text":"hello"}]}
```

HTTP+JSON 1.0 accepts the message directly at `/rest`:

```json
{"message":{"role":"ROLE_USER","parts":[{"text":"hello"}]}}
```

Use `--no-serve` to register an already-running external Agent. In that mode the
card is used as-is and the example does not bind or serve the three interfaces.

Multi-port grouping, mixed-schema validation and peer-instance selection are integration
fixture behavior and are not repeated in this example.

The included `agent-card.json` is an A2A 1.0 card with the three canonical
interfaces on `127.0.0.1:8080`. `--serve` replaces those URLs with the actual
bound host and port. Select the 0.3 card schema with `--a2a-version 0.3`.

Application metadata contains the required keys `ai-agent-name`, `ai-agent-card`, and
`ai-a2a-version`. Discovery may also include server-managed `region`, `zone`, `campus`,
and `version` keys.
Callers discover the endpoint from the card interfaces, never from
`instance.host:instance.port`. The SDK automatically heartbeats at TTL 5 seconds; the
example explicitly deregisters before destroying its context after `--duration`
(default 6 seconds). `--keep-running` waits for SIGINT/SIGTERM instead, which keeps
the process and instance registered until cleanup. Context destruction alone does not
deregister.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only a2a --latest --tail 30'
make -C examples cleanup ARGS='--only a2a --dry-run'
make -C examples cleanup ARGS='--only a2a'
```

Example logs live in this demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only a2a`, or
`./integration/verify_e2e.sh --only a2a` against a real registry. Test steps and
integration test artifacts are documented in
[integration/scenarios/a2a/test.md](../../integration/scenarios/a2a/test.md).
