# 环境变量与配置优先级

本文列出当前 Python SDK 实际读取的环境变量。完整 SDK 字段和默认值见
[polaris.yaml](polaris.yaml)，最小文件启动示例见
[examples/sdkconfig/file/polaris.yaml](../../examples/sdkconfig/file/polaris.yaml)。

SDK 启动配置和日志选项分别加载。环境变量属于进程，不属于某个 context；
SDK 配置环境变量在启用环境覆盖的加载入口读取，日志环境变量在创建 context 时读取，
不会监听环境变化或热更新已有 context。
不同 context 需要不同参数时，建议分别通过代码配置 `Configuration` 和 `LogOptions`。

Skill 配置位于 `ai.skill.serverConnector`，目前没有 SDK 专用环境覆盖变量；
可通过代码赋值或 YAML `${ENV}` 占位符配置地址、Token 和持久化目录。
`POLARIS_TOKEN` 专用覆盖修改 `global.serverConnector.token`；默认配置阶段若 Skill token
为空，则继承该 global token。显式 Skill token、文件占位符或代码赋值优先。
`examples/skill` 显式读取的 `POLARIS_SKILL_SERVER_ADDRESS/TOKEN/NAME/NAMESPACE/VERSION`
仅属于示例参数；Token 优先级是 `--token > POLARIS_SKILL_TOKEN > POLARIS_TOKEN`。

## 创建入口与优先级

### 默认启动

`init_context()` 和 `create_*_by_default_config_file()` 按以下顺序选择文件，只加载第一个命中项：

1. 非空 `POLARIS_CONFIG_FILE` 指定的文件。
2. 当前工作目录的 `polaris.yaml`。
3. `~/.config/polaris/polaris.yaml`。
4. 没有找到文件时，仅使用 SDK 配置环境变量，再补默认值。

`POLARIS_CONFIG_FILE` 只决定文件选择，不对应 YAML 字段。该变量指定的文件不存在、
格式不支持或内容非法时直接报错，不回退到其他文件。空字符串视为未指定。
只支持 `.yaml` 文件；`docs/config/polaris.yaml` 不参与默认查找。

加载文件后，同一 SDK 字段的优先级是：**环境变量覆盖 > 文件值 > 默认值**。
覆盖仅针对指定字段，其他文件值保留；缺少的字段在 context 初始化时补默认值并校验。

### 指定文件、文本或字典

`init_context_by_file(path)` / `create_*_by_file(path)` 使用显式文件路径，
不读取 `POLARIS_CONFIG_FILE`，也不查找默认文件，但默认仍应用其他 SDK 配置环境变量。

`Configuration.from_file()`、`Configuration.from_dict()` 和
`init_context_by_stream()` 默认同样使用 **环境变量覆盖 > 输入值 > 默认值**。
`Configuration.from_env()` 不读取配置文件，仅使用环境变量。
单独创建 `Configuration` 不会启动 SDK；`from_*()` 返回的配置可先调用
`set_default()` / `verify()` 检查，或直接交给 context 创建入口完成默认填充和校验。

传入 `apply_env=False` 会同时禁用 SDK 字段覆盖和 `${ENV}` / `${ENV:default}` / `$ENV`
占位符展开，
按 **输入值 > 默认值** 加载。这不禁用独立的日志环境变量。
API 文件工厂当前没有 `apply_env` 参数，需要禁用时使用：

```python
from polaris import init_context_by_file

context = init_context_by_file("polaris.yaml", apply_env=False)
try:
    pass
finally:
    context.destroy()
```

### 纯代码启动

`init_context_by_config(config)` / `create_*_by_config(config)` 不读取文件，
不自动应用 SDK 配置环境覆盖，也不展开配置对象中的占位符。
优先级为 **已赋值的配置对象 > 默认值**。
若对象此前由 `Configuration.from_file()` / `from_env()` 创建，它已经包含当时的环境覆盖结果；
之后在代码中赋值可以覆盖该结果，context 创建时不会再套用 SDK 配置环境变量。

默认填充不是严格的“非空就原样保留”：例如 `maxRetryTimes=0` 会按 Go 语义补为 `1`。
完整默认填充与校验限制见 [polaris.yaml](polaris.yaml)。

## SDK 字段覆盖变量

以下变量在应用环境覆盖时生效，变量名区分大小写。
时长覆盖值使用十进制整数毫秒，例如 `3000`；不能直接写 `3s`。
列表用逗号分隔，会去掉每项首尾空白和空项；列表整体替换，不与文件列表追加合并。

### 接入地址、鉴权与协议

- `POLARIS_SERVER_ADDRESSES`：覆盖 `global.serverConnector.addresses`，一个或多个完整 `host:port` 地址。
- `POLARIS_SERVER_ADDRESS`：同上，兼容别名，也支持逗号分隔多个完整地址。
- `POLARIS_SERVER`：文件地址未引用此变量时，作为完整地址列表覆盖；
  文件使用 `${POLARIS_SERVER}:8091` 或 `$POLARIS_SERVER:8091` 时，只替换占位符，端口留在文件中。
- `POLARIS_TOKEN`：覆盖 `global.serverConnector.token`，注册中心访问令牌，不是实例请求的
  service token；Skill token 为空时在默认配置阶段继承该值。
- `POLARIS_PROTOCOL`：覆盖 `global.serverConnector.protocol`；当前只有 `grpc` 连接器可用。

地址覆盖取第一个非空值：
**`POLARIS_SERVER_ADDRESSES` > `POLARIS_SERVER_ADDRESS` > `POLARIS_SERVER`**。
最后一项只在原输入地址列表没有引用 `POLARIS_SERVER` 占位符时参与整体覆盖。
两个完整地址变量始终可以覆盖展开后的整份地址列表。

例如文件包含：

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER}:8091
    token: ${POLARIS_TOKEN}
```

```bash
export POLARIS_SERVER=10.0.0.1
export POLARIS_TOKEN=access-token
```

地址展开为 `10.0.0.1:8091`。此时不要把 `POLARIS_SERVER` 设为 `10.0.0.1:8091`，
否则会展开为重复端口。若再设置 `POLARIS_SERVER_ADDRESSES=10.0.0.2:8091,10.0.0.3:8091`，
最终地址列表只包含这两个完整地址。

### API 超时与重试

- `POLARIS_API_TIMEOUT` / `POLARIS_TIMEOUT`：覆盖 `global.api.timeout`，整数毫秒。
- `POLARIS_API_MAX_RETRY_TIMES` / `POLARIS_MAX_RETRY_TIMES`：覆盖 `global.api.maxRetryTimes`，整数次数。
- `POLARIS_API_RETRY_INTERVAL` / `POLARIS_RETRY_INTERVAL`：覆盖 `global.api.retryInterval`，整数毫秒。

每对变量取第一个非空值，带 `POLARIS_API_` 的名称优先。
`global.api.timeout` 与 `global.serverConnector.messageTimeout` 不是同一字段；
当前一元 gRPC 请求使用后者，不能将 API 超时覆盖理解为修改所有网络超时。
`global.api.timeout` 限制实例首次 Discover 的远端等待。磁盘快照会先放进内存，
但不表示远端已更新，默认读取会继续等待远端；网络失败或超时后返回可用备份作降级。
服务不存在（400301）不降级，清理该服务内存、Discover 和对应备份。
该超时不关闭后台刷新。磁盘读取及其重试时间不计入远端等待预算。

### 本地缓存

磁盘读写重试通过 YAML 或代码设置 `persistMaxReadRetry`、`persistMaxWriteRetry`
和 `persistRetryInterval`，没有新增专用环境变量；也可在 YAML 中使用 `${APP_*}` 展开。
默认读额外重试 1 次、写及删除额外重试 5 次，间隔 1000ms。缺失或过期文件不重试。

- `POLARIS_LOCAL_CACHE_PERSIST_DIR` / `POLARIS_CACHE_PERSIST_DIR`：覆盖
  `consumer.localCache.persistDir`。第一个非空值优先，相对路径按当前工作目录解析。
  SDK context 默认使用 `./polaris/backup`。
  不同注册中心应使用不同目录，SDK 不自动追加随机子目录。
- `POLARIS_SERVICE_REFRESH_INTERVAL`：覆盖 `consumer.localCache.serviceRefreshInterval`，整数毫秒。
- `POLARIS_SERVICE_EXPIRE_TIME`：覆盖 `consumer.localCache.serviceExpireTime`，整数毫秒。
  资源在业务读取后闲置达到该时间可被淘汰；后台刷新和内部读取不续期。
  每 `min(serviceExpireTime / 2, 1h)` 扫描一次，默认闲置门槛 24 小时、每小时扫描。
  配置的系统服务不淘汰；淘汰释放内存、停止对应 Discover 并删除磁盘备份。
  同目录的删除会影响其他 context 的磁盘降级，需要独立备份生命周期时使用不同 `persistDir`。

### 统计上报

- `POLARIS_STAT_REPORTER_ENABLE`：覆盖 `global.statReporter.enable`。
  真值支持 `1/true/yes/on`，假值支持 `0/false/no/off`，不区分大小写，允许首尾空白。
- `POLARIS_STAT_REPORTER_CHAIN`：覆盖 `global.statReporter.chain`，逗号分隔的插件名称列表。

当前支持 prometheus 插件：默认 pull，每 30 秒聚合调用指标；push 按 pushInterval 推送。
启用时 chain 只接受 prometheus；插件字段与 global.admin 没有专用覆盖变量，
通过 YAML / 代码或显式占位符配置。指标和调用结果说明见 [可观测性](../observability.md)。

### TLS

global.serverConnector 与 ai.skill.serverConnector 分别支持 trustedCAFile/certFile/keyFile。
没有专用环境覆盖变量，可通过 YAML 的 ${APP_CA_FILE} 等占位符配置，
或直接给代码中的 trusted_ca_file/cert_file/key_file 赋值。两条连接不继承彼此的证书。
配置错误严格拒绝启动，不回退明文，详情见 [TLS](../tls.md)。

### 本地实例熔断

`sleepWindow`、`successCountAfterHalfOpen`、`defaultRuleEnable`、`defaultErrorCount`、
`defaultErrorPercent`、`defaultInterval` 和 `defaultMinimumRequest` 支持 YAML 和代码配置，
没有专用环境覆盖变量。可在 YAML 中显式引用 `${APP_*}`，按文件加载入口的占位符规则展开；
例如 `defaultInterval: ${APP_BREAKER_WINDOW:60s}`。参数含义见 [本地实例熔断](../circuitbreaker.md)。

### 空值、错误与占位符

除 `POLARIS_TOKEN` 外，上述 SDK 字段覆盖变量的空字符串视为未设置；
`POLARIS_TOKEN=""` 会显式清空输入配置中的令牌。非法整数或布尔值报 `SDKError`，
不会忽略错误后尝试低优先级别名；解析后的值还需通过配置校验。

应用环境覆盖时先展开输入配置中的字符串占位符，再应用上述专用字段覆盖。
占位符可引用任意 `${ENV}` / `$ENV`，不限 `POLARIS_` 前缀。`${ENV}` 未设置或为空时
替换为空字符串；`${ENV:default}` 未设置或为空时替换为 `default`。默认值从冒号后
到结束 `}` 为止，可以包含冒号，例如：

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
```

例如 `timeout: ${APP_TIMEOUT}` 与 `APP_TIMEOUT=3s` 可按 YAML
时长字段解析，这与必须使用整数毫秒的 `POLARIS_API_TIMEOUT` 专用覆盖不同。

SDK 不会把任意 `POLARIS_*` 名称自动映射到 YAML 字段。
`POLARIS_NAMESPACE`、`POLARIS_STAT_REPORTER_ADDRESSES` 不再有专用覆盖行为；
命名空间由注册 / 发现请求指定。其他未列出的字段可通过代码赋值，或在 YAML 中显式引用占位符。
示例使用的 `POLARIS_E2E`、`POLARIS_FIRST_*`、`POLARIS_SECOND_*` 等只由示例脚本读取，
不是 SDK 通用配置变量。

## 日志环境变量与优先级

日志选项不属于 `polaris.yaml`，也不写入 `Configuration`。
每个 context 创建时，按字段分别采用 **`LogOptions` 显式值 > 日志环境变量 > 默认值**：

- `POLARIS_LOG_LEVEL`：当 `LogOptions.level is None` 时读取。
  支持 `debug/info/warn/error`，不区分大小写，默认 `info`；空字符串或未知级别报 `SDKError`。
- `POLARIS_LOG_PATH`：当 `LogOptions.log_dir` 和 `LogOptions.file_path` 都为 `None` 时读取。
  默认根目录 `./polaris/log`，基础日志为 `base/polaris-<clientId>.log`，网络日志为
  `network/polaris-network-<clientId>.log`。已有目录、无扩展名路径、以 `/` 结尾的路径按
  根目录处理，例如 `./logs` 生成 `./logs/base/polaris-<clientId>.log`。
  兼容原有基础文件名，例如 `./logs/client.log` 生成 `./logs/client-<clientId>.log`，
  网络日志为 `./logs/network/client-network-<clientId>.log`；空字符串使用默认根目录。

`LogOptions.log_dir` 显式指定根目录，`LogOptions.file_path` 显式指定基础日志文件，
两者不得同时设置。显式文件名不追加 clientId，其他类别使用相同文件名前缀放入相邻子目录；
例如 `./logs/client-a.log` 的网络日志为 `./logs/network/client-a-network.log`。
基础文件已位于 `base/` 时，其他类别与 `base/` 同级。路径中的 `~` 会展开，
相对路径按当前工作目录解析。同一进程或不同进程的活动 context / SDK 进程日志，
不得占用相同分类文件路径，冲突立即报 `SDKError`，不会等待或共写。
基础文件和它的编号备份使用同一锁；例如 `client.log` 与显式 `client.log.1` 也不能同时使用，
即使编号超过当前备份数量上限，仍属于保留的备份命名空间。

支持目录：`base`、`network`、`cache`、`route`、`circuitbreaker`、
`stat`、`statReport`、`detect`、`event`、`lossless`、`auth`。
网络连接及重试、缓存读写及更新、路由、熔断状态变更和客户端上报错误分别进入对应类别，
其余 SDK 生命周期日志进入 `base`。分类文件首次使用时创建，所有条目保留 clientId；
支持某个日志类别不会自动启用对应 SDK 功能。
`max_bytes`、`backup_count`、`max_age_days` 仅支持代码配置，没有对应环境变量或 YAML 字段。
默认分别为 `50 * 1024 * 1024` 字节、5 份备份和 30 天，各类别独立按大小滚动，
不在午夜切分。备份继续使用 `.1`、`.2` 等编号，`.1` 最新；滚动时更新 `.1` 的修改时间，
以该时间计算保留期，一天为连续 24 小时。超过保留期或数量上限即删除，当前写入文件不按年龄删除。
`max_age_days=0` 关闭年龄清理，仍保留数量限制；参数为非负整数，布尔值不合法。

初始化清理全部分类的旧备份，运行期间每小时扫描，即使没有新日志也会清理。
自动包含 clientId 的文件名，还会清理相同根目录 / 文件名前缀下已过期、无活动持有者的
历史 UUID context 日志及备份；不同前缀、应用文件、符号链接和其他进程占用的文件不删除。
显式 `file_path` 只清理自身分类的备份。删除失败告警并在后续扫描重试。

每个分类路径提前取得操作系统独占锁，未打开的分类也受保护，大小滚动不会释放锁。
锁文件为日志旁的隐藏文件，例如 `.client-a.log.lock`，不参与年龄清理，关闭后也不删除，
避免删除并重建锁文件造成多个锁 inode。销毁 context 先停止清理线程，再关闭分类句柄和释放锁；
进程异常终止后操作系统释放锁，重启可复用路径。不要在运行期间手动删除锁文件。
这保证使用 SDK 日志入口的本地文件独占，不协调绕过 SDK 的外部写入器、外部滚动工具，
也不保证不支持文件锁的网络文件系统。fork 后应创建独立 context，不复用继承的日志对象。

```python
from polaris import Configuration, LogOptions, init_context_by_config

config = Configuration()
config.set_default()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]

options = LogOptions()
options.level = "warn"
options.log_dir = "./logs/client-a"
options.max_bytes = 50 * 1024 * 1024
options.backup_count = 5
options.max_age_days = 30

context = init_context_by_config(config, log_options=options)
try:
    pass
finally:
    context.destroy()
```

这个例子显式设置日志级别和路径，因此不受 `POLARIS_LOG_LEVEL` / `POLARIS_LOG_PATH` 影响。
如果只设置 `level`，文件路径仍使用环境变量或默认值。
纯代码入口和 `apply_env=False` 都不会关闭日志环境变量；要避免其影响，显式设置两个日志字段。
创建后修改 `options` 或环境变量，不会重配已有 context 的日志。

`polaris.api.log.init_log()` / `set_logger()` 是 context 操作之外的进程日志入口，
不会覆盖 context 的独立日志。`init_log()` 仅在进程默认 logger 尚未设置时初始化，
未指定参数读取同样的两个环境变量，但文件名不追加 clientId。
`init_log(log_dir="./logs")` 指定根目录，生成 `base/polaris.log`、`network/polaris-network.log`
等分类文件；`init_log(file_path="./client.log")` 保留原有基础文件路径。
`init_log()` / `create_log()` 也接受 `max_bytes`、`backup_count` 和 `max_age_days`，
使用相同的默认值、清理和独占锁；替换进程 logger 会停止旧清理任务并释放旧路径。
可通过 `polaris.api.log.get_logger("network")` 获取按当前 context 选择输出文件的日志入口；
已有 `debug/info/warning/error` 函数写入 `base`。`set_logger()` 设置的自定义进程 logger
用于 context 之外的所有类别，SDK 不为它创建额外文件。

## 实现与验证

SDK 环境覆盖和默认文件选择由 `src/polaris/pkg/config/loader.py` 实现；
创建入口在 `src/polaris/api/config.py`，日志选择在 `src/polaris/api/log.py`。
现有配置与日志测试、离线启动验证可在仓库根目录运行：

```bash
uv run --locked pytest -q tests/test_config.py tests/test_log.py
uv run --locked python examples/sdkconfig/verify.py
```
