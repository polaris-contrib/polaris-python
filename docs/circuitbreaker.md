# 本地实例熔断

当前仅支持 `composite` 本地实例级熔断，不支持远端规则、服务级、
接口级、慢调用或主动健康探测。

## 配置

```yaml
consumer:
  circuitBreaker:
    enable: true
    checkPeriod: 1m
    sleepWindow: 30s
    successCountAfterHalfOpen: 3
    defaultRuleEnable: true
    defaultErrorCount: 10
    defaultErrorPercent: 50
    defaultInterval: 60s
    defaultMinimumRequest: 10
    chain: [composite]
```

完整说明见 [配置参数说明](config/configuration-reference.md)。

- `sleepWindow`：打开到半开的等待时间。
- `successCountAfterHalfOpen`：关闭所需成功数，也是半开请求配额。
- `defaultErrorCount`：连续失败阈值。
- `defaultErrorPercent`：错误率阈值，整数百分比。
- `defaultInterval`：错误率窗口。
- `defaultMinimumRequest`：错误率检查最小样本数。
- `defaultRuleEnable=false`：不创建统计、定时器和熔断任务。

代码中的时长使用整数毫秒，字段使用 snake_case。

## 判错

- 返回码 `500-599` 或 `-1`：失败。
- 其他返回码：成功。
- `ret_status` 只做参数校验，不参与判错。
- `delay` 不参与慢调用判断。

连续失败达到阈值立即打开。错误率在窗口结束后检查，达到最小请求数且比例
不低于阈值时打开。打开经过 `sleepWindow` 进入半开；任一次失败重新打开，
达到成功数后关闭。

## 实例选择

- `get_one_instance()` 选中半开实例时扣减一个配额。
- `get_instances()` 只返回候选，不扣配额。
- `get_all_instances()` 返回完整缓存。

候选全部不可用时保留全死全活兜底，可能返回打开或配额耗尽的实例。
因此单实例发现不是严格的调用拒绝接口。

## 上报结果

应用必须在每次调用后主动上报：

```python
from polaris.pkg.model.service import RetStatus, ServiceCallResult

consumer.update_service_call_result(ServiceCallResult(
    called_instance=instance,
    ret_status=RetStatus.RetFail if code >= 500 else RetStatus.RetSuccess,
    ret_code=code,
    delay=elapsed_ms,
))
```

异步入口为 `await consumer.async_update_service_call_result(result)`。
`sync_update_service_call_result()` 是同步兼容入口。

禁用熔断后上报正常返回但不创建统计。跨 context 或旧缓存实例的结果会被忽略。
状态不写磁盘，重启后从关闭状态开始。

## 验证

```bash
./examples/verify.sh --only circuitbreaker
uv run pytest -q tests/test_circuitbreaker.py -W error::RuntimeWarning
```

示例说明见 [examples/circuitbreaker](../examples/circuitbreaker/README-zh.md)。
