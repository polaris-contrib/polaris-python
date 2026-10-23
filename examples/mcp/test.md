# MCP 验证

验证注册中心中的 MCP 实例生命周期，使用同一 SDKContext 和普通 Instance 缓存。
示例入口默认使用同步 API；异步 API 由单元测试覆盖。
默认离线脚本不访问任何外部服务；它替换 specification RPC 边界，保留真实 owner loop、
实例转换、Discover 缓存、路由、负载均衡、自动心跳、契约转换和退出流程。

## 脚本作用

从仓库根目录执行 `./examples/verify.sh --only mcp`。
统一脚本负责记录进程身份、执行 verify.py、保留控制台和验证结果。
`./examples/logs.sh --latest --tail 30` 查看日志；`./examples/cleanup.sh --dry-run`
预览本示例产物，确认范围后可通过统一 cleanup 入口删除。
清理支持 `--keep-logs` 和 `--delete-services`。
`make -C examples/mcp build/run/package/clean` 使用项目已有 Makefile 目标。
main.py 默认不连接外部服务，仅 POLARIS_E2E=1 才执行实际注册链路。

## 离线验证

1. 启动独立 context，使用 fake 8091 RPC。
2. 示例兼容检查后通过 ProviderAPI.register_instance 注册 ns/mcp，包含标准 MCP metadata，开启 TTL 自动心跳。
3. 通过同步 get_instances 读取 Discover 服务快照，检查注册的 ID 可见；
   同步 get_one_instance 选择单实例并返回普通 Instance。
4. URL 由实例 host、port、endpoint path 生成，协议版本与 Server 版本分别存储。
5. 示例组装并通过 ProviderAPI.report_service_contract 显式上报契约，ConsumerAPI.get_service_contract
   读取契约，检查 lookup、document、summarize 三项能力。
6. 验证只注册一次、只上报一次契约，Tool/Resource/Prompt 初始状态均 enabled。
7. 等待真实心跳调度并确认至少一次 heartbeat RPC。
8. 示例退出时显式反注册，确认 fake 远端无实例；SDK context 停止任务并释放缓存。

单元测试另覆盖示例严格兼容失败、非严格告警、发现检查失败继续注册、契约上报失败不回滚、
协议版本交集、IPv6 URL、参数校验，以及注册 / 契约读取 / 选址 / 反注册失败后的清理。
普通 SDK 同步 / 异步入口另有覆盖；context 销毁只停心跳，不隐式反注册。
缓存和 get_instances 保留全部实例，包括不健康、隔离、零权重和 OFFLINE 服务。
普通单实例选择走 SDK 路由，示例兼容检查和所选实例的 MCP 检查不修改原始快照，
不会让 SDK 自动过滤 Server 版本、协议版本或 MCP metadata。

## 执行产物与解读

每次运行保留本目录 `.logs/verify-<时间>-<编号>/`。
`console.log` 包含实例 ID、Instance 类型、URL、契约能力和最终 PASS/FAIL。
`result.json` 保存退出码、超时和中断状态；退出码 0 且未超时/中断才通过。
`verification.log` 保留断言与异常；`polaris/log/` 是分类日志，`polaris/backup/` 是实例 JSON 备份。
成功 JSON 包含 mcp=passed、heartbeat>=1、deregistered=true。
日志和备份在成功或失败后均保留，不自动删掉验证证据。

## 注册服务与实例

离线 namespace/service 为 ns/mcp；注册 ID 为 mcp-node，host/port 为 127.0.0.1:18080。
offline:8091 由 stub 替换，不监听真实注册中心端口。
实例端口只是用于注册和发现的示例值，验证器不启动 MCP HTTP 服务。
真实脚本使用临时服务 polaris-python-e2e-mcp-<时间> 和动态分配的端口。
直接运行 main.py 时，host/port 应对应应用已启动的 MCP HTTP 服务。

## 远端验证

这一路不替换 gRPC，也不启动 MCP HTTP 服务。注册的 host/port 只是实例地址。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only mcp
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-mcp-<年月日时分秒毫秒>`。本机端口由操作系统分配，host 固定 `127.0.0.1`，协议 `mcp-streamable-http`，协议版本 `2025-06-18`，服务版本 `v1`，TTL 1 秒。超时 30 秒。

步骤：

1. 注册普通 Instance，并上报启动契约，能力是 lookup、document、summarize。
2. 等待约 1.1 秒后，`get_all_instances` 必须看到刚返回的 instance id。超时默认 10 秒。
3. `get_one_instance` 选中的对象必须是健康、未隔离、权重大于 0，协议和版本与注册时一致，metadata 里的 MCP 服务名等于本次服务名。
4. `get_service_contract` 读到契约。服务端暂时返回 not found 时，在超时内每 0.2 秒重试。契约没带回 feature 明细时，用本地上报的三个名称填充。
5. 打印 JSON 后进程保持运行。验证器看到 JSON 且进程仍活着就结束检查，此时 `finally` 里的反注册还没执行。

通过条件：`instance_type` 为 `Instance`，`features` 正好是 lookup、document、summarize。不调用 tools/list，也不连接 MCP 客户端。离线验证里“退出后替身已空、至少一次心跳”不在这一路检查，因为进程被留下。

运行目录是 `.logs/verify-e2e-<时间>-<编号>/`。`mcp.stdout.log` 是示例 JSON，`result.json` 的 `exit_code` 为 0 才通过。停掉进程才会走到反注册；`./examples/cleanup.sh --force` 发 SIGTERM。服务对象用 `--delete-services` 删除。发现超时或契约读失败会非零退出。
