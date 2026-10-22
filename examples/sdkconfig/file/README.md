# polaris.yaml 启动示例

`main.py` 调用 `init_context_by_file()` 创建一个 `SDKContext`，让 Provider 和 Consumer 共用上下文，并在退出时调用 `destroy()`。配置文件只支持 `.yaml`，默认文件名为 `polaris.yaml`。

在仓库根目录执行：

```bash
uv run --locked python examples/sdkconfig/file/main.py --no-env
uv run --locked python examples/sdkconfig/file/main.py --config examples/sdkconfig/file/polaris.yaml
```

不传 `--config` 时读取脚本旁的 `polaris.yaml`。`--no-env` 关闭环境变量替换和覆盖，仅使用文件中的字面值。成功输出一行 JSON，包含实际生效配置、SDK 自身地址 `bind_ip`、`shared_context: true` 和 `context_destroyed: true`；Token 仅输出是否配置的 `token_set` 布尔值。配置错误返回非零退出码。

示例显式设置 `bindIP: 127.0.0.1`。删除此字段且不设置 `bindIf` 时，SDK 启动会按 `connectTimeout` 连接首个注册中心地址，获取连接的本地 IP 并关闭探测连接；失败只告警，`bind_ip` 保持空值。指定 `bindIf` 时严格读取该网卡，找不到或没有 IP 会启动报错；显式 `bindIP` 优先于网卡配置。这些设置只标识 SDK，注册请求仍必须显式设置业务实例的 `host`。

## Go provider 配置格式

提供的 `polaris.yaml` 使用 Go provider 相同的 `global.serverConnector` 结构，并补充了 API 和服务刷新配置。支持整数毫秒与 `1000ms`、`1s`、`1m30s` 等带单位时长，SDK 内部统一使用整数毫秒。

Go provider 的以下配置可直接加载：

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER}:8091
    token: ${POLARIS_TOKEN}
    connectTimeout: 1000ms
```

使用这种写法时，`POLARIS_SERVER` 只填写主机名或 IP，端口保留在文件中：

```bash
export POLARIS_SERVER=127.0.0.1
export POLARIS_TOKEN=
```

示例默认使用 `${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}`：变量未设置或为空时连接
`127.0.0.1:8091`，设置后使用该环境变量。要使用 Go 风格占位符，将 `addresses`
和 `token` 改成上述内容。未设置的普通占位符展开为空字符串。

也可以给占位符提供默认值。变量未设置或为空字符串时使用默认值；默认值可以包含冒号：

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
```

没有 `${POLARIS_SERVER}` 占位符时，`POLARIS_SERVER` 沿用完整 `host:port` 地址覆盖。`POLARIS_SERVER_ADDRESS` / `POLARIS_SERVER_ADDRESSES` 总是按完整地址覆盖，可用逗号指定多个地址。环境变量只覆盖对应字段，保留文件中的其他配置。

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8092 \
  uv run --locked python examples/sdkconfig/file/main.py
```

## 默认文件查找

`--default` 调用 SDK 的 `init_context()`，依次查找：

1. `POLARIS_CONFIG_FILE` 指向的 YAML 文件。
2. 当前工作目录的 `polaris.yaml`。
3. `~/.config/polaris/polaris.yaml`。
4. 没有文件时使用 SDK 默认值和环境变量。

```bash
POLARIS_CONFIG_FILE=examples/sdkconfig/file/polaris.yaml \
  uv run --locked python examples/sdkconfig/file/main.py --default
```

`POLARIS_CONFIG_FILE` 显式指定的文件不存在时直接报错。`--default` 不能与 `--no-env` 同时使用。
相对配置路径按当前工作目录解析；`run.sh` 的工作目录固定为本 demo 目录。
本示例日志保存在运行目录的 `polaris/log/` 下，再按 `base`、`network`、`cache` 等分类；
演示 cache 固定写入与 `polaris/log/` 同级的 `polaris/backup/file/`，直接运行时位于本 demo 的
`.logs/manual/polaris/backup/file/`。
SDK 默认日志根目录为 `polaris/log/`，基础日志为 `base/polaris-<clientId>.log`。
SDK 自身的 `consumer.localCache.persistDir` 默认仍是 `polaris/backup/`；
本 demo 会在创建 context 前覆盖它，保证示例产物集中保留。

## 真实服务发现

配置 Polaris 的 gRPC 地址和 Token，指定一个已有实例的服务：

```bash
uv run --locked python examples/sdkconfig/file/main.py \
  --config examples/sdkconfig/file/polaris.yaml \
  --service demo --namespace default --timeout 10000
```

`--namespace` 是请求参数，默认 `default`，不从配置文件读取；`--timeout` 限制服务发现总等待时间，单位为毫秒。成功输出额外的 `discovery.instances`；失败、超时或没有实例时返回非零退出码。仅启动成功表示配置和运行时初始化成功，不代表远端连接或鉴权成功。SDK 可能读取磁盘缓存，确认首次远端发现时应在没有该服务缓存的工作目录运行。

本示例通过独立 `log_options` 固定 demo 日志目录，级别仍可使用 `POLARIS_LOG_LEVEL`；
`--no-env` 只关闭 SDK 配置环境覆盖，不控制日志。顶层 `namespace`、系统 `logPath/logLevel`
及主动探测配置不接受，旧字段会明确报错。主动探测属于 P2，当前不支持。

离线自动验证见 [SDK 启动配置示例](../README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only sdkconfig/file
make -C examples/sdkconfig/file run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
`run.sh` 转发 `main.py` 参数。默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../../README-zh.md)。
