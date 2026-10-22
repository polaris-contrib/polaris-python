# 本地实例熔断验证

[English](README.md)

参考 Go `oldInstanceCircuitBreakerCaller` 的「发现实例 → HTTP 调用 → 上报结果 → 观察熔断与恢复」链路。
这里只验证已有的本地默认实例规则，不增加远端规则、服务级或接口级熔断。主动探测当前不支持。
无需在控制台创建熔断规则。

## 离线验证

在仓库根目录执行：

```bash
uv sync --group dev --locked
uv run --locked python examples/circuitbreaker/verify.py
```

脚本只替换注册中心 RPC，在 `127.0.0.1` 临时端口启动两个 HTTP Provider 和一个 Caller，
使用实际 SDK 的发现缓存、路由、调用结果上报和定时器。即使设置了 `POLARIS_E2E`，
也不会连接外部注册中心；缓存和日志保存在本 demo 的 `.logs/` 下，供查看和清理。末尾 JSON 输出
`passed_scenarios: 10`，覆盖：

1. HTTP 200 / 404 不计失败，请求 ID 透传至 Provider。
2. 连续失败达到配置阈值后仅熔断故障实例，后续路由选择正常实例。
3. 半开配额跟随配置的成功数，一次恢复失败立即重新打开。
4. 真实等待定时器转为半开，累计指定次数成功后关闭。
5. 错误率阈值与最小请求数驱动滑动窗口的延迟检查。
6. 全死全活兜底仍可调用打开实例。
7. 禁用默认规则时，异步发现与上报正常，但实例保持关闭。
8. 启用规则的异步调用可触发打开并恢复。
9. 网络异常上报 `-1`，两个 Provider 均有自动心跳并在退出时反注册。
10. 所有 context、熔断任务、Discover 流、HTTP 监听和缓存写线程完成清理。

只有离线脚本通过公开代码字段缩短窗口和阈值。`consumer/polaris.yaml` 保留默认参数：
连续失败 10 次、错误率窗口 60 秒、打开等待 30 秒、半开成功 3 次。
HTTP 映射和示例辅助逻辑的单测：

```bash
uv run --locked pytest -q tests/test_circuitbreaker_examples.py -W error::RuntimeWarning
```

## 连接注册中心

两个 `main.py` 默认跳过，不创建 SDK；显式设置 `POLARIS_E2E=1` 才启动。
如服务端要求预先创建服务，请先准备 `default/CircuitBreakerCallee`。
在三个终端分别设置环境变量，再于仓库根目录执行各自命令：

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=
```

终端 A，正常实例：

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18081 --status 200
```

终端 B，故障实例：

```bash
uv run --locked python examples/circuitbreaker/provider/main.py --port 18082 --status 500
```

终端 C，调用方：

```bash
uv run --locked python examples/circuitbreaker/consumer/main.py --port 18080
```

`POLARIS_TOKEN` 是连接注册中心的访问令牌，`POLARIS_SERVICE_TOKEN` 用于注册请求的服务令牌。
使用 `--config /path/to/polaris.yaml` 指定其他 SDK 配置。
Provider 的 `--host` 显式指定业务注册地址，默认 `127.0.0.1`；跨机器调用时须改为可达地址，
它与 SDK `bindIP` 无关。Caller 不注册自身，因为本地实例规则无需主调资源。

## 故障与恢复

```bash
for i in $(seq 1 60); do curl -s http://127.0.0.1:18080/echo; printf '\n'; done
curl -s http://127.0.0.1:18080/instances
curl -s 'http://127.0.0.1:18082/switch?openError=false'
sleep 31
for i in $(seq 1 30); do curl -s http://127.0.0.1:18080/echo; printf '\n'; done
curl -s http://127.0.0.1:18080/instances
```

加权随机选择下，总调用次数不固定；以 `/instances` 中故障实例进入 `open` 为准。
修复后等待半开，并累计足够的选中成功调用，实例回到 `closed`。
`/instances` 查询未过滤的缓存，不消耗半开配额。
`/echo` 返回 `instance_id`、`ret_code`、`circuit_state`、`delay_ms` 和 Provider 响应体；
HTTP 状态沿用下游状态，网络失败返回 502。`X-Request-ID` 原样透传，未指定时生成新 ID。

`/switch?openError=true` 恢复 HTTP 500；`/switch?status=404` 可验证客户端错误不计实例故障。
这些无鉴权控制接口**仅用于测试**，不要将 Provider 暴露到不可信网络。

通过 Ctrl+C 或 SIGTERM 停止三个进程。Provider 显式反注册后销毁 context；
Caller 等待 HTTP 处理结束后销毁 context。SIGKILL 无法执行这条清理链，心跳 TTL 默认 5 秒。

每次业务调用只用所属 context 发现的实例对象上报一次，没有额外的远端熔断上报。
保留全死全活兜底，因此并非严格的调用拒绝 API。完整边界见 [本地实例熔断](../../docs/circuitbreaker.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only circuitbreaker
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 运行完整熔断场景，日志保存在本目录的 `.logs/` 下。
Provider / Consumer 子目录也可独立执行 `verify.sh`，同样验证完整场景并保留各自日志。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../README-zh.md)。
