# 缓存闲置淘汰

[English](README.md)

实例资源空闲超过 `consumer.localCache.serviceExpireTime` 后，SDK 会释放它们。业务读取会重新计算空闲时间，后台刷新不会。每个 context 按空闲阈值的一半扫描一次，扫描间隔最长不超过一小时，并排除配置中的系统服务。

闲置淘汰会停止该资源的刷新任务和 Discover 流。连接通道仍可供其他资源使用。对应的磁盘备份会在更早入队的写任务完成之后删除；之后再次发现会重新建立内存和磁盘缓存。共用同一目录的 context 也会共用这些删除结果。需要独立备份生命周期时，为每个 context 设置不同的 `persistDir`。

## 运行

在仓库根目录执行，查询真实注册中心里已有的服务：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/expiry ARGS='default demo'
```

`--config path/to/polaris.yaml` 选择文件配置。`--expire-ms` 设置本示例的空闲阈值，最小值和默认值都是 5000 毫秒。示例不注册或反注册业务实例。

英文说明见 [README.md](README.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only cache/expiry --latest --tail 30'
make -C examples logs ARGS='--only cache/expiry --latest --category cache --follow'
make -C examples cleanup ARGS='--only cache/expiry --dry-run'
make -C examples cleanup ARGS='--only cache/expiry'
```

示例输出、备份和 SDK 日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行
`python main.py` 时使用 `.logs/manual/`。
`make -C examples/cache/expiry run ARGS='default demo'` 使用同一运行脚本。
默认清理先展示并确认，`--force` 跳过确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。
完整运行和目录规则见 [示例总览](../../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only cache/expiry`；真实验证使用
`./integration/verify_e2e.sh --only cache/expiry`。测试步骤和集成测试产物见
[integration/scenarios/cache/expiry/test.md](../../../integration/scenarios/cache/expiry/test.md)。
