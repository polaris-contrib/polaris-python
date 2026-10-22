# multicontext 测试说明

本目录验证两个独立 `SDKContext` 的注册、心跳、发现、缓存和日志隔离，以及销毁一个
context 后另一个仍可继续工作。验证不访问外部注册中心。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 在隔离子进程运行真实 `main.py`，替换 gRPC channel/stub 边界。 |
| `run.sh` | 对真实注册中心运行两个 context 场景。 |
| `logs.sh` | 查看两个客户端分组的 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并删除 `.logs/`、`.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
POLARIS_E2E=1 \
POLARIS_FIRST_SERVER=<host1>:8091 \
POLARIS_SECOND_SERVER=<host2>:8091 \
POLARIS_FIRST_TOKEN= \
POLARIS_SECOND_TOKEN= \
POLARIS_FIRST_SERVICE_TOKEN=<first-token> \
POLARIS_SECOND_SERVICE_TOKEN=<second-token> \
make -C examples/multicontext run ARGS="--namespace default --service multicontext-example --ttl 5 --seconds 6"
```

两个 context 分别注册不同端口实例。示例先发现两边服务，反注册并销毁第一个 context，
验证第一套 API 已拒绝访问；等待后第二个 context 仍能发现并继续工作，最后全部反注册。
`--work-dir` 与 `--backup-dir` 是同一参数；默认把 `first/`、`second/` 放在
`.logs/manual/polaris/backup/`，与 `polaris/log/` 日志同级。

## verify.sh 如何验证

验证器启动独立进程执行真实 `main.py`，只替换：

- `grpc.aio.insecure_channel`；
- `PolarisGRPCStub`；
- TCP 地址探测和本机 socket 获取。

stub 为每个 channel 保存 owner loop、clientId、调用记录和关闭状态，并检查：

- 两个 channel 属于不同事件循环、具有不同 clientId；
- Token 进入正确的 `x-polaris-token` metadata；
- 注册使用异步 metadata、正确 host 和 TTL；
- 每个 context 恰好注册和反注册一次；
- 第一个 context 至少心跳一次，第二个在第一个销毁后继续心跳；
- 两个 context 发现各自独立实例；
- 同步 `get_instances` 在工作线程中执行，返回结果与异步发现一致；
- 销毁第一个后，其 API 被拒绝，第二个仍可用；
- 最终两个 context 全部销毁，channel 全部关闭；
- 防火墙式检查确认一个 context 的日志不包含另一个 clientId；
- 两个 context 的磁盘 cache 目录不同；
- 线程、写线程、锁文件、注册状态、插件和日志句柄全部释放。

成功时输出：

```text
PASS multi-context registration, heartbeat, discovery and independent destruction
```

## 执行和产物

```bash
./examples/verify.sh --only multicontext
./examples/logs.sh --latest --tail 60
./examples/logs.sh --latest --category network --tail 60
./examples/cleanup.sh --dry-run
```

每次验证保存 `stdout.log`、`stderr.log`、`verification.log`、`result.json`。
两个客户端各自的 cache 位于 `polaris/backup/first/`、`polaris/backup/second/`，日志位于同级的
`polaris/log/first/`、`polaris/log/second/`。
任何 clientId 泄漏、错误的 loop/channel、未配对注册/反注册、未清理线程或错误的
发现结果都会返回非零。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 管理程序捕获的入口输出、场景顺序、`PASS`/`FAIL` 和异常。 |
| `result.json` | 管理器记录的退出码、超时和中断状态；直接运行 `main.py` 时不存在。 |
| `verification.log` | 验证器的 stdout/stderr、资源检查和 traceback。 |

`stdout.log`/`stderr.log` 是隔离子进程的独立输出；SDK 日志在 `polaris/log/first/`、
`polaris/log/second/`，cache 和锁文件在同级 `polaris/backup/first/`、`polaris/backup/second/`。
完整说明见[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

验证器在 fake registry 中注册两个实例：

| 项目 | 值 |
| --- | --- |
| namespace/service | `default/multicontext-example` |
| 实例数 | 2 |
| host | 两者均为 `127.0.0.1` |
| port | first 为 `8081`，second 为 `8082` |
| instance ID | fake registry 分别返回 `first:8091`、`second:8091` |
| registry 地址 | `first:8091`、`second:8091` |
| TTL | 验证时为 1 秒 |

两个 `SDKContext` 各自注册一个实例，并拥有不同 client ID、通道、cache 和日志目录。
验证不会连接真实 DNS 或网络；channel 和 stub 均被替换。手动运行时默认连接
`127.0.0.1:8091`，namespace/service 仍为 `default/multicontext-example`，注册
host 为到 registry 建连时使用的本机 IP，端口固定为 `8081` 和 `8082`。使用
`--first-server`、`--second-server` 可以切换 registry 地址。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only multicontext
```

脚本创建唯一服务 `polaris-python-e2e-multicontext-<年月日时分秒毫秒>`，在
`python-integration` 注册两个实例：本机探测 IP 的 `8081` 和 `8082`，TTL 3 秒。
两个 SDK context 使用独立 client ID、channel、cache 和日志。

成功效果为两个实例均能发现、心跳持续、销毁第一个后第二个仍可发现、最终两个实例都
反注册并销毁 context。最终 JSON 包含 service、两个 instance ID、host/port、
client IDs 和 `effect`。完整规则见[真实服务验证说明](../README-zh.md#真实服务验证)。
