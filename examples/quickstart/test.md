# examples/quickstart — 用例清单

本文档与 `verify_quickstart.sh` 保持一致。改脚本时同步改本文。

## 前置条件

| 依赖 | 说明 |
| --- | --- |
| Polaris | gRPC `127.0.0.1:8091` 可达。管理端口 `8090` 本脚本不用 |
| `uv`、`python3`、`curl` | 启动示例和发请求 |

## 运行

```bash
bash examples/quickstart/verify_quickstart.sh
bash examples/quickstart/verify_quickstart.sh --polaris-server 127.0.0.1 --service polaris-python-demo
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--polaris-server` | `127.0.0.1` | 服务端地址，脚本使用该地址的 `8091` |
| `--polaris-token` | 空 | 鉴权令牌 |
| `--namespace` | `default` | 命名空间 |
| `--service` | `polaris-python-demo` | 服务名 |
| `--provider-port` | `28111` | Provider HTTP 端口 |
| `--consumer-port` | `18080` | 异步 Consumer 端口 |

环境变量 `REQUEST_COUNT` 默认 `10`。

## 拓扑

```text
curl → consumer.py :18080 /echo
         └─ async_get_one_instance
              └─ provider.py :28111 /echo

consumer_sync.py（一次调用，无监听端口）
  └─ get_one_instance → provider.py :28111 /echo
```

脚本不创建路由、限流或熔断规则。

## 用例 1：异步 Consumer 代理

| 项 | 内容 |
| --- | --- |
| 操作 | 启动 provider，再启动 `consumer.py`，对 `:18080/echo` 发 `REQUEST_COUNT` 次 |
| 预期 | 每次 HTTP 200，响应体包含 `127.0.0.1:28111` |
| 判定 | 命中次数等于 `REQUEST_COUNT` |

## 用例 2：同步一次性发现

| 项 | 内容 |
| --- | --- |
| 操作 | 执行 `consumer_sync.py --service polaris-python-demo` |
| 预期 | 进程退出码 0，日志包含 `127.0.0.1:28111` |
| 判定 | 日志命中该地址 |

## 清理

`verify_quickstart.sh` 退出时会停掉自己拉起的进程。手动启动或脚本被中断后：

```bash
bash examples/quickstart/cleanup.sh -f
```

`cleanup.sh` 只按命令行匹配 `examples/quickstart/*.py`，并删除本目录 `.logs/`、`.build/`。不反注册实例；进程正常退出时 provider 自己反注册。

## 失败排查

| 现象 | 排查 |
| --- | --- |
| provider 未就绪 | 看 `.logs/provider.log`，确认 `8091` 可达 |
| 异步 consumer 命中次数不足 | 看 `.logs/consumer.log`，确认发现到的是本次 provider 端口 |
| `consumer_sync` 未打到 provider | 看 `.logs/consumer_sync.log` |
| 端口被占用 | 脚本会先停掉占用端口的进程；仍冲突时改 `--provider-port` / `--consumer-port` |
