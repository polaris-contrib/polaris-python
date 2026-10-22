# Polaris Python SDK

MCP 注册/发现和已发布 Skill 的只读查询、下载见 [AI registry 接口](docs/ai-registry.md)。
MCP 服务复用普通 `Instance` 缓存，Skill 使用独立连接并支持网络失败时的本地备份降级。
普通 A2A metadata 见 [A2A 示例](examples/a2a/README-zh.md)。
[可观测性](docs/observability.md) 支持调用上报、Prometheus 拉取与 Pushgateway 推送；
注册发现和 Skill 连接分别支持 [TLS](docs/tls.md)，证书配置错误不降级明文。

[English](README.md)

Polaris Python SDK 是北极星服务治理的 Python 客户端。它通过 gRPC 连接 Polaris，
协议桩来自 [`polarismesh-specification`](https://github.com/polarismesh/specification)。

发行包名是 `polaris-python`，导入包名是 `polaris`。

## 环境要求

- Python 3.12 及以上
- `grpcio>=1.84.0`
- `protobuf>=7.35.1,<8`
- `polarismesh-specification==1.9.0.dev4`
- `PyYAML>=6.0.2,<7`

本仓库不保存 `.proto` 或生成的 `*_pb2.py`，这些文件由 `polarismesh-specification` 提供。

## 安装

在本仓库检出目录中：

```bash
uv sync --group dev --locked
uv run pytest
```

本项目采用 `src` 源码布局。开发时先执行上面的 `uv sync`，它会将
`src/polaris/` 以可编辑方式安装到项目环境；修改源码后直接生效。
源码目录位置不属于导入名，应用仍使用 `import polaris`。

## 目录

```text
src/polaris/
├── api/                 # SDKContext、ProviderAPI、ConsumerAPI
├── pkg/
│   ├── common/          # 插件公共约定
│   ├── config/          # Configuration、默认值、YAML 与环境变量加载
│   ├── flow/            # Engine 与调用流程
│   ├── model/           # 请求、响应、实例、规则和错误
│   └── version/         # SDK 版本
├── plugin/
│   ├── circuit_breaker/  # 熔断契约与实现
│   ├── load_balancer/    # 负载均衡契约与实现
│   ├── local_registry/   # 内存和文件缓存注册表
│   ├── server_connector/ # gRPC 连接器
│   └── service_router/   # 服务路由
└── plugin_manager.py
```

SDK 默认路径与 Go 保持一致：日志为 `./polaris/log/`，备份为 `./polaris/backup/`，
相对当前工作目录解析。pytest 为每个测试切换到系统临时目录，默认运行文件也留在
该目录；demo 日志使用各自的 `.logs/`。测试和 demo 的运行文件与源码隔离。
源码位于 `src/polaris/`；从仓库根目录运行时，默认 `polaris/log/` 和
`polaris/backup/` 与源码是两个独立目录。源码包仍叫 `polaris`，使用 `import polaris`。

业务应用从源码检出目录运行时，可显式设置 `LogOptions(log_dir="./.polaris/log")`
及 `config.get_consumer().get_local_cache().persist_dir = "./.polaris/backup"`。
这些是应用自己的目录配置；SDK 默认值继续沿用 Go 语义。

## SDK 上下文

一个进程可以创建多个 `SDKContext`。每个上下文独立拥有 clientId、启动配置快照、
插件实例及订阅、连接、缓存、规则、后台任务和日志。需要共用同一个客户端时，
用同一个上下文创建 API；销毁一个 context 不影响另一个，即使两者连接同一地址。

`create_provider_by_config()`、`create_consumer_by_config()` 和
`create_skill_by_config()` 各自创建一个新上下文。客户端不再使用时调用
`context.destroy()`。`ConsumerAPI.destroy()` 会销毁它持有的上下文。`destroy()`
之后再次调用 API 会抛出 `SDKError`。

其他入口：

- `init_context()` 读取默认 YAML 文件；找不到文件时使用环境变量。
- `init_context_by_file(path)` 读取指定 YAML 文件。
- `init_context_by_stream(text)` 读取 YAML 文本或字节。
- `create_*_by_file(path)` 和 `create_*_by_default_config_file()` 用上述来源创建 API。

## 配置

在 Python 里设置的超时单位是毫秒。YAML 可以使用 `1000ms`、`3s` 这样的时长字符串。
连接器协议默认为 `grpc`，内置服务端地址是 `127.0.0.1:8091`。

完整字段、默认值和当前实现限制见 [`docs/config/polaris.yaml`](docs/config/polaris.yaml)。
完整环境变量清单、别名优先级、创建入口差异和独立日志选项见
[环境变量与配置优先级](docs/config/environment-variables.md)。
[`examples/sdkconfig/file/polaris.yaml`](examples/sdkconfig/file/polaris.yaml)
保留为最小启动示例；完整说明文件不会被自动加载。

配置结构以 Java、Go SDK 为标准，`discoverCluster`、`healthCheckCluster`、
`monitorCluster` 直接位于 `global.system` 下，不使用 `serverClusters` 包装。
代码中对应 `system.discover_cluster`、`system.health_check_cluster`、`system.monitor_cluster`。
配置发现 / 心跳集群后先经 bootstrap 二次寻址；push 指标未显式配置地址时使用
`monitorCluster`。`serverConnector.serverSwitchInterval` 会周期轮换多个服务端地址，
并重建受影响的 Discover 流。
Java、Go 默认值不同的地方，以 Go `pkg/config` 的实际实现为准：API 重试 `1` 次、
客户端上报 `60s`、服务刷新 `2s`、连接超时 `500ms`、消息超时 `1500ms`、熔断检查 `10s`。
主动探测属于 P2，当前不支持。
命名空间由注册 / 发现请求指定，不属于顶层 SDK 配置。
内部 Python SDK 只作为实现参考，不作为兼容标准。

`Configuration.from_file()` 默认用 `POLARIS_` 环境变量覆盖文件中的同名字段。传入
`apply_env=False` 时保留文件原值。`Configuration.from_env()` 只使用环境变量。

支持 Go provider 的启动配置格式。地址里使用 `${POLARIS_SERVER}` 占位符时，
`POLARIS_SERVER` 只填写主机名或 IP，端口留在 YAML 中。
`POLARIS_SERVER_ADDRESS` / `POLARIS_SERVER_ADDRESSES` 始终用完整 `host:port`
覆盖地址；没有占位符时，`POLARIS_SERVER` 也使用完整地址。环境覆盖保留文件中的
其他字段，未设置的占位符展开为空字符串。

纯代码启动时创建 `Configuration()`，调用 `set_default()` 后即可直接给各层配置
对象赋值。`init_context_by_config()` 和 `create_*_by_config()` 复制该对象，不读取
配置文件，也不自动应用环境变量。文件中所有配置字段均可通过代码直接赋值，
代码中的时长使用整数毫秒。

只接受 `.yaml` 文件。默认查找顺序是：

1. `POLARIS_CONFIG_FILE` 指向的文件。
2. 当前目录的 `polaris.yaml`。
3. `~/.config/polaris/polaris.yaml`。

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `POLARIS_SERVER` | `${POLARIS_SERVER}:8091` 中的主机；无占位符时为完整 gRPC 地址 |
| `POLARIS_SERVER_ADDRESSES` | 逗号分隔的 gRPC 地址 |
| `POLARIS_TOKEN` | 访问令牌 |
| `POLARIS_PROTOCOL` | 连接器协议 |
| `POLARIS_TIMEOUT` | API 超时，单位毫秒 |
| `POLARIS_MAX_RETRY_TIMES` | API 重试次数 |
| `POLARIS_RETRY_INTERVAL` | 重试间隔，单位毫秒 |
| `POLARIS_CACHE_PERSIST_DIR` | 本地缓存目录 |
| `POLARIS_SERVICE_REFRESH_INTERVAL` | 服务刷新间隔，单位毫秒 |
| `POLARIS_STAT_REPORTER_ENABLE` | 是否启用统计上报 |

`POLARIS_SERVER_ADDRESS`、`POLARIS_API_TIMEOUT`、`POLARIS_API_MAX_RETRY_TIMES`、
`POLARIS_API_RETRY_INTERVAL` 和 `POLARIS_LOCAL_CACHE_PERSIST_DIR` 是对应别名。

日志独立于 SDK YAML，每个 context 使用独立的分类文件和级别。所有 context / API 创建入口
均接受仅关键字参数 `log_options`：

```python
from polaris import Configuration, LogOptions, init_context_by_config

context = init_context_by_config(
    Configuration(), log_options=LogOptions(level="warn", log_dir="./logs/client-a")
)
try:
    print(context.get_client_id())
finally:
    context.destroy()
```

未显式设置的选项在创建时读取 `POLARIS_LOG_LEVEL` / `POLARIS_LOG_PATH`，默认级别
`info`，日志根目录 `./polaris/log`。参考 polaris-go，支持 `base`、`network`、`cache`、
`route`、`circuitbreaker`、`stat`、`statReport`、`detect`、`event`、`lossless`、`auth`
子目录。基础日志为 `base/polaris-<clientId>.log`，网络日志为
`network/polaris-network-<clientId>.log`，其他类别按同样规则命名，首次使用时创建文件。
日志类别的可用性不代表对应 SDK 功能已启用。
`LogOptions.log_dir` 指定日志根目录；`POLARIS_LOG_PATH` 支持目录或原有基础文件名。
尚不存在的目录使用无扩展名路径或以 `/` 结尾，环境文件名仍追加 clientId。
显式 `LogOptions.file_path` 原样用于基础日志，其他类别使用相同文件名前缀放入相邻子目录。
`log_dir` 和 `file_path` 不得同时设置。同一或不同进程的活动 context / SDK 进程日志
不得共用任何分类文件，冲突立即报 `SDKError`。
基础文件与编号备份共用锁，`client.log` 与显式 `client.log.1` 也不能同时占用。
各类别独立按 50MB 滚动、保留最多 5 份 / 30 天，一天为连续 24 小时，不做午夜切分。
备份仍使用 `.1`、`.2` 等编号，修改时间记录滚动时间。启动和每小时清理过期备份及同前缀下
已退出的 UUID context 日志，不删除活动持有者或无关文件。隐藏锁文件不要在运行中删除。
销毁会停止清理线程、关闭句柄并释放操作系统锁；进程异常终止后也可复用路径。
`init_log(log_dir=...)` / `set_logger()` 仍用于 context 操作之外的进程日志，不重配 context 日志。
`apply_env=False` 不关闭独立日志环境变量。
`LogOptions` 支持构造参数，也支持在创建 context 前直接给 `level`、`log_dir`、`file_path`、
`max_bytes`、`backup_count`、`max_age_days` 赋值；`max_age_days=0` 关闭年龄清理。
滚动选项也支持 `init_log()` / `create_log()`，没有 YAML 字段或环境变量；
之后修改选项对象不会重配已有 context 日志。
清理范围与文件系统限制见 [日志选项说明](docs/config/environment-variables.md#日志环境变量与优先级)。

磁盘缓存使用 `consumer.localCache.persistDir`，默认 `./polaris/backup`；
每个 context 独立持有写线程和队列，同目录可以有意共享文件。
备份文件名与 Go SDK 一致，格式为
`svc#<namespace>#<service>#<resource>.json`。namespace 和 service 会做 URL 编码，
resource 目前只有 `instance`；内容为 protobuf canonical JSON，可以直接打开查看。
闲置资源达到 `consumer.localCache.serviceExpireTime`（默认 24 小时）后，扫描任务
释放内存、停止对应 Discover 并删除备份；业务读取续期，后台刷新不续期。
每 `min(serviceExpireTime / 2, 1h)` 扫描，配置的系统服务不淘汰。
共享目录也共享文件删除；不同注册中心或独立备份生命周期应使用不同 `persistDir`，
不会自动增加随机子目录。离线验证见 [缓存淘汰示例](examples/cache/expiry/README.md)。
磁盘读写重试由 `persistMaxReadRetry`、`persistMaxWriteRetry` 和 `persistRetryInterval`
控制，次数不含首次操作；删除使用写重试配置。写入先同步临时文件，再原子替换备份。
重启时会把已有实例备份读入内存，但不按文件修改时间决定能否使用，也不把它当作默认发现结果。
默认读取继续等待远端；网络失败或超时后返回可用磁盘备份，后台发现继续运行，服务端恢复后更新缓存。
[异常重启示例](examples/cache/restart/README.md)
验证强制终止进程后，停止本地 gRPC 服务时同步 / 异步发现返回完整磁盘快照，服务端恢复后返回新的远端 revision。
服务不存在（400301）清理内存、Discover 和备份，不降级；相同 revision / DATA_NO_CHANGE
保留快照，成功的空实例响应替换原数据。
配置在启动时复制，修改原对象或 `get_config()` 不属于运行时热更新机制。
已移除的顶层 `namespace`、`global.system.logPath/logLevel`、
`global.statReporter.addresses` 和内部派生值 `global.api.bindIPValue` 会作为未知字段报错。

`global.api.bindIP` 标识 SDK 自身，不是业务实例注册地址。显式 IP 优先于 `bindIf`，
后者严格读取指定网卡，网卡不存在或没有 IP 则启动报错。两者都未设置时，启动会按
`connectTimeout` TCP 连接首个注册中心地址，读取本地 IP 并关闭探测连接；失败只告警，
保留空值，不阻止启动。通过 `context.get_config().get_global().get_api().get_bind_ip()`
可读取本 context 的解析结果。注册请求仍必须显式指定 `InstanceRegisterRequest.host`，
SDK 不会用自身 IP 补齐。

## 注册实例

`ProviderAPI.register()`、`deregister()` 和 `heartbeat()` 是同步方法。
异步入口分别为 `async_register()`、`async_deregister()`、`async_heartbeat()`；原有
`await provider.register(...)` 需迁移为 `await provider.async_register(...)`。
正在运行的事件循环内调用同步 RPC API 会抛 `SDKError`，应改用 `async_` 入口。

`register_instance()` / `async_register_instance()` 注册成功后开启 SDK 自动心跳，
TTL 未指定（`None`）时默认 5 秒；显式 TTL 必须是正整数秒，不能使用 0。
普通 `register()` 只有请求设置 `auto_heartbeat=True` 时才开启自动心跳。

重注册采用 Java 策略：连续 2 次收到实例不存在（`400202`），且首次注册已超过
`provider.minRegisterInterval`（默认 30 秒）后触发。其他错误继续心跳；重注册失败后
采用带随机偏移的指数退避，上限 60 秒。反注册前停止心跳与重注册任务，即使反注册 RPC
失败也不恢复。`provider.destroy()` / `context.destroy()` 停止任务并关闭运行时，
不会隐式反注册。完整流程见 [自动心跳示例](examples/quickstart/README.md)。

服务令牌用于注册、心跳和反注册。它和连接 Polaris 的 `POLARIS_TOKEN` 是两个值。

## 发现实例

进程内复用同一个 `ConsumerAPI`。它维护实例发现缓存。
`get_one_instance()` 和 `get_instances()` 会阻塞并返回具体结果。
`async_get_one_instance()` 和 `async_get_instances()` 是可等待的形式。两条路径使用同一个 Engine。
调用结束后用同步 `update_service_call_result()` 或异步 `async_update_service_call_result()`
上报结果，接入指标聚合和已有本地实例熔断；`sync_update_service_call_result()` 为同步兼容入口。
`get_instances()` 返回本地过滤候选，`get_all_instances()` 返回全量快照，
`get_healthy_instances()` 只做前后置隔离 / 恢复过滤、默认包含熔断实例。
列表结果提供 `.instances`，候选查询不扣减半开配额。

## 内置插件

| 类型 | 名称 |
| --- | --- |
| 服务端连接器 | `grpc` |
| 本地缓存 | `inmemory`、`file` |
| 服务路由 | `isolatedRouter`、`metadataRouter`、`recoverRouter` |
| 负载均衡 | `weightedRandom`、`random` |
| 熔断 | `composite`（本地实例错误计数、错误率及半开恢复） |

旧配置名称 `wr`、`err_count` 在补默认值时分别转换为 `weightedRandom`、`composite`。
不拉取远程治理规则。统计上报已接通 `prometheus`，支持 pull 与 push。
默认规则、调用结果上报、半开配额与全死全活边界见 [本地实例熔断](docs/circuitbreaker.md)。
本地默认规则阈值与恢复参数支持 YAML 和代码赋值，半开配额跟随 `successCountAfterHalfOpen`。

## 示例

见 [`examples/`](examples/) 目录，包括[多 context 生命周期验证](examples/multicontext/README.md)。

## 许可证

[BSD 3-Clause](LICENSE)。
