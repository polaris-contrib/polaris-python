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

## 离线验证

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
注册到 `default/CircuitBreakerCallee`，host 使用到 Polaris 建连时的
`get_local_host` 源 IP、port `18081`、TTL 5 秒；传入 `--port 0` 可改为动态端口，
显式传入 `--host` 时以应用提供的可达地址为准。

## 远端验证

`--only circuitbreaker/provider` 不只启动本目录 Provider。它和父目录跑同一套场景，日志写在本目录 `.logs/verify-e2e-<时间>-<编号>/`。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only circuitbreaker/provider
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-circuitbreaker-<年月日时分秒毫秒>`。

步骤：

1. 本目录 `main.py` 使用 `--port 0 --status 200 --ttl 3`。注册 host 默认通过
   `get_local_host(POLARIS_SERVER_ADDRESS)` 取本机到 Polaris 的 TCP 源 IP。
   监听动态端口，然后把该 IP 和实际端口注册并持续心跳。
2. 验证器最多等 20 秒，确认发现结果含这次的 instance id。
3. Consumer 调用 `/echo`。因为 Provider 固定返回 200，熔断状态应保持 `closed`，`ret_code` 为 200。
4. `/instances` 只有这一个实例。两个进程都保持运行，验证器不反注册，也不把状态切到 500。

通过条件是 `circuit_state` 为 `closed`。离线里切换 HTTP 状态、半开和全死全活不在这一路。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
