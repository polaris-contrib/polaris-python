# examples/route/nearby — 用例清单

本文档与 `verify_nearby_route.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `:8091`，HTTP 管控 `:8090` |
| `uv`、`python3`、`curl` | 启动示例、创建规则、发请求 |

## 运行

```bash
bash examples/route/nearby/verify_nearby_route.sh
bash examples/route/nearby/verify_nearby_route.sh --consumer-campus ap-guangzhou-1
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址 |
| `--polaris-token` | 空 | 鉴权令牌 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `RouteNearbyEchoServer` | 服务名 |
| `--consumer-port` | `18080` | Consumer 端口。与 rule、quickstart 默认端口相同，不要并行跑 |
| `--request-count` | `10` | 请求次数 |
| `--consumer-campus` | `ap-guangzhou-1` | Consumer 所在 campus |
| `--rule-name` | `<service>-auto-nearby` | 就近规则名 |

地域固定为 `REGION=china`、`ZONE=ap-guangzhou`。三个 provider 的 campus 依次是 `ap-guangzhou-1`、`ap-guangzhou-2`、`ap-guangzhou-3`。

## 拓扑

| 角色 | 端口 | campus |
| --- | --- | --- |
| provider | `28091` | `ap-guangzhou-1` |
| provider | `28092` | `ap-guangzhou-2` |
| provider | `28093` | `ap-guangzhou-3` |
| consumer | `18080` | `ap-guangzhou-1` |

规则 `POST /naming/v2/routings`，`routing_policy=NearbyPolicy`，`match_level=CAMPUS`，`max_match_level=REGION`，`strict_nearby=false`。服务端只在 `NEARBY_ROUTE_RULE` 类型的发现结果里下发就近规则。创建后轮询 `POST /v1/Discover`（`NEARBY_ROUTE_RULE`），规则名出现后再启动 consumer，最多等 30 秒。

## 用例：请求留在 Consumer 所在 campus

对 `GET /echo` 发 `REQUEST_COUNT` 次。

| 判定 | 每次 HTTP 200，响应体包含 `'campus': 'ap-guangzhou-1'`，命中次数等于 `REQUEST_COUNT` |
| --- | --- |

## 清理

```bash
bash examples/route/nearby/cleanup.sh -f
```

进程和日志由 `cleanup.sh` 清理。就近规则留在服务端。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| 创建规则失败 | 看响应体，确认 `/naming/v2/routings` 和令牌 |
| 命中其他 campus | 旧的就近规则还在，或 consumer 的 campus 参数不是 `ap-guangzhou-1` |
| 30 秒内规则未出现在 Discover | 服务端缓存未刷新，或规则创建在别的命名空间 |
| 全部未命中 | 看 `.logs/consumer.log`，确认 location 已写入发现结果 |
| 请求在三个 campus 间轮转 | 就近规则没有生效。SDK 负载均衡是平滑加权轮询，规则未生效时请求会分散到各实例 |
