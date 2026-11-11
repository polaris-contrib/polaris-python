# Integration E2E 测试说明

## 脚本作用

从仓库根目录执行：

```bash
./integration/verify.sh
./integration/verify.sh --only quickstart,cache
```

- `verify.sh`：运行全部或指定 demo，每个场景启动独立子进程。
- `logs.sh`：查看最近或指定分类日志。
- `cleanup.sh`：停止已记录进程并清理 integration 运行产物。
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

## 执行产物与解读

每次执行创建：

```text
integration/.logs/<场景>/verify-<时间>-<编号>/
integration/.logs/<场景>/verify-e2e-<时间>-<编号>/
integration/.logs/verify-summary-<时间>-<编号>/summary.json
```

主要文件：

| 文件 | 内容 |
| --- | --- |
| `console.log` | 合并 stdout / stderr |
| `verification.log` | 断言输出和 traceback |
| `result.json` | 退出码、超时和中断状态 |
| `polaris/log/` | SDK 分类日志，例如 `base/`、`network/`；AI 链路另有 `ai/` |
| `polaris/backup/` | 缓存快照、持久化资源和锁文件 |
| `work/` | 本次场景的配置副本、逐 case 目录和测试脚手架 |

`work/` 只承接测试运行需要的工作文件，不是示例源码。它和本次日志一起保留，便于
复现失败；对应场景执行 cleanup 时会与运行目录一并清理。

排查顺序：`result.json` → `verification.log` → `console.log` →
`polaris/log/` → `polaris/backup/`。

## 注册服务与实例

离线 Fixture 的服务和实例均由本地 fake RPC 或本机 HTTP 服务提供，不访问外部注册中心。
真实场景默认使用 python-integration 命名空间和 `polaris-python-e2e-<场景>-<时间>` 服务名；
需要固定服务名的示例会在各自 test.md 中说明。所有本机 HTTP 和监控端口均使用动态端口，
避免并行验证冲突。

## 清理

```bash
./integration/logs.sh --latest --tail 50
./integration/cleanup.sh --dry-run
./integration/cleanup.sh --force
```

默认清理 `integration/.runtime/` 中记录的进程，以及 `integration/.logs/` 和
`integration/.runtime/` 下的对应场景产物。不会读取或删除
`examples/**/.logs/`、`examples/**/.runtime/` 中的手动运行产物，也不会删除示例源码或 YAML。

## 远端验证

这一路不替换 gRPC，每个场景连接 `POLARIS_SERVER_ADDRESS`。入口是
`./integration/verify_e2e.sh`，单个场景默认 600 秒超时，可用 `--timeout` 覆盖；
失败不拦住后面的场景，最后汇总非零退出。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>   # 服务级鉴权时才需要
export POLARIS_E2E_SERVICE_TOKEN=<e2e-token>   # 可选，优先于上一行
export POLARIS_TOKEN=<sdk-token>               # 连接层鉴权时才需要
./integration/verify_e2e.sh
./integration/verify_e2e.sh --only quickstart,monitoring
```

`POLARIS_SERVICE_TOKEN` 是注册、心跳和反注册请求携带的服务级令牌；服务未开启
服务级鉴权时不需要设置，默认空字符串。`POLARIS_E2E_SERVICE_TOKEN` 是 E2E 脚手架
使用的可选覆盖值，存在时优先于 `POLARIS_SERVICE_TOKEN`，便于测试凭据与实际服务
凭据隔离。`POLARIS_TOKEN` 是连接注册中心的接入令牌，属于连接层鉴权，与前两者独立。
三个令牌都未设置时分别使用空字符串。

真实 E2E 默认使用更宽松的网络超时，避免远端服务偶发抖动造成假失败：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `POLARIS_E2E_CONNECT_TIMEOUT_MS` | `5000` | TCP/连接建立超时 |
| `POLARIS_E2E_MESSAGE_TIMEOUT_MS` | `15000` | 注册、心跳、ReportClient 等单次 RPC 超时 |
| `POLARIS_E2E_API_TIMEOUT_MS` | `15000` | 首次发现和 API 总超时 |
| `POLARIS_E2E_SKILL_TIMEOUT_MS` | `30000` | Skill 查询和列表 RPC 超时 |
| `POLARIS_E2E_SKILL_DOWNLOAD_TIMEOUT_MS` | `60000` | Skill ZIP 下载超时 |

这些变量只由 `integration/` 的 Fixture 运行时读取；公开示例不使用测试专用开关。
也可以通过进程级 `--timeout` 调整整个场景的最长运行时间。该预算也会作为场景
启动阶段的等待上限，例如无损 Provider 的延迟注册，不会在场景内部再被固定秒数
提前截断。

脚本自己设置内部标记 `POLARIS_E2E=1`，并把 `POLARIS_SERVER`、
`POLARIS_SERVER_ADDRESSES` 写成同一个地址。用户只需要提供真实注册中心地址和
可选凭据。
测试实例和测试服务固定进入 `python-integration`；`POLARIS_E2E_NAMESPACE` 只能覆盖为
其他隔离命名空间，不能设为共享的 `default`。监控推送把该主机端口改成 `9091`。
Skill 资源命名空间与实例命名空间相互独立。Skill 地址默认取注册中心主机与 `8094`
端口，可用 `POLARIS_SKILL_SERVER_ADDRESS` 覆盖。未配置
`POLARIS_SKILL_NAMESPACE` 时：指定了 `POLARIS_SKILL_NAME` 则默认 `default`；
未指定名称则自动发现和 fixture 使用隔离的实例 E2E 命名空间。`POLARIS_SKILL_NAME`
可省略，此时验证器通过只读 `GetSkillList` 自动选择该命名空间内按名称排序的第一个
已发布 Skill。若没有，则通过商业版
Polaris 控制面的 `POST /skill/v1/skills` 创建并立即发布固定名称的
`polaris-python-e2e-skill-fixture`。该资源会保留，后续 E2E 优先检查并复用。
SDK 本身仍保持只读。
控制面地址默认取同一主机的 `8090` 端口，可用 `POLARIS_CONSOLE_ADDRESS` 覆盖；
管理请求令牌优先使用 `POLARIS_CONSOLE_TOKEN`，未设置时依次回退到
`POLARIS_TOKEN` 和 service token。Skill fixture 不使用
`cleanup.sh --delete-services` 清理。

所有真实 E2E 场景创建的 Context 都会启用事件 Pushgateway，地址由
`POLARIS_SERVER_ADDRESS` 的 host 加端口 `9091` 得到，上报路径为
`/polaris/client/events`。各 demo 通过：

- `POLARIS_EVENT_REPORTER_ENABLE=1`
- `POLARIS_EVENT_REPORTER_ADDRESS=<host>:9091`
- `POLARIS_EVENT_REPORTER_PUSH_INTERVAL=250`
- `POLARIS_EVENT_REPORTER_MAX_RETRIES=3`
- `POLARIS_EVENT_REPORTER_RETRY_INTERVAL=100`

统一应用配置。`POLARIS_EVENT_REPORTER_*` 是示例 E2E 辅助变量，不是 SDK 自动配置变量。

每个场景的运行目录是
`integration/.logs/<scenario>/verify-e2e-<时间>-<编号>/`。`console.log` 含验证器
JSON，`result.json` 的 `exit_code` 为 0 才通过，`verification.log` 保存失败断言，
`polaris/log/` 是探测 context 的 SDK 日志，demo 标准输出在
`<子目录名>.stdout.log`。每次 suite 运行还会写一份 `integration/.logs/` 下的
`summary.json`。

| 场景 | 远端实际检查 |
| --- | --- |
| quickstart | 注册 TTL 1 秒的 HTTP Provider，Consumer `GET /echo` 返回 200 且正文含服务名。两个进程保持运行，不在验证器里反注册 |
| circuitbreaker | 注册 Provider 后真实触发失败、恢复：验证 `closed → open → half_open → closed`，并要求 Open、HalfOpen、Close 三个事件均成功上报到 `<host>:9091/polaris/client/events` |
| sdkconfig/code、file | 各注册一个 Provider，再用对应配置发现它，断言第一个实例 ID 相同。不重跑离线的 YAML 矩阵 |
| cache/expiry | 发现后按 5 秒闲置阈值等待并再次发现，前后实例 ID 相同。不关 Discover 流，不删磁盘备份 |
| cache/restart | 发现一次并确认 `svc#命名空间#服务#*.json` 已写入。不模拟进程被杀或注册中心中断 |
| loadbalancer/random、wr | 异步 2 次、同步 2 次，输出含 Provider 的 host 和 port。不检查 40 次分布 |
| servicerouter | 同样 4 次选择，输出含 Provider 的 host 和 port。不检查 metadata 路由矩阵 |
| multicontext | 两个 context 注册两个实例，clientId 不同，销毁第一个后第二个仍可见。进程保持运行 |
| mcp | 注册普通 Instance，契约含 lookup、document、summarize，进程保持运行 |
| skill | 查询并下载已发布 Skill；名称未提供时发现或创建并保留固定 fixture，后续运行优先复用，输出含 `zip_size` |
| a2a | 注册 card metadata，发现结果 `transport` 为 `JSONRPC`，进程退出前反注册 |
| monitoring | 本机 echo 三次调用 200、503、200，指标推到 `<host>:9091`，`calls=3` 且 `pushes>=1`，然后反注册 |
| events | 注册唯一 Provider，再使用真实注册中心发现并断言 `OnServiceAdded`；Provider 保持运行 |

需要先注册再发现的场景，用 quickstart Provider 注册，然后每 0.5 秒用不带缓存的发现探测，最多 20 秒。服务对象留在 Polaris 上。`./integration/cleanup.sh --force` 停止仍在运行的 demo 进程；`--delete-services` 只删除当前命名空间里 `polaris-python-e2e-` 前缀的服务。各场景的逐步说明在 `integration/scenarios/<scenario>/test.md`。

真实实例的注册 IP 统一通过 `get_local_host(POLARIS_SERVER_ADDRESS)` 获取，即本机
连接到 Polaris 时 TCP socket 的源地址。验证器会把这个结果与 demo JSON、Provider
输出和 multicontext 发现结果中的 `host` 逐一比较；离线 loopback stub 仍可使用
`127.0.0.1`，因为它们不向真实注册中心发布实例。
