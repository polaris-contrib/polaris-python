# SDK 启动配置示例

示例按 Java、Go SDK 的「能力 / 场景」方式组织：

- [`file/`](file/README.md)：从 `polaris.yaml` 启动，支持环境变量占位符和默认文件查找。
- [`code/`](code/README.md)：直接给 `Configuration` 各层对象赋值，无需配置文件。

完整字段、默认值与实现限制见 [`docs/config/polaris.yaml`](../../docs/config/polaris.yaml)。
`file/polaris.yaml` 只保留最小启动配置，系统集群直接位于 `global.system` 下，与 Java / Go 一致。

在仓库根目录执行验证：

```bash
uv sync --group dev --locked
uv run --locked python examples/sdkconfig/verify.py
```

验证覆盖 YAML 和代码启动场景，包括完整配置说明文件、Java / Go 系统集群层级、YAML 加载、Go provider 的 `${POLARIS_SERVER}:8091` / `${POLARIS_TOKEN}` / `1000ms` 写法、`${ENV:default}` 默认值、默认文件优先级、环境覆盖、错误配置与纯代码启动。本地实例熔断覆盖自定义参数、关闭默认规则、时长占位符与纯代码赋值。SDK 地址场景检查自动获取、失败保留空值、指定网卡、显式 IP 优先和无效网卡报错。每个场景在独立进程和本 demo 的验证工作目录运行，检查配置生效值、API 共用上下文和销毁标记。

离线验证替换启动时的 TCP 探测、网卡枚举和客户端上报 RPC，并模拟用户目录。配置解析、地址解析策略、校验、插件装配和 SDK 后台事件循环使用实际实现；检查首个配置地址、探测连接关闭和上报 IP。代码配置场景还禁止调用文件加载和默认文件查找入口，确认即使存在损坏的 `polaris.yaml` 或无效的 `POLARIS_CONFIG_FILE` 也能启动。验证日志和缓存保留在各 demo 的 `.logs/` 下，可通过 `logs.sh` 查看、`cleanup.sh` 清理。

本目录演示 SDK 本地启动配置；远程配置中心的读取和监听示例后续放在 `configuration/`。

发现请求的命名空间用 `--namespace` 指定，示例参数默认 `default`，不从配置文件读取。
示例通过独立 `LogOptions` 固定各自日志目录，级别可使用 `POLARIS_LOG_LEVEL`；
代码示例显式传入 `log_options`，日志选项不属于 `Configuration`。
每个 context 拥有独立日志、配置快照和缓存写线程；多 context 验证见
[`multicontext`](../multicontext/README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only sdkconfig
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../README-zh.md)。
