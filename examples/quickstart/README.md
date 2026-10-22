# Quickstart

本示例对齐 Go SDK quickstart：Provider 提供 `/echo` 服务并注册到 Polaris，Consumer 提供
HTTP 入口，收到请求后同步发现一个实例、同步调用 Provider，并同步上报调用结果。SDK 调用全部使用同步接口。

先设置 Polaris gRPC 地址和访问令牌：

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
```

Provider 和 Consumer 默认分别读取脚本旁边的
`provider/polaris.yaml` 与 `consumer/polaris.yaml`。两个配置都使用
`${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}` 和 `${POLARIS_TOKEN:}`：环境变量为空时使用
冒号后的默认值，非空时使用环境变量。`--config` 可显式指定其他 YAML 文件。

启动 Provider。`--service-token` 是服务令牌，用于注册、心跳和反注册，不是 `POLARIS_TOKEN`：

```bash
uv run --locked python examples/quickstart/provider/main.py \
  --namespace default --service DiscoverEchoServer \
  --service-token service-token --port 0
```

Provider 会连接第一个 Polaris 地址，取该 TCP 连接的本地源 IP 作为注册 host，调用
`register_instance()` 开启 SDK 自动心跳，并输出实际监听端口。收到 Ctrl-C 或 SIGTERM 时，
示例会同步反注册、关闭 HTTP 服务并销毁 context。

另开一个终端启动 Consumer：

```bash
uv run --locked python examples/quickstart/consumer/main.py \
  --namespace default --service DiscoverEchoServer --port 18080
```

验证服务发现和调用：

```bash
curl http://127.0.0.1:18080/echo
```

也可以在请求体中指定命名空间和服务：

```bash
curl -X POST http://127.0.0.1:18080/echo-with-body \
  -H 'Content-Type: application/json' \
  -d '{"namespace":"default","service":"DiscoverEchoServer"}'
```

`provider/polaris.yaml` 包含 `provider.minRegisterInterval`，并为 Provider 进程设置独立的
本地缓存目录。`consumer/polaris.yaml` 包含 `consumer.localCache`、`serviceRouter`、
`loadbalancer` 和 `circuitBreaker` 配置示例。

Consumer 使用 `get_one_instance()` 选择实例，用标准库 HTTP 客户端同步调用 Provider，
最后调用 `sync_update_service_call_result()` 上报成功或失败结果。

离线验证不依赖 Polaris 服务端，会通过假的 gRPC 响应启动真实示例进程：

```bash
uv run --locked python examples/quickstart/verify.py
```

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only quickstart
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 运行完整 Provider / Consumer 场景，日志保存在本目录的 `.logs/` 下。
Provider / Consumer 子目录也可独立执行 `verify.sh`，同样验证完整场景并保留各自日志。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../README-zh.md)。
