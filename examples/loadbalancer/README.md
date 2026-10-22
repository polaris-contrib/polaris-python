# 单实例发现示例

这些示例从服务里选出一个实例：

- [`random`](random/README.md)：按实例数量均匀随机选择，实例权重不参与选择。
- [`wr`](wr/README.md)：先异步选择并上报调用结果，再做同样次数的同步选择。

可以在仓库根目录或 demo 目录运行，并先设置 `POLARIS_SERVER` 和可选的 `POLARIS_TOKEN`。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only loadbalancer
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

汇总验证依次运行子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志。
默认清理先展示并确认，`--force` 跳过确认，只停止本目录及子 demo 的已记录进程，
并删除 `.logs/`、`.runtime/`。完整运行和目录规则见 [示例总览](../README-zh.md)。
