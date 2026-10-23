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

## 远端验证

这一路不替换 gRPC。注册中心和监控 Pushgateway 使用同一主机，端口分别是 8091 和 9091。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only monitoring
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-monitoring-<年月日时分秒毫秒>`。脚本把 Pushgateway 设为 `<host>:9091`，超时 90 秒。`POLARIS_TOKEN` 只放进 SDK 连接，服务令牌放进注册请求。

步骤：

1. 在 `127.0.0.1` 的动态端口启动 HTTP echo，向注册中心注册，协议 http，TTL 5 秒。指标监听也是动态端口，模式固定为 push，推送间隔用示例默认的 10 秒。
2. 最多等 40 秒，直到 `get_one_instance` 能看到刚注册的实例。
3. 对这个实例依次请求 `/echo?status=200`、`503`、`200`。每次调用后 `async_update_service_call_result`：状态码小于 500 记成功，503 记失败。主调服务名是 `demo-caller`。
4. 再等待默认 31 秒，让至少一个推送周期完成。
5. 退出时按 instance id 反注册并销毁 context。

通过条件是最后一行 JSON 里 `mode` 为 `push`、`calls` 为 3、`pushes` 至少为 1。远端 Pushgateway 不把这三次调用回显到 `/metrics`，所以不读回指标正文。离线验证里的 pull `/metric` 和 0.1 秒聚合周期不在这一路执行。

运行目录是 `.logs/verify-e2e-<时间>-<编号>/`。`console.log` 里有验证器 JSON，`monitoring.stdout.log` 是示例输出，`result.json` 的 `exit_code` 为 0 才通过。Polaris 上的服务对象会留下，用 `./examples/cleanup.sh --delete-services` 删除 `polaris-python-e2e-` 前缀的服务。注册后一直发现不到实例、Pushgateway 非 2xx、或反注册失败，都会非零退出。
