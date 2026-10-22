# 本地实例熔断

当前仅支持 `consumer.circuitBreaker.chain: [composite]` 的本地默认实例级熔断。
配置入口见 [polaris.yaml](config/polaris.yaml)，默认开启；支持调整下列本地规则参数，`plugin` 参数尚未生效。
不支持远端规则、服务级、接口级、慢调用或自定义规则对象。主动探测属于 P2，当前不支持。

## 配置参数

```yaml
consumer:
  circuitBreaker:
    sleepWindow: 30s
    successCountAfterHalfOpen: 3
    defaultRuleEnable: true
    defaultErrorCount: 10
    defaultErrorPercent: 50
    defaultInterval: 60s
    defaultMinimumRequest: 10
```

- `sleepWindow`：打开到半开的等待时间；与 Java composite 一致，生效值按整秒截断。
- `successCountAfterHalfOpen`：半开关闭所需成功数，也决定半开配额；正整数，`0` 使用默认值 `3`。
- `defaultRuleEnable`：布尔值；`false` 时不装配本地熔断链，不创建统计和检查任务，上报正常返回。当前没有其他规则来源，与关闭 `enable` 的熔断效果相同。
- `defaultErrorCount`：触发打开的连续失败数，正整数。
- `defaultErrorPercent`：触发打开的错误率，整数百分比 `[0, 100]`，不是 `0.5` 这样的比例。
- `defaultInterval`：错误率窗口和首次失败后的延迟检查时长；与 Java composite 一致，生效值按整秒截断，小于 1 秒时回退为 60 秒。使用 10 个桶，桶宽向上取整到整数毫秒。
- `defaultMinimumRequest`：错误率检查所需最小请求数，正整数。

YAML 时长支持 `30s`、`1500ms` 或整数毫秒。代码赋值使用 snake_case 字段和整数毫秒：

```python
from polaris import Configuration, create_consumer_by_config

config = Configuration()
config.set_default()
rule = config.get_consumer().get_circuit_breaker()
rule.sleep_window = 15000
rule.success_count_after_half_open = 2
rule.default_rule_enable = True
rule.default_error_count = 5
rule.default_error_percent = 60
rule.default_interval = 30000
rule.default_minimum_request = 20
consumer = create_consumer_by_config(config)
try:
    consumer.check_available()
finally:
    consumer.destroy()
```

配置在 context 初始化时校验并读取为独立快照，之后赋值不热更新已有熔断器。
没有新增专用环境变量；文件可通过 `${APP_*}` 占位符引用应用变量。

## 默认规则

- 返回码 `500-599` 或 `-1` 为失败，其他返回码为成功。`ret_status` 保留参数校验，但不参与熔断判错；`delay` 不参与慢调用判定。
- 连续 `defaultErrorCount` 次失败立即打开，默认 10；任一次成功重置连续计数，计数不因跨统计桶或闲置自动重置。
- 错误率采用 `defaultInterval` 窗口，默认 60 秒、10 个桶；窗口从首次上报开始建桶。首次失败延迟一个窗口后检查，后续失败不推迟该检查；最近窗口至少 `defaultMinimumRequest` 次且失败率 `>=defaultErrorPercent` 时打开，默认 10 次 / 50%。未打开时，后续失败可安排下一次检查。
- 连续失败和错误率两个 trigger 独立暂停与恢复。连续失败触发后清零自身计数；错误率触发后暂停自身统计。打开状态仍会派发未暂停的 trigger；半开任一次失败立即重新打开，累计 `successCountAfterHalfOpen` 次成功关闭，默认 3。半开结果不计入旧统计，关闭后恢复原 trigger 状态，不重建窗口。
- 打开经过 `sleepWindow` 后进入半开，默认 30 秒。
- `checkPeriod` 默认为 10 秒，用于补充扫描，不改变错误率窗口或恢复等待。

## 实例选择

`get_one_instance()` / `async_get_one_instance()` 在最终选中半开实例时扣减一个配额，
每个半开阶段共 `successCountAfterHalfOpen` 个，默认 3；候选筛选和调用结果上报不扣配额。
配额不会随每次成功返还。
`get_instances()` / `async_get_instances()` 返回本地过滤后的候选，不消耗半开配额。
`get_all_instances()` / `async_get_all_instances()` 返回完整缓存，不执行过滤。

保留全死全活兜底：路由候选全部不可用时，仍可能返回打开或半开配额耗尽的实例。
因此单实例发现不是严格的调用拒绝接口。`serviceRouter.percentOfMinInstances` 设置为非零时，
候选低于该比例也可能回退原集合。

SDK 不拦截业务调用。应用应对每次调用上报一次结果；未上报的半开请求会占用配额，
且不会推进恢复。上报入口没有请求标识或调用阶段标识，不能去重，也不能区分同一实例跨状态的延迟结果。

## 调用结果上报

同步调用使用 `update_service_call_result()`，异步调用使用
`await async_update_service_call_result()`；`sync_update_service_call_result()` 为同步兼容入口。
实例必须来自同一个 Consumer context，建议直接使用单实例发现返回的对象。

```python
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from polaris import Configuration, create_consumer_by_config
from polaris.pkg.model.service import GetOneInstanceRequest, RetStatus, ServiceCallResult

config = Configuration()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]
consumer = create_consumer_by_config(config)
try:
    instance = consumer.get_one_instance(GetOneInstanceRequest(namespace="default", service="echo"))
    if instance is None:
        raise RuntimeError("no provider instance")
    host = instance.get_host()
    authority = f"[{host}]" if ":" in host else host
    started = time.monotonic()
    code = -1
    try:
        with urlopen(f"http://{authority}:{instance.get_port()}/echo", timeout=2) as response:
            code = response.status
            body = response.read()
    except HTTPError as error:
        code = error.code
        raise
    finally:
        failed = code == -1 or 500 <= code <= 599
        consumer.sync_update_service_call_result(ServiceCallResult(
            called_instance=instance,
            ret_status=RetStatus.RetFail if failed else RetStatus.RetSuccess,
            ret_code=code,
            delay=int((time.monotonic() - started) * 1000),
        ))
finally:
    consumer.destroy()
```

禁用熔断后，上报正常返回，但不创建熔断统计或任务。其他 context 或已淘汰实例的旧对象上报会被忽略；
相同实例 ID 的刷新保留本地状态，新实例重新统计。状态和统计不写入磁盘，重启后从关闭状态开始。
实例移除、缓存淘汰和 context 销毁均清理对应定时任务。

边界与生命周期回归：`uv run --locked pytest -q tests/test_circuitbreaker.py -W error::RuntimeWarning`。

## 可运行验证

[examples/circuitbreaker](../examples/circuitbreaker/README-zh.md) 提供两个可切换故障的 HTTP Provider
和调用方，覆盖发现、业务调用、一次结果上报、熔断与半开恢复。相邻 `polaris.yaml` 保留默认规则参数，
真实启动通过 `POLARIS_E2E=1` 开启；无需创建远端熔断规则。

```bash
uv run --locked python examples/circuitbreaker/verify.py
```

默认离线验证仅替换注册中心 RPC，使用真实 SDK 运行时和本机临时 HTTP 端口，
通过公开代码字段缩短等待并调整阈值。覆盖 10 个场景，包括错误率定时检查、半开精确配额、
同步 / 异步、禁用规则、全死全活、网络失败、自动心跳 / 反注册及各 context 的资源清理。
