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

## 离线验证

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

## 远端验证

`--only circuitbreaker/consumer` 和父目录跑同一套场景，日志写在本目录 `.logs/verify-e2e-<时间>-<编号>/`。不跑离线的十个熔断场景。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only circuitbreaker/consumer
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-circuitbreaker-<年月日时分秒毫秒>`。

步骤：

1. 父目录 Provider 以 `127.0.0.1`、动态端口、HTTP 200、TTL 3 秒注册，并保持心跳。
2. 最多 20 秒，直到不带缓存的发现看到这个 instance id。
3. 本目录 Consumer 监听动态端口，自己不注册实例。验证器请求 `/echo`，要求 HTTP 200、`ret_code` 200、`circuit_state` 为 `closed`。
4. `/instances` 必须只有这一个实例，且 id 与注册结果相同。
5. 两个进程保持运行。验证器不上报失败，也不反注册。

通过条件是 `circuit_state` 为 `closed`。半开和错误率只在离线验证。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
