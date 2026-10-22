# 可观测性

SDK 支持应用主动上报调用结果、内部注册 / 反注册 / 心跳 / 契约 RPC 统计，
以及 Prometheus 拉取和 Pushgateway 推送。每个 context 独立持有指标、HTTP 监听、
推送 session 与任务，销毁时关闭自己的资源，不影响其他 context。

## 配置

完整默认配置见 [polaris.yaml](config/polaris.yaml)。默认启用 prometheus pull，
监听 `0.0.0.0:28080/metric`，每 30 秒聚合一次；`/-/healthy` 返回相同指标。
`global.admin.port=-1` 禁用 pull；0 使用操作系统临时端口。
多个 context 使用不同端口，否则启动明确报错。
拉取入口的 target、port、path、protocol 会包含在 SDK ReportClient 的 stat 字段中。

```python
from polaris import Configuration, init_context_by_config

config = Configuration()
config.set_default()
config.get_global().get_admin().host = "127.0.0.1"
config.get_global().get_admin().port = 28081
options = config.get_global().get_stat_reporter().get_prometheus()
options.type = "push"
options.address = ["127.0.0.1:9091"]
options.push_interval = 10000
options.open_gzip = True
context = init_context_by_config(config)
try:
    pass
finally:
    context.destroy()
```

push 不开启指标 listener。address 支持 host:port 或 http(s)://host:port；
空列表优先通过 `global.system.monitorCluster` 发现实例，默认 Polaris/polaris.monitor；
仅当 monitorCluster 的 namespace/service 均为空时，才回退到插件自身的 namespace/service。
overrideHost 替换选中端点的 host，保留端口。pathRegexList 按顺序完整匹配调用
method，匹配后使用正则文本作为 method 标签，避免动态路径产生过多序列。

每 pushInterval 向 `/metrics/job/polaris-client/instance/<clientId>` POST 周期指标；
HTTP 非 2xx 或网络错误不推进周期，保留数据继续尝试。POST 期间的新调用进入下一周期，
失败则合并回当前周期。销毁不会执行最终推送，不承诺恢复尚未推送的内存统计。

## 调用结果

```python
from polaris.pkg.model.service import RetStatus, ServiceCallResult

def report(consumer, instance, code, delay_ms):
    consumer.update_service_call_result(ServiceCallResult(
        called_instance=instance,
        method="/search",
        ret_status=RetStatus.RetSuccess if code < 500 else RetStatus.RetFail,
        ret_code=code,
        delay=delay_ms,
        labels="env=production",
    ))
```

普通方法同步，异步使用 `await consumer.async_update_service_call_result(result)`；
`sync_update_service_call_result` 是保留的同步兼容入口。
调用方自行测量和报告，SDK 不拦截 HTTP、MCP 或 Agent 调用。
也可不传 called_instance，显式填写 namespace/service/host/port，仅产生统计。
caller_service、caller_ip、instance_type 可选，缺省 caller_ip 使用 SDK bindIP。
instance_type 支持 microservice、mcp、a2a。
约定上，MCP Tool 调用的 method 使用 Tool 名，A2A 调用的 method 使用 Agent 操作或消息路径；
Agent 标识、运行环境等附加维度由 caller_service 和 labels 承载。
已有本地 composite 仍接收属于当前缓存实例的调用结果，没有新增治理规则。

## 指标

全部为周期 Gauge，不是累计 Counter，delay 单位毫秒：

- `upstream_rq_total`：调用次数。
- `upstream_rq_success`：成功次数。
- `upstream_rq_timeout`：延迟总和，不是超时次数。
- `upstream_rq_max_timeout`：最大延迟。
- `upstream_rq_min_timeout`：最小延迟。

标签包含 callee_namespace/service/method/instance/instance_type/result_code/result，
caller_namespace/service/ip/labels 和 metric_name。缺失值为 `__NULL__`，空字符串保留。
不同结果码和结果状态分开聚合。pull 无调用的序列置零，超过两次闲置 revision 后删除。
高基数 method、labels、调用方标识由应用控制。

不包含 tracing、审计、限流、熔断规则或路由规则的统计。日志选项仍在 YAML 之外；
环境变量及优先级见 [环境变量](config/environment-variables.md)。
实际 HTTP 拉取、推送及调用示例见 [examples/monitoring](../examples/monitoring/README-zh.md)。
