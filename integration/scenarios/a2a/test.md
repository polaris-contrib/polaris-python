# a2a 测试说明

## 测试拓扑

### 拉起进程

| 阶段 | 进程与生命周期 |
| --- | --- |
| 离线 fixture | 1 个验证器进程；`integration/fixtures/a2a.py` 在同一进程内执行，不启动 Agent HTTP Server。 |
| 公开示例测试 | `tests/test_example_apps.py` 在 1 个测试进程内启动真实 aiohttp Provider，绑定 `127.0.0.1:0`，测试结束关闭 listener。 |
| 远端 | 1 个验证器进程 + 1 个 `examples/a2a/main.py` 子进程；子进程同时提供 A2A HTTP 服务和 Polaris 注册/心跳，cleanup 时退出。 |

### 创建服务与实例

| 阶段 | 服务 | 实例 |
| --- | --- | --- |
| 离线基线 | `ns/document-agent` | 本次注册 1 个实例，host `127.0.0.1`，port `1`。部分用例额外放入 1 个旧版本 peer 实例验证快照收敛。 |
| 远端 | `polaris-python-integration/a2a-provider-<时间>` | 1 个普通实例，host 为到 Polaris 的路由源 IP，port `1`。 |

### 服务访问与验证

| 访问关系 | 验证内容 |
| --- | --- |
| demo → ProviderAPI | 注册普通 Instance，`version` 取 AgentCard version，metadata 只写 `ai-agent-name`、`ai-agent-card`、`ai-a2a-version`。 |
| 验证器 → ConsumerAPI | 发现实例并比对 instance ID、Host、Port、Version、metadata 和 AgentCard 内容。 |
| A2A 客户端 → `/a2a/v1` | 发送 1.0 JSON-RPC `SendMessage`，`result.message` 返回 `ROLE_AGENT` echo Message，不含 `kind`。 |
| A2A 客户端 → `/a2a/legacy` | 发送 0.3 JSON-RPC `message/send`，返回 legacy `agent` echo message。 |
| A2A 客户端 → `/rest/message:send` | 从 `/rest` 基址追加标准路由，发送 1.0 HTTP+JSON 请求，返回 `{"message": {...}}` 的 SendMessageResponse。 |
| 验证器 → AgentCard endpoint | 从 `/.well-known/agent-card.json` 读取最终卡片，确认三个接口共享同一 host/port。 |

## 脚本作用

本目录使用 `integration/fixtures/a2a.py` 验证复杂 AgentCard schema/覆盖流程；
`examples/a2a/main.py` 的真实 Provider 和三个可调用接口由
`tests/test_example_apps.py` 单独验证，保持 integration fixture 与 examples 的
所有权边界。
从仓库根目录执行 `./integration/verify.sh --only a2a`。管理脚本使用项目解释器，
创建独立运行目录并捕获全部控制台输出，不依赖当前工作目录。
`make -C examples/a2a run ARGS="--help"` 可以查看业务参数。
Fixture 的测试开关由验证器自动设置，不需要手工导出。

## 离线验证

验证器只替换 gRPC RPC 边界，实际使用 SDKContext、ProviderAPI、ConsumerAPI。
读取 1.0 格式的 `agent-card.json`，用普通 `InstanceRegisterRequest` 注册一个实例。
metadata key 集合严格为 `ai-agent-name`、`ai-agent-card`、`ai-a2a-version`；
卡片文本原样写入 `ai-agent-card`，不重新格式化。

公开示例的 endpoint 测试启动真实 aiohttp listener，分别执行三个 Message 请求；
这里验证的是同一 IP、同一业务端口下的多 path/多 transport，不启动外部 Agent 框架。
1.0 使用 `SendMessage` 和 `SendMessageResponse`；0.3 使用 `message/send`、
`kind=message` 和 `kind=text`。同时断言两个 JSON-RPC endpoint 拒绝另一版本的方法名，
并覆盖 REST 标准路由与两个兼容别名。

断言覆盖：

- `service=AgentCard.name`，name 同时写入 `ai-agent-name`。
- 三个 interface 共享 IP `127.0.0.1` 和业务端口，path/transport 不同，只注册一个实例。
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

默认 fixture 用例等待 5.2 秒覆盖首轮心跳；其他 fixture 用例不等待。公开示例测试
通过 `/.well-known/agent-card.json` 和三个 message endpoint 验证实际调用，不引入
A2A SDK 或额外治理规则拉取。

## 注册服务与实例

离线 namespace 为 `ns`；service 为 `document-agent`，host 为 `127.0.0.1`，
注册端口默认 `1`。默认卡片包含同一 `127.0.0.1:8080` 下的
`/a2a/v1`、`/a2a/legacy` 和 `/rest` 三个接口。公开示例会按实际动态绑定端口重写
这三个 URL 后注册；离线 fixture 仍只验证卡片和实例映射。
注册中心使用 offline:8091 的 RPC 替身，不向该地址建立真实连接。
示例注册的是普通 Instance，不向 SDK 增加服务专用模型。
服务 token 为测试值 `token`。离线 fixture 没有 `--host`、`--port` 或 `--service`，
注册身份完全由卡片和 `--registration-port` 决定；公开示例使用 `--host` 和 `--port`
确定业务监听地址，再据此生成卡片。

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

这一路不替换 gRPC。公开示例实际启动 Agent HTTP 服务，注册后验证器会请求三个接口。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./integration/verify_e2e.sh --only a2a
```

命名空间默认 `polaris-python-integration`。服务名是
`a2a-provider-<年月日时分秒毫秒>`。业务监听端口动态分配，实例注册端口仍为 `1`。
超时 90 秒。

步骤：

1. 验证器在运行目录生成卡片模板。服务名使用上面的唯一值，接口 IP 为本机到
   Polaris 的路由源 IP。
2. `main.py` 在 `--host <源 IP> --port 0` 上启动真实 Provider，把实际业务端口写入
   三个 interface URL，然后以 `service=AgentCard.name`、共享 IP、
   `registration_port=1`、`version=AgentCard.version` 和空 protocol 注册一个普通实例。
3. 从注册中心发现实例，校验必需的三个业务 metadata key；允许注册中心追加
   `region/zone/campus/version`，Host/Port/Version/Protocol、AgentCard 原样内容
   和接口 endpoint 仍必须匹配。
4. 分别 POST `/a2a/v1` 的 `SendMessage`、`/a2a/legacy` 的 `message/send` 和
   `/rest/message:send` 的 HTTP+JSON 请求。断言两个 1.0 绑定返回
   `SendMessageResponse.message`，内部 Message 不含 `kind`；0.3 返回直接 Message，
   包含 `kind=message` 和 `kind=text`。每个响应都要有 messageId 和预期 echo 文本，
   1.0 响应还需包含 contextId。
5. 验证成功后 `--keep-running` 让进程持续心跳和提供接口，保留实例直到 cleanup。

通过条件是最后一行 JSON 的 `transport` 为 `JSONRPC`、`a2a_version` 为 `1.0`、
`port` 为 `1`、`protocol` 为空、`instances` 为 1，`endpoint` 等于卡片第一个接口，
且 `host` 等于本机到 Polaris 的路由源 IP；`endpoints` 必须完整包含三个接口，
三个 HTTP 调用都返回 200 和预期版本标识。
离线验证里“等待 5.2 秒确认至少一次心跳、反注册后替身为空”不在这一路重复。

运行目录是 `integration/.logs/a2a/verify-e2e-<时间>-<编号>/`。`a2a.stdout.log` 是示例输出，
`result.json` 的 `exit_code` 为 0 才通过。成功后进程和实例继续运行，便于在控制台
核查；`./integration/cleanup.sh --force --delete-services` 停止进程、触发优雅反注册并
删除 `a2a-provider-*` 服务。
