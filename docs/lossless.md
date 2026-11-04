# 无损上下线

Python SDK 对齐 Java SDK 的 lossless 插件，提供无损上线、无损下线、readiness 探活和
消费端权重预热。规则优先使用服务端下发的无损规则（按 metadata 匹配），本地配置作为兜底。

## 配置

```yaml
provider:
  lossless:
    enable: true
    # DELAY_BY_TIME: 延迟注册；DELAY_BY_HEALTH_CHECK: 探测通过后注册
    strategy: DELAY_BY_HEALTH_CHECK
    delayRegisterInterval: 30s
    healthCheckInterval: 5s
    healthCheckPath: /ready

consumer:
  weightAdjust:
    enable: true
    chain: [warmup]
```

`global.admin` 指定内置 HTTP 端口（默认 `0.0.0.0:28080`，与 Prometheus 指标共用）。
`port: -1` 关闭内置 HTTP。

## 无损上线

```python
from polaris import Configuration, ProviderAPI, init_context_by_config
from polaris.pkg.model.server import InstanceRegisterRequest

context = init_context_by_config(Configuration.from_dict({...}))
provider = ProviderAPI(context)
provider.lossless_register(InstanceRegisterRequest(...))
```

- `DELAY_BY_TIME`：等待 `delayRegisterInterval` 后真正注册。
- `DELAY_BY_HEALTH_CHECK`：周期探测 `127.0.0.1:实例端口 + healthCheckPath`，
  探测成功后真正注册。
- 探测期间 `/readiness`（兼容 `/online`）返回 `503 UNREGISTERED`；注册完成返回
  `200 REGISTERED`，可直接作为 K8s readinessProbe。

服务端规则中的 `losslessOnline.delayRegister`、`warmup`、`readiness` 会覆盖本地同名配置。

## 无损下线

```python
provider.lossless_deregister(request)
```

或在 preStop 钩子中调用内置端点（仅允许本机访问）：

```bash
curl -X POST http://127.0.0.1:28080/offline
```

`/offline` 会立即反注册所有开启无损下线的实例，让消费端尽快摘除节点；返回
`200 ok`。K8s 建议在 preStop 中先调用 `/offline`，再配合 `sleep` 等待消费端缓存刷新。

## 自定义动作

需要完全接管注册、反注册或探测时，使用 `LosslessAPI`：

```python
from polaris import LosslessAPI, LosslessInstance, LosslessActionProvider

class MyProvider(LosslessActionProvider):
    async def do_register(self, properties):
        ...

    async def do_deregister(self):
        ...

    async def do_health_check(self) -> bool:
        return True

    def is_enable_health_check(self) -> bool:
        return True

    def get_name(self) -> str:
        return "my"

instance = LosslessInstance(namespace="ns", service="svc", host="127.0.0.1", port=8080)
api = LosslessAPI(context)
api.set_lossless_action_provider(instance, MyProvider())
api.lossless_register(instance)
```

## 消费端预热

`consumer.weightAdjust.chain` 包含 `warmup` 时，单实例发现按服务端无损规则中的
`losslessOnline.warmup` 调整新实例动态权重：

`weight = ceil((uptime / intervalSecond) ^ curvature * 原权重)`

预热结束或超过 `overloadProtectionThreshold` 比例的实例同时在预热时，不调整权重。
