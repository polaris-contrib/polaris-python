# 本地缓存示例

这些示例检查发现结果的磁盘备份：进程被强制结束后能否用已完成的快照恢复，以及闲置服务的内存和备份何时被删除。

在仓库根目录执行，默认不连接外部注册中心：

```bash
uv run --locked python examples/cache/expiry/verify.py
uv run --locked python examples/cache/restart/verify.py
```

| 目录 | 内容 |
| --- | --- |
| [闲置淘汰](expiry/README-zh.md) | 超过 `serviceExpireTime` 后停止刷新、关闭 Discover 流并删除备份 |
| [重启恢复](restart/README-zh.md) | 写入过程中 `SIGKILL`，再用同一 `persistDir` 做同步和异步发现 |

连接真实注册中心时设置 `POLARIS_E2E=1`。示例只发现已有服务，不注册或反注册实例。不同 context 或不同注册中心应使用不同的 `persistDir`。

英文说明见 [`expiry/README.md`](expiry/README.md) 和 [`restart/README.md`](restart/README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only cache
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../README-zh.md)。
