# a2a 测试说明

## 脚本作用

本目录使用 `integration/fixtures/a2a.py` 验证复杂客户端流程，公开示例保持为最小
AgentCard 注册演示。
从仓库根目录执行 `./integration/verify.sh --only a2a`。管理脚本使用项目解释器，
创建独立运行目录并捕获全部控制台输出，不依赖当前工作目录。
`make -C examples/a2a run ARGS="--help"` 可以查看业务参数。
Fixture 的测试开关由验证器自动设置，不需要手工导出。

## 离线验证

验证器只替换 gRPC RPC 边界，实际使用 SDKContext、ProviderAPI、ConsumerAPI。
读取 1.0 格式的 `agent-card.json`，用普通 `InstanceRegisterRequest` 注册一个实例。
metadata key 集合严格为 `ai-agent-name`、`ai-agent-card`、`ai-a2a-version`；
卡片文本原样写入 `ai-agent-card`，不重新格式化。

断言覆盖：

- `service=AgentCard.name`，name 同时写入 `ai-agent-name`。
- 两个 interface 的端口、path 不同，但共享 IP `127.0.0.1`，只注册一个实例。
- 实例 host 取自卡片接口 IP，不是 SDK 路由源 IP，也不是调用参数。
- 默认实例端口为 `1`；显式传 `--registration-port 18080` 时使用 `18080`。
- `Instance.version` 取 `AgentCard.version`，`Instance.protocol` 为空。
- `ai-a2a-version=1.0`，与接口的 `protocolVersion` 独立。
- 多 IP 卡片、0.3/1.0 字段混合以及声明版本与卡片格式不匹配都在 RPC 前失败。
- 0.3 卡片按顶层 `url`、可选 `preferredTransport` 和 `additionalInterfaces` 解析；
  transport 省略时默认 `JSONRPC`，additionalInterfaces 允许省略或为 null，
  metadata `ai-a2a-version` 归一化为 `0.3`。
- 同 service 已有其他版本实例时仍按本次注册返回的 instance id 校验，不会选择或
  反注册同服务的其他合法实例。
- 同一 service、IP 和 registration_port 覆盖注册但发现流短暂返回旧卡片时，继续
  等待 instance id、卡片内容和实例字段收敛，不会因旧快照提前报错并反注册。
- SIGINT/SIGTERM 从注册开始前就纳入生命周期；启动发现和 keep-running 阶段收到
  停止信号都会走显式反注册和 context 销毁。
- 自动心跳至少执行一次，结束时显式反注册，RPC 替身不再保留实例。

默认用例等待 5.2 秒覆盖首轮心跳；其他用例不等待。没有 A2AAPI、远程 AgentCard
获取、Agent 调用或额外治理规则拉取。

## 注册服务与实例

离线 namespace 为 `ns`；service 为 `document-agent`，host 为 `127.0.0.1`，
注册端口默认 `1`。卡片包含 `127.0.0.1:8080/a2a` 和 `127.0.0.1:8081/a2a/rest`
两个接口，它们只用于 metadata 展示，不启动 Agent HTTP Server。
注册中心使用 offline:8091 的 RPC 替身，不向该地址建立真实连接。
示例注册的是普通 Instance，不向 SDK 增加服务专用模型。
服务 token 为测试值 `token`。示例没有 `--host`、`--port` 或 `--service`：
注册身份完全由卡片和 `--registration-port` 决定。

## 执行产物与解读

`console.log` 保存示例输出、验证 JSON 和错误，`result.json` 保存退出码、
timed_out、interrupted 和 action。`verification.log` 保存断言和异常 traceback。
三者保存在 `integration/.logs/a2a/verify-<时间>-<编号>/` 下。
SDK 分类日志保存到同级 `polaris/log/`，实例备份在 `polaris/backup/`，`work/` 只用于验证脚手架。
验证成功时 result.json.exit_code 为 0 且 timed_out 为 false。
日志中的预期网络警告不能替代断言，最终 PASS 与结果 JSON 才是验证依据。
可通过 `./integration/logs.sh --latest --category statReport --tail 60` 检查指标错误；
`./integration/cleanup.sh --dry-run` 预览清理，确认后使用 --force。
清理不会修改源码、card 或 YAML，不会删除管理目录外的显式备份路径。

## 远端验证

这一路不替换 gRPC，也不启动 Agent HTTP 服务。卡片里的业务地址只作为实例 metadata。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./integration/verify_e2e.sh --only a2a
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-a2a-<年月日时分秒毫秒>`。超时 90 秒。

步骤：

1. 验证器在运行目录生成 1.0 实例级 AgentCard。服务名使用上面的唯一值；两个接口
   共享本机到 Polaris 的路由源 IP，业务端口分别为 8080 和 8081。
2. `main.py` 以 `service=AgentCard.name`、共享 IP、`registration_port=1`、
   `version=AgentCard.version` 和空 protocol 注册一个普通实例。
3. 从注册中心发现实例，校验必需的三个业务 metadata key；允许注册中心追加
   `region/zone/campus/version`，Host/Port/Version/Protocol、AgentCard 原样内容
   和接口 endpoint 仍必须匹配。
4. 验证成功后 `--keep-running` 让进程持续心跳，保留实例直到 cleanup。

通过条件是最后一行 JSON 的 `transport` 为 `JSONRPC`、`a2a_version` 为 `1.0`、
`port` 为 `1`、`protocol` 为空、`instances` 为 1，`endpoint` 等于卡片第一个接口，
且 `host` 等于本机到 Polaris 的路由源 IP。验证器不发 JSON-RPC 请求，也不检查心跳次数。
离线验证里“等待 5.2 秒确认至少一次心跳、反注册后替身为空”不在这一路重复。

运行目录是 `integration/.logs/a2a/verify-e2e-<时间>-<编号>/`。`a2a.stdout.log` 是示例输出，
`result.json` 的 `exit_code` 为 0 才通过。成功后进程和实例继续运行，便于在控制台
核查；`./integration/cleanup.sh --force --delete-services` 停止进程、触发优雅反注册并
删除 `polaris-python-e2e-a2a-*` 服务。
