# Cache Examples

本目录汇总 [expiry](expiry/README.md) 和 [restart](restart/README.md) 两个缓存 demo。

从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/expiry ARGS='default demo'
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/restart ARGS='default demo'
```

示例只发现已有服务。也可用 `make -C examples/cache run DEMO=expiry ARGS='default demo'`
选择子示例，并设置相同环境变量。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only cache --latest --tail 30'
make -C examples logs ARGS='--only cache --latest --category cache --follow'
make -C examples cleanup ARGS='--only cache --dry-run'
make -C examples cleanup ARGS='--only cache'
```

示例日志保存在各子 demo 的 `.logs/run-<时间>-<id>/`；直接执行 `python main.py` 时
使用 `.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only cache`；真实验证使用
`./integration/verify_e2e.sh --only cache`。测试步骤和集成测试产物见
[integration/scenarios/cache/test.md](../../integration/scenarios/cache/test.md)。
