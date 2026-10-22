# 加权随机选择实例

`main.py` 复用同一个 `ConsumerAPI`，用加权随机负载均衡调用 `async_get_one_instance()` 和 `get_one_instance()`。日志级别设为 `warn`，连接超时设为 2 秒。

在仓库根目录执行：

```bash
export POLARIS_SERVER=127.0.0.1:8091
export POLARIS_TOKEN=
uv run --locked python examples/loadbalancer/wr/main.py \
  <namespace> <service> <times>
```

例如：

```bash
uv run --locked python examples/loadbalancer/wr/main.py \
  default demo 3
```

`<times>` 是每一轮的选择次数。示例先做 `<times>` 次异步选择：每次打印 `host` 和 `port`，上报一次成功调用结果，再等待 5 秒；`--interval` 可调整等待秒数。异步轮次结束后打印 `use sync method`，再做 `<times>` 次同步选择，并同样上报成功结果。没有可用实例时退出。结束时销毁这个 Consumer。

调用结果上报放在真实调用下游之后。本示例没有真实下游，固定上报成功、返回码 `0`、延迟 `1`。查看全部实例和 context 隔离时，参考 [多 context 示例](../../multicontext/README.md)。

## 验证、日志和清理

离线验证使用实际加权随机插件，替换注册中心 RPC；同步和异步各选择 40 次，检查每次
选择均上报一次调用结果，并确认退出时关闭 context、线程和日志句柄。

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only loadbalancer/wr
make -C examples/loadbalancer/wr run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
`run.sh` 转发 `main.py` 参数。默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../../README-zh.md)。
