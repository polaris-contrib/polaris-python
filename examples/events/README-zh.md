# SDK 事件

[English](README.md)

订阅当前 SDK 已实现能力发出的事件：实例缓存新增 / 更新 / 删除，以及本地实例熔断状态转换。
可选 Pushgateway 只上报 `InstanceThreadEnd` 和熔断状态事件。不提供限流、无损上下线、配置中心或 watch 事件。

从仓库根目录执行，连接真实注册中心：

```bash
make -C examples run DEMO=events ARGS='--server 127.0.0.1:8091 --namespace default --service DiscoverEchoServer'
```

监听接口和字段见 [事件中心](../../docs/guides/events.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only events --latest --tail 30'
make -C examples cleanup ARGS='--only events --dry-run'
make -C examples cleanup ARGS='--only events'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only events`；真实验证使用
`./integration/verify_e2e.sh --only events`。测试步骤和集成测试产物见
[integration/scenarios/events/test.md](../../integration/scenarios/events/test.md)。
