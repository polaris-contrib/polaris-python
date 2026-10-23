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

## 如何验证

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
7. 启用 `global.eventReporter` 和 pushgateway 插件，事件批量 POST 到本地
   `/polaris/client/events`；最终断言远端收到相同 6 个事件序列。
8. 最终断言完整序列只有这 6 个事件，没有限流、无损、配置或 watch 事件。
9. 销毁 context 后检查事件监听器清空，owner loop 和写线程停止。

默认日志监听器把事件写入本 context 的 `event` 分类文件；业务监听器只保存事件名，
不会改变 SDK 行为。多个 context 的事件中心相互隔离，一个 context 的监听器不会收到
另一个 context 的事件。

## 执行产物与解读

每次运行保存 `.logs/verify-<时间>-<编号>/console.log`、result.json 和 verification.log。
console.log 输出 `events=passed` 和 6 个事件名；result.json 的 exit_code 为 0 才通过。
polaris/log/event/ 保存本地事件日志；Pushgateway 上报失败时才会出现 warning。
polaris/log/event/ 保存事件日志，polaris/backup/ 保存实例备份，运行结束不主动删除。

## 注册服务与实例

离线验证使用 ns/svc 和 event-node 实例，不连接外部服务。真实入口需要
`POLARIS_E2E=1`，默认服务为 default/DiscoverEchoServer；若注册中心要求鉴权，设置
`POLARIS_TOKEN`。真实入口只验证首次发现事件的订阅链路，不伪造服务端删除或熔断错误。

监控端口使用操作系统临时端口，避免多个示例同时运行时冲突。事件示例不注册业务实例，
也不调用外部 Agent 或 MCP 客户端。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
POLARIS_E2E=1 ./examples/verify_e2e.sh --only events
```

真实环境需要 default/DiscoverEchoServer 已有可发现实例。若要观察更新和删除事件，
需要在服务端修改或删除该服务实例。熔断事件需要业务持续上报 500-599 或 -1 调用结果。
