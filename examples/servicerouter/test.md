# 服务路由测试说明

本目录验证 Python SDK 已按 Java SDK 的三段路由链结构执行实例筛选：

- `beforeChain` 默认为 `isolatedRouter`，剔除隔离实例和权重为 0 的实例；
- `chain` 默认为空，`metadataRouter` 不默认参与路由；
- `afterChain` 默认为 `recoverRouter`，剔除不健康和已熔断实例，并在全部不可用时执行全死全活回退。

`metadataRouter` 是显式开启的业务路由插件。开启后按请求 metadata 的全部 key/value 精确匹配，
支持 `none`、`all`、`others` 三种降级策略。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 使用 fake registry RPC 验证默认链、metadata 精确匹配、others 降级和全死全活。 |
| `run.sh` | 对真实注册中心执行异步和同步实例选择。 |
| `logs.sh` | 查看本目录保留的控制台、验证和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

默认链示例：

```bash
POLARIS_SERVER=<host>:8091 POLARIS_TOKEN= \
  make -C examples/servicerouter run ARGS="default demo 3 --interval 0"
```

显式开启 `metadataRouter` 并按 `env=prod` 过滤：

```bash
POLARIS_SERVER=<host>:8091 POLARIS_TOKEN= \
  make -C examples/servicerouter run \
    ARGS="default demo 3 --mode metadata --metadata env=prod --failover none --interval 0"
```

示例先执行 `<times>` 次异步选择，每次打印 `host` 和 `port` 并上报一次成功调用结果；
随后打印 `use sync method`，再执行相同次数的同步选择。`--mode` 可选 `default` 和
`metadata`；`--metadata` 可重复传入 `KEY=VALUE`；`--failover` 仅在 metadata 路由中生效。

## verify.sh 如何验证

验证器替换 `GrpcConnection._stub`，保留真实 SDK context、路由插件、缓存线程、负载均衡和
结果上报 API。fake registry 提供以下实例：

| 实例 ID | 端口 | 状态 | 权重 | metadata |
| --- | --- | --- | --- | --- |
| `isolated` | 8081 | 健康 | 100 | 无 |
| `zero-weight` | 8082 | 健康 | 0 | 无 |
| `prod` | 8083 | 健康 | 100 | `env=prod` |
| `stable` | 8084 | 健康 | 100 | `env=stable` |
| `unhealthy-prod` | 8085 | 不健康 | 100 | `env=prod` |
| `missing` | 8086 | 健康 | 100 | 无 |

验证顺序和断言如下：

1. 默认链：`beforeChain=[isolatedRouter]`、`chain=[]`、`afterChain=[recoverRouter]`。
   异步和同步各选择 2 次，所有被选择实例必须来自健康候选，隔离、权重 0 和不健康实例不能被选择。
2. 显式开启 metadata：`chain=[metadataRouter]`，请求 `env=prod` 且 failover 为 `none`。
   异步和同步各选择 2 次，每次都必须选中 `prod`。
3. others 降级：请求 `env=missing` 且 failover 为 `others`。没有实例的 metadata 匹配该值时，
   返回不包含请求 key 的 `missing` 实例。
4. 全死全活：fake registry 只返回两个不健康实例。`recoverRouter` 过滤后为空，按配置回退全部输入，
   异步和同步各完成 2 次选择。

验证器同时断言：

- 每次选择后调用一次对应的结果上报 API；
- `metadataRouter` 只有显式配置后才进入主链；
- 四个场景的 context 均已销毁；
- owner loop 线程和 cache 写线程停止；
- 所有 SDK 日志句柄关闭。

成功时输出 JSON，包含 `metadata_router_opt_in: true`、`metadata_exact_match: ["prod"]`、
`metadata_others_failover: ["missing"]`、`all_down_recovery: true` 和
`context_destroyed: true`。

## 执行和日志

```bash
./examples/verify.sh --only servicerouter
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category route --tail 50
./examples/cleanup.sh --dry-run
```

失败包括默认链配置错误、隔离或不健康实例被选择、metadata 精确匹配失败、`others` 降级选择错误、
全死全活没有回退、上报次数不正确或线程和日志未释放。SDK 日志在 `.logs/verify-*/polaris/log/`，
cache 和锁文件在同级 `polaris/backup/`；所有产物在运行结束后都可直接查看。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 四个验证场景顺序、实例选择、`PASS`/`FAIL` 和异常。 |
| `result.json` | 验证入口的退出码、超时和中断状态；任何断言失败时非零。 |
| `verification.log` | 路由链配置、metadata 匹配结果、降级结果、上报次数和 context 清理断言。 |

实际 SDK 日志在 `polaris/log/`，每个场景使用独立 cache 目录，避免上一个场景的磁盘备份影响下一个场景。
完整说明见[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

离线验证不向 Polaris 注册业务服务，只从 fake registry 发现上表中的 6 个实例；SDK client 会执行
`ReportClient` 和调用结果上报。手动运行时，可用实例由目标 Polaris 返回。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only servicerouter
```

脚本注册一个唯一的动态端口 Provider，并等待实例可见。`servicerouter` demo 使用默认链执行
两次异步和两次同步选择，共 4 次并上报结果。成功效果为 `selected_calls: 4`，输出包含真实
Provider host/port、context 销毁和 Provider 反注册。
