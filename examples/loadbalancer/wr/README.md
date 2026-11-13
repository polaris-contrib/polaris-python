# 加权随机选择实例

`main.py` 复用同一个 `ConsumerAPI`，用加权随机负载均衡调用 `async_get_one_instance()` 和 `get_one_instance()`。日志级别设为 `warn`，连接超时设为 2 秒。

在仓库根目录执行：

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=loadbalancer/wr ARGS='<namespace> <service> <times>'
```

例如：

```bash
make -C examples run DEMO=loadbalancer/wr ARGS='default demo 3'
```

`<times>` 是每一轮的选择次数。示例先做 `<times>` 次异步选择：每次打印 `host` 和 `port`，上报一次成功调用结果，再等待 5 秒；`--interval` 可调整等待秒数。异步轮次结束后打印 `use sync method`，再做 `<times>` 次同步选择，并同样上报成功结果。没有可用实例时退出。结束时销毁这个 Consumer。

调用结果上报放在真实调用下游之后。本示例没有真实下游，固定上报成功、返回码 `0`、延迟 `1`。查看全部实例和 context 隔离时，参考 [多 context 示例](../../multicontext/README.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only loadbalancer/wr --latest --tail 30'
make -C examples logs ARGS='--only loadbalancer/wr --latest --category network --follow'
make -C examples cleanup ARGS='--only loadbalancer/wr --dry-run'
make -C examples cleanup ARGS='--only loadbalancer/wr'
```

示例输出和 SDK 日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py`
时使用 `.logs/manual/`。本目录 `make run ARGS='default demo 3'` 使用同一运行脚本。
默认清理先展示并确认，`--force` 跳过确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。
完整运行和目录规则见 [示例总览](../../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only loadbalancer/wr`；真实验证使用
`./integration/verify_e2e.sh --only loadbalancer/wr`。测试步骤和集成测试产物见
[integration/scenarios/loadbalancer/wr/test.md](../../../integration/scenarios/loadbalancer/wr/test.md)。
