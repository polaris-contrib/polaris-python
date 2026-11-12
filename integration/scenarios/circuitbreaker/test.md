# circuitbreaker 测试说明

本目录验证 SDK 的本地实例熔断、路由回退、HTTP 结果分类、请求 ID 传播、同步/异步调用和
资源销毁。验证保留真实 SDK、真实本机 HTTP 服务及真实定时器，只替换注册中心 gRPC
stub，因此不依赖外部 Polaris。

## 测试拓扑

### 拉起进程

| 阶段 | 进程与生命周期 |
| --- | --- |
| 离线 | 1 个验证器进程；两个 Provider HTTP listener、Consumer HTTP listener 和 SDK context 均为进程内任务，不启动额外业务子进程。 |
| 远端 | 1 个验证器进程 + 1 个 Provider 子进程 + 1 个 Consumer 子进程；两者在验证后保持运行。 |

### 创建服务与实例

| 阶段 | 服务 | 实例 |
| --- | --- | --- |
| 离线 | `default/CircuitBreakerCallee` | 2 个 Provider 实例，`127.0.0.1:<动态端口>`，ID `instance-<端口>`，TTL 1 秒；Consumer 不注册。 |
| 远端 | `polaris-python-integration/circuitbreaker-callee-<时间>` | 1 个 Provider 实例，host 为路由源 IP，动态端口，TTL 3 秒。 |
| 远端 | `polaris-python-integration/circuitbreaker-caller-<时间>` | 1 个 Consumer HTTP 前端实例，host 为路由源 IP，动态端口。 |

### 服务访问与验证

| 访问关系 | 验证内容 |
| --- | --- |
| 验证器/Consumer → Provider | 通过 ConsumerAPI 发现 callee，向 `/echo`、`/switch` 等真实 HTTP 入口发起请求，并传播 request ID。 |
| Consumer → 调用结果仓库 | 200/404/500、超时和传输失败都上报结果，驱动实例熔断状态机。 |
| Consumer → load balancer | 故障实例打开后只路由健康实例；全开时验证全死全活兜底。 |
| SDK event reporter → Pushgateway | Open、HalfOpen、Close 三个事件 POST 到 `<host>:9091/polaris/client/events`。 |
| 验证器 → Consumer endpoints | 检查 `/instances`、熔断状态和最终恢复为 `closed`。 |

## 脚本作用

下列入口都在仓库的 `integration/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行完整的 10 场景熔断验证。 |
| `logs.sh` | 查看控制台、验证输出和按类别拆分的 SDK 日志。 |
| `cleanup.sh` | 停止本目录及 Provider/Consumer 子 demo 的已记录进程并清理产物；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有手动示例入口；从仓库根目录使用
`make -C examples run DEMO=circuitbreaker/provider` 或 `circuitbreaker/consumer`。

## 验证环境

验证器注册两个临时 Provider：

- `provider-a` 默认返回 HTTP 200；
- `provider-b` 可切换到 HTTP 500；
- 两者使用不同端口、独立 config、日志目录和缓存目录；
- 注册、心跳、发现流和反注册由可观察的 `RegistryStub` 处理；
- Provider 和 Consumer 的 HTTP 服务均为本机真实进程内服务器。

Consumer 使用不同规则创建多个 context，包括连续失败、错误率、半开成功数、
sleep window、默认规则关闭和异步调用。每个 context 使用独立日志与缓存。

## 离线验证

1. HTTP 200/404 分类与请求 ID：
   Provider 即使在 404 时熔断状态仍保持 `closed`，响应正文中的 request ID 与请求一致。
2. 连续失败只打开故障实例：
   配置连续失败阈值为 3；故障实例进入 `open` 后，后续调用只路由到健康实例。
3. 半开许可限制：
   配置半开许可数为 2；前两个请求可以占用许可，恢复失败时实例立即重新打开。
4. 真实 sleep timer 与恢复：
   等待真实计时器进入 `half_open`；配置的成功数达到 2 后实例转为 `closed`。
5. 错误率与最小样本：
   在滑动窗口内构造 3 次成功、3 次失败，检查最小样本和 50% 错误率规则；
   到达真实 deadline 后才进入 `open`。
6. 全死全活兜底：
   两个实例都打开时，最终路由仍选择一个实例，避免没有可用节点的空调用。
7. 异步调用和禁用默认规则：
   连续异步失败时，默认规则关闭的实例保持 `closed`，且不创建熔断定时器。
8. 启用默认规则的异步熔断：
   异步调用达到阈值后进入 `open`；服务恢复后经过半开和一次成功回到 `closed`。
9. 传输失败与反注册：
   Provider 关闭后调用返回 `-1`；两个 Provider 均从 fake registry 删除并完成反注册。
10. 独立资源清理：
    检查每个 context、事件循环线程、cache 写入线程、锁文件、熔断计时器、
    发现流、注册状态和日志句柄均已关闭。

任一断言失败会抛出异常并返回非零退出码。成功时输出 10 行 `PASS`，最后输出 JSON
汇总 `passed_scenarios`、context 数量以及注册/反注册实例列表。

## 执行和结果

```bash
./integration/verify.sh --only circuitbreaker
./integration/logs.sh --latest --tail 80
./integration/logs.sh --latest --category circuitbreaker --tail 80
./integration/cleanup.sh --dry-run
```

验证大约需要十余秒，因为半开和错误率检查依赖真实时间窗口。每次执行创建独立
`integration/.logs/circuitbreaker/verify-<时间>-<编号>/`，其中保存：

- `console.log` 和 `verification.log`；
- `provider-a/`、`provider-b/`、`caller/` 等场景的工作文件；
- `polaris/log/<context>/<category>/` 分类日志；
- `polaris/backup/<context>/` 下的 cache 和锁文件；
- `result.json` 退出结果。

验证失败时日志仍然保留。外部注册中心和真实远端的联调使用
`integration/verify_e2e.sh`；公开 Provider/Consumer 示例可直接通过
`make -C examples run DEMO=...` 运行。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 10 个场景的 `PASS`/`FAIL`、Provider 端口、HTTP 结果、注册/反注册 JSON 和异常。 |
| `result.json` | `exit_code`、`timed_out`、`interrupted` 和动作；仅退出码 0 且未超时、未中断为正常成功。 |
| `verification.log` | 熔断断言、JSON 汇总和 traceback，是定位第一个失败场景的首选文件；`make -C examples run` 通常不生成。 |

实际 SDK 日志在 `polaris/log/<context>/`，cache 和锁文件在同级 `polaris/backup/<context>/`。
建议按 `result.json` → `verification.log` → `console.log` → `polaris/log/` → `polaris/backup/`
顺序排查。完整说明见[执行产物与解读](../../test.md#执行产物与解读)。

## 注册服务与实例

验证器在 fake registry 中注册两个业务实例：

| 项目 | 值 |
| --- | --- |
| namespace/service | `default/CircuitBreakerCallee` |
| 实例数 | 2 |
| host | 两者均为 `127.0.0.1` |
| port | 两者都以 `0` 启动，实际端口动态分配 |
| instance ID | `instance-<实际端口>` |
| TTL | 1 秒 |
| 服务令牌 | `example-token` |
| Consumer | 不注册业务实例；HTTP 前端使用动态端口 |

两个实际 Provider 端口会出现在 `console.log` 的注册 JSON 和 HTTP 场景输出中；fake
registry 地址是 `offline.invalid:8091`，stub 会断言该地址并替代远端连接。

手动运行时，Provider 默认注册 `default/CircuitBreakerCallee`，host 使用
`get_local_host(POLARIS_SERVER_ADDRESS)`、port `18081`、TTL 5 秒。
Provider 和 Consumer 的默认监听端口都是 `18081`，同时运行时需给其中至少一个
显式传入不同 `--port`。

## 远端验证

这一路不替换 gRPC，也不跑离线的十个熔断场景，但会真实触发核心状态机和事件上报。
`--only circuitbreaker`、`circuitbreaker/provider` 和 `circuitbreaker/consumer`
是同一套检查，日志落在各自目录。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./integration/verify_e2e.sh --only circuitbreaker
```

命名空间默认 `polaris-python-integration`。Provider 注册为
`circuitbreaker-callee-<年月日时分秒毫秒>`，Consumer 的 HTTP 前端注册为
`circuitbreaker-caller-<年月日时分秒毫秒>`。两个服务各有一个实例，端口均动态分配。

步骤：

1. 启动 Provider，在 callee 服务注册实例。`--port 0`，`--status 200`，`--ttl 3`。注册 host 通过
   `get_local_host(POLARIS_SERVER_ADDRESS)` 得到，必须是本机到 Polaris 的路由源 IP。
   初始返回 HTTP 200，进程保持运行并心跳。
2. 每 0.5 秒用不带缓存的发现确认 instance id，最多 20 秒。
3. Consumer 监听动态端口，并把该 HTTP 前端注册为 `circuitbreaker-caller-*` 实例。
   使用本次运行目录中的临时 YAML，把检查周期设为 `1s`、sleep window 设为 `2s`、
   连续失败阈值设为 3、半开成功阈值设为 2。
4. 先确认实例为 `closed`，再通过 Provider 的 `/switch?openError=true` 返回 HTTP 500，
   连续触发 3 次失败。
5. 等待本地熔断进入 `open`；sleep window 到期后等待进入 `half_open`。
6. 把 Provider 切回 HTTP 200，连续成功 2 次，确认恢复为 `closed`。
7. 每个 Context 都启用事件 Pushgateway。验证器检查 event 日志中出现
   `reported event to Pushgateway`，且事件分别为 `CircuitBreakerOpen`、
   `CircuitBreakerHalfOpen`、`CircuitBreakerClose`。Pushgateway 地址取自 Polaris host
   的 `9091` 端口。

通过条件是状态序列为 `closed → open → half_open → closed`，三个熔断事件都收到
Pushgateway 2xx 响应。JSON 的 `services` 分别包含 caller 和 callee 服务名，
`caller` 与 `provider` 分别包含实例 ID、host 和端口，另含 `circuit_states`、
`reported_events` 和 `consumer_port`。
`./integration/cleanup.sh --force` 停进程，`--delete-services` 删服务。
