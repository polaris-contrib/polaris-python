# monitoring 测试说明

## 测试拓扑

### 拉起进程

| 阶段 | 进程与生命周期 |
| --- | --- |
| 离线 | 1 个验证器进程；pull、push 两次 demo 顺序在进程内运行，本机 echo listener 和 Pushgateway 接收器也在进程内。 |
| 远端 | 1 个验证器进程 + 1 个 `monitoring/main.py` 子进程；成功后子进程保持运行。 |

### 创建服务与实例

| 阶段 | 服务 | 实例 |
| --- | --- | --- |
| 离线 | `ns/echo` | 每个模式启动并注册 1 个 echo 实例，`127.0.0.1:<动态端口>`，TTL 5 秒。 |
| 远端 | `polaris-python-integration/monitoring-provider-<时间>` | 1 个 echo 实例，host 为路由源 IP，动态端口，TTL 5 秒。 |

### 服务访问与验证

| 访问关系 | 验证内容 |
| --- | --- |
| demo Consumer → demo Provider | 通过 Discover 找到自身实例，真实请求 `/echo` 三次，状态依次 200、503、200。 |
| demo → 调用结果仓库 | 每次 HTTP 调用后上报 ret_code、成功/失败、延迟和 `callee_method=/echo`。 |
| 验证器 → Prometheus pull | 请求真实 `/metric`，检查 `/echo` 标签和 3 次调用、2 次成功聚合。 |
| SDK stat reporter → Pushgateway | POST `/metrics/job/polaris-client/instance/<clientId>`，验证 payload。 |
| 停止信号 → demo 生命周期 | 注册、发现、调用和聚合等待期间收到停止信号都进入反注册、context 销毁和 listener 清理。 |

## 脚本作用

本目录通过 `integration/fixtures/monitoring.py` 验证完整客户端流程，公开示例只保留
最小 Pull/Push 演示。
从仓库根目录执行 `./integration/verify.sh --only monitoring`。管理脚本使用项目解释器，
创建独立运行目录并捕获全部控制台输出，不依赖当前工作目录。
`make -C examples/monitoring run ARGS="--help"` 可以查看业务参数。
Fixture 的测试开关由验证器自动设置，不需要手工导出。

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
服务 token 为测试值 token。真实入口默认把 `get_local_host(POLARIS_SERVER_ADDRESS)`
作为注册 IP，也可用 `--host` 显式覆盖；SDK bindIP 不是注册 IP。

## 执行产物与解读

`console.log` 保存示例输出、验证 JSON 和错误，`result.json` 保存退出码、
timed_out、interrupted 和 action。`verification.log` 保存断言和异常 traceback。
三者保存在 `integration/.logs/monitoring/verify-<时间>-<编号>/` 下。
SDK 分类日志保存到同级 polaris/log/，实例备份在 polaris/backup/，work/ 只用于验证脚手架。
验证成功时 result.json.exit_code 为 0 且 timed_out 为 false。
日志中的预期网络警告不能替代断言，最终 PASS 与结果 JSON 才是验证依据。
可通过 `./integration/logs.sh --latest --category statReport --tail 60` 检查指标错误；
`./integration/cleanup.sh --dry-run` 预览清理，确认后使用 --force。
清理不会修改源码、card 或 YAML，不会删除管理目录外的显式备份路径。

## 远端验证

这一路不替换 gRPC。注册中心和监控 Pushgateway 使用同一主机，端口分别是 8091 和 9091。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./integration/verify_e2e.sh --only monitoring
```

命名空间默认 `polaris-python-integration`。服务名是
`monitoring-provider-<年月日时分秒毫秒>`。脚本把 Pushgateway 设为 `<host>:9091`，
超时 90 秒。`POLARIS_TOKEN` 只放进 SDK 连接，服务令牌放进注册请求。

步骤：

1. 使用 `get_local_host(POLARIS_SERVER_ADDRESS)` 取得本机到 Polaris 的 TCP 源 IP，
   在该 IP 的动态端口启动 HTTP echo 并注册，协议 http，TTL 5 秒。指标监听也是
   动态端口，模式固定为 push，推送间隔用示例默认的 10 秒。
2. 最多等 40 秒，直到 `get_one_instance` 能看到刚注册的实例。
3. 对这个实例依次请求 `/echo?status=200`、`503`、`200`。每次调用后 `async_update_service_call_result`：状态码小于 500 记成功，503 记失败。主调服务名是 `demo-caller`。
4. 再等待默认 31 秒，让至少一个推送周期完成。
5. 通过 `--keep-running` 保留 HTTP listener、context、进程和 instance；
   cleanup 发送 SIGTERM 后再按 instance id 反注册并销毁 context。如果 SIGTERM
   在注册、实例发现、调用上报或聚合等待期间到达，当前等待会提前结束，随后仍执行
   显式反注册和 context 销毁。

通过条件是最后一行 JSON 里 `mode` 为 `push`、`calls` 为 3、`pushes` 至少为 1，
且 `host` 等于远端验证器计算出的本机路由源 IP。远端 Pushgateway 不把这三次调用
回显到 `/metrics`，所以不读回指标正文。离线验证里的 pull `/metric` 和
0.1 秒聚合周期不在这一路执行。

运行目录是 `integration/.logs/monitoring/verify-e2e-<时间>-<编号>/`。`console.log` 里有验证器 JSON，
`monitoring.stdout.log` 是示例输出，`result.json` 的 `exit_code` 为 0 才通过。
成功后进程和实例继续运行；用 `./integration/cleanup.sh --force --delete-services`
停止进程、优雅反注册并删除 `monitoring-provider-*` 服务。注册后一直发现不到
实例或 Pushgateway 非 2xx 都会非零退出。
