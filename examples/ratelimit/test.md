# examples/ratelimit — 用例清单

本文档与 `verify_ratelimit.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `:8091`，HTTP 管控 `:8090` |
| `uv`、`python3`、`curl` | 启动示例、创建规则、发请求 |

## 运行

```bash
bash examples/ratelimit/verify_ratelimit.sh
bash examples/ratelimit/verify_ratelimit.sh --max-amount 2
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址 |
| `--polaris-token` | 空 | 鉴权令牌 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `RateLimitEchoServer` | 服务名 |
| `--provider-port` | `28201` | Provider 端口 |
| `--max-amount` | `2` | 窗口内放行次数 |

`BURST_COUNT` 默认 `12`。窗口长度在规则里固定为 `60s`。

## 规则

| 字段 | 值 |
| --- | --- |
| name | `RateLimitEchoServer-auto-qps` |
| resource | `QPS` |
| type | `LOCAL` |
| method | EXACT `/echo` |
| amounts | `maxAmount=2`，`validDuration=60s` |
| action | `REJECT` |

## 用例 1：Provider 上同时出现放行和拒绝

| 项 | 内容 |
| --- | --- |
| 操作 | 启动 provider，创建规则，最多等 30 轮。每轮对 `http://127.0.0.1:28201/echo` 发 12 次 |
| 预期 | 同一轮里既有 HTTP 200，也有 HTTP 429 |
| 判定 | `allowed > 0` 且 `limited > 0` |

规则刚创建时 provider 可能还没拉到配额，所以脚本会重试。60 秒窗口内阈值只有 2 次，12 次突发里应出现 429。

## 用例 2：Client 经发现调用同一服务

| 项 | 内容 |
| --- | --- |
| 操作 | 运行 `client.py --service RateLimitEchoServer --count 8` |
| 预期 | 进程退出码 0，日志中有 `status=` |
| 判定 | 存在 `status=` 行 |

Client 只确认发现和调用走通。200/429 的比例在用例 1 判定。

## 清理

```bash
bash examples/ratelimit/cleanup.sh -f
```

`cleanup.sh` 停止 `examples/ratelimit/provider.py` 和 `client.py`，并删除 `.logs/`、`.build/`。限流规则 `RateLimitEchoServer-auto-qps` 留在服务端。同名规则再次创建失败时，先在控制台删除，或换 `--service`。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| 30 轮后仍然只有 200 | 规则未下发。看创建接口的响应，以及 `.logs/provider.log` |
| 全部 429 | 上一次运行的窗口配额还在。等窗口结束，或换服务名 |
| 创建规则失败 | 鉴权环境加 `--polaris-token`；同名规则已存在时先删除 |
| client 没有 `status=` | 看 `.logs/client.log`，确认发现到了本次 provider |
