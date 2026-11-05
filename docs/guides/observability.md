# 可观测性

SDK 支持应用上报调用结果、内部 RPC 统计和指标导出。

**公有云当前默认支持 Pushgateway。** 公有云部署优先使用 push 模式，将指标主动
推送到 Pushgateway；Prometheus pull 更适合自建环境或由应用自行抓取的场景。

## 公有云 Pushgateway

推荐配置：

```yaml
global:
  statReporter:
    enable: true
    chain: [pushgateway]
    plugin:
      prometheus:
        type: push
        address: []
        pushInterval: 10s
        openGzip: true
```

`address: []` 时先使用 `plugin.prometheus.namespace/service` 发现监控入口。插件
namespace/service 未成对配置时，才使用 `global.system.monitorCluster`：

```yaml
global:
  statReporter:
    plugin:
      prometheus:
        namespace: Polaris
        service: polaris.pushgateway
```

寻址顺序为 `plugin.prometheus.address` →
`plugin.prometheus.namespace/service` →
`global.system.monitorCluster.namespace/service`。两处服务发现配置都不可用时，
推送会记录明确错误；显式 `address` 始终优先且不经过服务发现。

也可以直接配置地址：

```yaml
plugin:
  prometheus:
    type: push
    address: ["pushgateway.example.com:9091"]
```

关键行为：

- `chain: [pushgateway]` 是 Prometheus push 模式的别名。
- 使用该别名时，`plugin.prometheus.type` 必须为 `push`。
- Push 模式不启动指标 HTTP 监听。
- `pushInterval` 最小为 1 秒，默认 10 秒。
- 推送失败不会推进周期，当前数据保留到后续尝试。
- `pathRegexList` 按顺序完整匹配 method，用正则文本生成低基数标签。
- `openGzip` 控制 Push 请求是否 gzip。

代码配置：

```python
settings = config.get_global().get_stat_reporter().get_prometheus()
settings.type = "push"
settings.address = ["pushgateway.example.com:9091"]
settings.push_interval = 10000
settings.open_gzip = True
```

## 自建 Prometheus Pull

```yaml
global:
  admin:
    host: 0.0.0.0
    port: 28080
  statReporter:
    enable: true
    chain: [prometheus]
    plugin:
      prometheus:
        type: pull
        path: /metric
```

- `admin.port=-1` 关闭 pull。
- `admin.port=0` 使用临时端口。
- 多个 context 必须使用不同端口。
- `/-/healthy` 返回相同指标。

## 分类日志

SDK 默认按分类落盘，便于分别排查网络、缓存和指标链路：

```text
<log_dir>/
  base/polaris-<clientId>.log
  network/polaris-network-<clientId>.log
  cache/polaris-cache-<clientId>.log
  route/polaris-route-<clientId>.log
  circuitbreaker/polaris-circuitbreaker-<clientId>.log
  statReport/polaris-statReport-<clientId>.log
  event/polaris-event-<clientId>.log
  lossless/polaris-lossless-<clientId>.log
  admin/polaris-admin-<clientId>.log
```

- `base`：引擎初始化与配置摘要、后台任务、心跳/注册生命周期和 `reportClient`。
- `network`：连接、注册/反注册、心跳、Discover 流和 RPC 失败。
- `cache`：本地缓存初始化、写入、读取、删除和关闭。
- `route`：路由链初始化及逐级过滤、负载均衡选择（明细为 `DEBUG`）。
- `circuitbreaker`：熔断链初始化和状态变化。
- `statReport`：指标上报启停、周期聚合、Pull 请求和 Push 导出。
- `event`：事件中心启停、事件分发和上报。
- `lossless`：无损上下线规则拉取、健康检查与预热。
- `admin`：管理端口启用/禁用、监听、请求结果和关闭。

默认级别为 `INFO`。只有初始化、状态变化和实际数据更新记录 `INFO`；重复刷新、
无变化的缓存检查、空闲指标聚合、心跳成功、路由逐步过滤和 admin 请求明细记录在
`DEBUG`，避免长运行日志膨胀。指标 revision 摘要与 Go 一致，每 30 分钟记录一次
`INFO`；缓存文件加载、写入和删除等实际 I/O 记录 `INFO`。日志目录可通过
`LogOptions(log_dir=...)` 或 `POLARIS_LOG_PATH` 指定。

## 调用上报

```python
from polaris.pkg.model.service import RetStatus, ServiceCallResult

consumer.update_service_call_result(ServiceCallResult(
    called_instance=instance,
    method="/search",
    ret_status=RetStatus.RetSuccess,
    ret_code=200,
    delay=12,
    labels="env=production",
))
```

异步入口为 `async_update_service_call_result()`。
`instance_type` 支持 `microservice`、`mcp`、`a2a` 和 `langgraph`。

## 指标

指标是周期 Gauge，不是累计 Counter：

- `upstream_rq_total`
- `upstream_rq_success`
- `upstream_rq_timeout`
- `upstream_rq_max_timeout`
- `upstream_rq_min_timeout`

标签覆盖 callee、caller、method、instance type、结果码和用户 labels。
缺失值为 `__NULL__`。高基数标签由应用控制。

完整配置见 [configuration-reference.md](../config/configuration-reference.md)，
运行示例见 [examples/monitoring](../../examples/monitoring/README-zh.md)。
