# Polaris Python SDK

[English](README.md)

北极星服务治理 Python 客户端，支持服务注册发现、治理、AI Registry、
可观测性和 TLS。

发行包名为 `polaris-python`，导入名为 `polaris`。

## 安装

要求 Python 3.12+。

```bash
uv sync --group dev --locked
uv run pytest
```

项目使用 `src` 布局。`uv sync` 会以可编辑方式安装 `src/polaris/`，源码修改立即生效。

## 配置

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
    token: ${POLARIS_TOKEN:}
```

YAML 使用 `Configuration.from_file()`，环境变量使用 `Configuration.from_env()`，
代码 mapping 使用 `Configuration.from_dict()`。Python 时长单位为整数毫秒；
YAML 也支持 `500ms`、`1s`、`1m30s`。

详细说明：

- [配置参数说明](docs/config/configuration-reference.md)
- [最小 YAML 示例](docs/config/polaris.yaml)
- [环境变量与优先级](docs/config/environment-variables.md)
- [最小文件配置](examples/sdkconfig/file/polaris.yaml)

## Context

每个 `SDKContext` 独立持有配置快照、clientId、插件、连接、缓存、任务和日志。
需要共享同一客户端时，用同一个 context 创建 API。

```python
from polaris import Configuration, init_context_by_config

config = Configuration()
config.set_default()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]

context = init_context_by_config(config)
try:
    ...
finally:
    context.destroy()
```

`destroy()` 后继续调用 API 会抛出 `SDKError`。

## Provider

`ProviderAPI` 提供同步方法及对应的 `async_` 方法。`register_instance()`
默认开启 SDK 自动心跳。

```python
from polaris.pkg.model.server import InstanceRegisterRequest

response = provider.register_instance(InstanceRegisterRequest(
    service="demo",
    service_token="service-token",
    namespace="default",
    host="127.0.0.1",
    port=8080,
    ttl=5,
))
```

服务令牌用于注册、心跳和反注册，与连接 Polaris 的 `POLARIS_TOKEN` 不同。

自动重注册采用 Java 策略：连续 2 次 `400202` 且超过
`provider.minRegisterInterval` 后重注册。反注册前停止心跳任务。
销毁 context 不会隐式反注册实例。

## Consumer

每个 context 内复用 `ConsumerAPI`。同步入口包括 `get_one_instance()`、
`get_instances()`、`get_all_instances()` 和 `get_healthy_instances()`，
均提供对应 `async_` 方法。

```python
from polaris.pkg.model.service import GetOneInstanceRequest

instance = consumer.get_one_instance(GetOneInstanceRequest(
    namespace="default",
    service="demo",
))
```

实际调用下游后，用 `update_service_call_result()` 或
`async_update_service_call_result()` 上报结果。

缓存淘汰、磁盘重试和异常重启恢复见示例和
[配置参数说明](docs/config/configuration-reference.md)。

## AI Registry

- MCP、A2A 使用普通 `Instance` 注册发现。
- 服务契约使用 `report_service_contract()` / `get_service_contract()`。
- `SkillAPI` 通过独立连接提供只读查询、列表和下载。
- Skill 网络失败时可按版本从本地备份降级。

详见 [AI Registry API](docs/ai-registry.md)：

- [MCP 示例](examples/mcp/README-zh.md)
- [A2A 示例](examples/a2a/README-zh.md)
- [Skill 示例](examples/skill/README-zh.md)

## 插件

| 类型 | 名称 |
| --- | --- |
| 服务端连接器 | `grpc` |
| 本地缓存 | `inmemory`、`file` |
| 服务路由 | `isolatedRouter`、`metadataRouter`、`recoverRouter` |
| 负载均衡 | `weightedRandom`、`random` |
| 熔断 | `composite` |
| 统计上报 | `prometheus`（push 模式可用 `pushgateway` 链别名） |
| 事件上报 | `pushgateway` |

旧名称 `wr`、`err_count` 会规范化为 `weightedRandom`、`composite`。
当前不拉取远端治理规则，也不启用主动健康探测。

## 可观测性与安全

公有云当前默认支持 Pushgateway 主动推送；Prometheus pull 适用于自建或自定义抓取环境，
见 [可观测性](docs/observability.md)。

每个 context 有独立事件中心，仅暴露已实现的实例缓存和本地熔断事件，
并支持可选 Pushgateway 事件上报，见 [事件中心](docs/events.md)。

注册中心连接和 Skill 连接分别支持 TLS / mTLS。证书配置错误会拒绝启动，
不会降级为明文，见 [TLS](docs/tls.md)。

## 示例

运行全部离线验证：

```bash
./examples/verify_all.sh
```

运行或查看单个 demo：

```bash
cd examples/quickstart
./run.sh --help
./verify.sh
./logs.sh --latest --tail 30
./cleanup.sh --force
```

入口见 [examples/README-zh.md](examples/README-zh.md)。连接真实注册中心的示例需要
`POLARIS_E2E=1`。

## 许可证

[BSD 3-Clause](LICENSE)
