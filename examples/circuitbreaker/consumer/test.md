# circuitbreaker Consumer 测试说明

本目录的 `verify.sh` 执行父级完整熔断验证，覆盖真实 Consumer HTTP 前端、同步和异步
实例选择、调用结果上报、熔断状态和恢复流程。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 调用父级 10 场景熔断验证，产物保存在本目录。 |
| `run.sh` | 启动一个可被 HTTP 调用的 Consumer 前端。 |
| `logs.sh` | 查看控制台和 Consumer SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
make -C examples/circuitbreaker/consumer run ARGS="--namespace default --service CircuitBreakerCallee"\
  --port 18081 --call-timeout 2
```

Consumer 提供：

- `GET /echo`：选择一个实例、发起 HTTP 调用并上报结果；
- `GET /instances`：返回缓存实例及当前熔断状态；
- `POST /echo-with-body`：从 JSON 请求指定 namespace/service；
- 收到 SIGTERM/SIGINT 时等待 HTTP handler 结束并销毁 context。

真实远端运行需要设置 `POLARIS_E2E=1` 和
`POLARIS_SERVER_ADDRESS=<host>:8091`；Consumer 还需要可发现的 Provider。

## 验证如何工作

父级验证器用 fake registry RPC 提供两个实例，但真实运行 Consumer：

1. 检查 HTTP 200/404 如何映射为调用成功或失败；
2. 检查请求 ID 从 Consumer 传播到 Provider 再返回；
3. 验证连续失败只打开故障实例；
4. 验证健康实例仍被加权随机路由；
5. 验证半开许可数、失败重开和成功恢复；
6. 验证错误率、最小样本和真实延时检查；
7. 验证所有实例打开时仍有兜底调用；
8. 验证异步 discovery、HTTP 和 reporting；
9. 验证禁用默认规则时不会误熔断；
10. 验证 context、cache 写线程、计时器和日志流清理。

## 查看结果

```bash
./examples/verify.sh --only circuitbreaker/consumer
./examples/logs.sh --latest --category circuitbreaker --tail 80
./examples/logs.sh --latest --tail 80
./examples/cleanup.sh --dry-run
```

完整状态转换和断言见[父目录测试说明](../test.md)。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | Consumer 启动、实例选择、熔断状态、HTTP 状态、上报和异常。 |
| `result.json` | `verify`/`run` 的退出码、超时和中断状态；人工停止常驻进程会记录 `interrupted`。 |
| `verification.log` | 完整熔断场景断言和 traceback；`run.sh` 通常没有此文件。 |

SDK 分类日志在 `polaris/log/consumer/`，cache 和锁文件在同级 `polaris/backup/consumer/`。
完整解释见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

Consumer 不注册业务服务实例，只创建 SDK context 并发现以下实例：

| 项目 | 值 |
| --- | --- |
| 发现 namespace/service | `default/CircuitBreakerCallee` |
| Provider 实例数 | 2 |
| Provider host | `127.0.0.1` |
| Provider port | 动态分配，ID 为 `instance-<实际端口>` |
| Consumer HTTP 端口 | 验证时为动态端口 |
| 手动运行默认端口 | `18081` |

Consumer 会发送 client/report 数据并上报调用结果，但不会在 Polaris 创建业务实例。
默认 `18081` 与 Provider 默认端口相同；同机同时运行时应显式选择不同端口。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only circuitbreaker/consumer
```

验证自动注册一个动态端口的 `polaris-python-e2e-circuitbreaker-<年月日时分秒毫秒>` Provider，
并启动动态本机端口的 Consumer。Consumer 不注册实例，但会从真实注册中心发现、调用、
上报结果并销毁 context。

成功效果为 HTTP 200、`circuit_state: closed`、Provider 反注册。最终 JSON 展示
实际 instance ID、host/port、consumer_port 和 `effect`。完整说明见
[真实服务验证说明](../../README-zh.md#真实服务验证)。
