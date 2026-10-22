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

## verify.sh 如何验证

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

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only cache/restart
```

脚本注册一个 `polaris-python-e2e-cache-restart-<年月日时分秒毫秒>` Provider，host 为本机 IP，端口
动态分配。restart demo 从真实 Polaris 读取服务数据，并将实例快照写入
`polaris/backup/restart/svc#<namespace>#<service>#instance.json`。

成功效果是结果 ID 等于 Provider ID、快照文件实际存在、Provider 反注册。最终 JSON
展示 service、instance ID、host/port、revision 和 `effect`。完整说明见
[真实服务验证说明](../../README-zh.md#真实服务验证)。
