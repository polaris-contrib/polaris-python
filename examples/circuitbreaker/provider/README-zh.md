# 可切换故障的 Provider

[English](README.md)

从仓库根目录执行，在两个终端分别设置以下环境并启动：

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18081 --status 200'
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18082 --status 500'
```

脚本以前台运行，使用多个终端或 `&`。

`/echo` 返回指定状态；`/switch?openError=true/false` 切换到 500/200，
`/switch?status=404` 可指定 200..599 范围内的其他状态码。非法参数返回 400，原状态不变。
控制接口没有鉴权，仅用于本地演示。

注册 IP 默认通过 `get_local_host(POLARIS_SERVER_ADDRESS)` 获取；`--host` 可显式覆盖，
它不是 SDK `bindIP`。
`--service-token` 默认读取 `POLARIS_SERVICE_TOKEN`。使用 `register_instance()` 注册并自动心跳，
`--ttl` 默认 5 秒。Ctrl+C / SIGTERM 停止 HTTP、反注册并销毁 context。
`--port 0` 选择临时端口，启动时打印端口和实例 ID。

完整运行步骤见 [场景说明](../README-zh.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only circuitbreaker/provider --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker/provider --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker/provider --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker/provider'
```

示例输出和 SDK 日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py`
时使用 `.logs/manual/`。本目录 `make run ARGS='...'` 使用同一运行脚本。
默认清理先展示并确认，`--force` 跳过确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。
完整运行和目录规则见 [示例总览](../../README-zh.md)。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only circuitbreaker/provider`；真实验证使用
`./integration/verify_e2e.sh --only circuitbreaker/provider`，两者验证所属完整场景。
测试步骤和集成测试产物见
[integration/scenarios/circuitbreaker/provider/test.md](../../../integration/scenarios/circuitbreaker/provider/test.md)。
