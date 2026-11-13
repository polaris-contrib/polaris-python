# 熔断调用方

[English](README.md)

先启动 [Provider](../provider/README-zh.md)，再从仓库根目录执行：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=circuitbreaker/consumer ARGS='--port 18080'
```

脚本以前台运行，Provider 使用其他终端。

`/echo` 发现实例、执行 HTTP，并上报一次结果；`/instances` 返回全部缓存实例的状态，
不扣减半开配额。相邻 `polaris.yaml` 展示本地默认规则的 7 个参数。
可通过 `--config`、`--namespace`、`--service` 和 `--call-timeout` 修改示例设置。
Ctrl+C / SIGTERM 等待 HTTP 处理结束后销毁自己创建的 SDK context。

完整运行步骤见 [场景说明](../README-zh.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only circuitbreaker/consumer --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker/consumer --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker/consumer --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker/consumer'
```

示例输出和 SDK 日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py`
时使用 `.logs/manual/`。本目录 `make run ARGS='...'` 使用同一运行脚本。
默认清理先展示并确认，`--force` 跳过确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。
完整运行和目录规则见 [示例总览](../../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only circuitbreaker/consumer`；真实验证使用
`./integration/verify_e2e.sh --only circuitbreaker/consumer`，两者验证所属完整场景。
测试步骤和集成测试产物见
[integration/scenarios/circuitbreaker/consumer/test.md](../../../integration/scenarios/circuitbreaker/consumer/test.md)。
