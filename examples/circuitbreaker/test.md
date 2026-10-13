# examples/circuitbreaker — 用例清单

本文档与 `verify_circuitbreaker.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `:8091`，HTTP 管控 `:8090` |
| `uv`、`python3`、`curl` | 启动示例、创建规则、发请求 |

## 运行

```bash
bash examples/circuitbreaker/verify_circuitbreaker.sh
bash examples/circuitbreaker/verify_circuitbreaker.sh --consecutive-error 3
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址 |
| `--polaris-token` | 空 | 鉴权令牌，开启鉴权时必填 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `CircuitBreakerCallee` | 被调服务名 |
| `--provider-port` | `19102` | 失败 Provider 端口 |
| `--consecutive-error` | `3` | 连续失败阈值 |

`CLIENT_COUNT` 默认 `20`，是 `client.py --count` 的调用次数。

## 拓扑

```text
client.py
  └─ get_one_instance(CircuitBreakerCallee)
       └─ provider.py :19102 /echo   初始返回 500
            上报失败后，后续调用应被熔断拦截
```

规则由脚本创建，客户端不写本地规则。

| 字段 | 值 |
| --- | --- |
| name | `CircuitBreakerCallee-auto-cb` |
| level | `INSTANCE` |
| destination | 当前 namespace + `CircuitBreakerCallee` |
| 错误条件 | 返回码精确匹配 `500` |
| 触发 | `CONSECUTIVE_ERROR=3` |
| 恢复 | `sleep_window=30`，`consecutiveSuccess=1` |

## 用例 1：失败实例触发熔断打开

| 项 | 内容 |
| --- | --- |
| 操作 | 启动 `--initial-error` 的 provider，确认 `/echo` 为 500；创建上述规则（请求体为数组）；轮询 `POST /v1/Discover`（`CIRCUIT_BREAKER`）直到规则名出现；运行 `client.py --count 20` |
| 预期 | 日志里先出现 `status=500`，之后出现 `blocked by Polaris circuit breaker` |
| 判定 | 两行都存在，且 client 进程退出码为 0 |

本脚本只验证「先看到失败，再看到熔断打开」。半开恢复、服务级、接口级不在本 demo 的自动用例里。

## 清理

```bash
bash examples/circuitbreaker/cleanup.sh -f
```

`cleanup.sh` 停止匹配 `examples/circuitbreaker/provider.py` 和 `client.py` 的进程，并删除 `.logs/`、`.build/`。

脚本创建的熔断规则不会被 `cleanup.sh` 删除。重复执行若因同名规则失败，到控制台删除 `CircuitBreakerCallee-auto-cb`，或换 `--service`。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| 创建规则 HTTP 非 200 | 看日志里的响应体。鉴权环境加上 `--polaris-token` |
| 没有 `status=500` | provider 未处于失败态，确认启动参数含 `--initial-error` |
| 没有 `blocked by Polaris circuit breaker` | 规则尚未同步到客户端，或连续失败次数不够。可加大 `CLIENT_COUNT` |
| provider 未就绪 | 看 `.logs/provider.log` |
