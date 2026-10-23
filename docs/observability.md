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
`instance_type` 支持 `microservice`、`mcp` 和 `a2a`。

## 指标

指标是周期 Gauge，不是累计 Counter：

- `upstream_rq_total`
- `upstream_rq_success`
- `upstream_rq_timeout`
- `upstream_rq_max_timeout`
- `upstream_rq_min_timeout`

标签覆盖 callee、caller、method、instance type、结果码和用户 labels。
缺失值为 `__NULL__`。高基数标签由应用控制。

完整配置见 [configuration-reference.md](config/configuration-reference.md)，
运行示例见 [examples/monitoring](../examples/monitoring/README-zh.md)。
