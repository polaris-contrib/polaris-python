# examples/route/rule — 用例清单

本文档与 `verify_rule_route.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `:8091`，HTTP 管控 `:8090` |
| `uv`、`python3`、`curl` | 启动示例、创建规则、发请求 |

## 运行

```bash
bash examples/route/rule/verify_rule_route.sh
bash examples/route/rule/verify_rule_route.sh --route-envs dev,test,pre,prod
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址 |
| `--polaris-token` | 空 | 鉴权令牌 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `RouteEchoServer` | 服务名 |
| `--consumer-port` | `18080` | Consumer 端口。与 nearby、quickstart 的默认 consumer 端口相同，不要并行跑 |
| `--request-count` | `10` | 每个 env 的请求次数 |
| `--route-envs` | `dev,test,pre,prod` | 标签列表，顺序对应端口 |
| `--rule-name` | `<service>-auto-rule` | 路由规则名 |

## 拓扑

| 角色 | 端口 | metadata |
| --- | --- | --- |
| provider | `28081` | `env=dev` |
| provider | `28082` | `env=test` |
| provider | `28083` | `env=pre` |
| provider | `28084` | `env=prod` |
| consumer | `18080` | 无固定 metadata，按每次请求的 query 匹配 |

规则 `POST /naming/v2/routings`。每个 env 一条子规则：来源 query `env` 精确等于该值，目的实例标签 `env` 精确等于该值，权重 100。创建后轮询 `POST /v1/Discover`（`ROUTING`），规则名出现后再启动 consumer，最多等 30 秒。

## 用例：query env 命中对应实例

对每个 env 发 `REQUEST_COUNT` 次 `GET /echo?env=<env>`。

| 判定 | 每次 HTTP 200，响应体包含 `'env': '<env>'`，命中次数等于 `REQUEST_COUNT` |
| --- | --- |

## 清理

```bash
bash examples/route/rule/cleanup.sh -f
```

进程和 `.logs/`、`.build/` 由 `cleanup.sh` 清理。路由规则留在服务端。重复创建同名规则失败时，删除 `RouteEchoServer-auto-rule` 或改 `--rule-name`。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| 创建规则失败 | 看响应体。鉴权环境加 `--polaris-token` |
| 30 秒内规则未出现在 Discover | 服务端缓存未刷新，或规则创建在别的命名空间 |
| 命中次数不足 | 看 `.logs/consumer.log`；SDK 每 `refresh_interval_seconds`（默认 2 秒）刷新一次规则 |
| 打到别的 env | 服务上还有优先级更高的旧规则 |
