# Cache Examples

本目录汇总 [expiry](expiry/README.md) 和 [restart](restart/README.md) 两个缓存 demo。

从仓库根目录执行：

```bash
./examples/verify.sh --only cache
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category cache --follow
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

验证输出和 SDK 分类日志分别保存在 `expiry/.logs/` 和 `restart/.logs/` 下。
两个子目录用 `make -C examples/cache/expiry run` 和 `make -C examples/cache/restart run` 启动。
日志、缓存和已记录的进程可通过 `cleanup.sh` 清理；默认先展示并确认。
