# A2A Metadata

[中文](README-zh.md)

This example uses ordinary Provider/Consumer APIs to register an already-running
agent endpoint, discover its Instance and decode the JSON card carried in metadata.
It does not provide an A2A SDK, fetch a remote AgentCard or invoke an agent.

Run the offline verification:

```bash
./examples/verify.sh --only a2a
```

Register an existing endpoint explicitly:

```bash
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/a2a run ARGS="--namespace default --service demo-agent --card agent-card.json"
```

Set host, port, transport, path and card to the actual endpoint. The SDK automatically
heartbeats at TTL 5 seconds; the example explicitly deregisters before destroying its
context after `--duration` (default 6 seconds). Context destruction alone does not deregister.

Metadata uses `ai-agent-name`, `a2a.agent.card`, `a2a.transport` and `a2a.path`.
The card JSON is application data, not a new SDK request model.
Logs and backups remain in this demo's `.logs/` directory. See [test.md](test.md).
