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

## verify.sh 如何验证

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

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only loadbalancer/wr
```

脚本创建一个 `polaris-python-e2e-loadbalancer-wr-<年月日时分秒毫秒>` Provider，host 为本机 IP，port
动态分配。weightedRandom Consumer 只发现和选择实例，执行两次异步和两次同步选择。

成功效果为 `selected_calls: 4`、输出包含真实 Provider host/port、context 销毁和
Provider 反注册。最终 JSON 包括临时 service 和 instance ID。完整说明见
[真实服务验证说明](../../README-zh.md#真实服务验证)。
