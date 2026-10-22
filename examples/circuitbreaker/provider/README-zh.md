# 可切换故障的 Provider

[English](README.md)

仓库根目录设置 `POLARIS_E2E=1` 后，在两个终端分别执行：

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18081 --status 200
uv run --locked python examples/circuitbreaker/provider/main.py --port 18082 --status 500
```

`/echo` 返回指定状态；`/switch?openError=true/false` 切换到 500/200，
`/switch?status=404` 可指定 200..599 范围内的其他状态码。非法参数返回 400，原状态不变。
控制接口没有鉴权，仅用于测试。

`--host` 是显式指定的业务注册地址，不是 SDK `bindIP`。
`--service-token` 默认读取 `POLARIS_SERVICE_TOKEN`。使用 `register_instance()` 注册并自动心跳，
`--ttl` 默认 5 秒。Ctrl+C / SIGTERM 停止 HTTP、反注册并销毁 context。
`--port 0` 选择临时端口，启动时打印端口和实例 ID。

完整步骤与离线验证见 [场景说明](../../README-zh.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only circuitbreaker/provider
make -C examples/circuitbreaker/provider run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证所属完整场景，并将日志保存在本目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
`run.sh` 转发 `main.py` 参数。默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../../README-zh.md)。
