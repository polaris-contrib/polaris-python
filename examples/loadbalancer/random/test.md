# loadbalancer/random 测试说明

本目录验证 `random` 负载均衡器按实例数量均匀选择，不受实例权重影响。异步和同步 API
全部使用真实 SDK 路径。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 使用 fake registry RPC 执行确定性随机选择验证。 |
| `run.sh` | 对真实注册中心执行异步和同步随机选择。 |
| `logs.sh` | 查看保留输出和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
POLARIS_SERVER=<host>:8091 POLARIS_TOKEN= \
  make -C examples/loadbalancer/random run ARGS="default demo 3 --interval 0"
```

示例先做 `<times>` 次异步选择，每次上报一次结果；随后打印 `use sync method`，
再做相同次数的同步选择。`--interval` 控制异步选择间隔。

## 离线验证

验证器替换 `GrpcConnection._stub`，提供端口 8081/8082 两个实例，权重分别为 99 和 1。
为了防止“40 次偶然只选一个实例”造成 flaky，验证器固定
`polaris.plugin.load_balancer.random.randint` 的索引序列为 0、1 交替。

在真实 context 中执行：

- 异步选择 40 次；
- 同步选择 40 次；
- 每次选择后调用相应的结果上报 API；
- 捕获上报的实例 ID。

最终断言：

- 异步和同步各上报 40 次；
- 每个阶段 8081、8082 各被选择 20 次；
- 负载均衡配置确实为 `random`；
- context 已销毁，事件循环线程和 cache 写线程停止；
- 所有 SDK 日志句柄关闭。

成功时输出 `weight_independent: true`、`reported_once_per_call: true` 和
`context_destroyed: true`。

## 执行和日志

```bash
./examples/verify.sh --only loadbalancer/random
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

失败包括选择次数不对、两个实例分布不符合固定序列、上报次数不正确、配置类型不是
`random` 或线程/日志未释放。SDK 日志在 `.logs/verify-*/polaris/log/`，cache 和锁文件在
同级 `polaris/backup/`；所有产物在运行结束后都可直接查看。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 80 次实例选择、异步/同步切换、`PASS`/`FAIL` 和异常。 |
| `result.json` | 验证入口的退出码、超时和中断状态；分布或上报断言失败时非零。 |
| `verification.log` | 异步/同步各 20/20 分布、配置类型、context 和线程清理断言。 |

打印出的 host/port 是选择过程记录；最终结论以 `result.json` 和
`verification.log` 为准。完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

| 项目 | 值 |
| --- | --- |
| namespace/service | `ns/svc` |
| 实例 1 | ID `8081`，`127.0.0.1:8081`，权重 99 |
| 实例 2 | ID `8082`，`127.0.0.1:8082`，权重 1 |
| 注册实例 | 无 |
| fake registry | `offline:8091` |

random 按实例数量选择，因此固定随机索引后两个实例各选 20 次。验证器只创建客户端
context 和结果上报，不向 Polaris 注册服务实例。

## 远端验证

这一路不替换 gRPC，也不固定随机序列。只有一个真实实例，所以每次选择都应落到它上面。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only loadbalancer/random
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-loadbalancer-random-<年月日时分秒毫秒>`。demo 超时 30 秒。

步骤：

1. quickstart Provider 注册实例。动态端口，host 为建连时的本机 IP，TTL 1 秒，进程保持心跳。
2. 最多 20 秒，直到不带缓存的发现返回这个 instance id。
3. 本目录 `main.py` 参数为命名空间、服务名、`2`、`--interval 0`。异步选择 2 次，再同步选择 2 次。每次打印一行 `host:`，并上报一次成功结果。本 demo 不注册实例。
4. `host:` 行必须是 4 行，输出必须含 Provider 的 host 和 port。Provider 进程仍须存活。

通过条件是 `selected_calls` 为 4。离线的 40 次、两个实例各 20 次不在这一路。验证器不反注册。运行目录是 `.logs/verify-e2e-<时间>-<编号>/`，选择过程在 `random.stdout.log`。`./examples/cleanup.sh --force` 停 Provider，`--delete-services` 删服务。
