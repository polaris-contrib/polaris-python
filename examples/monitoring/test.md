# monitoring 测试说明

## 脚本作用

本目录通过 `main.py` 演示实际 SDK 入口，`verify.py` 验证完整客户端流程。
从仓库根目录执行 `./examples/verify.sh --only monitoring`。管理脚本使用项目解释器，
创建独立运行目录并捕获全部控制台输出，不依赖当前工作目录。
`make -C examples/monitoring run ARGS="--help"` 可以查看业务参数。
默认执行 main 不连接外部注册中心，只有显式设置 POLARIS_E2E=1 才运行注册流程。

## 离线验证

验证器仅替换注册中心 gRPC 边界，启动真实本地 HTTP echo 和 Pushgateway 接收器。
通过异步 Provider 注册端点，Consumer 发现后发起三次真实 HTTP 调用，
状态码依次为 200、503、200。每次主动调用 async_update_service_call_result。
Pull 使用实际 /metric 请求并检查 /echo 标签；为缩短离线测试，仅把 30 秒聚合周期替换为 0.1 秒。
Push 使用默认配置模型和 1 秒推送间隔，验证收到 POST
/metrics/job/polaris-client/instance/<clientId>，指标总次数为 3，成功次数为 2。
注册、上报、指标聚合和 context 清理都走实际 SDK；不会读取服务治理规则。
两个模式退出均显式反注册、关闭 HTTP listener、销毁 SDK，释放独立任务和 session。

## 注册服务与实例

离线 namespace 为 ns；service 为 echo，HTTP echo 使用 127.0.0.1 和操作系统动态分配的端口。
注册中心使用 offline:8091 的 RPC 替身，不向该地址建立真实连接。
指标监听与 Pushgateway 接收器也使用动态端口，避免与其他 context 冲突。
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
./examples/verify_e2e.sh --only monitoring
```

真实验证需要提供可访问的注册中心和 Pushgateway。
服务名称使用 polaris-python-e2e-monitoring-<本地时间毫秒>，默认 namespace 为 python-integration。
POLARIS_TOKEN 是 SDK 接入令牌，与注册请求的 service token 用途不同。
真实验证只使用 Push 模式。Pushgateway 地址取 Polaris 地址的主机名并把端口改为 9091，
例如 Polaris 为 `1.14.219.4:8091` 时上报到 `http://1.14.219.4:9091`。
示例完成三次真实调用后等待推送周期，并在 JSON 中输出 `pushes` 成功次数；
验证器要求 `mode=push`、`calls=3` 且 `pushes>=1`。当前远端 Pushgateway
只接受上报、不在 `/metrics` 中返回业务序列，因此不使用读回指标作为远程判据。
示例结束时主动反注册并销毁；服务对象与日志仍保留，必要时按根目录清理说明处理。
网络失败、索引传播超时、Pushgateway 返回非 2xx、metadata 不一致和反注册失败
都会导致非零退出码。
