# circuitbreaker Consumer 测试说明

`integration/verify.sh --only circuitbreaker/consumer` 执行父级完整熔断验证，覆盖真实
Consumer HTTP 前端、同步和异步
实例选择、调用结果上报、熔断状态和恢复流程。

## 测试拓扑

### 拉起进程

| 阶段 | 进程与生命周期 |
| --- | --- |
| 离线 | 1 个验证器进程；Consumer HTTP 前端、两个 Provider listener 和 SDK context 均在进程内。 |
| 远端 | 跑父级完整场景：1 个验证器 + 1 个 Provider 子进程 + 1 个本 Consumer 子进程。 |

### 创建服务与实例

| 阶段 | 服务 | 实例 |
| --- | --- | --- |
| 离线 | `default/CircuitBreakerCallee` | fake registry 提供 2 个 Provider 实例；Consumer 不注册。 |
| 远端 | `polaris-python-integration/circuitbreaker-callee-<时间>` | 1 个 callee 实例，供 Consumer 发现和调用。 |
| 远端 | `polaris-python-integration/circuitbreaker-caller-<时间>` | 1 个 caller 实例，对应 Consumer HTTP 前端。 |

### 服务访问与验证

| 访问关系 | 验证内容 |
| --- | --- |
| 验证器 → Consumer `/echo` | 请求 Consumer 前端，Consumer 通过 Discover 选择 callee 并发起真实 HTTP。 |
| Consumer → callee | 200/404/500 和请求 ID 透传决定成功、失败和熔断状态。 |
| Consumer → 调用结果仓库 | 每次调用后上报 ret_code、状态和延迟，驱动本地实例熔断。 |
| 验证器 → Consumer `/instances` | 检查缓存实例、fault 状态和最终 `closed`。 |
| 服务之间 | caller 是被调用入口，callee 是下游；不反向调用 caller。 |

## 脚本作用

下列入口都在仓库的 `integration/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 调用父级 10 场景熔断验证，产物保存在本目录。 |
| `make -C examples run` | 启动一个可被 HTTP 调用的 Consumer 前端。 |
| `logs.sh` | 查看控制台和 Consumer SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## make -C examples run

```bash
make -C examples/circuitbreaker/consumer run ARGS="--namespace default --service CircuitBreakerCallee"\
  --port 18081 --call-timeout 2
```

Consumer 提供：

- `GET /echo`：选择一个实例、发起 HTTP 调用并上报结果；
- `GET /instances`：返回缓存实例及当前熔断状态；
- `POST /echo-with-body`：从 JSON 请求指定 namespace/service；
- 收到 SIGTERM/SIGINT 时等待 HTTP handler 结束并销毁 context。

真实远端运行需要 `POLARIS_SERVER_ADDRESS=<host>:8091`；Consumer 还需要可发现的
Provider。复杂断言由 `integration/fixtures/circuitbreaker_consumer.py` 承担。

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
./integration/verify.sh --only circuitbreaker/consumer
./integration/logs.sh --latest --category circuitbreaker --tail 80
./integration/logs.sh --latest --tail 80
./integration/cleanup.sh --dry-run
```

完整状态转换和断言见[父目录测试说明](../test.md)。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | Consumer 启动、实例选择、熔断状态、HTTP 状态、上报和异常。 |
| `result.json` | `verify`/`run` 的退出码、超时和中断状态；人工停止常驻进程会记录 `interrupted`。 |
| `verification.log` | 完整熔断场景断言和 traceback；`make -C examples run` 通常没有此文件。 |

SDK 分类日志在 `polaris/log/consumer/`，cache 和锁文件在同级 `polaris/backup/consumer/`。
完整解释见[执行产物与解读](../../../test.md#执行产物与解读)。

## 注册服务与实例

离线验证中的 Consumer 不注册业务服务实例，只创建 SDK context 并发现以下实例：

| 项目 | 值 |
| --- | --- |
| 发现 namespace/service | `default/CircuitBreakerCallee` |
| Provider 实例数 | 2 |
| Provider host | `127.0.0.1` |
| Provider port | 动态分配，ID 为 `instance-<实际端口>` |
| Consumer HTTP 端口 | 离线验证时为动态端口 |
| 手动运行默认端口 | `18081` |

离线验证中 Consumer 会发送 client/report 数据并上报调用结果，但不会创建业务实例。
真实 E2E 会为 Consumer HTTP 前端启用 `--caller-service`，并注册一个 caller 实例。
默认 `18081` 与 Provider 默认端口相同；同机同时运行时应显式选择不同端口。

## 远端验证

`--only circuitbreaker/consumer` 和父目录跑同一套场景，运行产物写入
`integration/.logs/circuitbreaker/verify-e2e-<时间>-<编号>/`。不跑离线的十个熔断场景。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./integration/verify_e2e.sh --only circuitbreaker/consumer
```

命名空间默认 `polaris-python-integration`。Provider 注册为
`circuitbreaker-callee-<年月日时分秒毫秒>`，Consumer HTTP 前端注册为
`circuitbreaker-caller-<年月日时分秒毫秒>`。

步骤：

1. 父目录 Provider 以 `127.0.0.1`、动态端口、HTTP 200、TTL 3 秒注册，并保持心跳。
2. 最多 20 秒，直到不带缓存的发现看到这个 instance id。
3. 本目录 Consumer 监听动态端口，并把该端口注册到 `circuitbreaker-caller-*`。
   验证器请求 Consumer 的 `/echo`，要求 HTTP 200、`ret_code` 200、
   `circuit_state` 为 `closed`。
4. `/instances` 必须只有这一个实例，且 id 与注册结果相同。
5. 验证器切换 callee 失败并恢复，覆盖 Open、HalfOpen、Close 和事件上报。
6. caller 与 callee 两个进程保持运行，服务对象和实例保留到显式 cleanup。

通过条件是 `circuit_state` 为 `closed`。半开和错误率只在离线验证。
`./integration/cleanup.sh --force` 停进程，`--delete-services` 删服务。
