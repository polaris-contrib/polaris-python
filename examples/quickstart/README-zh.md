# 快速开始

[English](README.md)

同步 Provider / Consumer 示例：

1. Provider 提供 `/echo` 并自动心跳注册。
2. Consumer 发现一个实例，调用服务并上报调用结果。
3. Provider 在 Ctrl-C 或 SIGTERM 时反注册。

两个进程都读取各自目录中的 `polaris.yaml`。

## 运行

从仓库根目录执行；在两个终端中设置环境变量：

```bash
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=

# 终端 1
make -C examples run DEMO=quickstart/provider ARGS='--service-token "" --port 0'
# 终端 2
make -C examples run DEMO=quickstart/consumer ARGS='--port 18080'
```

进程以前台方式运行；使用不同终端或 `&`。`--service-token` 用于注册、心跳和反注册，
未开启服务鉴权时传空字符串。`POLARIS_TOKEN` 用于认证 SDK 连接。Provider 会打印动态
分配的监听端口。

分组 Makefile 可以选择子示例：

```bash
make -C examples/quickstart run DEMO=provider ARGS='--service-token "" --port 0'
```

调用服务：

```bash
curl http://127.0.0.1:18080/echo
```

## 验证

从仓库根目录执行：

```bash
./integration/verify.sh --only quickstart
./integration/verify_e2e.sh --only quickstart
```

测试步骤和集成测试产物见
[integration/scenarios/quickstart/test.md](../../integration/scenarios/quickstart/test.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only quickstart --latest --tail 30'
make -C examples cleanup ARGS='--only quickstart --dry-run'
make -C examples cleanup ARGS='--only quickstart'
```

示例日志保存在各子示例的 `.logs/run-<时间>-<id>/`；直接执行 `python main.py` 时使用
`.logs/manual/`。清理默认需要确认，只停止记录的示例 PID 并删除本地产物，不删除远端
服务。完整规则见[示例总览](../README-zh.md)。
