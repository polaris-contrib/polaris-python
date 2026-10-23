# examples 测试说明

## 脚本作用

从仓库根目录或任意目录执行：

```bash
./examples/verify_all.sh
./examples/verify.sh --only quickstart,cache
```

- `verify.sh`：运行全部或指定 demo，每个场景启动独立子进程。
- `logs.sh`：查看最近或指定分类日志。
- `cleanup.sh`：停止已记录进程并清理 demo 本地产物。
- `verify_e2e.sh`：连接真实 Polaris，需显式环境变量。

## 离线验证

默认验证覆盖：

| 场景 | 验证内容 |
| --- | --- |
| quickstart | 同步注册、心跳、发现、HTTP 调用、上报、反注册 |
| circuitbreaker | 连续失败、错误率、半开、路由、全死全活 |
| sdkconfig/code | 纯代码配置、生效值和 context 销毁 |
| sdkconfig/file | YAML、环境覆盖、占位符、默认查找和错误配置 |
| cache/expiry | 闲置淘汰、Discover 关闭、备份删除和重载 |
| cache/restart | SIGKILL、完整备份恢复和远端 revision 更新 |
| loadbalancer/random | 同步 / 异步均匀随机选择 |
| loadbalancer/wr | 同步 / 异步加权随机选择 |
| multicontext | 独立 clientId、连接、心跳、缓存、日志和销毁 |
| mcp/a2a/skill/monitoring | AI Registry 和指标导出链路 |
| events | 实例缓存事件和本地实例熔断事件 |

离线验证只替换必要的 gRPC 边界；配置、Context、缓存、路由、负载均衡、
熔断、日志和本机 HTTP 交互使用真实实现。

## 判定

一次场景通过必须同时满足：

- 子进程退出码为 `0`
- 未超时
- 未收到中断信号
- 验证器没有断言异常

失败场景不会阻止后续场景执行，最终整体返回非零退出码。

## 运行目录

## 执行产物与解读

每次执行创建：

```text
.logs/verify-<时间>-<编号>/
.logs/run-<时间>-<编号>/
```

主要文件：

| 文件 | 内容 |
| --- | --- |
| `console.log` | 合并 stdout / stderr |
| `verification.log` | 断言输出和 traceback |
| `result.json` | 退出码、超时和中断状态 |
| `sdk/` | SDK 分类日志 |
| `work/` | 配置和测试脚手架 |
| `backup/` | 缓存快照和锁文件 |

排查顺序：`result.json` → `verification.log` → `console.log` → `sdk/`。

## 注册服务与实例

离线示例的服务和实例均由本地 fake RPC 或本机 HTTP 服务提供，不访问外部注册中心。
真实示例默认使用 python-integration 命名空间和 `polaris-python-e2e-<场景>-<时间>` 服务名；
需要固定服务名的示例会在各自 test.md 中说明。所有本机 HTTP 和监控端口均使用动态端口，
避免并行验证冲突。

## 清理

```bash
./examples/logs.sh --latest --tail 50
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

默认只清理 `examples/` 下有进程身份记录的进程、`.logs/` 和 `.runtime/`。
不会删除源码、YAML 或外部自定义缓存目录。

## 真实服务端验证

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
./examples/verify_e2e.sh
```

`POLARIS_TOKEN` 用于 SDK 接入鉴权；`POLARIS_SERVICE_TOKEN` 用于注册实例。
真实场景使用唯一服务名，默认保留日志和测试服务，需手动清理。
