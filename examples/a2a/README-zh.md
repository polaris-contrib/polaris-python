# A2A 元数据

[English](README.md)

示例会启动一个真实的本地 A2A Provider，根据实际绑定的 host 和 port 生成实例级
AgentCard，通过普通 Provider/Consumer 注册并发现一个 Polaris Instance，再校验
实例和卡片内容。Provider 提供三个可调用接口：

| 接口 | 路径 | 消息绑定 |
| --- | --- | --- |
| A2A JSON-RPC 1.0 | `/a2a/v1` | `SendMessage` |
| A2A JSON-RPC 0.3 | `/a2a/legacy` | `message/send` |
| A2A HTTP+JSON 1.0 | `/rest`（基址） | POST `/rest/message:send` |

三个接口共享同一个 IP 和业务端口，用于验证多 transport 仍保留在一张 AgentCard
中，并且只注册一个 Polaris 实例。AgentCard 也可从
`/.well-known/agent-card.json` 读取。

从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=a2a ARGS="--namespace default --duration 60"
```

进程监听 `--host` 和 `--port`（默认 `127.0.0.1:0`），把三个标准接口改写成实际
绑定地址，并打印可调用 endpoint。一张 AgentCard 注册一个实例：`service` 取
`AgentCard.name`，`host` 取接口中的 IP，`version` 取 `AgentCard.version`，
`protocol` 为空。实例身份端口默认 `registration_port=1`；并行保留不同版本时，用
`--registration-port` 指定不同端口。

调用 JSON-RPC 1.0：

```bash
curl -sS http://127.0.0.1:<业务端口>/a2a/v1 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"request-1","role":"ROLE_USER","parts":[{"text":"hello"}]}}}'
```

JSON-RPC 0.3 使用 `/a2a/legacy`、`message/send` 和旧版 text part：

```json
{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"kind":"message","messageId":"request-1","role":"user","parts":[{"kind":"text","text":"hello"}]}}}
```

HTTP+JSON 1.0 在卡片中公布 `/rest` 基址，实际向 `/rest/message:send` 提交消息：

```bash
curl -sS http://127.0.0.1:<业务端口>/rest/message:send \
  -H 'Content-Type: application/json' \
  -d '{"message":{"messageId":"request-1","role":"ROLE_USER","parts":[{"text":"hello"}]}}'
```

两个 1.0 绑定都返回 `SendMessageResponse`，内容为 `{"message": {...}}`，分别放在
JSON-RPC `result` 和 REST 响应体中；内部 1.0 Message 不含 `kind` 字段。
0.3 直接返回带 `kind=message` 的 Message，text part 使用 `kind=text`。
`/rest` 和 `/rest/v1/message:send` 继续保留为兼容别名。

给 `--no-serve` 可以保留“注册外部已运行 Agent”的用法；该模式不会绑定或提供这三个
接口，卡片按原文件内容注册。

多端口分组、混合 schema 校验和 peer 实例选择属于集成测试 Fixture 的复杂场景，
不在公开示例中重复实现。

本目录的 `agent-card.json` 是 A2A 1.0 卡片，包含三个指向 `127.0.0.1:8080`
的接口。`--serve` 会用实际绑定的 host 和业务端口覆盖 URL；0.3 card schema
通过 `--a2a-version 0.3` 选择。

应用写入的 metadata 必须包含 `ai-agent-name`、`ai-agent-card` 和
`ai-a2a-version`。发现结果中还可能包含注册中心补充的 `region`、`zone`、`campus`
和 `version`。调用方从卡片接口读取 endpoint，不能用
`instance.host:instance.port` 拼装地址。
默认 TTL 为 5 秒，注册成功自动心跳；运行 6 秒后显式反注册并销毁 context。
可通过 `--duration` 修改运行时间；`--keep-running` 会等待 SIGINT/SIGTERM，
在 cleanup 前保留进程和注册实例。销毁 context 本身不会隐式反注册。

Card 校验和 endpoint 解析属于应用层，不改变普通实例缓存与路由行为。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only a2a --latest --tail 30'
make -C examples cleanup ARGS='--only a2a --dry-run'
make -C examples cleanup ARGS='--only a2a'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only a2a`；真实验证使用
`./integration/verify_e2e.sh --only a2a`。测试步骤和集成测试产物见
[integration/scenarios/a2a/test.md](../../integration/scenarios/a2a/test.md)。
