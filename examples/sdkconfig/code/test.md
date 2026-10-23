# sdkconfig/code 测试说明

本目录验证完全由代码构造 `Configuration` 的启动路径。验证检查配置生效值、
三个 API 共用 context、context 销毁，以及纯代码模式不读取文件或环境变量。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行 `sdkconfig/verify.py --only code`。 |
| `run.sh` | 启动本目录 `main.py`，验证手动运行时的配置输出。 |
| `logs.sh` | 查看本目录保留的控制台和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并清理 `.logs/`、`.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

## 离线验证

验证器在隔离进程中运行 `main.py`，解析最后一行 JSON，并检查：

- 地址、protocol、超时、重试和 bind IP；
- cache 类型、刷新间隔和 load balancer；
- 指定 `--service` 时，同步 `get_instances` 返回目标服务实例；
- 状态上报开关；
- 本地实例熔断的 7 个参数；
- `source: code`；
- Provider、Consumer 共用同一个 context；
- `context_destroyed: true`。

验证包含两个 case：

1. 目录中没有配置文件时正常启动；
2. 创建损坏的 YAML，同时设置缺失的 `POLARIS_CONFIG_FILE`、远端地址和非法超时，
   纯代码启动仍必须忽略这些输入并成功。

这说明代码配置不会意外触发默认文件查找，也不依赖 SDK 配置环境变量覆盖。
日志选项仍通过独立的 `LogOptions` 指定。

## run.sh

```bash
make -C examples/sdkconfig/code run ARGS="--help"
```

示例启动后会打印实际生效配置并自动销毁 context。它主要用于观察配置，不会执行远端
注册或服务发现。修改 `create_configuration()` 可以直接改变运行参数。

## 查看和清理

```bash
./examples/verify.sh --only sdkconfig/code
./examples/logs.sh --latest --tail 50
./examples/cleanup.sh --dry-run
```

每个 case 的 stdout/stderr、SDK 日志和验证输出都保存在本次 `.logs/verify-*` 下。
失败时管理程序返回非零并保留全部产物。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 两个纯代码配置 case 的启动 JSON、`PASS`/`FAIL` 和 traceback。 |
| `result.json` | 管理器的最终退出码、超时和中断状态；退出码 0 才表示验证入口完成。 |
| `verification.log` | 配置字段断言和异常；直接 `run.sh` 通常不生成。 |

各 case 的详细输出在 `cases/<entry>-NN/`，SDK 日志在其 `polaris/log/`，cache 和锁文件在
同级 `polaris/backup/`。完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

本 demo 不注册业务服务，不创建服务实例，也不监听业务端口。

| 项目 | 值 |
| --- | --- |
| namespace/service | 无 |
| 实例数 | 0 |
| SDK context | 每个 case 创建 1 个 |
| 配置中的连接地址 | `127.0.0.1:8091`，验证时由 fake RPC 边界处理 |
| 业务监听端口 | 无 |

代码配置中出现的 `127.0.0.1:8091` 是 Polaris gRPC 地址，不是注册实例端口。
`ReportClient` 使用 SDK client ID，但不会在 Polaris 创建业务服务实例。

## 远端验证

这一路不替换 gRPC，也不重跑离线的损坏 YAML、非法超时和默认文件查找。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only sdkconfig/code
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-sdkconfig-code-<年月日时分秒毫秒>`。demo 超时 30 秒。

步骤：

1. quickstart Provider 注册实例。动态端口，host 为建连时的本机 IP，TTL 1 秒，进程保持心跳。
2. 最多 20 秒，直到不带缓存的发现返回这个 instance id。
3. 本目录 `main.py` 不读 YAML。`--server` 直接写成 `POLARIS_SERVER_ADDRESS`，再带上命名空间、服务名和 `--timeout 5000`。连接超时、消息超时、bind IP 和重试次数用代码里的赋值。
4. 发现结果 `discovery.instances[0].id` 必须等于注册得到的 instance id。demo 销毁自己的 context。Provider 仍在运行，验证器不反注册。

通过条件就是这个 ID 相等。JSON 还含 service、provider host/port。离线打印的整份生效配置对照不在这一路。运行目录是 `.logs/verify-e2e-<时间>-<编号>/`，示例输出在 `code.stdout.log`。`./examples/cleanup.sh --force` 停 Provider，`--delete-services` 删服务。
