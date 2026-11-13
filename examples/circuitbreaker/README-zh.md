# 本地实例熔断示例

[English](README.md)

演示 Python SDK 的本地 `composite` 实例规则：连续失败、错误率、半开配额、
路由及全死全活兜底。

## 真实注册中心

从仓库根目录执行，在每个终端设置以下环境，使用多个终端或 `&` 启动两个 Provider
和一个 Caller：

```bash
export export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=

# 终端 1
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18081 --status 200'
# 终端 2
make -C examples run DEMO=circuitbreaker/provider ARGS='--port 18082 --status 500'
# 终端 3
make -C examples run DEMO=circuitbreaker/consumer ARGS='--port 18080'
```

脚本以前台运行。Caller 不注册。Provider 默认用 `get_local_host(POLARIS_SERVER_ADDRESS)` 作为业务注册
地址；显式 `--host` 可覆盖，SDK `bindIP` 与注册 IP 独立。

观察实例状态和恢复：

```bash
curl http://127.0.0.1:18080/instances
curl 'http://127.0.0.1:18082/switch?openError=false'
```

故障切换接口仅用于本地演示，不要暴露到不可信网络。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only circuitbreaker --latest --tail 30'
make -C examples logs ARGS='--only circuitbreaker --latest --category circuitbreaker --follow'
make -C examples cleanup ARGS='--only circuitbreaker --dry-run'
make -C examples cleanup ARGS='--only circuitbreaker'
```

示例日志保存在各子 demo 的 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时
使用 `.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only circuitbreaker`；真实验证使用
`./integration/verify_e2e.sh --only circuitbreaker`。测试覆盖和集成测试产物见
[integration/scenarios/circuitbreaker/test.md](../../integration/scenarios/circuitbreaker/test.md)。

规则说明见 [本地实例熔断](../../docs/guides/circuitbreaker.md)。
