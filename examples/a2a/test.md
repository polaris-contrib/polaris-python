# a2a 测试说明

## 脚本作用

本目录通过 `main.py` 演示实际 SDK 入口，`verify.py` 验证完整客户端流程。
从仓库根目录执行 `./examples/verify.sh --only a2a`。管理脚本使用项目解释器，
创建独立运行目录并捕获全部控制台输出，不依赖当前工作目录。
`make -C examples/a2a run ARGS="--help"` 可以查看业务参数。
默认执行 main 不连接外部注册中心，只有显式设置 POLARIS_E2E=1 才运行注册流程。

## 离线验证

验证器只替换 gRPC RPC 边界，实际使用 SDKContext、ProviderAPI、ConsumerAPI。
读取 agent-card.json，使用普通 InstanceRegisterRequest 携带四个标准 metadata：
ai-agent-name、a2a.agent.card、a2a.transport、a2a.path。
检查自动心跳至少执行一次、发现得到完整 JSON card 和端点字段；
结束时显式 deregister_instance，确认远端替身不再包含实例。
TTL 为 5 秒，验证等待 5.2 秒，因此会覆盖首轮自动心跳。
没有 A2AAPI、AgentCard 网络获取、Agent 调用或额外治理规则拉取。
Card 的名称与 ai-agent-name 必须一致，transport 为 JSONRPC，path 为 /a2a。

## 注册服务与实例

离线 namespace 为 ns；service 为 demo-agent，host/port 为 127.0.0.1:8080，端口为 8080。这个端点仅为元数据展示，不启动 Agent HTTP Server。
注册中心使用 offline:8091 的 RPC 替身，不向该地址建立真实连接。
示例注册的是普通 Instance，不向 SDK 增加服务专用模型。
服务 token 为测试值 token。真实入口默认把 `get_local_host(POLARIS_SERVER_ADDRESS)`
作为注册 IP，也可用 `--host` 显式覆盖；SDK bindIP 不是注册 IP。

## 执行产物与解读

`console.log` 保存示例输出、验证 JSON 和错误，`result.json` 保存退出码、
timed_out、interrupted 和 action。`verification.log` 保存断言和异常 traceback。
三者在本目录独立的 .logs/verify-<时间>-<编号>/ 下。
SDK 分类日志保存到同级 polaris/log/，实例备份在 polaris/backup/，work/ 只用于验证脚手架。
验证成功时 result.json.exit_code 为 0 且 timed_out 为 false。
日志中的预期网络警告不能替代断言，最终 PASS 与结果 JSON 才是验证依据。
可通过 `./examples/logs.sh --latest --category statReport --tail 60` 检查指标错误；
`./examples/cleanup.sh --dry-run` 预览清理，确认后使用 --force。
清理不会修改源码、card 或 YAML，不会删除管理目录外的显式备份路径。

## 远端验证

这一路不替换 gRPC，也不启动 Agent HTTP 服务。card 里的地址只作为实例 metadata。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only a2a
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-a2a-<年月日时分秒毫秒>`。超时 90 秒。

步骤：

1. 读取本目录 `agent-card.json`，用普通 `InstanceRegisterRequest` 注册。metadata 带
   `ai-agent-name`、`a2a.agent.card`、`a2a.transport`、`a2a.path`。注册 host 默认通过
   `get_local_host(POLARIS_SERVER_ADDRESS)` 取得，端口使用 `8080`；这个端口上没有
   Agent 进程，只验证实例 metadata。
2. 从注册中心发现该服务，检查返回的 transport。
3. 示例进程退出前显式反注册并销毁 context。

通过条件是最后一行 JSON 的 `transport` 为 `JSONRPC`，`instances` 至少为 1，
且 `host` 等于本机到 Polaris 的路由源 IP。验证器不发 JSON-RPC 请求，也不检查心跳次数。
离线验证里“等待 5.2 秒确认至少一次心跳、反注册后替身为空”不在这一路重复。

运行目录是 `.logs/verify-e2e-<时间>-<编号>/`。`a2a.stdout.log` 是示例输出，`result.json` 的 `exit_code` 为 0 才通过。服务对象留在 Polaris 上，用 `./examples/cleanup.sh --delete-services` 删除。发现失败、metadata 写不进去或反注册失败都会非零退出。
