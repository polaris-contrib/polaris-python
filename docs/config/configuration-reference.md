# Configuration Reference

[polaris.yaml](polaris.yaml) 只包含最小必要配置。省略的字段会在初始化时使用
SDK 默认值。本文件说明字段含义、类型、格式、范围、默认值和注意事项。

约定：

- duration 可使用整数毫秒，或 `ns/us/ms/s/m/h` 组合，例如 `500ms`、`1s`、`1m30s`。
- 空字符串写 `""`，不要写 `null`。
- 字符串支持 `${ENV}`、`$ENV` 和 `${ENV:default}`。
- 环境变量优先级见 [environment-variables.md](environment-variables.md)。
- `[预留]` 表示字段可加载和校验，但能力尚未生效。

## global.system

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `mode` | int enum：`0`、`1` | `0` | `0` 直连 Polaris；`1` 代理模式尚未实现。 |
| `discoverCluster.namespace` | string | `""` | 服务发现系统集群命名空间。 |
| `discoverCluster.service` | string | `""` | 服务发现系统集群服务名。 |
| `discoverCluster.refreshInterval` | duration，>=100ms | `1m` | 系统服务后台 Discover 刷新周期。 |
| `healthCheckCluster.namespace` | string | `""` | 健康检查系统集群命名空间。 |
| `healthCheckCluster.service` | string | `""` | 健康检查系统集群服务名。 |
| `healthCheckCluster.refreshInterval` | duration，>=100ms | `1m` | 系统服务后台 Discover 刷新周期。 |
| `monitorCluster.namespace` | string | `""` | 监控集群命名空间；与 service 同时非空才启用。 |
| `monitorCluster.service` | string | `""` | 监控集群服务名；与 namespace 同时非空才启用。 |
| `monitorCluster.refreshInterval` | duration，>=100ms | `1m` | 监控集群刷新周期。 |

`discoverCluster` / `healthCheckCluster` / `monitorCluster` 的空 namespace/service
表示不装配对应系统服务。发现 / 心跳集群未配置时直接使用 `serverConnector.addresses`；
Prometheus push 仅在插件自身 namespace/service 未成对配置时使用监控集群。

## global.api

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `timeout` | duration，>0 | `1s` | 调用方等待第一次服务发现远端结果的时间预算。磁盘读取不计入；请求上的非 0 `timeout` 优先。 |
| `bindIP` | IP string | `""` | SDK 自身 IP，优先于 bindIf 和自动探测；不是实例注册 host。 |
| `bindIf` | 网卡名 string | `""` | 从指定网卡取 SDK 自身 IP；网卡不存在或无 IP 时启动失败。 |
| `reportInterval` | duration，>0 | `60s` | 向 `serverConnector.addresses` 发送 `ReportClient` 的周期。不是实例心跳，也不是 Pushgateway。 |
| `maxRetryTimes` | int，>=0 | `1` | 网络错误重试次数；显式 0 会回退为默认值。 |
| `retryInterval` | duration，>=500ms | `500ms` | 重试退避初始间隔。 |

`timeout` 包住第一次发现的整段远端等待和其中的重试。超时后若磁盘上已有合法备份，调用返回备份；没有备份则返回超时错误。之后的后台刷新不再受这次调用限制。注册、反注册、心跳和 `ReportClient` 的单次 RPC 超时使用 `serverConnector.messageTimeout`。服务契约请求的 `timeout` 大于 0 时，该次 RPC 使用请求值；为 0 时同样使用 `messageTimeout`。Prometheus push 的 HTTP 客户端总超时使用本字段。

`reportInterval` 上报 SDK 自身信息：`host`（`bindIP`、`bindIf` 或连向注册中心的本地出口地址）、`clientId`、固定类型 `SDK`、SDK 版本。Prometheus 为 pull 且监听已启动时，再附带一条 `stat`：`target=prometheus`、监听端口、`path`、`protocol=http`。`type=push` 或监听未启动时不带 `stat`。context 启动后先上报一次，后台每 10 秒检查是否到达周期。服务端响应中的 `region`、`zone`、`campus` 用来更新本地位置，请求本身不填写这些字段。

## global.serverConnector

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `addresses` | `list[string]`，`host:port` / `[IPv6]:port` | `[127.0.0.1:8091]` | Polaris gRPC 地址，至少 1 项。 |
| `protocol` | string | `grpc` | 当前只支持 gRPC。 |
| `token` | string | `""` | SDK 接入令牌，不是实例 service token。 |
| `connectTimeout` | duration，>0 | `500ms` | SDK 自身 IP TCP 探测超时。 |
| `messageTimeout` | duration，>0 | `5s` | 注册、反注册、心跳和 `ReportClient` 的单次 gRPC 超时。Discover 长连接不使用它。 |
| `connectionIdleTimeout` | duration，>=100ms | `60s` | Discover 流空闲回收周期；超时后关闭流，保留 gRPC channel。 |
| `requestQueueSize` | int，>=0 | `1000` | 服务端连接器请求排队容量；0 表示没有额外排队，最多 1 个在途请求。 |
| `serverSwitchInterval` | duration，>idle timeout | `10m` | 多地址轮换周期；切换时重建 Discover 流。 |
| `trustedCAFile` | PEM path | `""` | TLS 信任根；非空时校验服务端证书。 |
| `certFile` | PEM path | `""` | mTLS 客户端证书，必须与 keyFile 成对。 |
| `keyFile` | PEM path | `""` | mTLS 客户端私钥。 |
| `plugin` | map | `{}` | [预留] 当前 gRPC 连接器不读取插件参数。 |

某一台服务器在 `messageTimeout` 内没有返回时，按 `maxRetryTimes` 和 `retryInterval` 换地址重试。Discover 流的超时为空，空闲回收由 `connectionIdleTimeout` 控制。`connectTimeout` 只用于探测 SDK 自身 IP 的 TCP 连接。

证书缺失、PEM 无效或私钥不匹配会拒绝启动，不回退明文。

## global.admin

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | string | `0.0.0.0` | Prometheus pull 监听地址。 |
| `port` | int，`-1..65535` | `28080` | `-1` 关闭监听，`0` 分配临时端口。多 context 必须使用不同端口。 |

## global.eventReporter

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | bool | `false` | 开启远端事件上报。只发送 `InstanceThreadEnd` 与熔断事件；缓存生命周期事件和本地 event 日志始终保留。 |
| `chain` | `list[string]` | `[pushgateway]` | 当前仅支持 pushgateway。 |
| `plugin.pushgateway.address` | `list[string]` | `[]` | Pushgateway 地址；为空时通过 namespace/service 发现。 |
| `plugin.pushgateway.eventQueueSize` | int，>0 | `1000` | 内存事件队列容量。 |
| `plugin.pushgateway.maxBatchSize` | int，>0 | `100` | 单批最大事件数。 |
| `plugin.pushgateway.namespace` | string | `Polaris` | 服务发现命名空间。 |
| `plugin.pushgateway.service` | string | `polaris.pushgateway` | 服务发现服务名。 |
| `plugin.pushgateway.reportPath` | absolute path | `/polaris/client/events` | 事件 HTTP 上报路径。 |
| `plugin.pushgateway.pushInterval` | duration，>0 | `1s` | 批量上报周期。 |
| `plugin.pushgateway.maxRetries` | int，>0 | `3` | 单批 HTTP 失败后的额外尝试次数。 |
| `plugin.pushgateway.retryInterval` | duration，>=0 | `1s` | 重试间隔。 |
| `plugin.pushgateway.overrideHost` | string | `""` | 替换上报 URL 的 host，保留端口和路径。 |

## global.statReporter

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | bool | `true` | 是否启用 Prometheus 统计。 |
| `chain` | `list[string]` | `[prometheus]` | 支持 `[prometheus]`；`[pushgateway]` 是 push 模式别名。 |
| `plugin.prometheus.type` | enum：`pull`、`push` | `pull` | pull 启动 HTTP 监听；push 主动推送。 |
| `plugin.prometheus.path` | absolute path | `/metric` | pull 指标路径。 |
| `plugin.prometheus.address` | `list[string]` | `[]` | Pushgateway 地址；为空时先使用下方 namespace/service，未成对配置时使用 monitorCluster。 |
| `plugin.prometheus.namespace` | string | `Polaris` | Pushgateway 服务发现命名空间。 |
| `plugin.prometheus.service` | string | `polaris.pushgateway` | Pushgateway 服务发现服务名。 |
| `plugin.prometheus.pushInterval` | duration，>=1s | `10s` | Push 周期。 |
| `plugin.prometheus.openGzip` | bool | `false` | Push 请求是否 gzip。 |
| `plugin.prometheus.pathRegexList` | `list[regex]` | `[]` | 按顺序完整匹配 method，以正则文本作为低基数标签。 |
| `plugin.prometheus.overrideHost` | string | `""` | 覆盖上报 host 标签。 |

详细行为见 [可观测性](../observability.md)。

公有云部署当前优先使用 `chain: [pushgateway]` 和 `type: push`。
自建环境可使用 Prometheus pull。

## provider

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `minRegisterInterval` | duration，>0 | `30s` | 连续 `400202` 后自动重注册的最小间隔。 |

## consumer.localCache

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `type` | string | `inmemory` | 当前内存缓存类型。 |
| `serviceExpireTime` | duration，>=5s | `24h` | 业务读取后续期的闲置淘汰时间。 |
| `serviceRefreshInterval` | duration，>0 | `2s` | 后台 Discover 刷新周期。 |
| `persistDir` | path | `./polaris/backup` | 磁盘备份目录，相对当前工作目录。 |
| `persistMaxWriteRetry` | int，>=0 | `1` | 写入/删除额外重试次数；0 回退默认值。 |
| `persistMaxReadRetry` | int，>=0 | `0` | 读取额外重试次数；0 回退默认值，即不额外重试。 |
| `persistRetryInterval` | duration，>=0 | `500ms` | 磁盘重试间隔。 |
| `plugin` | map | `{}` | [预留] 当前无参数。 |

系统服务不参与闲置淘汰。不同注册中心建议使用不同 persistDir。

## consumer.serviceRouter

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `beforeChain` | `list[string]` | `[isolatedRouter]` | 前置链，不能为空；剔除隔离和零权重实例。 |
| `chain` | `list[string]` | `[metadataRouter]` | 主链。未带请求 metadata 时该路由不筛选；空列表回退这个默认值。 |
| `afterChain` | `list[string]` | `[recoverRouter]` | 后置链，不能为空；处理不健康和熔断实例。 |
| `percentOfMinInstances` | float，`[0,1)` | `0.0` | [预留] 当前路由插件不读取。 |
| `plugin` | map | `{}` | 路由插件参数。 |

`plugin.metadataRouter.metadataFailOverType`：

- 类型：enum string
- 可选值：`none`、`all`、`others`
- 默认值：`all`
- 说明：无匹配时，`all` 返回原集合，`others` 返回缺少任一请求 key 的实例，
  `none` 抛出路由不匹配错误。
- 别名：`metadata_fail_over_type`
- 优先级：请求 `metadata_failover_type` > 服务 `internal-metadata-failover-type` >
  插件参数。

`plugin.recoverRouter.excludeCircuitBreakInstances`：

- 类型：bool
- 默认值：`true`
- 说明：是否排除 Open 熔断实例；不健康实例始终排除。
- 别名：`exclude_circuit_break_instances`

`plugin.recoverRouter.allRecoverEnable`：

- 类型：bool
- 默认值：`true`
- 说明：过滤后为空时是否回退到进入 recoverRouter 前的实例集合。
- 别名：`all_recover_enable`

## consumer.loadbalancer

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `type` | string | `weightedRandom` | 支持 `weightedRandom`、`random`；`wr` 会规范化。 |
| `plugin` | map | `{}` | [预留] 当前无参数。 |

只有单实例发现 API 执行负载均衡。

## consumer.circuitBreaker

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | bool | `true` | 熔断总开关。 |
| `checkPeriod` | duration，>=1s | `1m` | 后台补充检查周期。 |
| `sleepWindow` | duration，>=1s | `30s` | 打开到半开的等待时间。 |
| `successCountAfterHalfOpen` | int，>0 | `3` | 半开恢复成功数及请求配额；0 回退默认值。 |
| `defaultRuleEnable` | bool | `true` | 本地默认规则开关。 |
| `defaultErrorCount` | int，>0 | `10` | 连续失败阈值。 |
| `defaultErrorPercent` | int，`0..100` | `50` | 错误率百分比阈值。 |
| `defaultInterval` | duration，>0 | `60s` | 错误率窗口。 |
| `defaultMinimumRequest` | int，>0 | `10` | 错误率最小样本数。 |
| `chain` | `list[string]` | `[composite]` | 当前仅本地 composite；`err_count` 会规范化。 |
| `plugin` | map | `{}` | [预留] 当前无参数。 |

返回码 `500-599` 或 `-1` 计为失败。详见 [本地实例熔断](../circuitbreaker.md)。

## ai.skill.serverConnector

| 字段 | 类型 / 格式 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `connectorType` | string | `polaris` | 当前仅支持 Polaris Skill 服务。 |
| `protocol` | string | `grpc` | Skill 独立 gRPC 连接。 |
| `addresses` | `list[string]` | `[127.0.0.1:8094]` | 不读取主注册中心地址。 |
| `token` | string | `""` | Skill 接入令牌；空值时继承主连接 token，显式值优先。 |
| `trustedCAFile` | PEM path | `""` | Skill TLS 信任根。 |
| `certFile` | PEM path | `""` | Skill mTLS 客户端证书。 |
| `keyFile` | PEM path | `""` | Skill mTLS 客户端私钥。 |
| `messageTimeout` | duration，>0 | `5s` | Skill 查询、列表，以及非 ZIP 下载的单次 RPC 超时。与主连接的 `messageTimeout` 分开。 |
| `downloadTimeout` | duration，>0 | `30s` | ZIP 下载超时。 |
| `persistEnable` | bool | `true` | 是否持久化 Skill。 |
| `persistDir` | path | `./polaris/backup/skill` | Skill 独立备份目录。 |
| `persistMaxWriteRetry` | int，>=0 | `1` | 写入额外重试次数。 |
| `persistMaxReadRetry` | int，>=0 | `0` | 读取额外重试次数。 |
| `persistRetryInterval` | duration，>=0 | `500ms` | 磁盘重试间隔。 |
| `fallbackToLocalCache` | bool | `true` | 网络错误时是否读取本地备份。 |

Skill 行为见 [AI Registry](../ai-registry.md)，TLS 见 [TLS](../tls.md)。
