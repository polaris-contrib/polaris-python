# loadbalancer 测试说明

本目录汇总两种实例选择策略：

- `random`：按实例数量均匀随机，实例权重不参与；
- `wr`：按实例权重加权随机。

两个策略都同时验证异步 `async_get_one_instance()` 和同步 `get_one_instance()`，
并在每次选择后上报一次调用结果。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 依次运行 `random` 和 `wr`。 |
| `logs.sh` | 查看两个子 demo 的控制台、验证和 SDK 分类日志。 |
| `cleanup.sh` | 停止目录树内的已记录进程，删除 `.logs/` 和 `.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有 `main.py`，不提供 `run.sh`。

## 选择子场景

```bash
./examples/verify.sh
./examples/verify.sh --only loadbalancer/random
./examples/verify.sh --only loadbalancer/wr
./examples/verify.sh --only loadbalancer/random,loadbalancer/wr
```

## 离线验证

两个验证器都使用真实 SDK 插件、真实 context、缓存写线程和结果上报 API，只替换注册
中心的 discover/report RPC：

- random：提供权重 99/1 的两个实例，固定随机索引序列；
- wr：提供权重 25/75 的两个实例，使用实际 weightedRandom 插件；
- 两个策略的异步、同步各执行 40 次；
- 每次选择必须上报一次，且只使用两个测试实例。

random 额外断言两个实例各被选择 20 次，证明选择按实例数量均匀而不是按权重；
wr 验证加权插件能够在这组权重下完成真实选择并正确上报。

成功时两个子场景分别输出 JSON，包含选择次数、上报状态和 context 销毁状态。

## 执行和清理

```bash
./examples/verify.sh --only loadbalancer
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

默认汇总应输出 `2 passed, 0 failed`。两个 demo 的选择细节分别见
[`random/test.md`](random/test.md) 和 [`wr/test.md`](wr/test.md)。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | random/wr 子场景顺序、实例选择、`PASS`/`FAIL` 和异常。 |
| `result.json` | 每个子场景的退出码、超时和中断状态。 |
| `verification.log` | 选择次数、上报次数、实例分布、context 和线程清理断言。 |

实际 SDK 日志在 `polaris/log/`，cache 和锁文件在 `polaris/backup/`。完整说明见
[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

两个负载均衡验证都不注册实例，只从 fake registry 发现：

| 子场景 | namespace/service | 发现的实例 | 端口 | 权重 |
| --- | --- | --- | --- | --- |
| random | `ns/svc` | `8081`、`8082` | `127.0.0.1:8081`、`127.0.0.1:8082` | 99/1，但 random 忽略权重 |
| wr | `ns/svc` | `8081`、`8082` | `127.0.0.1:8081`、`127.0.0.1:8082` | 25/75 |

实例 ID 使用端口字符串。SDK client 会执行 `ReportClient` 和调用结果上报，但不会注册
业务服务。手动运行时，服务名以及可用实例端口由目标 Polaris 返回。

## 远端验证

`--only loadbalancer` 依次跑 random 和 wr。两个子目录的 `test.md` 写了各自的逐步说明。这一路不替换 gRPC，也不使用离线的两个固定权重实例。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only loadbalancer
./examples/verify_e2e.sh --only random
```

每个子场景单独注册一个 Provider：动态端口，host 是建连时的本机 IP，TTL 1 秒。等发现能看到该 instance id 后，demo 以次数 2、间隔 0 做 2 次异步选择和 2 次同步选择。通过条件都是输出里有 4 行 `host:`，并且含这次 Provider 的 host 和 port。`selected_calls` 为 4。

不检查 40 次分布，也不要求 30/10 或 20/20。Provider 保持运行，验证器不反注册。服务名分别是 `polaris-python-e2e-loadbalancer-random-<时间>` 和 `polaris-python-e2e-loadbalancer-wr-<时间>`，命名空间默认 `python-integration`。日志在各子目录的 `.logs/verify-e2e-<时间>-<编号>/`。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
