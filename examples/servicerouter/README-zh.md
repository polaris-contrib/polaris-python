# 服务路由

[English](README.md)

该示例通过公开 `polaris` API 演示 metadata router、熔断过滤和 recover router。

从仓库根目录执行，查询已有服务：

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=servicerouter ARGS='default demo 3 --mode default --interval 0'
make -C examples run DEMO=servicerouter ARGS='default demo 3 --mode metadata --metadata env=prod --failover none --interval 0'
```

每次运行先异步选择，再同步选择，打印各实例的 `host` 和 `port`。
`--metadata KEY=VALUE` 可重复传入；metadata 匹配的 `--failover` 支持 `none`、`all`、
`others`。本示例只选择实例，固定上报成功，不实际调用下游。
本目录 `make run ARGS='default demo 3 --mode default --interval 0'` 使用同一运行脚本。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only servicerouter --latest --category route --tail 30'
make -C examples cleanup ARGS='--only servicerouter --dry-run'
make -C examples cleanup ARGS='--only servicerouter'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only servicerouter`；真实验证使用
`./integration/verify_e2e.sh --only servicerouter`。测试步骤和集成测试产物见
[`integration/scenarios/servicerouter/test.md`](../../integration/scenarios/servicerouter/test.md)。
