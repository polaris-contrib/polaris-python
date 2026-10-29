# events 测试说明

本目录验证 context 私有事件中心、Pushgateway 事件插件和当前 SDK 已实现能力的事件序列。
离线验证只替换 gRPC RPC 边界，配置、owner loop、本地缓存、刷新任务、熔断状态机、事件派发、
HTTP 批量上报和销毁清理都使用真实实现。

## 脚本作用

从仓库根目录执行 `./examples/verify.sh --only events`。统一入口运行 verify.py 并记录
console.log、result.json 与 verification.log。`make -C examples/events run ARGS="--help"`
可以查看真实入口参数；`make -C examples/events clean` 清理本目录产物。

事件监听器通过 `SDKContext.get_event_center()` 注册，支持 callable 或实现
`on_sdk_event(event)` 的对象，也可按 `SDKEventType.INSTANCE` 或
`SDKEventType.CIRCUIT_BREAKING` 过滤。监听器抛出的异常只记录 warning，不影响发现或熔断主流程。

## 离线验证

1. fake gRPC 返回 ns/svc 的一个健康实例，首次发现触发 `OnServiceAdded`。
2. 修改 revision 后执行后台刷新任务，本地缓存触发 `OnServiceUpdated`。
3. 上报一次 500 调用结果并执行熔断检查，实例状态 Closed 到 Open，
   触发 `CircuitBreakerOpen`。
4. 等待 1s sleep window 后再次检查，Open 到 HalfOpen，触发
   `CircuitBreakerHalfOpen`。
5. 上报一次 200 成功调用并检查，HalfOpen 到 Close，触发
   `CircuitBreakerClose`。
6. 关闭 Discover 流后让服务端返回 400301，本地缓存删除资源，触发
   `OnServiceDeleted`。
7. 启用 `global.eventReporter` 和 pushgateway 插件，可上报事件批量 POST 到本地
   `/polaris/client/events`。远端只收到 `CircuitBreakerOpen`、`CircuitBreakerHalfOpen`、
   `CircuitBreakerClose`，且 `event_type` 为 `CIRCUIT_BREAKING`。缓存新增、更新和删除不上报。
8. 最终断言本地完整序列只有这 6 个事件，没有限流、无损、配置或 watch 事件。
9. 销毁 context 后检查事件监听器清空，owner loop 和写线程停止。

默认日志监听器把事件写入本 context 的 `event` 分类文件；业务监听器只保存事件名，
不会改变 SDK 行为。多个 context 的事件中心相互隔离，一个 context 的监听器不会收到
另一个 context 的事件。

## 执行产物与解读

每次运行保存 `.logs/verify-<时间>-<编号>/console.log`、result.json 和 verification.log。
console.log 输出 `events=passed` 和 6 个事件名；result.json 的 exit_code 为 0 才通过。
polaris/log/event/ 同时保存本地事件和 Pushgateway POST 结果。POST 成功是 info，失败是 warning，两行都带该事件的本地日志正文。
polaris/log/event/ 保存事件日志，polaris/backup/ 保存实例备份，运行结束不主动删除。

## 注册服务与实例

离线验证使用 ns/svc 和 event-node 实例，不连接外部服务。手工真实入口需要
`POLARIS_E2E=1`，默认服务为 default/DiscoverEchoServer；统一远端脚本会注册
`polaris-python-e2e-events-<时间>` 并显式传入。若注册中心要求鉴权，设置
`POLARIS_TOKEN`。真实入口只验证首次发现事件的订阅链路，不伪造服务端删除或熔断错误。

监控端口使用操作系统临时端口，避免多个示例同时运行时冲突。事件示例不注册业务实例，
也不调用外部 Agent 或 MCP 客户端。

## 远端验证

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
./examples/verify_e2e.sh --only events
```

验证器会先注册一个唯一命名的 quickstart Provider，等待真实注册中心返回该实例，
再运行 `events/main.py`，使用动态指标端口发现该服务。通过条件是：

- JSON 结果的 `instances` 至少为 1；
- `events` 包含首次发现产生的 `OnServiceAdded`；
- quickstart Provider 在验证期间保持运行。

远端这一路验证真实注册、发现和事件订阅链路。所有真实 E2E Context 都会启用事件
Pushgateway；`OnServiceAdded` 本身只进入本地 event 日志，不进入远端批量上报。
熔断事件上报由 `circuitbreaker` 远端场景验证。运行目录是
`.logs/verify-e2e-<时间>-<编号>/`，demo JSON 保存在 `events.stdout.log`。
