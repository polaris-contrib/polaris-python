# A2A 元数据

[English](README.md)

示例通过普通 Provider/Consumer 注册已启动的 Agent 端点，发现普通 Instance，
读取 metadata 中的 JSON card，不增加 A2AAPI、AgentCard 网络获取或 Agent 调用接口。

从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=a2a ARGS='--namespace default --card $PWD/examples/a2a/agent-card.json'
```

一张 AgentCard 注册一个实例。示例读取第一个 interface：`service` 取
`AgentCard.name`，`host` 取该 URL 中的 IP，`version` 取 `AgentCard.version`，
`protocol` 为空。实例身份端口默认 `registration_port=1`；并行保留不同版本时，用
`--registration-port` 指定不同端口。

多端口分组、混合 schema 校验和 peer 实例选择属于集成测试 Fixture 的复杂场景，
不在公开示例中重复实现。

本目录的 `agent-card.json` 是 A2A 1.0 卡片，包含两个指向 `127.0.0.1` 的接口。
真实运行前把 URL 改成 Agent 的实际 IP、端口、path 和 scheme。0.3 旧格式卡片必须
显式传入 `--a2a-version 0.3`。

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
