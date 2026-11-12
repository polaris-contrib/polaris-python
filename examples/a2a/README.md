# A2A Metadata

[中文](README-zh.md)

This example uses ordinary Provider/Consumer APIs to register an already-running
agent endpoint, discover its Instance and decode the JSON card carried in metadata.
It does not provide an A2A SDK, fetch a remote AgentCard or invoke an agent.

Register an existing endpoint explicitly from the repository root:

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=a2a ARGS="--namespace default --card '$PWD/examples/a2a/agent-card.json'"
```

One AgentCard registers one instance. The example uses the first advertised interface:
`service` comes from `AgentCard.name`, `host` comes from that URL, `version` comes from
`AgentCard.version`, and `protocol` is empty. The instance identity port defaults to
`registration_port=1`; use `--registration-port` when separate versions need to coexist.

Multi-port grouping, mixed-schema validation and peer-instance selection are integration
fixture behavior and are not repeated in this example.

The included `agent-card.json` is an A2A 1.0 card with two interfaces on
`127.0.0.1`. Replace its URLs with the Agent's real IP and ports. Select a 0.3 legacy
card explicitly with `--a2a-version 0.3`.

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
