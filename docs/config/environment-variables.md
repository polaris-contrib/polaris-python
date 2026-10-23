# 环境变量与配置优先级

字段说明见 [configuration-reference.md](configuration-reference.md)，
最小配置见 [polaris.yaml](polaris.yaml)。

## 加载入口

`init_context()` 默认按顺序查找：

1. `POLARIS_CONFIG_FILE` 指定的文件。
2. 当前目录的 `polaris.yaml`。
3. `~/.config/polaris/polaris.yaml`。
4. 未找到文件时只使用环境变量，再补默认值。

同一字段的优先级：

```text
SDK 环境变量覆盖 > 文件值 > 默认值
```

`POLARIS_CONFIG_FILE` 指定的文件不存在或格式错误时直接报错，不回退其他文件。

- `Configuration.from_file()`、`from_dict()` 和 `init_context_by_stream()` 默认应用环境覆盖。
- `apply_env=False` 禁用字段覆盖和占位符展开，但不影响独立的日志环境变量。
- `Configuration.from_env()` 只读取环境变量。
- `init_context_by_config()` / `create_*_by_config()` 不读取文件，也不重新应用环境变量。

## SDK 环境变量

时长覆盖使用整数毫秒，不接受 `3s`。列表使用逗号分隔，并整体替换文件列表。

| 变量 | 覆盖字段 |
| --- | --- |
| `POLARIS_SERVER_ADDRESSES` | `global.serverConnector.addresses` |
| `POLARIS_SERVER_ADDRESS` | 地址列表，兼容别名 |
| `POLARIS_SERVER` | 无地址占位符时为完整地址列表 |
| `POLARIS_TOKEN` | `global.serverConnector.token` |
| `POLARIS_PROTOCOL` | `global.serverConnector.protocol` |
| `POLARIS_API_TIMEOUT` / `POLARIS_TIMEOUT` | `global.api.timeout` |
| `POLARIS_API_MAX_RETRY_TIMES` / `POLARIS_MAX_RETRY_TIMES` | `global.api.maxRetryTimes` |
| `POLARIS_API_RETRY_INTERVAL` / `POLARIS_RETRY_INTERVAL` | `global.api.retryInterval` |
| `POLARIS_CACHE_PERSIST_DIR` / `POLARIS_LOCAL_CACHE_PERSIST_DIR` | `consumer.localCache.persistDir` |
| `POLARIS_SERVICE_REFRESH_INTERVAL` | `consumer.localCache.serviceRefreshInterval` |
| `POLARIS_SERVICE_EXPIRE_TIME` | `consumer.localCache.serviceExpireTime` |
| `POLARIS_STAT_REPORTER_ENABLE` | `global.statReporter.enable` |
| `POLARIS_STAT_REPORTER_CHAIN` | `global.statReporter.chain` |

地址优先级：

```text
POLARIS_SERVER_ADDRESSES > POLARIS_SERVER_ADDRESS > POLARIS_SERVER
```

`POLARIS_SERVER` 在文件使用 `${POLARIS_SERVER}:8091` 时只提供主机，端口保留在文件中。

除 `POLARIS_TOKEN` 外，空字符串视为未设置。`POLARIS_TOKEN=""` 会显式清空令牌。
非法整数或布尔值会抛出 `SDKError`。

`POLARIS_NAMESPACE`、`POLARIS_STAT_REPORTER_ADDRESSES` 不是 SDK 配置变量。
示例使用的 `POLARIS_E2E`、`POLARIS_SKILL_*` 等由示例脚本读取。

## 占位符

文件字符串支持：

```text
${ENV}          未设置或为空时展开为空字符串
$ENV            未设置或为空时展开为空字符串
${ENV:default}  未设置或为空时使用 default
```

默认值从冒号后到 `}` 为止，可以包含冒号：

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
    token: ${POLARIS_TOKEN:}
```

自定义时长字段也可以使用占位符：

```yaml
consumer:
  circuitBreaker:
    defaultInterval: ${APP_BREAKER_WINDOW:60s}
```

## Skill 配置

Skill 配置位于 `ai.skill.serverConnector`，没有专用环境覆盖变量。
可以使用 YAML 占位符或代码赋值：

- `POLARIS_TOKEN` 只覆盖主注册中心 token。
- 默认配置阶段 Skill token 为空时继承主注册中心 token。
- 显式 Skill token 优先。
- Skill TLS、地址和持久化配置独立于普通注册发现。

## 日志环境变量

日志不属于 `polaris.yaml`。每个 context 创建时分别采用：

```text
LogOptions 显式值 > 日志环境变量 > 默认值
```

| 变量 | 作用 |
| --- | --- |
| `POLARIS_LOG_LEVEL` | `debug`, `info`, `warn`, `error`；默认 `info` |
| `POLARIS_LOG_PATH` | 日志根目录；默认 `./polaris/log` |

`POLARIS_LOG_PATH` 也可兼容基础日志文件名。已有目录、无扩展名路径或以 `/`
结尾的路径按目录处理。环境变量文件名会追加 clientId。

`LogOptions.log_dir` 指定目录，`file_path` 指定基础文件，两者不能同时设置。
显式文件名不追加 clientId。活动 context 或进程日志不得占用相同分类文件。

默认分类：

```text
base network cache route circuitbreaker statReport event
```

分类文件首次使用时创建。代码配置默认每类 50MB 滚动、保留 5 份和 30 天；
`max_age_days=0` 关闭年龄清理。没有对应 YAML 或环境变量。

```python
from polaris import LogOptions

options = LogOptions(
    level="warn",
    log_dir="./logs/client-a",
    max_bytes=50 * 1024 * 1024,
    backup_count=5,
    max_age_days=30,
)
```

`init_log()` / `set_logger()` 是 context 外的进程日志入口，不重配已有 context。

## 相关文档

- [配置参数说明](configuration-reference.md)
- [TLS](../tls.md)
- [可观测性](../observability.md)
- [本地熔断](../circuitbreaker.md)
