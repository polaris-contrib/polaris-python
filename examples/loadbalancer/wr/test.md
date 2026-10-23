# loadbalancer/wr 测试说明

本目录验证 `weightedRandom` 负载均衡器通过真实插件执行异步和同步实例选择，并在每次
选择后上报调用结果。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 使用 fake registry RPC 验证异步和同步加权随机路径。 |
| `run.sh` | 对真实注册中心执行加权随机选择。 |
| `logs.sh` | 查看 console、验证和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
POLARIS_SERVER=<host>:8091 POLARIS_TOKEN= \
  make -C examples/loadbalancer/wr run ARGS="default demo 3 --interval 0"
```

示例先做异步选择，再切换为同步方法；每次选择打印 host/port 并上报成功结果。

## 离线验证

验证器只替换注册中心 RPC，提供两个实例：

- 端口 8081，权重 25；
- 端口 8082，权重 75。

示例本身在真实 context 中复用同一个 ConsumerAPI，异步和同步各选择 40 次。验证器
替换结果上报方法并记录实例 ID，然后断言：

- 异步和同步各产生 40 次上报；
- 每次上报的实例都来自测试集合；
- 实际 weightedRandom 插件完成选择，没有绕过负载均衡器；
- context 已销毁；
- 事件循环线程、cache 写线程均已停止；
- 日志类别中的文件句柄均已关闭。

该验证不固定随机数，因此不要求精确的 30/10 分布；它验证真实加权插件能够完成全部
调用，且每条调用路径都正确上报。成功输出 `sync_selections: 40`、
`async_selections: 40`、`reported_once_per_call: true` 和
`context_destroyed: true`。

## 执行和日志

```bash
./examples/verify.sh --only loadbalancer/wr
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

SDK 日志在本次运行的 `polaris/log/`，cache 和锁文件在同级 `polaris/backup/`；断言失败或超时都会返回
非零，产物仍会保留用于查看。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 异步/同步加权随机选择、实例 host/port、`PASS`/`FAIL` 和异常。 |
| `result.json` | 退出码、是否超时和是否被中断；正常成功要求退出码 0 且无超时/中断。 |
| `verification.log` | 选择与上报次数、context、cache writer 和日志句柄清理断言。 |

加权随机不要求固定的 25/75 分布，不能用 `console.log` 中实例出现次数单独判定失败。
完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

| 项目 | 值 |
| --- | --- |
| namespace/service | `ns/svc` |
| 实例 1 | ID `8081`，`127.0.0.1:8081`，权重 25 |
| 实例 2 | ID `8082`，`127.0.0.1:8082`，权重 75 |
| 注册实例 | 无 |
| fake registry | `offline:8091` |

验证器不注册业务实例，只创建 Consumer context、发现两个 fake 实例并上报选择结果。

## 远端验证

这一路不替换 gRPC。只有一个真实实例，权重分布无法观察，只检查 weightedRandom 能选中它。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only loadbalancer/wr
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-loadbalancer-wr-<年月日时分秒毫秒>`。demo 超时 30 秒。

步骤：

1. quickstart Provider 注册实例。动态端口，host 为建连时的本机 IP，TTL 1 秒，进程保持心跳。注册请求里的 weight 使用 Provider 默认值，不是离线的 25/75。
2. 最多 20 秒，直到不带缓存的发现返回这个 instance id。
3. 本目录 `main.py` 参数为命名空间、服务名、`2`、`--interval 0`。异步 2 次、同步 2 次，每次打印 `host:` 并上报一次成功结果。
4. `host:` 行必须是 4 行，输出必须含 Provider 的 host 和 port。Provider 进程仍须存活。

通过条件是 `selected_calls` 为 4。离线的 40 次和 30/10 权重分布不在这一路。验证器不反注册。运行目录是 `.logs/verify-e2e-<时间>-<编号>/`，选择过程在 `wr.stdout.log`。`./examples/cleanup.sh --force` 停 Provider，`--delete-services` 删服务。
