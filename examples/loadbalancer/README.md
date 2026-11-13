# 单实例发现示例

这些示例从服务里选出一个实例：

- [`random`](random/README.md)：按实例数量均匀随机选择，实例权重不参与选择。
- [`wr`](wr/README.md)：先异步选择并上报调用结果，再做同样次数的同步选择。

可以在仓库根目录或 demo 目录运行，并先设置 `POLARIS_SERVER` 和可选的 `POLARIS_TOKEN`。

从仓库根目录执行：

```bash
POLARIS_SERVER=127.0.0.1:8091 make -C examples run DEMO=loadbalancer/random ARGS='default demo 3'
POLARIS_SERVER=127.0.0.1:8091 make -C examples run DEMO=loadbalancer/wr ARGS='default demo 3'
```

组 Makefile 可用 `make -C examples/loadbalancer run DEMO=random ARGS='default demo 3'`
选择子示例。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only loadbalancer --latest --tail 30'
make -C examples logs ARGS='--only loadbalancer --latest --category network --follow'
make -C examples cleanup ARGS='--only loadbalancer --dry-run'
make -C examples cleanup ARGS='--only loadbalancer'
```

示例日志保存在各子 demo 的 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时
使用 `.logs/manual/`。默认清理先展示并确认，`--force` 跳过确认，只停止记录的示例 PID
并清除本地生成产物，不删除远端服务。完整运行规则见 [示例总览](../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only loadbalancer`；真实验证使用
`./integration/verify_e2e.sh --only loadbalancer`。测试步骤和集成测试产物见
[integration/scenarios/loadbalancer/test.md](../../integration/scenarios/loadbalancer/test.md)。
