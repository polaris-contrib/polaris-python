# Quickstart Consumer

Consumer 读取相邻的 `polaris.yaml`，通过同步发现调用 Provider 的 `/echo` 并上报调用结果。
先按 [quickstart](../README.md) 启动 Provider，再在另一个终端启动 Consumer。

从仓库根目录执行：

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=quickstart/consumer ARGS='--port 18080'
```

脚本以前台运行，访问 `http://127.0.0.1:18080/echo` 可收到 Provider 的响应。
`--namespace`、`--service` 应与 Provider 一致；Ctrl-C / SIGTERM 时停止 HTTP 并销毁 context。
也可用 `make -C examples/quickstart/consumer run ARGS='--port 18080'`。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only quickstart/consumer --latest --tail 30'
make -C examples logs ARGS='--only quickstart/consumer --latest --category cache --follow'
make -C examples cleanup ARGS='--only quickstart/consumer --dry-run'
make -C examples cleanup ARGS='--only quickstart/consumer'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，仅停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only quickstart/consumer`；真实验证使用
`./integration/verify_e2e.sh --only quickstart/consumer`。测试步骤和集成测试产物见
[integration/scenarios/quickstart/consumer/test.md](../../../integration/scenarios/quickstart/consumer/test.md)。
