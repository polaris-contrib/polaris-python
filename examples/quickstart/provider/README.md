# Quickstart Provider

Provider / Consumer 在本目录读取相邻的 `polaris.yaml`，验证运行完整 quickstart 场景。

从仓库根目录执行：

```bash
./examples/verify.sh --only quickstart/provider
make -C examples/quickstart/provider run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category cache --follow
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

验证输出和 SDK 分类日志保存在本 demo 的 `.logs/` 下。`make run` 把 `ARGS` 传给 `main.py`。
日志、缓存和已记录的进程可通过 `cleanup.sh` 清理；默认先展示并确认。
