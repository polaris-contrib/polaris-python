# 随机选择实例

`main.py` 复用同一个 `ConsumerAPI`，将负载均衡器配置为 `random`，通过
`async_get_one_instance()` 和 `get_one_instance()` 从服务实例列表中按数量均匀随机选择。
实例权重不参与该策略；需要按权重选择时使用 [`wr`](../wr/README.md)。

在仓库根目录执行：

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
uv run --locked python examples/loadbalancer/random/main.py \
  <namespace> <service> <times>
```

例如：

```bash
uv run --locked python examples/loadbalancer/random/main.py \
  default demo 3
```

`<times>` 是每一轮的选择次数。示例先做异步选择，每次打印 `host` 和 `port`，上报一次成功
调用结果，再等待 5 秒；`--interval` 可调整等待秒数。异步轮次结束后打印
`use sync method`，再做相同次数的同步选择并上报结果。没有可用实例时退出，结束时销毁
Consumer。

## 验证、日志和清理

离线验证使用实际的 `random` 插件，替换注册中心 RPC。两个实例使用不同权重，验证器固定
随机索引序列，确认异步和同步各选择 40 次、两个实例各被选择 20 次，并检查每次选择都上报
一次结果，退出时 context、线程和日志句柄均已关闭。

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only loadbalancer/random
make -C examples/loadbalancer/random run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；父目录 `loadbalancer` 依次验证 `random` 和 `wr`。
每次执行保留独立的 `.logs/` 目录、控制台输出、SDK 分类日志和结果。
完整运行和清理规则见[示例总览](../../README-zh.md)。
