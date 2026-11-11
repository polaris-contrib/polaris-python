# 随机选择实例

`main.py` 复用同一个 `ConsumerAPI`，将负载均衡器配置为 `random`，通过
`async_get_one_instance()` 和 `get_one_instance()` 从服务实例列表中按数量均匀随机选择。
实例权重不参与该策略；需要按权重选择时使用 [`wr`](../wr/README.md)。

在仓库根目录执行：

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
make -C examples run DEMO=loadbalancer/random ARGS='<namespace> <service> <times>'
```

例如：

```bash
make -C examples run DEMO=loadbalancer/random ARGS='default demo 3'
```

`<times>` 是每一轮的选择次数。示例先做异步选择，每次打印 `host` 和 `port`，上报一次成功
调用结果，再等待 5 秒；`--interval` 可调整等待秒数。异步轮次结束后打印
`use sync method`，再做相同次数的同步选择并上报结果。没有可用实例时退出，结束时销毁
Consumer。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only loadbalancer/random --latest --tail 30'
make -C examples logs ARGS='--only loadbalancer/random --latest --category network --follow'
make -C examples cleanup ARGS='--only loadbalancer/random --dry-run'
make -C examples cleanup ARGS='--only loadbalancer/random'
```

示例输出和 SDK 日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py`
时使用 `.logs/manual/`。本目录 `make run ARGS='default demo 3'` 使用同一运行脚本。
默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，不删除远端服务。
完整运行和清理规则见[示例总览](../../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only loadbalancer/random`；真实验证使用
`./integration/verify_e2e.sh --only loadbalancer/random`。测试步骤和集成测试产物见
[integration/scenarios/loadbalancer/random/test.md](../../../integration/scenarios/loadbalancer/random/test.md)。
