# A2A 元数据

示例通过普通 Provider/Consumer 注册已启动的 Agent 端点，发现普通 Instance，
读取 metadata 中的 JSON card，不增加 A2AAPI、AgentCard 网络获取或 Agent 调用接口。

```bash
./examples/verify.sh --only a2a
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/a2a run ARGS="--namespace default --service demo-agent --card agent-card.json"
```

真实运行前修改 card 和 host/port/transport/path，使它们对应已启动的业务端点。
默认 TTL 为 5 秒，注册成功自动心跳；运行 6 秒后显式反注册并销毁 context。
可通过 `--duration` 修改运行时间，销毁 context 本身不会隐式反注册。

标准 metadata 为 `ai-agent-name`、`a2a.agent.card`、`a2a.transport`、`a2a.path`。
Card 校验和端点拼装属于应用层，不改变普通实例缓存与路由行为。
完整步骤和产物见 [test.md](test.md)。日志和备份保留在本目录 `.logs/`。
