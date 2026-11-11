# 无损上下线

[English](README.md)

从仓库根目录执行，在每个终端设置以下环境。先启动 consumer，再使用多个终端或 `&`
启动一个或多个 provider：

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
# 终端 1
make -C examples run DEMO=lossless/consumer
# 终端 2
make -C examples run DEMO=lossless/provider ARGS='--port 18081 --admin-port 28080'
# 终端 3
make -C examples run DEMO=lossless/provider ARGS='--port 18082 --admin-port 28081'
```

脚本以前台运行，两个程序分别读取相邻的 `polaris.yaml`。

Provider 会先启动 `/ready` 和 `/echo`，再调用 `lossless_register()`。默认策略为
`DELAY_BY_HEALTH_CHECK`，SDK 会轮询 `http://127.0.0.1:provider端口/ready`；
探测通过后才注册实例。探测期间 SDK 的 admin 端点返回 `503 UNREGISTERED`：

```bash
curl http://127.0.0.1:28080/readiness
```

注册完成后返回 `200 REGISTERED`。Consumer 已开启 warmup，新注册实例通过
`get_one_instance()` 获得的流量占比会逐渐增加；退出时会输出每个实例 ID 的调用次数。

无损下线时可以给 provider 发送 SIGTERM，也可以调用仅允许本机访问的 admin 端点：

```bash
curl -X POST http://127.0.0.1:28080/offline
```

SDK 会立即反注册实例，让消费端尽快从发现结果中移除它。

服务端下发的 lossless 规则优先于 `polaris.yaml` 中的本地配置。
`--service-token` 默认读取 `POLARIS_SERVICE_TOKEN`。完整配置见
[docs/guides/lossless.md](../../docs/guides/lossless.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only lossless --latest --tail 30'
make -C examples cleanup ARGS='--only lossless --dry-run'
make -C examples cleanup ARGS='--only lossless'
```

示例日志保存在各子 demo 的 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时
使用 `.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only lossless`；真实验证使用
`./integration/verify_e2e.sh --only lossless`。测试步骤和集成测试产物见
[integration/scenarios/lossless/test.md](../../integration/scenarios/lossless/test.md)。
