# 示例

[English](README.md)

示例均使用公开 `polaris` API。

| Demo | 内容 |
| --- | --- |
| [quickstart](quickstart/README.md) | 同步注册、发现、HTTP 调用和结果上报 |
| [circuitbreaker](circuitbreaker/README-zh.md) | 本地实例熔断、路由和半开恢复 |
| [sdkconfig/file](sdkconfig/file/README.md) | YAML 启动 |
| [sdkconfig/code](sdkconfig/code/README.md) | 纯代码启动 |
| [cache/expiry](cache/expiry/README-zh.md) | 闲置淘汰和重新加载 |
| [cache/restart](cache/restart/README-zh.md) | 进程中断和离线恢复 |
| [loadbalancer/random](loadbalancer/random/README.md) | 均匀随机选择 |
| [loadbalancer/wr](loadbalancer/wr/README.md) | 加权随机选择 |
| [multicontext](multicontext/README.md) | 独立 context 和生命周期 |
| [mcp](mcp/README-zh.md) | MCP 注册和发现 |
| [a2a](a2a/README-zh.md) | A2A metadata |
| [skill](skill/README-zh.md) | Skill 查询和下载 |
| [monitoring](monitoring/README-zh.md) | Prometheus pull / push |
| [events](events/README-zh.md) | 实例缓存与本地熔断事件 |

## 运行与验证

首次在仓库根目录安装：

```bash
uv sync --group dev --locked
```

验证全部离线示例：

```bash
./examples/verify_all.sh
```

验证指定示例：

```bash
cd examples
./verify.sh --only quickstart,loadbalancer
```

每个 demo 提供：

```text
run.sh       启动 main.py
verify.sh    离线验证
logs.sh      查看保留日志
cleanup.sh   停止已记录进程并清理本地产物
```

脚本可从任意工作目录执行。

## 输出目录

每次运行创建独立目录：

```text
.logs/verify-<时间>-<编号>/
.logs/run-<时间>-<编号>/
```

保留内容包括：

- `console.log`
- `verification.log`
- `result.json`
- `sdk/` 下的分类日志
- `work/` 或 `.runtime/` 下的运行数据

查看和清理：

```bash
./logs.sh --latest --tail 30
./logs.sh --latest --category circuitbreaker --follow
./cleanup.sh --dry-run
./cleanup.sh --force
```

清理只作用于 demo 记录过的进程和 demo 本地目录。

## 真实注册中心

真实入口通常要求：

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
```

`POLARIS_TOKEN` 用于连接鉴权；注册 Provider 时另有服务令牌。
