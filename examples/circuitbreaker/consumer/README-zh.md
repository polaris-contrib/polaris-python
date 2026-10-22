# 熔断调用方

[English](README.md)

仓库根目录设置 `POLARIS_E2E=1` 后执行：

```bash
uv run --locked python examples/circuitbreaker/consumer/main.py --port 18080
```

`/echo` 发现实例、执行 HTTP，并上报一次结果；`/instances` 返回全部缓存实例的状态，
不扣减半开配额。相邻 `polaris.yaml` 展示本地默认规则的 7 个参数。
可通过 `--config`、`--namespace`、`--service` 和 `--call-timeout` 修改示例设置。
Ctrl+C / SIGTERM 等待 HTTP 处理结束后销毁自己创建的 SDK context。

完整步骤与离线验证见 [场景说明](../../README-zh.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only circuitbreaker/consumer
make -C examples/circuitbreaker/consumer run ARGS="--help"
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
