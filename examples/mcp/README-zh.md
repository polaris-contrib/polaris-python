# MCP 注册与发现

[English](README.md)

通过普通 ProviderAPI / ConsumerAPI 验证 HTTP MCP Server 注册、自动心跳、
普通 Instance 发现、显式单次契约上报及退出反注册，没有 SDK 专用 MCP API。
本示例只验证注册中心链路，不启动 MCP HTTP 服务，也不执行 tools/list 或 Tool 调用。

```bash
./examples/verify.sh --only mcp
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only mcp
```

离线脚本仅替换 gRPC RPC 边界，实例缓存、路由、负载均衡、自动心跳和销毁使用真实 SDK。
真实验证创建临时服务，发现已注册实例、读取契约并检查退出后反注册。

手动指定自己的 MCP 地址：

```bash
POLARIS_E2E=1 POLARIS_SERVICE_TOKEN=<service-token> \
make -C examples/mcp run ARGS="--server <host>:8091 --service search-mcp --port 8000"
```

注册 IP 默认通过 `get_local_host(--server 地址)` 获取；只有应用有独立可达地址时才显式传 `--host`。
`--protocol` 支持 `mcp-streamable-http`、`mcp-sse`；`--path` 默认分别为 `/mcp`、`/sse`。
`--version` 为 Server 版本，`--protocol-version` 为协议版本，`--ttl` 为心跳秒数。
兼容检查、能力组装、URL 拼装和退出反注册都在示例层；SDK 发现仍使用普通路由。
默认不兼容只告警，`--strict-compatible` 拒绝明确不兼容注册；发现检查失败仍继续注册。
关闭前显式反注册并停止心跳，最后销毁自己的 context；销毁本身不会隐式反注册。
详细判定和产物见 [test.md](test.md)，公开接口说明见 [AI registry](../../docs/ai-registry.md)。
