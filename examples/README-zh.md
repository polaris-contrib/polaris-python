# 示例

[English](README.md)

示例目录放公开 `polaris` API 的可运行代码、配置、预期效果，以及手动运行和清理脚本。
验证逻辑和测试资源管理统一放在 [`../integration/`](../integration/README-zh.md)。

每个程序只演示一项公开能力。Stub、故障注入、复杂步骤断言和测试专用 Fixture 应用都
放在 `integration/`；示例不导入集成测试代码，也不依赖测试专用环境开关。

| Demo | 内容 |
| --- | --- |
| [quickstart](quickstart/README.md) | 同步注册、发现、HTTP 调用和结果上报 |
| [lossless](lossless/README-zh.md) | 无损注册、预热与反注册 |
| [circuitbreaker](circuitbreaker/README-zh.md) | 本地实例熔断、路由和半开恢复 |
| [sdkconfig/file](sdkconfig/file/README.md) | YAML 启动 |
| [sdkconfig/code](sdkconfig/code/README.md) | 纯代码启动 |
| [cache/expiry](cache/expiry/README-zh.md) | 闲置淘汰和重新加载 |
| [cache/restart](cache/restart/README-zh.md) | 进程中断和离线恢复 |
| [loadbalancer/random](loadbalancer/random/README.md) | 均匀随机选择 |
| [loadbalancer/wr](loadbalancer/wr/README.md) | 加权随机选择 |
| [servicerouter](servicerouter/README.md) | 路由链 |
| [multicontext](multicontext/README.md) | 独立 Context 和生命周期 |
| [mcp](mcp/README-zh.md) | MCP 注册和发现 |
| [a2a](a2a/README-zh.md) | A2A Provider，提供 JSON-RPC 1.0/0.3 和 HTTP+JSON |
| [skill](skill/README-zh.md) | Skill 查询和下载 |
| [monitoring](monitoring/README-zh.md) | Prometheus pull / push |
| [events](events/README-zh.md) | 缓存与本地熔断事件 |

## 安装

在仓库根目录执行：

```bash
uv sync --group dev --locked
```

## 运行

从仓库根目录运行单个示例；Provider 和 Consumer 分别在不同终端启动：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=quickstart/provider ARGS='--service-token "" --port 18081'
```

每个 demo 的 Makefile 支持：

```text
build       生成本地启动脚本
run         运行 main.py
package     打包示例目录
clean       清理本地构建产物
logs        查看当前示例日志
cleanup     停止已记录的示例进程并清理本地产物
```

在示例根目录可用 `make -C examples run DEMO=quickstart/provider ARGS='...'` 选择应用；
在分组目录可用 `make -C examples/quickstart run DEMO=provider ARGS='...'` 选择子示例。

## 日志与清理

```bash
make -C examples logs ARGS='--only quickstart/provider --latest --tail 30'
make -C examples cleanup ARGS='--only quickstart/provider --dry-run'
make -C examples cleanup ARGS='--only quickstart/provider --force --keep-logs'
```

每次运行的控制台输出、退出结果、SDK 日志和缓存保存在
`examples/<demo>/.logs/run-<时间>-<编号>/`。清理时校验进程身份并等待优雅退出，
只处理所选示例的本地产物；默认确认，`--force` 跳过确认，`--keep-logs` 仅停止进程和
清理运行记录，保留日志及构建产物。不会删除远端服务或集成测试资源。
直接通过 `python main.py` 启动的进程不在脚本管理范围内，需要自行停止。

## 集成测试

```bash
./integration/verify.sh --only quickstart
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 ./integration/verify_e2e.sh --only quickstart
```

测试断言、测试进程保留和测试资源清理均由 `integration/` 负责。
