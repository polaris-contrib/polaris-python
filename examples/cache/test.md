# cache 测试说明

本目录汇总 SDK 本地缓存的两种验证：

- `expiry`：资源闲置淘汰、发现流关闭、备份删除和重新加载；
- `restart`：写入中断、临时文件忽略、进程重启和离线备份恢复。

默认 `verify.sh` 依次运行两者，也可以只选择其中一个：

```bash
./examples/verify.sh --only cache/expiry
./examples/verify.sh --only cache/restart
```

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 依次运行 `cache/expiry` 和 `cache/restart`。 |
| `logs.sh` | 查看两个子 demo 的控制台、验证和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录树内的已记录进程并删除 `.logs/`、`.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有 `main.py`，不提供 `run.sh`。

## 验证特性

两个验证都不访问外部 Polaris：

- expiry 用 fake discover stream 保留真实淘汰器、cache 和后台扫描；
- restart 在 `127.0.0.1` 启动临时真实 gRPC 服务，通过实际 transport 获取快照；
- restart 的读取进程使用独立子进程，并在一次备份写入过程中被 `SIGKILL`；
- 所有 cache 和锁文件均在与 `polaris/log/` 同级的 `.logs/verify-*/polaris/backup/` 下；
  `work/` 只保存测试脚手架。

expiry 主要观察内存资源、后台任务、发现流和备份是否同时清理；restart 主要观察进程
在非正常退出后能否丢弃未完成临时文件；服务端停止时默认发现不返回磁盘快照，服务端恢复后返回新的远端 revision。
前者验证“闲置后的正确释放”，后者验证“崩溃后的可恢复性”，两者共同覆盖 cache 的
删除与读取生命周期。

完整断言和产物说明见各子目录的 `test.md`。

verify.sh 会为两个场景分别创建独立 Python 子进程和结果目录。子验证器内部再启动
后台事件循环、文件写线程、临时 gRPC 服务或 worker 进程，并把控制台输出、逐客户端
SDK 日志和 `result.json` 写入各自运行目录。这样并发场景不会共享锁文件、备份目录或
进程 PID 记录。

## 执行和清理

```bash
./examples/verify.sh --only cache
./examples/logs.sh --latest --tail 80
./examples/logs.sh --latest --category cache --tail 80
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

汇总验证会根据子进程退出码报告 `2 passed, 0 failed`。任一子场景失败时，另一个仍会
继续执行，最后返回非零。超时、断言失败、子进程异常退出或资源未释放都不会被当成
成功；日志和失败现场会一直保留，直到显式执行 `cleanup.sh`。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | expiry/restart 子场景顺序、`PASS`/`FAIL`、恢复 JSON 和异常。 |
| `result.json` | 每个子场景的退出码、超时和中断状态；退出码 0 表示该场景验证结束。 |
| `verification.log` | 各子验证器的淘汰、恢复、临时文件和资源清理断言。 |

`polaris/log/` 保存 SDK 分类日志，`polaris/backup/` 保存快照、锁文件和 `.tmp`，`work/` 只保存
测试脚手架。完整说明见[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

两种 cache 验证都只发现服务，不注册业务实例：

| 子场景 | namespace/service | 发现的实例 | 注册实例 | 端口 |
| --- | --- | --- | --- | --- |
| expiry | `ns/svc` | `instance-1` | 无 | `127.0.0.1:8080` |
| restart | `ns/svc` | `instance-1` | 无 | `192.0.2.1:8080` |

cache/restart 自己启动的 gRPC 服务使用 `127.0.0.1:0` 动态端口，不注册业务实例。
手动运行时，`demo` 服务名和实例端口由目标 Polaris 中已有服务决定。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only cache
```

expiry 和 restart 分别创建唯一的动态端口 Provider，并由 cache demo 发现，不注册
业务实例。expiry 等待真实闲置阈值后重载同一实例；restart 从真实注册中心获取快照并
写入 `polaris/backup/restart/`。

效果：

- expiry 的 `initial_ids` 和 `reloaded_ids` 均包含临时 Provider ID；
- restart 的结果包含同一 Provider ID，且 backup 中存在对应快照；
- Provider 最后反注册，context 和写线程关闭。

可用 `--only expiry` 或 `--only restart`。完整说明见
[真实服务验证说明](../README-zh.md#真实服务验证)。
