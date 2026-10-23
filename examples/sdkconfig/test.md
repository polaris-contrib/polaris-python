# sdkconfig 测试说明

本目录是 SDK 启动配置验证的汇总目录，包含两个独立子场景：

- `code`：完全通过代码创建配置；
- `file`：从 YAML 文件、默认文件或环境变量创建配置。

默认 `verify.sh` 依次运行两者。也可以只运行一个：

```bash
./examples/verify.sh --only sdkconfig/code
./examples/verify.sh --only sdkconfig/file
./examples/verify.sh --only sdkconfig/code,sdkconfig/file
```

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 通过 `--only` 选择并运行一个或两个配置场景。 |
| `logs.sh` | 查看 `code/` 和 `file/` 下的验证及 SDK 分类日志。 |
| `cleanup.sh` | 清理本目录及两个子 demo 的日志、运行时缓存和已记录进程；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有 `main.py`，不提供 `run.sh`。

## 验证组织

`sdkconfig/verify.py` 定义成功和预期失败两类验证：

- 成功场景运行 `main.py`，解析最后一行 JSON，逐字段比较生效配置；
- 失败场景要求进程非零退出，并检查错误文本包含预期原因；
- 每个场景都在独立 `cases/<entry>-NN/` 目录执行；
- 地址探测、网卡枚举和启动上报 RPC 使用测试替身；
- YAML 解析、环境覆盖、配置校验、插件装配、context 启动和销毁使用实际实现。

`code` 和 `file` 共用这个验证器，管理程序分别传入 `--only code` 和
`--only file`，所以不会重复运行无关场景。

## 离线验证

`file` 场景覆盖：

- 显式 YAML 与脚本旁 `polaris.yaml`；
- 本地实例熔断参数、默认规则开关和时长占位符；
- 最小配置参考和默认值填充；
- 自动探测 SDK IP、探测失败、指定网卡和显式 IP 优先级；
- `global.system` 下的 `discoverCluster`、`healthCheckCluster`、`monitorCluster`；
- 文件占位符、环境变量覆盖和 `--no-env`；
- `POLARIS_CONFIG_FILE`、当前目录和用户配置目录查找；
- Go provider 的 `${POLARIS_SERVER}:8091` 写法；
- 完整 `host:port` 环境变量覆盖；
- 缺失文件、非法 YAML、未知字段、旧字段和非 YAML 扩展名；
- 非法环境变量值。

`code` 场景覆盖：

- 不读取文件即可启动；
- 默认值与代码赋值生效；
- 本地熔断规则生效；
- 即使存在损坏 YAML 和非法环境变量，纯代码配置也不受其影响；
- Provider、Consumer 共用 context，并在退出时销毁。

## 判定和产物

验证器只有确认所有预期成功值、错误文本和退出码后才返回 0。任何配置字段不符合预期、
本应失败却成功、本应成功却失败，都会输出 `FAIL` 并返回非零。

```bash
./examples/verify.sh --only sdkconfig
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

每次验证在对应子目录的 `.logs/verify-<时间>-<编号>/` 下保存
`verification.log`、每个 case 的输出、SDK 日志和 `result.json`。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 汇总验证依次运行的 code/file 场景、每条 `PASS`/`FAIL` 和异常。 |
| `result.json` | 每个子场景的退出码、超时和中断状态；不是两个子场景的聚合统计。 |
| `verification.log` | 对应验证器的断言、JSON 和 traceback；`run.sh` 和直接运行通常不生成。 |

每个 case 还会生成自己的 `stdout.log`、`stderr.log`、`polaris/log/` 和 `polaris/backup/`。
完整字段说明见[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

`sdkconfig/code` 和 `sdkconfig/file` 都不注册 Polaris 业务服务，也不创建业务实例：

| 子场景 | 服务注册 | 实例 | 业务端口 |
| --- | --- | --- | --- |
| code | 无 | 无；仅创建 SDK context | 不监听 |
| file | 无 | 无；仅创建 SDK context | 不监听 |

验证中的 fake RPC 只处理 `ReportClient` 和启动 IP 探测。地址字段通常为
`127.0.0.1:8091`，部分 case 使用 `127.0.0.2:8091`、`127.0.0.3:8092` 等模拟地址，
用于检查环境变量和配置优先级；这些都不是实际注册的服务实例。

## 远端验证

`--only sdkconfig` 依次跑 code 和 file。离线那一组 YAML 优先级、占位符和非法超时不在这一路重复。两个子目录的 `test.md` 写了逐步说明。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only sdkconfig
./examples/verify_e2e.sh --only code
```

每个子场景先用 quickstart Provider 注册一个 TTL 1 秒的实例，动态端口，host 为建连时的本机 IP，并等到发现能看到该 instance id。然后：

- code 用 `--server <POLARIS_SERVER_ADDRESS>` 在代码里填地址，超时 5000 毫秒，发现该服务。
- file 不传 `--server`，读 `file/polaris.yaml`，由环境变量 `POLARIS_SERVER_ADDRESS` 覆盖地址，超时同样 5000 毫秒。

两边都只断言发现结果的第一个实例 ID 等于刚注册的 ID。两个场景的服务名不同，分别是 `polaris-python-e2e-sdkconfig-code-<时间>` 和 `polaris-python-e2e-sdkconfig-file-<时间>`，命名空间默认 `python-integration`。Provider 保持运行，验证器不反注册。日志在各子目录 `.logs/verify-e2e-<时间>-<编号>/`。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
