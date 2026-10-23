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

## 远端验证

这一路不替换 gRPC，每个场景连接 `POLARIS_SERVER_ADDRESS`。入口是 `./examples/verify_e2e.sh`，单个场景默认 300 秒超时，失败不拦住后面的场景，最后汇总非零退出。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh
./examples/verify_e2e.sh --only quickstart,monitoring
```

`POLARIS_E2E_SERVICE_TOKEN` 与 `POLARIS_SERVICE_TOKEN` 等价。脚本自己设置 `POLARIS_E2E=1`，并把 `POLARIS_SERVER`、`POLARIS_SERVER_ADDRESSES` 写成同一个地址。命名空间默认 `python-integration`，用 `POLARIS_E2E_NAMESPACE` 修改。监控推送把该主机端口改成 `9091`。Skill 另需 `POLARIS_SKILL_SERVER_ADDRESS`（通常是同一主机的 `8094`）和 `POLARIS_SKILL_NAME`。

每个场景的运行目录是对应 demo 下的 `.logs/verify-e2e-<时间>-<编号>/`。`console.log` 含验证器 JSON，`result.json` 的 `exit_code` 为 0 才通过，`verification.log` 保存失败断言，`polaris/log/` 是探测 context 的 SDK 日志，demo 标准输出在 `<子目录名>.stdout.log`。

| 场景 | 远端实际检查 |
| --- | --- |
| quickstart | 注册 TTL 1 秒的 HTTP Provider，Consumer `GET /echo` 返回 200 且正文含服务名。两个进程保持运行，不在验证器里反注册 |
| circuitbreaker | 注册固定返回 200 的 Provider，Consumer `/echo` 为 200 且 `circuit_state=closed`，`/instances` 只有这一个实例。不制造失败，不检查半开 |
| sdkconfig/code、file | 各注册一个 Provider，再用对应配置发现它，断言第一个实例 ID 相同。不重跑离线的 YAML 矩阵 |
| cache/expiry | 发现后按 5 秒闲置阈值等待并再次发现，前后实例 ID 相同。不关 Discover 流，不删磁盘备份 |
| cache/restart | 发现一次并确认 `svc#命名空间#服务#*.json` 已写入。不模拟进程被杀或注册中心中断 |
| loadbalancer/random、wr | 异步 2 次、同步 2 次，输出含 Provider 的 host 和 port。不检查 40 次分布 |
| servicerouter | 同样 4 次选择，输出含 Provider 的 host 和 port。不检查 metadata 路由矩阵 |
| multicontext | 两个 context 注册两个实例，clientId 不同，销毁第一个后第二个仍可见。进程保持运行 |
| mcp | 注册普通 Instance，契约含 lookup、document、summarize，进程保持运行 |
| skill | 只查询并下载已发布 Skill，输出含 `zip_size`。不上传、不发布 |
| a2a | 注册 card metadata，发现结果 `transport` 为 `JSONRPC`，进程退出前反注册 |
| monitoring | 本机 echo 三次调用 200、503、200，指标推到 `<host>:9091`，`calls=3` 且 `pushes>=1`，然后反注册 |
| events | 注册唯一 Provider，再使用真实注册中心发现并断言 `OnServiceAdded`；Provider 保持运行 |

需要先注册再发现的场景，用 quickstart Provider 注册，然后每 0.5 秒用不带缓存的发现探测，最多 20 秒。服务对象留在 Polaris 上。`./examples/cleanup.sh --force` 停止仍在运行的 demo 进程；`--delete-services` 只删除当前命名空间里 `polaris-python-e2e-` 前缀的服务。各场景的逐步说明在对应目录的 `test.md`。
