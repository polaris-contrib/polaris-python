# MCP 注册与发现

[English](README.md)

通过普通 ProviderAPI / ConsumerAPI 演示 HTTP MCP Server 注册、自动心跳、
普通 Instance 发现、显式单次契约上报及退出反注册，没有 SDK 专用 MCP API。
本示例演示注册中心链路，不启动 MCP HTTP 服务，也不执行 tools/list 或 Tool 调用。

从仓库根目录执行，手动指定自己的 MCP 地址：

```bash
POLARIS_SERVICE_TOKEN=service-token \
  make -C examples run DEMO=mcp ARGS='--server 127.0.0.1:8091 --service search-mcp --port 8000'
```

注册 IP 默认通过 `get_local_host(--server 地址)` 获取；只有应用有独立可达地址时才显式传 `--host`。
`--protocol` 支持 `mcp-streamable-http`、`mcp-sse`；`--path` 默认分别为 `/mcp`、`/sse`。
`--version` 为 Server 版本，`--protocol-version` 为协议版本，`--ttl` 为心跳秒数。
能力组装、URL 拼装和退出反注册都使用普通 SDK API；SDK 发现仍使用普通路由。
契约上报后遇到暂时的 `400202 NotFoundResource`，公开示例会在 `--timeout` 内每
0.2 秒重试；其他契约错误立即抛出。更完整的兼容矩阵和失败路径由
`integration/fixtures/mcp.py` 覆盖。关闭前显式反注册并停止心跳，最后销毁自己的
context。
公开接口说明见 [AI registry](../../docs/guides/ai-registry.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only mcp --latest --tail 30'
make -C examples cleanup ARGS='--only mcp --dry-run'
make -C examples cleanup ARGS='--only mcp'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only mcp`；真实验证使用
`./integration/verify_e2e.sh --only mcp`。测试步骤和集成测试产物见
[integration/scenarios/mcp/test.md](../../integration/scenarios/mcp/test.md)。
