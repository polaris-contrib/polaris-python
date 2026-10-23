# 事件中心

每个 `SDKContext` 持有一个独立事件中心。事件中心只暴露当前 SDK 已实现能力的事件，
不提供限流、无损上下线、配置中心、外部 watch 或远端治理规则事件。

## 监听事件

```python
from polaris import ConsumerAPI, SDKEventName, SDKEventType
from polaris.pkg.model.service import GetInstancesRequest

context = ...
events = []
context.get_event_center().register_listener(
    lambda event: events.append(event.event_name), SDKEventType.INSTANCE)

consumer = ConsumerAPI(context)
consumer.get_instances(GetInstancesRequest(namespace="default", service="DiscoverEchoServer"))
print(events)  # first successful discovery emits OnServiceAdded
```

监听器可以是 callable，也可以是实现 `on_sdk_event(event)` 的对象。第二个参数可选：
`SDKEventType.INSTANCE` 只接收实例事件，`SDKEventType.CIRCUIT_BREAKING` 只接收本地实例
熔断事件，省略时接收全部事件。两者的 wire 值分别为 `INSTANCE` 和 `CIRCUIT_BREAKING`。
`unregister_listener(listener, event_type)` 移除一次完全相同的注册。

事件派发是同步的，监听器异常会被捕获并记录到 `event` 分类日志，不影响发现、刷新或
熔断主流程。事件中心随 context 销毁清空，不同 context 互不影响。

## 事件范围

| 事件 | 触发时机 |
| --- | --- |
| `InstanceThreadEnd` | 显式反注册成功后触发 |
| `OnServiceAdded` | 实例快照首次进入本地缓存；按 Java 语义，磁盘备份首次加载也会触发 |
| `OnServiceUpdated` | 远端成功返回新 revision 并替换实例快照 |
| `OnServiceDeleted` | 服务端返回 400301，或闲置淘汰删除实例资源；两者均按 Java 语义触发 |
| `CircuitBreakerOpen` | 本地默认实例熔断状态转换为 Open |
| `CircuitBreakerHalfOpen` | 本地默认实例熔断状态转换为 HalfOpen |
| `CircuitBreakerClose` | 本地默认实例熔断状态转换为 Close |

实例事件携带 `old_value` / `new_value` 快照对象；删除事件的新值为 `None`。熔断事件携带
实例 ID、host、port、前后状态和 `additional["isolation_object"]`。当前本地规则没有远端
规则名，因此 `rule_name` 保持空字符串，不伪造规则信息。

默认 logger 监听器会把事件写入每个 context 的 `event` 分类日志；远端上报由可选的
Pushgateway 插件完成。

## Pushgateway 上报

`global.eventReporter.enable=true` 时启用 `pushgateway` 插件。插件作为当前 context 的
事件监听器工作，事件先进入容量为 `eventQueueSize` 的内存队列；队列满时丢弃新事件并记录
warning。后台任务每 `pushInterval` 批量 POST，一次最多 `maxBatchSize` 个事件。

请求路径默认为 `/polaris/client/events`，JSON body 为 `{"batch":[...]}`。显式
`address` 优先；为空时通过 `namespace/service` 服务发现 Pushgateway 实例，
`overrideHost` 可只替换选中地址的 host。HTTP 非 2xx 或网络错误按 `maxRetries` /
`retryInterval` 重试，最终失败丢弃该批并记录 warning，不影响 SDK 主流程。context
销毁前会停止接收新事件并 flush 已接受事件。

完整字段见 [配置参数说明](config/configuration-reference.md)。默认 `global.eventReporter.enable=false`，
因此不会默认连接远端事件服务。
