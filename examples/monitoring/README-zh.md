# 调用监控

[English](README.md)

示例启动本地 HTTP echo 服务，通过 Polaris 注册和发现，实际调用三次
（200、503、200），并上报调用结果。支持 Prometheus 拉取和 Pushgateway 推送。

从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=monitoring ARGS='--mode pull'
```

拉取模式打印本机 `/metric` 地址，默认运行 31 秒，等待第一个 30 秒聚合周期后
打印指标。`--keep-running` 会保留 listener、context、进程和注册实例，直到
SIGINT/SIGTERM cleanup；默认模式退出时显式反注册并销毁 context。

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples run DEMO=monitoring ARGS='--mode push --push-address 127.0.0.1:9091'
```

不指定推送地址时发现 `Polaris/polaris.pushgateway`。
推送模式在配置的间隔后输出成功上报次数 `pushes`。
示例使用 `async_update_service_call_result` 上报调用结果；SDK 不自动拦截业务调用。
指标说明见 [可观测性](../../docs/guides/observability.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only monitoring --latest --tail 30'
make -C examples cleanup ARGS='--only monitoring --dry-run'
make -C examples cleanup ARGS='--only monitoring'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only monitoring`；真实验证使用
`./integration/verify_e2e.sh --only monitoring`。测试步骤和集成测试产物见
[integration/scenarios/monitoring/test.md](../../integration/scenarios/monitoring/test.md)。
