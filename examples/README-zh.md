# 示例

[English](README.md)

本项目示例覆盖已有 SDK 能力：

- [quickstart](quickstart/README.md)：同步注册、HTTP 服务发现、调用和结果上报。
- [circuitbreaker](circuitbreaker/README-zh.md)：本地实例熔断、路由和半开恢复。
- [sdkconfig/file](sdkconfig/file/README.md)、[sdkconfig/code](sdkconfig/code/README.md)：YAML 和纯代码启动。
- [cache/expiry](cache/expiry/README-zh.md)：闲置淘汰、流关闭和重新加载。
- [cache/restart](cache/restart/README-zh.md)：中断写入及离线进程重启恢复。
- [loadbalancer/random](loadbalancer/random/README.md)：异步及同步均匀随机选择。
- [loadbalancer/wr](loadbalancer/wr/README.md)：异步及同步加权随机选择。
- [servicerouter](servicerouter/test.md)：Java 对齐的前置 / 主 / 后置路由链和可选元数据路由。
- [multicontext](multicontext/README.md)：独立注册、心跳、发现和销毁。
- [mcp](mcp/README-zh.md)：通过 Provider/Consumer 注册 MCP、发现普通实例、显式上报契约与反注册。
- [skill](skill/README-zh.md)：已发布 Skill 查询、ZIP 下载与本地备份降级。
- [a2a](a2a/README-zh.md)：普通实例的 Agent metadata 注册、心跳、发现与反注册。
- [monitoring](monitoring/README-zh.md)：实际 HTTP 调用上报、Prometheus 拉取与 Pushgateway 推送。

首次在仓库根目录安装依赖：

```bash
uv sync --group dev --locked
```

每个 demo 目录都有 Makefile，目标与 Go examples 一致。`build` 生成 `bin`，`run` 运行它，`package` 生成 `.build/<目录名>.tar.gz`。程序参数用 `ARGS` 传入。`build-x86` 只在 linux/amd64 上执行。

```bash
make -C examples/quickstart/provider build
make -C examples/quickstart/provider run ARGS="--help"
make -C examples/quickstart package
```

`examples/Makefile` 运行同级脚本，参数放在 `ARGS` 里：

```bash
make -C examples verify ARGS="--help"
make -C examples verify ARGS="--only cache/expiry"
make -C examples verify-e2e ARGS="--only cache/restart"
make -C examples logs ARGS="--latest --tail 30"
make -C examples cleanup ARGS="--dry-run"
```

也可以直接写脚本名：`make -C examples verify_e2e.sh ARGS="--help"`。

离线验证、真实服务验证、日志和清理只从 `examples/` 根目录进入。脚本按自身位置查找仓库，
不依赖当前工作目录。优先使用 `POLARIS_PYTHON`，然后使用仓库 `.venv`，缺少时通过
`uv --project` 使用项目环境。

```bash
./examples/verify.sh
./examples/verify.sh --only circuitbreaker,cache
./examples/verify.sh --only cache/expiry
make -C examples/circuitbreaker/consumer run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category circuitbreaker --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
  ./examples/cleanup.sh --keep-logs --delete-services --force
```

`Makefile` 的 `run` 在 demo 目录启动 `main.py`，相对路径的 `--config` 从该目录解析。
各验证场景的判定步骤写在该目录的 `test.md`。

连接真实 Polaris：

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh
./examples/verify_e2e.sh --only cache/expiry
```

脚本会自动注册临时 Provider、验证发现和调用，并默认保留进程与注册实例；需要清理时
手动执行 `./examples/cleanup.sh --keep-logs --force` 只停进程、保留日志；执行
`--delete-services` 时会删除 `POLARIS_E2E_NAMESPACE` 下 `polaris-python-e2e-*`
测试服务。鉴权变量见下文
[真实服务验证](#真实服务验证)。

Provider / Consumer 子目录验证会运行其所属完整 quickstart 或熔断场景，结果保存在
所选子目录内。父目录逐一验证子 demo；`sdkconfig/code` 和 `sdkconfig/file` 各自只验证
对应启动场景。离线验证无需外部注册中心；quickstart、circuitbreaker、cache/restart
会监听本机临时端口。

每次执行生成独立的 `<demo>/.logs/verify-<时间>-<编号>/` 或 `run-<时间>-<编号>/`。
`console.log` 保存运行输出，`verification.log` 保存验证输出，`result.json` 保存退出结果。
SDK 日志在 `polaris/log/` 或逐场景的 `cases/<entry>-NN/polaris/log/` 下，按 `base`、`network`、`cache`、`route`、
`circuitbreaker` 等子目录分类，文件保留 clientId。多个 Provider 或 context 各有独立
组件目录。成功或失败后都保留日志和验证缓存，可查看、跟踪并清理。
直接执行 `python main.py` 时 SDK 日志位于本 demo 的 `.logs/manual/polaris/log/`。`make run`
会同时保留控制台输出。直接执行 `python verify.py` 也会保留验证产物。
所有 demo 的缓存都放在与本次 `polaris/log/` 日志同级的 `polaris/backup/` 下。管理脚本和验证运行使用
`<运行目录>/polaris/backup/`；直接执行 `python main.py` 使用本 demo 的
`.logs/manual/polaris/backup/`。多个 Provider 或 context 再按组件拆分目录。
重启示例的 `--persist-dir` 默认指向该目录，多 context 示例的备份根目录也默认使用它。
`work/` 只保存配置和测试脚手架，不再保存 cache。

清理只作用于所选目录及其子 demo 的已记录进程、`.logs/` 和 `.runtime/`。
默认先展示并确认；`--dry-run` 只展示，`--force` 无需交互。`--keep-logs`
（别名 `--processes-only`）只停止已记录进程并保留 `.logs/`；进程记录会由 demo
在正常退出时自行移除。
`--delete-services`（别名 `--remote`）只删除测试创建的 `polaris-python-e2e-*` 服务。
进程记录校验 PID、启动时间和命令行，避免误停其他 demo 或复用 PID 的进程。
优先发送 SIGTERM，让 Provider 反注册并销毁 context；强制结束不能保证远端反注册。
显式指定并位于管理目录外的缓存、YAML 和源码不删除。

连接真实注册中心的 demo 保留原有参数及 `POLARIS_E2E` 开关要求，详见各目录说明。
`POLARIS_TOKEN` 是接入令牌，服务令牌用于 Provider 注册，两者用途不同。

## 真实服务验证

`examples/verify_e2e.sh` 连接真实 Polaris，自动注册临时服务实例，执行 demo 行为，
检查可观察结果。默认不反注册、不停止常驻进程；进程 PID 会记录到 `.runtime/processes`，
供 `cleanup.sh --keep-logs` 手动清理。清理后日志仍保留，进程记录会随正常退出移除。

### 必需环境变量

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
```

`POLARIS_E2E_SERVICE_TOKEN` 可以代替 `POLARIS_SERVICE_TOKEN`。服务令牌用于创建临时
Provider 实例；`POLARIS_TOKEN` 是 SDK 接入令牌，按服务端鉴权配置提供。

可选变量：

- `POLARIS_E2E_NAMESPACE`：验证使用的 namespace，默认 `python-integration`；
- `POLARIS_TOKEN`：SDK 接入令牌；
- `POLARIS_PYTHON`：选择执行验证的 Python 解释器。

### 运行

```bash
./examples/verify_e2e.sh
./examples/verify_e2e.sh --only cache/expiry
./examples/verify_e2e.sh --only loadbalancer/random
./examples/verify_e2e.sh --only cache
./examples/verify_e2e.sh --only loadbalancer/random,loadbalancer/wr
./examples/verify_e2e.sh --timeout 420
```

### 临时服务和实例

除特别说明外，验证使用以下命名：

```text
polaris-python-e2e-<demo 目录>-<年月日时分秒毫秒>
```

目录里的 `/` 写成 `-`。后缀是本地时间，精确到毫秒，例如 `20261021172930123`。
这些服务都注册到 `python-integration`。`cache/restart` 会注册为
`polaris-python-e2e-cache-restart-20261021172930123`，`loadbalancer/wr` 会注册为
`polaris-python-e2e-loadbalancer-wr-20261021172930123`。

每次执行创建新的 service 名，避免与已有实例冲突。Provider 通常以 `--port 0`
启动，由操作系统选择端口；实际服务名、instance ID、host 和 port 会打印在最终 JSON
中，同时写入 `console.log` 和 `verification.log`。

验证结束后脚本会：

1. 保留 Provider、Consumer、MCP 或多 context 进程；
2. 保留远端注册实例与心跳状态；
3. 把每个进程 PID 记录到对应 demo 的 `.runtime/processes/`；
4. 输出包含 `service`、`provider` 和 `effect` 的成功 JSON；
5. 不删除 `.logs/` 或 `polaris/backup/`。

手动清理时执行：

```bash
./examples/cleanup.sh --keep-logs --force
```

该命令只停止已记录进程，不删除日志。进程收到 SIGTERM 后会按 demo 自身
逻辑反注册并销毁 context；如果被强制杀死或验证中途中断，反注册可能无法完成，需要
根据输出的 service 名和 instance ID 在 Polaris 控制台清理残留实例。

### 与离线 verify.sh 的区别

| 脚本 | 注册中心 | 目的 |
| --- | --- | --- |
| `verify.sh` | fake stub，不连接外部服务 | 快速、确定性地验证完整逻辑和异常分支 |
| `verify_e2e.sh` | 真实 `POLARIS_SERVER_ADDRESS` | 验证实际网络、鉴权、注册、发现和调用效果，默认保留运行状态 |

两者使用相同的独立运行目录。真实服务验证的 `result.json.action` 为
`verify-e2e`，日志和 cache 仍分别位于 `polaris/log/`、`polaris/backup/`。

成功时 `result.json.exit_code` 为 0，`timed_out` 为 false，`interrupted` 为 null，
`verification.log` 有真实服务检查输出，最终 stdout 有 `PASS <demo>` 和包含 `effect`
的 JSON，且目标进程仍在运行。

常见失败包括服务令牌缺失、服务端不可达、注册后实例尚未被索引、目标实例无法从当前
网络访问、发现超时或反注册失败。验证器会轮询服务可见性，避免仅因注册索引传播延迟
产生偶发失败。

## 测试产物

`verify.sh` 和 `make run` 每次运行都会创建独立目录：

```text
<demo>/.logs/verify-<时间>-<编号>/   # 验证
<demo>/.logs/run-<时间>-<编号>/      # 运行
├── console.log
├── verification.log                 # 验证模式
├── result.json
├── polaris/log/                             # SDK 分类日志
├── polaris/backup/                          # cache、锁文件和持久化快照
└── work/                            # 配置及测试脚手架
```

部分父子 demo 会在运行目录下再建立 `provider/`、`consumer/` 或 `cases/`。

`console.log` 是管理程序捕获的入口子进程控制台输出，合并了 stdout 和 stderr。
常见内容包括 `RUN`、`VERIFY`、`PASS`、`FAIL`、启动 JSON、host/port、响应正文、
未捕获异常和嵌套子进程输出。它不包含完整的 SDK 分类日志；SDK 日志在 `polaris/log/` 下。

```bash
./examples/logs.sh --latest --tail 100
```

`result.json` 在子进程结束后生成：

```json
{
  "entry": "examples/cache/expiry/verify.py",
  "exit_code": 0,
  "timed_out": false,
  "interrupted": null,
  "action": "verify-e2e"
}
```

- `exit_code == 0`、`timed_out == false`、`interrupted == null`：正常完成；
- `exit_code != 0`：断言、配置、网络或启动失败；
- `timed_out == true`：超过 `--timeout`，管理程序返回 124；
- `interrupted != null`：被 SIGINT/SIGTERM 停止，管理程序返回 `128 + signal`。

`make run` 启动常驻 Provider/Consumer 后，用 Ctrl+C 结束时即使完成了反注册，
`result.json` 仍会记录 `interrupted`。这是人工中断，不代表业务断言失败。
直接执行 `python main.py` 或 `python verify.py` 不生成 `result.json`。

`verification.log` 保存验证器的 stdout、stderr、`PASS`/`FAIL`、JSON 汇总和 traceback。
文件为空或不存在时，当前操作可能是 `make run`、直接运行，或入口尚未进入验证逻辑。

`polaris/log/` 中的 `ERROR` 不一定意味着测试失败，以验证断言和 `result.json` 为准。
`polaris/backup/` 与 `polaris/log/` 同级，保存 cache 快照、锁文件和重启恢复所需的资源。
直接执行 `python main.py` 时产物位于 `<demo>/.logs/manual/polaris/log/` 和
`<demo>/.logs/manual/polaris/backup/`。`work/` 只保存临时配置和测试脚手架。

建议先看 `result.json`，再看 `verification.log`，然后用 `console.log` 对照启动和清理，
最后按失败类型查看 `polaris/log/` 或 `polaris/backup/`。`./examples/cleanup.sh --force` 会删除所选
demo 的 `.logs/`。
