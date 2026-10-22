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
服务 token 为测试值 token。真实业务 host 必须由应用显式提供，SDK bindIP 不是注册 IP。

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

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only a2a
```

真实验证需应用提供可访问的商业注册中心；本次开发没有实际执行此项。
服务名称使用 polaris-python-e2e-a2a-<本地时间毫秒>，默认 namespace 为 python-integration。
POLARIS_TOKEN 是 SDK 接入令牌，与注册请求的 service token 用途不同。
真实验证注册普通 A2A 元数据，检查发现结果，不调用实际 Agent。
这两个一次性示例结束时主动反注册并销毁，不保留常驻实例；服务对象与日志仍保留，
必要时按根目录清理说明处理测试服务。网络失败、索引传播超时、拉取失败、
指标缺失、metadata 不一致和反注册失败都会导致非零退出码。
