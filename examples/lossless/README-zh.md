# 无损上下线

[English](README.md)

先启动 consumer，再启动一个或多个 provider：

```bash
POLARIS_E2E=1 uv run --locked python examples/lossless/consumer/main.py
POLARIS_E2E=1 uv run --locked python examples/lossless/provider/main.py --port 18081 --admin-port 28080
POLARIS_E2E=1 uv run --locked python examples/lossless/provider/main.py --port 18082 --admin-port 28081
```

Provider 会先启动 `/ready` 和 `/echo`，再调用 `lossless_register()`。默认策略为
`DELAY_BY_HEALTH_CHECK`，SDK 会轮询 `http://127.0.0.1:provider端口/ready`；
探测通过后才注册实例。探测期间 SDK 的 admin 端点返回 `503 UNREGISTERED`：

```bash
curl http://127.0.0.1:28080/readiness
```

注册完成后返回 `200 REGISTERED`。Consumer 已开启 warmup，新注册实例通过
`get_one_instance()` 获得的流量占比会逐渐增加；退出时会输出每个实例 ID 的调用次数。

无损下线时可以给 provider 发送 SIGTERM，也可以调用仅允许本机访问的 admin 端点：

```bash
curl -X POST http://127.0.0.1:28080/offline
```

SDK 会立即反注册实例，让消费端尽快从发现结果中移除它。

服务端下发的 lossless 规则优先于 `polaris.yaml` 中的本地配置。
`--service-token` 默认读取 `POLARIS_SERVICE_TOKEN`。完整配置见
[docs/lossless.md](../../docs/lossless.md)。
