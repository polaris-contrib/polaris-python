# 纯代码启动示例

`main.py` 创建 `Configuration`，填充 SDK 默认配置，再直接给各层对象赋值，通过 `init_context_by_config()` 创建上下文。整个过程不读取配置文件，也不自动应用 `POLARIS_` 环境变量。文件中可配置的各个字段，同样可以在代码中直接赋值；时长使用整数毫秒。

在仓库根目录执行：

```bash
uv run --locked python examples/sdkconfig/code/main.py
```

修改 `create_configuration()` 中的地址、Token、超时、重试、缓存或治理配置即可改变启动参数。

示例也直接设置本地实例熔断的 7 个参数：打开等待 15 秒、半开成功数与配额 2、连续失败 5、
错误率 60%、窗口 30 秒、最小样本 20，默认规则开启。输出包含对应生效值，
参数定义见 [本地实例熔断](../../../docs/circuitbreaker.md)。

日志通过 YAML 之外的 `LogOptions` 配置，例如：

```python
from polaris import Configuration, ProviderAPI, init_context_by_config
from examples._internal._runtime import demo_log_options
config = Configuration()
config.set_default()
connector = config.get_global().get_server_connector()
connector.addresses = ["127.0.0.1:8091"]
connector.token = "access-token"
connector.connect_timeout = 1000
connector.message_time = 3000
config.get_global().get_api().timeout = 5000
config.get_consumer().get_local_cache().service_refresh_interval = 5000
system = config.get_global().get_system()
system.discover_cluster.namespace = "Polaris"
system.discover_cluster.service = "polaris.discover"
system.discover_cluster.refresh_interval = 60000

log_options = demo_log_options(__file__, level="warn")
log_options.max_bytes = 50 * 1024 * 1024
log_options.backup_count = 5
log_options.max_age_days = 30
context = init_context_by_config(config, log_options=log_options)
try:
    provider = ProviderAPI(context)
    provider.check_available()
finally:
    context.destroy()
```

也可以通过 `GlobalConfig`、`ServerConnectorConfig`、`ConsumerConfig` 等配置类的构造函数组装对象后传入 `Configuration`。启动成功输出实际生效配置、共用上下文和销毁标记，Token 仅输出是否配置。

三个系统集群可以直接从 `SystemConfig` 赋值，层级与 Java / Go 一致；当前仍只连接显式接入地址，尚未按这些系统服务动态发现服务端节点。完整字段见 [配置说明](../../../docs/config/polaris.yaml)。

命名空间由注册 / 发现请求指定，不提供顶层 `config.namespace`。
日志不属于 SDK 配置；创建 context 时未指定的日志选项读取 `POLARIS_LOG_*`。
本示例显式设置日志级别和根目录，不受这两个环境变量覆盖。日志按 `base`、`network`、
`cache`、`route`、`circuitbreaker` 等子目录划分，每类文件保留 clientId 并独立滚动。
也可使用 `file_path` 指定基础日志文件；它不能与 `log_dir` 同时设置。主动探测属于 P2，当前不支持。
配置在创建 context 时深拷贝，原对象的后续修改不会影响其他 context。
`LogOptions` 同时支持构造参数和直接字段赋值；每个 context 在创建时读取选项，
之后修改该对象不会热更新已有日志文件、级别或滚动参数。

离线自动验证见 [SDK 启动配置示例](../README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only sdkconfig/code
make -C examples/sdkconfig/code run ARGS="--help"
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
