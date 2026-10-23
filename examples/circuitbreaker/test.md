# circuitbreaker 测试说明

本目录验证 SDK 的本地实例熔断、路由回退、HTTP 结果分类、请求 ID 传播、同步/异步调用和
资源销毁。验证保留真实 SDK、真实本机 HTTP 服务及真实定时器，只替换注册中心 gRPC
stub，因此不依赖外部 Polaris。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行完整的 10 场景熔断验证。 |
| `logs.sh` | 查看控制台、验证输出和按类别拆分的 SDK 日志。 |
| `cleanup.sh` | 停止本目录及 Provider/Consumer 子 demo 的已记录进程并清理产物；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有 `main.py`，不提供 `run.sh`。直接运行示例请进入 `provider/` 或
`consumer/`。

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
./examples/verify.sh --only circuitbreaker
./examples/logs.sh --latest --tail 80
./examples/logs.sh --latest --category circuitbreaker --tail 80
./examples/cleanup.sh --dry-run
```

验证大约需要十余秒，因为半开和错误率检查依赖真实时间窗口。每次执行创建独立
`.logs/verify-<时间>-<编号>/`，其中保存：

- `console.log` 和 `verification.log`；
- `provider-a/`、`provider-b/`、`caller/` 等场景的工作文件；
- `polaris/log/<context>/<category>/` 分类日志；
- `polaris/backup/<context>/` 下的 cache 和锁文件；
- `result.json` 退出结果。

验证失败时日志仍然保留。外部注册中心和真实远端的联调不应使用本 `verify.sh`，
而应通过 Provider/Consumer 的 `run.sh` 并按各自 README 设置 `POLARIS_E2E`。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 10 个场景的 `PASS`/`FAIL`、Provider 端口、HTTP 结果、注册/反注册 JSON 和异常。 |
| `result.json` | `exit_code`、`timed_out`、`interrupted` 和动作；仅退出码 0 且未超时、未中断为正常成功。 |
| `verification.log` | 熔断断言、JSON 汇总和 traceback，是定位第一个失败场景的首选文件；`run.sh` 通常不生成。 |

实际 SDK 日志在 `polaris/log/<context>/`，cache 和锁文件在同级 `polaris/backup/<context>/`。
建议按 `result.json` → `verification.log` → `console.log` → `polaris/log/` → `polaris/backup/`
顺序排查。完整说明见[测试产物说明](../README-zh.md#测试产物)。

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

手动运行时，Provider 默认注册 `default/CircuitBreakerCallee`，host
`127.0.0.1`、port `18081`、TTL 5 秒。Provider 和 Consumer 的默认监听端口都是
`18081`，同时运行时需给其中至少一个显式传入不同 `--port`。

## 远端验证

这一路不替换 gRPC，也不跑离线的十个熔断场景。`--only circuitbreaker`、`circuitbreaker/provider` 和 `circuitbreaker/consumer` 是同一套检查，日志落在各自目录。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only circuitbreaker
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-circuitbreaker-<年月日时分秒毫秒>`。

步骤：

1. 启动 Provider。`--host 127.0.0.1`，`--port 0`，`--status 200`，`--ttl 3`。它只返回 HTTP 200，进程保持运行并心跳。
2. 每 0.5 秒用不带缓存的发现确认 instance id，最多 20 秒。
3. Consumer 监听动态端口。验证器请求 `GET /echo`，要求状态 200、JSON 里 `ret_code` 为 200、`circuit_state` 为 `closed`。
4. 再请求 `GET /instances`，要求状态 200、只有 1 个实例，且 `instance_id` 等于注册结果。
5. 两个进程都必须仍在运行。验证器不反注册，也不上报 500 去打开熔断。

通过条件是 `circuit_state` 为 `closed`。JSON 含 service、provider instance id、host、port、`consumer_port`。连续失败、错误率、半开、全死全活和真实 sleep window 只在离线验证里。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
