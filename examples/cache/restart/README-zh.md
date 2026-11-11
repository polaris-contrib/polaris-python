# 异常重启恢复示例

[English](README.md)

演示进程在缓存写入期间被终止后，如何从最后一次完整备份恢复。

只加载完整备份，中断写入留下的临时文件不会参与加载。

备份名称与 Go 一致：

```text
svc#<namespace>#<service>#instance.json
```

## 真实注册中心

从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=cache/restart ARGS='default demo --persist-dir $PWD/examples/cache/restart/.logs/manual/polaris/backup/restart'
```

示例只发现已有服务。跨次运行复用这个 `--persist-dir` 可观察重启恢复；
不指定时，每次统一脚本运行使用独立备份目录。不同注册中心或独立缓存生命周期应使用不同目录。

`global.api.timeout` 限制首次远端等待。网络失败或超时后可返回完整备份，
后台发现继续运行，服务恢复后更新缓存。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only cache/restart --latest --category cache --tail 30'
make -C examples cleanup ARGS='--only cache/restart --dry-run'
make -C examples cleanup ARGS='--only cache/restart'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only cache/restart`；真实验证使用
`./integration/verify_e2e.sh --only cache/restart`。测试步骤和集成测试产物见
[integration/scenarios/cache/restart/test.md](../../../integration/scenarios/cache/restart/test.md)。
