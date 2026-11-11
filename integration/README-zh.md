# 集成测试

[English](README.md)

`integration/` 负责离线验证、真实 Polaris E2E、测试 Fixture、故障注入、进程保留、
运行产物和清理。公开示例只保留单一能力的最小演示；复杂测试应用和配置放在
`fixtures/`，不会回流到 `examples/`。

## 命令

```bash
# 离线验证
./integration/verify.sh
./integration/verify.sh --only quickstart,loadbalancer

# 真实注册中心验证
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 ./integration/verify_e2e.sh --only lossless

# 查看与清理
./integration/logs.sh --latest --tail 50
./integration/cleanup.sh --dry-run
./integration/cleanup.sh --force --delete-services
```

手动运行示例统一使用 `examples/Makefile` 的
`make -C examples run|logs|cleanup` 目标。
集成测试命令只管理 `integration/` 下记录的测试资源，不清理手动运行的示例。

## 目录

```text
integration/
├── scenarios/        离线验证器和场景文档
├── fixtures/         复杂测试专用应用和配置
├── _support.py       测试传输与运行时配置
├── _real_verify.py   真实服务断言
├── _manage.py        场景选择与进程托管
├── _runtime.py       运行产物和进程身份
├── verify.sh         离线验证
├── verify_e2e.sh     真实服务验证
├── logs.sh           日志查看
├── cleanup.sh        进程、服务和产物清理
├── .logs/            生成的运行产物
└── .runtime/         生成的进程身份记录
```

场景覆盖、环境变量、产物结构和清理范围见 [test.md](test.md)。
