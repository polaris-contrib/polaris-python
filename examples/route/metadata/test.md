# examples/route/metadata — 用例清单

本文档与 `verify_metadata_route.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `:8091` 可达。本脚本不调用规则管理 API |
| `uv`、`python3`、`curl` | 启动示例和发请求 |

元数据匹配在 SDK 内完成，控制台不需要路由规则。

## 运行

```bash
bash examples/route/metadata/verify_metadata_route.sh
bash examples/route/metadata/verify_metadata_route.sh --request-count 10
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址 |
| `--polaris-token` | 空 | 鉴权令牌 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `RouteMetadataEchoServer` | 服务名 |
| `--consumer-port` | `18090` | Consumer 端口 |
| `--request-count` | `10` | 每个 env 的请求次数 |
| `--route-envs` | `dev,test,pre,prod` | 正用例标签，顺序对应下面四个端口 |
| `--negative-env` | `noexist` | 负用例标签 |

## 拓扑

| 角色 | 端口 | metadata |
| --- | --- | --- |
| provider | `28071` | `env=dev` |
| provider | `28072` | `env=test` |
| provider | `28073` | `env=pre` |
| provider | `28074` | `env=prod` |
| consumer | `18090` | 启动参数默认 `env=dev`，每次请求用 query `env` 覆盖 |

```text
curl :18090/echo?env=<value>
  └─ consumer.py 按 query 做元数据路由
       └─ 命中 metadata env=<value> 的 provider
```

## 用例 1–4：四个 env 全部命中

对 `dev`、`test`、`pre`、`prod` 各发 `REQUEST_COUNT` 次 `GET /echo?env=<env>`。

| 判定 | 每次 HTTP 200，且响应体包含 `'env': '<env>'`，命中次数等于 `REQUEST_COUNT` |
| --- | --- |

## 用例 5：不存在的 env 被拒绝

对 `env=noexist` 发同样次数的请求。

| 判定 | 每次 HTTP 都不是 200，拒绝次数等于 `REQUEST_COUNT` |
| --- | --- |

## 清理

```bash
bash examples/route/metadata/cleanup.sh -f
```

脚本不创建服务端规则，`cleanup.sh` 只停进程并删除 `.logs/`、`.build/`。实例随 provider 退出反注册。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| 正用例命中不足 | 看 `.logs/consumer.log` 和对应 `.logs/provider_<env>.log`，确认四个实例都注册成功 |
| 负用例仍返回 200 | 请求没有带上不存在的 env，或 consumer 退回了全量实例 |
| consumer 未就绪 | 发现缓存还没拉到实例。脚本最多等 40 秒 |
