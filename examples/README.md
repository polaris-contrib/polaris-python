# Polaris Python SDK Examples

示例目录按 Polaris Go SDK 的功能组织，默认连接本地 Polaris 服务端
`127.0.0.1:8091`。也可以通过环境变量覆盖：

```bash
export POLARIS_SERVER_ADDRESSES=127.0.0.1:8091
export POLARIS_NAMESPACE=default
export POLARIS_TOKEN=
```

## 示例

| 目录 | 内容 | 运行方式 |
| --- | --- | --- |
| `quickstart/provider.py` | HTTP Provider 注册、心跳、反注册 | `python examples/quickstart/provider.py` |
| `quickstart/consumer.py` | 异步发现实例并代理 HTTP 请求 | `python examples/quickstart/consumer.py` |
| `quickstart/consumer_sync.py` | 同步发现实例并调用 HTTP 服务 | `python examples/quickstart/consumer_sync.py` |
| `route/metadata/` | 元数据路由 provider/consumer | `python examples/route/metadata/consumer.py` |
| `route/rule/` | 规则路由 provider/consumer | `python examples/route/rule/consumer.py` |
| `route/nearby/` | 就近路由 provider/consumer | `python examples/route/nearby/consumer.py` |
| `ratelimit/provider.py` | 注册 Provider 并调用服务端限流配额 | `python examples/ratelimit/provider.py` |
| `ratelimit/client.py` | 同步发现并调用限流服务 | `python examples/ratelimit/client.py` |
| `circuitbreaker/provider.py` | 可切换成功/失败响应的 Provider | `python examples/circuitbreaker/provider.py` |
| `circuitbreaker/client.py` | 同步拉取服务端规则并调用熔断服务 | `python examples/circuitbreaker/client.py` |

先启动 Provider，再启动 Consumer：

```bash
python examples/quickstart/provider.py --service polaris-python-demo
python examples/quickstart/consumer.py --service polaris-python-demo
curl http://127.0.0.1:18080/echo
```

异步 Consumer 使用 `async_get_one_instance`；同步 Consumer 使用对应的
`get_one_instance`。实例选择内部会执行健康过滤、路由和负载均衡：

```bash
python examples/quickstart/consumer_sync.py --service polaris-python-demo
```

路由示例的 provider 需要先启动，并且路由规则需要在 Polaris 控制台配置，详见
[`route/README.md`](route/README.md)。除 quickstart 的异步 consumer 外，其余示例
默认使用同步接口。

限流和熔断示例不会在客户端硬编码规则；第一次调用
`get_one_instance` 时，SDK 会同时订阅服务端下发的
`RATE_LIMIT` / `CIRCUIT_BREAKER` 规则。

## 自动化验证

每个 demo 有一个 `verify_*.sh`，会启动对应进程、在需要时通过 Polaris HTTP API
创建规则，并检查调用结果。需要本机 Polaris 已在 `127.0.0.1:8091` 监听，管理端口
为 `8090`。

```bash
bash examples/verify_all.sh
```

也可以单独运行，例如 `bash examples/quickstart/verify_quickstart.sh`。地址和令牌用
`POLARIS_SERVER`、`POLARIS_TOKEN` 覆盖。

## E2E 测试

E2E 测试默认跳过。确认 Polaris 服务端已启动后执行：

```bash
POLARIS_E2E=1 \
POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
uv run pytest -m e2e -q
```

可选变量：`POLARIS_E2E_NAMESPACE`、`POLARIS_E2E_SERVICE`、
`POLARIS_E2E_TIMEOUT`、`POLARIS_TOKEN`。测试会创建唯一实例，验证注册、发现、
健康过滤、心跳和反注册，并在结束时清理实例。
