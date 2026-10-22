# cache/expiry 测试说明

本目录验证资源闲置淘汰是否真正停止刷新、关闭发现流、删除磁盘备份，并在下一次访问时
重新从服务端加载。验证不访问外部 Polaris，但使用真实 SDK cache、后台事件循环、
淘汰扫描器和文件写入线程。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行约 8 秒的淘汰和重新加载验证。 |
| `run.sh` | 使用真实注册中心执行同一业务场景。 |
| `logs.sh` | 查看控制台和 `cache`、`network` 等 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并删除本目录产物；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=<host>:8091 \
  make -C examples/cache/expiry run ARGS="default demo --expire-ms 5000"
```

示例要求服务中已存在 `default/demo` 实例。它会发现两次：首次加载，等待闲置淘汰后
再次加载。`--expire-ms` 最小值是 5000；`--config` 可指定 YAML。

## verify.sh 如何验证

验证器构造实例资源，并把 fake stub 注入真实
`GrpcConnection._stub`。之后：

1. 使用 5000 ms 闲置阈值和 2500 ms 扫描间隔启动真实 SDK context。
2. 通过同步 `get_instances` 发起首次发现，并写入内存及本次运行 `polaris/backup/` 下的磁盘 cache。
3. 等待实际扫描触发，检查实例资源已淘汰。
4. 检查服务注册表、后台刷新任务和 discover stream 已清空或关闭。
5. 检查实例备份文件及 cache 查询结果均已删除。
6. 再次通过同步 `get_instances` 重新发现，确认返回相同实例 ID，但对象是新加载的实例。
7. 检查重新建立的 1 个流和重新写入的实例备份。
8. 销毁 context，确认第二次建立的流关闭、事件线程停止、写入线程结束、锁文件关闭。

成功时输出 JSON，包含 `evicted_resources: 1`、`reopened_streams: 1`、
`backups_deleted: true` 和 `context_destroyed: true`。

## 判定和日志

任何资源未淘汰、流未关闭、备份未删除、重新加载 ID 不一致或线程未退出都会返回非零。

```bash
./examples/verify.sh --only cache/expiry
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category cache --follow
./examples/cleanup.sh --dry-run
```

验证耗时来自真实的时间和后台扫描，不使用“跳过 sleep”的 mock。SDK 日志在
`.logs/verify-*/polaris/log/`，cache 和锁文件在同级 `polaris/backup/`，结果保存在运行目录根部，
运行结束后均可直接查看或统一清理。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 淘汰和重载 JSON、`PASS`/`FAIL`、后台任务异常。 |
| `result.json` | 退出码、是否超时和是否被中断；退出码 0 且未超时才表示验证完成。 |
| `verification.log` | 淘汰数量、重新加载 ID、流关闭、备份删除和线程清理断言。 |

验证成功时 `polaris/backup/` 可能只保留当前快照和锁文件，因为淘汰阶段会按断言删除旧备份。
完整说明见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

| 项目 | 值 |
| --- | --- |
| namespace/service | `ns/svc` |
| 发现实例 ID | `instance-1` |
| host/port | `127.0.0.1:8080` |
| 注册实例 | 无 |
| fake registry | `offline:8091`，由 stub 替换 |

验证器创建 SDK context 和 discover 流，但没有 Provider 注册。手动运行
`make -C examples/cache/expiry run ARGS="default demo"` 时，服务 `default/demo` 必须已经存在，实例端口由远端返回。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only cache/expiry
```

脚本注册一个 `polaris-python-e2e-cache-expiry-<年月日时分秒毫秒>` Provider，host 为本机 IP，端口
动态分配。expiry demo 只发现该实例，等待 5 秒闲置阈值和真实扫描后重新发现。

成功效果是 `initial_ids` 与 `reloaded_ids` 都包含同一 Provider ID，context 销毁，
cache 写线程结束。最终 JSON 给出 service、instance ID、host/port、淘汰和重载结果。
完整规则见[真实服务验证说明](../../README-zh.md#真实服务验证)。
