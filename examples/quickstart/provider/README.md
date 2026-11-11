# Quickstart Provider

Provider 读取相邻的 `polaris.yaml`，启动 `/echo` HTTP 服务并注册实例，自动发送心跳。
`--port 0` 分配临时端口并在启动时打印；Ctrl-C / SIGTERM 时显式反注册并销毁 context。

从仓库根目录执行：

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=quickstart/provider ARGS='--service-token "" --port 0'
```

`--service-token` 必填，未开启服务鉴权时可传空字符串；服务端地址通过
`POLARIS_SERVER_ADDRESS` 配置。脚本以前台运行，Consumer 在另一终端启动，完整步骤见
[quickstart](../README.md)。也可用
`make -C examples/quickstart/provider run ARGS='--service-token "" --port 0'`。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only quickstart/provider --latest --tail 30'
make -C examples logs ARGS='--only quickstart/provider --latest --category cache --follow'
make -C examples cleanup ARGS='--only quickstart/provider --dry-run'
make -C examples cleanup ARGS='--only quickstart/provider'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，仅停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only quickstart/provider`；真实验证使用
`./integration/verify_e2e.sh --only quickstart/provider`。测试步骤和集成测试产物见
[integration/scenarios/quickstart/provider/test.md](../../../integration/scenarios/quickstart/provider/test.md)。
