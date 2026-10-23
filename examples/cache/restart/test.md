# cache/restart 测试说明

本目录验证 SDK 在同一持久化目录中，经过一次中断写入和进程强制退出后，仍能用完整
备份恢复实例资源。验证使用真实 gRPC transport、真实文件写入和真实子进程，
不依赖外部注册中心。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 启动临时 gRPC 服务、子进程和恢复流程，执行完整验证。 |
| `run.sh` | 使用真实注册中心发现并写入指定持久化目录。 |
| `logs.sh` | 查看控制器、子进程和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录已记录进程并清理验证产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=<host>:8091 \
  make -C examples/cache/restart run ARGS="default demo"
```

`--persist-dir` 省略时使用与 `polaris/log/` 日志同级的 `.logs/manual/polaris/backup/restart`，
也可以显式选择其他可保留目录。示例只发现服务，不注册实例。
远端不可用时，用相同目录再次启动会在首次等待超时后返回合法磁盘快照。

## 离线验证

验证器先启动一个临时 loopback gRPC 服务，然后运行三个独立子进程阶段：

1. `seed`：
   - 通过实际 gRPC transport 获取实例快照；
   - 等待正常备份写入；
   - 拦截 `os.replace`，在临时文件已同步但尚未替换正式文件时阻塞；
   - 验证器发送 `SIGKILL`，模拟进程崩溃。
2. `sync` / `async`，服务端已停止：
   - 用同一 `persistDir` 分别在备份年龄为 0 秒和 120 秒时发现；
   - 首次等待受 API timeout 限制，超时后返回备份里的 `instance-1`，不将其标记为远端已更新。
3. 重新启动服务端并返回 `revision-live`：
   - 备份年龄仍为 120 秒；
   - 同步和异步发现都返回远端实例和这个新 revision。

验证器还检查：

- 中断后 `.tmp` 文件至少存在一个；
- 未完成临时文件不会被当成完整快照；
- 正式备份只有 `svc#ns#svc#instance.json`；
- 离线降级后磁盘 revision 仍是 seed 写入的 `revision-1`；
- 每个子进程退出时事件线程、cache 写线程和读线程均结束。

成功时输出包含 `abrupt_exit: true`、`offline_restart_loaded: ["sync", "async"]`、
`remote_revision: "revision-live"`、`backup_ages_seconds: [0, 120]` 和
`partial_write_ignored: true` 的 JSON。

## 执行和日志

```bash
./examples/verify.sh --only cache/restart
./examples/logs.sh --latest --tail 80
./examples/logs.sh --latest --category cache --tail 80
./examples/cleanup.sh --dry-run
```

验证约需十余秒。多个子进程的 SDK 日志在本次 `.logs/verify-*/polaris/log/`，cache 快照、
锁文件、正式文件和 `.tmp` 文件在同级 `polaris/backup/`，结果在运行目录根部。
任何阶段超时、返回码错误、临时文件被误用或恢复字段不一致都会失败。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | seed、SIGKILL、sync/async 恢复流程、恢复 JSON、`PASS`/`FAIL` 和异常。 |
| `result.json` | 验证入口的退出码、超时和中断状态；恢复断言失败会返回非零。 |
| `verification.log` | 临时文件、备份年龄、revision 和资源清理断言。 |

`polaris/backup/` 中正式快照和 `.tmp` 同时存在是验证的预期现象，验证器需要确认未完成的
`.tmp` 不会被读取。不要仅凭 `.tmp` 存在判断失败。完整说明见
[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

| 项目 | 值 |
| --- | --- |
| namespace/service | `ns/svc` |
| 快照实例 ID | `instance-1` |
| host/port | `192.0.2.1:8080` |
| 注册实例 | 无 |
| 临时 gRPC 服务 | `127.0.0.1:0`，动态端口 |

临时 gRPC 服务只返回 Discover 快照和 `ReportClient` 响应，不注册业务实例。
手动运行 `make -C examples/cache/restart run ARGS="default demo"` 时只发现已有的 `default/demo`；实例的 host/port
由目标注册中心返回，不由该 demo 创建。

## 远端验证

这一路不替换 gRPC，也不杀进程，也不把注册中心停掉再拉起来。它只确认真实发现能落地一份备份。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only cache/restart
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-cache-restart-<年月日时分秒毫秒>`。demo 超时 30 秒。

步骤：

1. quickstart Provider 注册实例。动态端口，host 为建连时的本机 IP，TTL 1 秒，进程保持心跳。
2. 最多 20 秒，直到不带缓存的发现返回这个 instance id。
3. 本目录 `main.py` 用环境变量里的注册中心地址做一次异步 `get_instances`，
   `--metrics-port 0` 让指标监听使用动态端口。持久化目录是这次运行目录下的
   `polaris/backup/restart`。
4. 返回的实例 ID 列表必须等于 `[注册得到的 instance id]`。
5. 该目录下必须存在匹配 `svc#<命名空间>#<服务>#*.json` 的文件。命名空间和服务名里的特殊字符按 URL 编码写进文件名。demo 销毁自己的 context。Provider 仍在运行，验证器不反注册。

统一远端验证明确使用动态指标端口，避免与前面保留运行的 demo 冲突。离线验证里的
半截临时文件、SIGKILL、磁盘 revision 降级和远端新 revision 不在这一路。
运行目录是 `.logs/verify-e2e-<时间>-<编号>/`，发现 JSON 在
`restart.stdout.log`。`./examples/cleanup.sh --force` 停 Provider，
`--delete-services` 删服务。
