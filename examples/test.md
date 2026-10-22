# examples 测试说明

本目录是所有示例验证入口的汇总目录。这里的 `verify.sh` 不需要外部 Polaris
注册中心，默认会依次运行 9 个可执行验证场景：

1. `quickstart`
2. `circuitbreaker`
3. `sdkconfig/code`
4. `sdkconfig/file`
5. `cache/expiry`
6. `cache/restart`
7. `loadbalancer/random`
8. `loadbalancer/wr`
9. `multicontext`

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 按顺序运行全部或通过 `--only` 选择的场景。 |
| `logs.sh` | 汇总显示本目录树中各个 demo 的保留日志。 |
| `cleanup.sh` | 停止本目录树下已记录的 demo 进程；默认删除验证产物，`--keep-logs` 只停进程并保留日志，`--delete-services` 额外删除测试服务。 |

这些脚本可以在仓库根目录、本目录或任意工作目录执行。脚本根据自身位置定位
仓库、Python 解释器和共享管理程序，因此不依赖调用者的当前目录。

## 执行方式

从仓库根目录运行全部场景：

```bash
./examples/verify.sh
```

只选择部分分组：

```bash
./examples/verify.sh
./examples/verify.sh --only circuitbreaker,cache
./examples/verify.sh --only loadbalancer
./examples/verify.sh --timeout 240
```

`--timeout` 是每个场景的超时时间，默认 180 秒。查看当前参数：

```bash
./examples/verify.sh --help
```

## 验证如何执行

`verify.sh` 最终调用 `_manage.py`。管理程序会为每个场景创建独立的
`.logs/verify-<时间>-<编号>/` 目录，然后启动新的 Python 子进程。每个运行目录使用：

```text
<run>/
├── polaris/log/       # 分类日志
├── polaris/backup/    # cache、锁文件和持久化快照
└── work/      # 配置和测试脚手架
```

`polaris/log/` 与 `polaris/backup/` 始终同级。每个子进程使用独立的进程组，并继承调用环境中的
`POLARIS_TOKEN` 等变量。

运行期间会产生三类结果：

- `console.log`：场景的标准输出和错误输出。
- `verification.log`：验证器直接执行时保存的断言输出。
- `result.json`：子进程退出码、是否超时、是否被中断。

管理程序还会把 `src/` 和仓库根目录加入 `PYTHONPATH`，因此验证使用当前工作区的
SDK 源码，而不是旧的安装副本。cache 与日志都留在本次运行目录中，运行结束后可直接
查看；只有显式传入自定义 cache 路径时才会写到别处。

## 各场景的验证边界

| 场景 | 验证内容 | 外部服务 |
| --- | --- | --- |
| `quickstart` | 同步注册、发现、HTTP 调用、调用结果上报、反注册和资源释放 | 不需要；替换 gRPC 注册中心边界，HTTP 使用本机真实端口 |
| `circuitbreaker` | 10 个熔断、恢复、路由、HTTP 分类和清理场景 | 不需要；替换注册中心，使用本机真实 HTTP |
| `sdkconfig/code` | 纯代码启动、配置生效和 context 销毁 | 不需要 |
| `sdkconfig/file` | YAML、环境变量、默认查找、错误配置和代码启动 | 不需要 |
| `cache/expiry` | 闲置淘汰、流关闭、备份删除和重新加载 | 不需要；替换服务端流 |
| `cache/restart` | 强制中断写入、临时文件忽略和进程重启恢复 | 不需要外部注册中心；本地 gRPC 服务由验证器启动 |
| `loadbalancer/random` | 异步、同步均匀随机选择和调用结果上报 | 不需要；替换注册中心 |
| `loadbalancer/wr` | 异步、同步加权随机选择和调用结果上报 | 不需要；替换注册中心 |
| `multicontext` | 两个 context 的注册、心跳、发现、隔离和独立销毁 | 不需要；替换 gRPC channel/stub |

## 判定标准

只有子进程在超时前以退出码 `0` 结束，管理程序才输出 `PASS`。断言失败、未捕获异常、
超时或被信号中断都会产生非零退出码。运行结束会打印汇总，例如：

```text
Verification: 9 passed, 0 failed.
```

任何场景失败都会继续执行其他场景，最后返回非零状态，方便定位全部失败项。

## 日志和清理

查看最近的日志：

```bash
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
```

清理前预览：

```bash
./examples/cleanup.sh --dry-run
```

确认不再需要日志和进程后执行：

```bash
./examples/cleanup.sh --force
```

只想停止进程并保留日志时执行：

```bash
./examples/cleanup.sh --keep-logs --force
```

同时删除远端测试服务时执行：

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/cleanup.sh --keep-logs --delete-services --force
```

清理只处理 `examples` 下有记录进程身份的 PID、`.logs/` 和 `.runtime/`；
`--keep-logs` 保留 `.logs/`，进程记录会随正常退出移除。默认清理也不会递归删除
源码、YAML 或用户指定的外部 cache 目录。`--delete-services` 只删除
`polaris-python-e2e-*` 服务。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 管理程序捕获的合并 stdout/stderr，包含运行顺序、启动 JSON、`PASS`/`FAIL`、嵌套进程输出和异常。它不是完整 SDK 日志。 |
| `result.json` | 每个场景的 `entry`、`action`、`exit_code`、`timed_out`、`interrupted`。正常成功要求退出码 0、未超时、未中断。 |
| `verification.log` | 验证器的断言输出、JSON 汇总和 traceback，是定位测试失败的首选文件。`run.sh` 和直接运行通常没有该文件。 |

建议先看 `result.json`，再看 `verification.log`，最后结合 `console.log`、`polaris/log/`
和 `polaris/backup/` 排查。各字段、退出码和人工 Ctrl+C 的含义见
[测试产物说明](README-zh.md#测试产物)。

## 注册服务与实例

默认全量验证涉及的服务和实例如下。`动态` 表示验证器传入端口 `0`，由操作系统选择
临时端口，实际值记录在该场景的 `console.log` JSON 中。

| 子场景 | namespace/service | 注册实例 | 业务端口 |
| --- | --- | --- | --- |
| quickstart | `ns/svc` | 1 个 Provider：host `127.0.0.1`，fake ID `quickstart-provider` | Provider 和 Consumer 都是动态端口 |
| circuitbreaker | `default/CircuitBreakerCallee` | 2 个 Provider，host `127.0.0.1`，ID 为 `instance-<实际端口>` | 两个 Provider 和 Consumer 前端均为动态端口 |
| sdkconfig/code | 无 | 不注册业务实例 | 不监听业务端口 |
| sdkconfig/file | 无 | 不注册业务实例 | 不监听业务端口 |
| cache/expiry | `ns/svc` | 不注册；fake registry 提供 `instance-1` | 提供实例为 `127.0.0.1:8080` |
| cache/restart | `ns/svc` | 不注册；临时服务提供 `instance-1` | 实例为 `192.0.2.1:8080`；gRPC 服务使用动态端口 |
| loadbalancer/random | `ns/svc` | 不注册；fake registry 提供 2 个实例 | `127.0.0.1:8081`、`127.0.0.1:8082` |
| loadbalancer/wr | `ns/svc` | 不注册；fake registry 提供 2 个实例 | `127.0.0.1:8081`、`127.0.0.1:8082` |
| multicontext | `default/multicontext-example` | 2 个实例，host `127.0.0.1` | `8081`、`8082`；fake registry 地址为 `first:8091`、`second:8091` |

fake registry 只模拟注册中心 RPC，不会在真实 Polaris 平台创建服务或实例。Consumer、
发现类验证和 cache 验证通常只读取实例，不注册业务实例；SDK context 自己的
`ReportClient` 不等于业务服务实例注册。

## 真实服务端验证

设置真实服务和注册令牌后执行：

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
./examples/verify_e2e.sh
```

该脚本连接真实 Polaris，依次运行 12 个真实场景。每个场景使用唯一的
`polaris-python-e2e-<demo 目录>-<年月日时分秒毫秒>` 服务名，目录中的 `/` 写成 `-`，后缀是本地时间并精确到毫秒，自动创建 Provider 实例，执行发现或
HTTP 调用，并默认保留运行进程与注册实例。

效果包括：quickstart/circuitbreaker 返回 HTTP 200 并保持进程运行；code/file 从真实注册中心
发现临时实例；cache/expiry 完成淘汰和重载；cache/restart 在 `polaris/backup/restart/` 写入
真实快照；random/wr/servicerouter 各完成 4 次选择；multicontext 注册 `8081`、`8082`
两个实例并保持运行；mcp 验证标准注册、发现、契约上报/读取并保持运行；skill 查询并
下载已发布 Skill。成功结果为 `12 passed`，失败时 `result.json` 非零，日志和 backup
仍保留。手动只停进程、保留日志时执行 `./examples/cleanup.sh --keep-logs --force`。
完整环境变量和执行规则见[真实服务验证说明](README-zh.md#真实服务验证)。
