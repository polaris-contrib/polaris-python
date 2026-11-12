# lossless 测试说明

本目录验证无损上线、健康探测、readiness、消费端发现与无损下线的完整链路。离线验证保留真实 SDKContext、ProviderAPI、ConsumerAPI、admin HTTP 服务、业务 HTTP 服务和本地缓存刷新，只替换注册中心 gRPC 边界。

## 测试拓扑

### 拉起进程

| 阶段 | 进程与生命周期 |
| --- | --- |
| 离线 | 1 个验证器进程；Provider 和 Consumer 是同一进程内的两个异步任务，各自启动真实业务/管理 HTTP listener。 |
| 远端 | 1 个验证器进程 + 1 个 Provider 子进程 + 1 个 Consumer 子进程；验证完成后 Consumer 退出，Provider 保持心跳直到 cleanup。 |

### 创建服务与实例

| 阶段 | 服务 | 实例 |
| --- | --- | --- |
| 离线 | `ns/svc` | Provider 1 个实例 `lossless-provider`，业务端口和 admin 端口均动态分配，TTL 1 秒；Consumer 不注册。 |
| 远端 | `polaris-python-integration/lossless-provider-<时间>` | Provider 1 个实例，host 为到 Polaris 的路由源 IP，业务端口动态；Consumer 不注册。 |

### 服务访问与验证

| 访问关系 | 验证内容 |
| --- | --- |
| 验证器 → Provider admin | 注册前 `/readiness` 为 `503 UNREGISTERED`，注册后为 `200 REGISTERED`。 |
| SDK health probe → Provider `/ready` | 按 lossless warmup 规则探测健康后再注册。 |
| Consumer → Provider | Consumer 通过 Discover 选择 Provider，并真实请求 `/echo`。 |
| registry → Consumer Discover | Provider 反注册后，发现流收到空实例并停止向已下线实例路由。 |
| 验证器 → registry stub | 断言注册/反注册各 1 次，并观察到 lossless 规则 Discover 与实例 Discover。 |

## 脚本作用

| 文件 | 作用 |
| --- | --- |
| `provider/main.py` | 启动 `/ready` 与 `/echo`，执行 `lossless_register()`，收到停止信号后执行 `lossless_deregister()`。 |
| `consumer/main.py` | 开启 warmup，持续调用 `async_get_one_instance()` 并请求 Provider 的 `/echo`。 |
| `verify.py` | 使用 integration Fixture 和 fake registry 流验证完整生命周期。 |
| `Makefile` | 汇总 provider 与 consumer 的构建、运行和验证入口。 |

公开示例始终执行注册或调用流程。离线验证使用 `integration/fixtures/`，测试开关由
验证器自动设置。

## 离线验证

验证器替换 `GrpcConnection._stub`，fake registry 会：

1. 对 `Discover` 保持长连接，每 10ms 推送当前实例快照；
2. 对 lossless 资源返回启用 warmup 的规则；
3. `RegisterInstance` 时把实例加入快照并写入创建时间；
4. `DeregisterInstance` 时把实例从快照移除。

验证顺序和断言如下：

1. 先启动 Consumer 和 Provider 的真实业务 HTTP 服务；
2. Provider 调用 `lossless_register()` 后，先请求 admin `/readiness`，要求返回 `503 UNREGISTERED`；
3. SDK 按 `DELAY_BY_HEALTH_CHECK` 策略探测 Provider 的 `/ready`，探测通过后执行注册；
4. 注册发生后再次请求 `/readiness`，要求返回 `200 REGISTERED`；
5. 等待 Consumer 通过真实服务发现选择 Provider，并成功请求 `/echo`；
6. 触发 Provider 停止事件，要求它调用 `lossless_deregister()`；
7. 等待 fake registry 快照为空，确认 Consumer 的发现流会收到删除后的实例列表；
8. 最后断言注册和反注册各发生一次，lossless 规则 Discover 和实例 Discover 都发生过。

warmup 的精确流量分布、过载保护和服务端规则覆盖本地配置由 `tests/test_lossless.py` 的集成测试覆盖。示例验证关注真实入口、真实 HTTP 和生命周期编排。
Provider 等待非空 instance id 时不再另设 30 秒内部截止时间；合法的延迟注册和
健康探测只受外层验证器进程超时约束。

## 执行产物与解读

统一脚本会创建 `integration/.logs/lossless/verify-<时间>-<编号>/`：

| 文件 | 内容 |
| --- | --- |
| `console.log` | 验证顺序、Provider 启动 JSON、最终 `lossless passed` JSON 和异常。 |
| `result.json` | 退出码、`timed_out`、`interrupted` 和 `action`。 |
| `verification.log` | 断言失败时的 traceback。 |

SDK 分类日志保存在同级 `polaris/log/`，实例备份在 `polaris/backup/`。`work/` 只用于验证脚手架。验证成功要求 `result.json.exit_code` 为 0，且 `timed_out` 和 `interrupted` 均为 false。

## 注册服务与实例

离线验证使用 `ns/svc`：

| 项目 | 值 |
| --- | --- |
| Provider host | `127.0.0.1` |
| Provider 业务端口 | 动态端口 |
| admin 端口 | 动态端口 |
| TTL | 1 秒 |
| instance id | `lossless-provider` |
| 注册中心 | fake gRPC stream |

Consumer 的 `consumer.weightAdjust.chain` 配置为 `[warmup]`。Provider 的本地策略为 `DELAY_BY_HEALTH_CHECK`，探测路径 `/ready`，探测间隔 1 秒；如果服务端下发规则，服务端规则优先。

## 远端验证

执行：

```bash
./integration/verify.sh --only lossless
```

仓库根目录也可以执行 `./integration/verify_e2e.sh --only lossless`，两者都会进入同一套远端验证。

需要设置：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091
POLARIS_SERVICE_TOKEN=<token>
```

远端验证使用 `integration/_real_verify.py --demo lossless`。它会启动本目录 Provider，
检查 host 为本机到 Polaris 的路由源 IP，等待 `/readiness` 返回 `REGISTERED`，
再等待实例在注册中心可见；随后启动 Consumer 并产生真实 HTTP 调用。Consumer
汇总调用后停止，Provider 保持运行并继续心跳，供控制台核查，直到显式 cleanup。
命名空间默认 `polaris-python-integration`，Provider 服务名为
`lossless-provider-<年月日时分秒毫秒>`，Provider 和 Consumer 使用动态端口。
Provider 启动等待使用 `verify_e2e.sh --timeout` 传入的场景预算，因此健康探测或
延迟注册超过 60 秒时仍可在默认 600 秒场景预算内完成。
离线验证仍覆盖 provider 停止时的 `lossless_deregister()` 和 readiness 状态切换。

真实服务端需要在控制台为 `ns/svc` 配置 lossless 规则；未配置时 SDK 会回退到示例本地配置。远端场景不自动创建 lossless 规则。
