# MCP Registry

[中文](README-zh.md)

Use ordinary `ProviderAPI` / `ConsumerAPI` calls to register an HTTP MCP server,
maintain automatic heartbeats, discover its Polaris `Instance`, and explicitly
report Tool, Resource and Prompt definitions once at startup.
This example demonstrates registry behavior; it does not start an MCP HTTP server or call tools.

From the repository root, supply your existing MCP endpoint:

```bash
POLARIS_SERVICE_TOKEN=service-token \
  make -C examples run DEMO=mcp ARGS='--server 127.0.0.1:8091 --service search-mcp --port 8000'
```

`--host` and `--port` identify the caller's MCP server. `--protocol` accepts
`mcp-streamable-http` or `mcp-sse`; `--path` defaults to `/mcp` or `/sse`, respectively.
Version and protocol version have separate options; `--ttl` controls heartbeat seconds.
Capability assembly, URL formatting and exit deregistration use ordinary SDK APIs,
not a dedicated MCP API. SDK discovery uses ordinary routing. Compatibility matrices,
retry boundaries and failure paths are covered by the integration fixture.
Context destruction does not implicitly deregister instances.
See [AI registry APIs](../../docs/guides/ai-registry.md) for the full API and lifecycle behavior.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only mcp --latest --tail 30'
make -C examples cleanup ARGS='--only mcp --dry-run'
make -C examples cleanup ARGS='--only mcp'
```

Example logs live in this demo's `.logs/run-<timestamp>-<id>/`; direct
`python main.py` runs use `.logs/manual/`. Cleanup confirms by default and only
stops recorded demo PIDs and removes local generated artifacts. It does not delete
remote services.

## Verify

From the repository root, run `./integration/verify.sh --only mcp`, or
`./integration/verify_e2e.sh --only mcp` against a real registry. Test steps and
integration test artifacts are documented in
[integration/scenarios/mcp/test.md](../../integration/scenarios/mcp/test.md).
