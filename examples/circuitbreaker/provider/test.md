# circuitbreaker Provider 测试说明

本目录的 `verify.sh` 执行父级 `examples/circuitbreaker` 的完整熔断验证。它会同时启动
两个真实本机 HTTP Provider 和多个 Consumer，因此覆盖的不只是 Provider 启动。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 调用父级完整熔断验证，结果保存在本目录。 |
| `run.sh` | 启动一个可切换 HTTP 状态的 Provider。 |
| `logs.sh` | 查看本目录下保留的控制台和 SDK 分类日志。 |
| `cleanup.sh` | 停止本目录记录的进程并删除本目录 `.logs/`、`.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh

```bash
make -C examples/circuitbreaker/provider run ARGS="--namespace default --service CircuitBreakerCallee"\
  --service-token <service-token> --port 0 --status 200 --ttl 1
```

Provider 提供：

- `GET /echo`：返回配置的 HTTP 状态；
- `GET /switch?status=<code>`：在 200 到 599 中切换状态；
- `GET /switch?openError=true|false`：切换 500/200；
- 注册时自动心跳；
- SIGTERM/SIGINT 时反注册并销毁 context。

`--host` 是注册到 Polaris 的业务地址；SDK 的 `bindIP` 是另一个配置项。
真实远端运行需要 `POLARIS_E2E=1`、
`POLARIS_SERVER_ADDRESS=<host>:8091` 和注册服务令牌。

## 父级验证如何覆盖 Provider

验证器创建 `provider-a` 和 `provider-b`：

1. Provider 请求使用 fake `RegisterInstance` 注册；
2. fake registry 检查 host、service token、TTL 和实例端口；
3. Provider 的真实 HTTP 状态可在验证过程中动态切换；
4. Consumer 根据状态变化触发熔断；
5. 验证结束时关闭 Provider，检查心跳和反注册；
6. 关闭后再次调用返回传输失败 `-1`。

因此本目录验证覆盖 Provider 的注册、HTTP、状态切换、心跳、反注册和日志清理。

## 查看结果

```bash
./examples/verify.sh --only circuitbreaker/provider
./examples/logs.sh --latest --category circuitbreaker --tail 80
./examples/cleanup.sh --dry-run
```

父级验证的详细 10 个场景见[父目录测试说明](../test.md)。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | Provider 注册、HTTP 请求、状态切换、反注册、父级断言和管理器输出。 |
| `result.json` | 记录退出码、超时和中断状态。手动 Ctrl+C 使 `interrupted` 非空时，顶层会有 `FAIL`，但业务断言可能已经通过。 |
| `verification.log` | 父级熔断验证的 `PASS`/`FAIL` 和 traceback；只在验证模式下生成。 |

缓存和锁文件在 `polaris/backup/provider/`，SDK 日志在 `polaris/log/provider/`。
详细字段和退出码见[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

父级离线验证注册两个 Provider：

- namespace/service：`default/CircuitBreakerCallee`；
- 实例数：2；
- host：均为 `127.0.0.1`；
- port：均传 `0`，实际值动态分配；
- instance ID：`instance-<实际端口>`；
- TTL：1 秒；
- service token：`example-token`。

实际端口可在 `console.log` 的注册和调用 JSON 中查看。`run.sh` 默认启动一个实例并
注册到 `default/CircuitBreakerCallee`，host `127.0.0.1`、port `18081`、TTL 5 秒；
传入 `--port 0` 可改为动态端口。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only circuitbreaker/provider
```

该入口运行完整熔断真实场景：注册一个 `polaris-python-e2e-circuitbreaker-<年月日时分秒毫秒>`
Provider，host `127.0.0.1`、动态端口、TTL 3 秒，再由动态端口的 Consumer 发现和调用。

效果为注册、发现、HTTP 200、状态 `closed`、反注册和 context 清理。输出 JSON
提供实际服务名、instance ID、端口和 `effect`。完整说明见
[真实服务验证说明](../../README-zh.md#真实服务验证)。
