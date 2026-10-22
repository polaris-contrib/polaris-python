# 缓存闲置淘汰

实例资源空闲超过 `consumer.localCache.serviceExpireTime` 后，SDK 会释放它们。业务读取会重新计算空闲时间，后台刷新不会。每个 context 按空闲阈值的一半扫描一次，扫描间隔最长不超过一小时，并排除配置中的系统服务。

闲置淘汰会停止该资源的刷新任务和 Discover 流。连接通道仍可供其他资源使用。对应的磁盘备份会在更早入队的写任务完成之后删除；之后再次发现会重新建立内存和磁盘缓存。共用同一目录的 context 也会共用这些删除结果。需要独立备份生命周期时，为每个 context 设置不同的 `persistDir`。

在仓库根目录执行，不需要 Polaris 服务端：

```bash
uv run --locked python examples/cache/expiry/verify.py
```

验证大约需要 8 秒。它检查实际的周期淘汰、流关闭、备份删除、重新加载和 context 清理，只替换服务端边界。

查询真实注册中心里已有的服务：

```bash
POLARIS_E2E=1 POLARIS_SERVER=127.0.0.1:8091 \
  uv run --locked python examples/cache/expiry/main.py default demo
```

`--config path/to/polaris.yaml` 选择文件配置。`--expire-ms` 设置本示例的空闲阈值，最小值和默认值都是 5000 毫秒。示例不注册或反注册业务实例。

英文说明见 [README.md](README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only cache/expiry
make -C examples/cache/expiry run ARGS="--help"
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
