# MCP Registry

[中文](README-zh.md)

Use ordinary `ProviderAPI` / `ConsumerAPI` calls to register an HTTP MCP server,
maintain automatic heartbeats, discover its Polaris `Instance`, and explicitly
report Tool, Resource and Prompt definitions once at startup.
This example verifies registry behavior; it does not start an MCP HTTP server or call tools.

```bash
./examples/verify.sh --only mcp
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only mcp
```

The offline verifier replaces specification RPC boundaries and runs real SDK caching,
routing, heartbeat scheduling, contract conversion and shutdown. The real verifier uses
a temporary service and confirms deregistration after the example exits.

```bash
POLARIS_E2E=1 POLARIS_SERVICE_TOKEN=<service-token> \
make -C examples/mcp run ARGS="--server <host>:8091 --service search-mcp --port 8000"
```

`--host` and `--port` identify the caller's MCP server. `--protocol` accepts
`mcp-streamable-http` or `mcp-sse`; `--path` defaults to `/mcp` or `/sse`, respectively.
Version and protocol version have separate options; `--ttl` controls heartbeat seconds.
Compatibility checks, capability assembly, URL formatting and exit deregistration
belong to this example, not a dedicated SDK MCP API. `--strict-compatible` rejects
explicit incompatibility; the default only warns. SDK discovery uses ordinary routing.
Context destruction does not implicitly deregister instances.
See [test.md](test.md) for results and retained artifacts,
and [AI registry APIs](../../docs/ai-registry.md) for the full API and lifecycle behavior.
