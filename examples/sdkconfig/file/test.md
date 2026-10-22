# sdkconfig/file 测试说明

本目录验证 YAML 文件启动、环境变量替换和覆盖、默认文件查找、字段校验及代码配置隔离。
这是 `sdkconfig` 中规模最大的验证场景。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行 `sdkconfig/verify.py --only file`。 |
| `run.sh` | 使用指定文件、默认查找或环境配置启动 SDK。 |
| `logs.sh` | 查看本目录的验证、控制台和 SDK 分类日志。 |
| `cleanup.sh` | 清理本目录的运行产物和已记录进程；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh 的典型用法

```bash
make -C examples/sdkconfig/file run ARGS="--no-env"
make -C examples/sdkconfig/file run ARGS="--config polaris.yaml"
make -C examples/sdkconfig/file run ARGS="--default"
make -C examples/sdkconfig/file run ARGS="--service demo --namespace default --timeout 10000"
```

- `--config` 显式加载 YAML；
- `--no-env` 禁止配置环境覆盖；
- `--default` 触发 `POLARIS_CONFIG_FILE`、当前目录和用户目录查找；
- `--service` 在启动后通过同步 `get_instances` 执行一次真实服务发现；
- 不指定 `--config` 时使用相邻 `polaris.yaml`。

日志由独立 `LogOptions` 管理；`--no-env` 不关闭日志环境变量。

## verify.sh 如何验证

验证器为每个 case 建立独立工作目录并运行 `main.py`。成功 case 比较完整 JSON；
失败 case 要求非零退出并匹配预期错误文本。启动时的 TCP 地址探测、网卡枚举和
客户端上报 RPC 被替换，其余配置加载与 SDK 生命周期使用真实实现。

覆盖范围包括：

- 显式文件、相邻文件、完整配置参考和系统集群层级；
- 熔断参数、默认规则开关及带单位时长；
- 自动 SDK IP、探测失败、指定网卡、显式 IP 和缺失网卡；
- 文件值保留与环境变量覆盖；
- `POLARIS_CONFIG_FILE`、当前目录、用户目录及显式路径优先级；
- `${POLARIS_SERVER}:8091`、`${POLARIS_SERVER_ADDRESS:默认值}` 等占位符；
- 缺失文件、损坏 YAML、未知字段、移除字段、错误扩展名和非法环境值；
- 代码配置不受损坏文件和非法环境变量影响。

## 判定和日志

只有全部预期成功和预期失败 case 都匹配时，验证器才返回 0。每个 case 的输出位于
本次 `.logs/verify-*/cases/` 下；SDK 分类日志在各 case 的 `polaris/log/`，cache 和锁文件在
同级 `polaris/backup/file/`，运行结束后仍可直接查看。

```bash
./examples/verify.sh --only sdkconfig/file
./examples/logs.sh --latest --tail 80
./examples/cleanup.sh --dry-run
```

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 每个 YAML/环境变量 case 的 `PASS`/`FAIL`、错误文本、JSON 和异常。 |
| `result.json` | 验证入口的退出码、超时和中断状态；单个预期失败 case 不会导致整体失败。 |
| `verification.log` | 所有 case 的断言汇总和 traceback；直接运行 `main.py` 时不存在。 |

预期失败 case 只有在进程非零退出且错误文本匹配时才算通过，因此不能只根据
`console.log` 中是否出现 `Error` 判断。每个 case 的 `stdout.log`、`stderr.log`、
`polaris/log/`、`polaris/backup/file/` 都位于独立 `cases/<entry>-NN/` 下。
完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

本 demo 不注册业务服务，也不创建业务实例：

| 项目 | 值 |
| --- | --- |
| namespace/service | 无 |
| 实例数 | 0 |
| SDK context | 成功 case 创建 1 个；预期失败 case 在 context 创建前退出 |
| 默认连接/探测地址 | `127.0.0.1:8091` |
| 多地址 case | `127.0.0.2:8091`、`127.0.0.3:8092` 等 |
| 业务监听端口 | 无 |

这些地址用于验证 YAML、占位符、环境变量和 SDK bind IP 探测。测试替身会接收连接和
`ReportClient`，但不会向 Polaris 注册服务实例。使用 `--service` 手动运行时也只做
发现，不注册实例。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only sdkconfig/file
```

脚本先注册一个 `polaris-python-e2e-sdkconfig-file-<年月日时分秒毫秒>` Provider，host 为 SDK 探测到的
本机 IP，端口动态分配。随后使用本目录 YAML 和环境覆盖启动 Consumer，通过真实 gRPC
发现该实例；file demo 不注册业务实例。

成功效果为 discovery 返回相同 instance ID、配置和 shared context 生效、context 销毁。
最终 JSON 包含临时 service、Provider 信息和完整 discovery 结果。
完整规则见[真实服务验证说明](../../README-zh.md#真实服务验证)。
