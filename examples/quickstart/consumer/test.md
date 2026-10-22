# quickstart Consumer 测试说明

本目录的验证入口执行完整的 quickstart 场景，验证 Consumer 从 SDK 发现 Provider、
通过真实本机 HTTP 发起同步调用，并上报调用结果。验证同时覆盖父目录中的 Provider，
但 SDK 注册中心 RPC 使用 fake stub。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行父级 quickstart 完整验证，产物保存在本目录。 |
| `run.sh` | 在当前目录启动 Consumer `main.py`。 |
| `logs.sh` | 查看本目录保留的控制台、验证和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录日志/运行时文件；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh 的作用

Consumer 启动后监听 HTTP 端口，通过 SDK 的 `get_one_instance()` 选择 Provider，
再调用 Provider 的 `/echo` 并上报 `ServiceCallResult`。

```bash
make -C examples/quickstart/consumer run ARGS="--namespace default --service DiscoverEchoServer"\
  --port 18080 --call-timeout 2
```

- `--port` 是 Consumer 自己的监听端口，不能使用 0；
- `--call-timeout` 是本机 HTTP 调用超时；
- `--config` 指定独立的 Consumer YAML；
- 配置中的业务 Provider 和 SDK 注册中心地址是两个不同概念。

真实远端联调需要先启动可发现的 Provider，并设置
`POLARIS_SERVER_ADDRESS` 和必要的 `POLARIS_TOKEN`。quickstart 入口不检查
`POLARIS_E2E`；设置它不会改变该 demo 的行为。

## verify.sh 如何验证

验证器启动 Provider 和 Consumer 两个真实进程，然后：

1. 等待 Provider 输出 `registered` 和临时端口。
2. 等待 Consumer 输出 HTTP 监听地址。
3. 请求 `GET /echo`，断言 HTTP 200。
4. 断言正文中的服务名、Provider host 和 port 正确。
5. 请求 `POST /echo-with-body`，断言返回相同 Provider 响应。
6. 捕获 Consumer fake RPC 记录，确认发生 `discover` 和 `report`。
7. 终止两个进程，确认 Consumer 正常退出和资源释放。

该验证不会访问外部注册中心。失败可能来自端口启动失败、发现失败、HTTP 正文
不一致、未上报结果或进程清理失败；管理程序会将退出码写入 `result.json`。

## 查看结果

```bash
./examples/verify.sh --only quickstart/consumer
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category cache --tail 50
./examples/cleanup.sh --dry-run
```

日志按本次运行隔离。`consumer/` 子目录保存真实 Consumer 的工具输出，SDK 日志按
`base`、`network`、`cache` 等类别保存。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | Consumer 监听、发现、HTTP 调用、结果上报、清理和异常输出。 |
| `result.json` | `verify`/`run` 动作的最终退出码、是否超时和是否人工中断。 |
| `verification.log` | 完整 quickstart 断言的 stdout/stderr 和 traceback；直接 `run.sh` 通常不生成。 |

实际 SDK 日志在 `polaris/log/consumer/`，缓存和锁文件在同级 `polaris/backup/consumer/`。
建议按 `result.json` → `verification.log` → `console.log` → `polaris/log/` 的顺序排查。
完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

Consumer 不注册业务实例，也不创建 Polaris 服务。它只创建 SDK context，并读取
Provider 注册的实例：

| 项目 | 值 |
| --- | --- |
| 发现 namespace/service | `ns/svc` |
| Provider 实例 | `127.0.0.1:<动态端口>`，fake ID 为 `quickstart-provider` |
| Consumer HTTP 端口 | 验证器动态选择，记录在 `console.log` 的 `started.listen` |
| 手动运行默认端口 | `18080` |
| Consumer 注册实例 | 无 |

Consumer 会向 fake registry 上报自身的 client ID 和调用结果，但这不属于业务服务
实例注册。实际被发现的 Provider 端口以 `registered.port` 为准。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only quickstart/consumer
```

验证自动创建 `polaris-python-e2e-quickstart-<年月日时分秒毫秒>` 服务和 1 个动态端口 Provider，
Consumer 使用动态本机 HTTP 端口。Consumer 不注册业务实例，但会真实发现 Provider、
调用 `/echo`、上报结果并销毁 context。

成功效果为 HTTP 200、调用正文包含服务名、Provider 完成反注册。最终 JSON 包含实际
instance ID、host/port、consumer_port 和 `effect`。完整说明见
[真实服务验证说明](../../README-zh.md#真实服务验证)。
