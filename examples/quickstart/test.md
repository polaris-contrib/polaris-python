# quickstart 测试说明

本目录验证同步 Provider 注册、Consumer 服务发现、HTTP 调用、调用结果上报和退出清理。
验证使用真实 SDK、真实本机 HTTP 服务以及真实 gRPC 请求处理链，只替换注册中心的
gRPC stub 边界，因此不需要外部 Polaris 服务。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 运行完整的 quickstart Provider/Consumer 场景。 |
| `logs.sh` | 查看本次或历史验证的 console、SDK 分类日志和结果。 |
| `cleanup.sh` | 停止本目录及子 demo 的已记录进程，删除 `.logs/` 和 `.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

本目录没有 `main.py`，所以不提供 `run.sh`。需要直接运行示例时进入
`provider/` 或 `consumer/`。

## 验证如何执行

验证器在一个隔离目录中启动两个 Python 子进程：

1. Provider 以临时端口启动 HTTP 服务。
2. Consumer 以另一个临时端口启动 HTTP 代理服务。
3. Provider 通过 SDK 注册实例并启动心跳。
4. Consumer 通过 SDK 发现实例。
5. 验证器请求 Consumer 的真实 HTTP 接口，由 Consumer 再调用 Provider。
6. 停止两个子进程，检查反注册、调用结果上报和资源释放。

注册中心 RPC 使用 fake stub，但以下行为均走实际实现：

- 配置加载；
- SDK context 和插件生命周期；
- Provider 注册、心跳和反注册流程；
- Consumer 发现缓存和同步调用流程；
- 本机 HTTP Provider 与 Consumer；
- 调用结果构造和上报入口。

## 核心断言

验证器会检查：

- 注册请求包含测试服务名、服务令牌和 TTL；
- Provider 打印的临时端口与后续调用使用的端口一致；
- `GET /echo` 返回 HTTP 200，正文包含正确的服务名和 Provider 地址；
- `POST /echo-with-body` 也能发现并调用同一个 Provider；
- Provider 的 fake RPC 记录中出现 `register`、`heartbeat` 和 `deregister`；
- Consumer 的 fake RPC 记录中出现 `discover` 和 `report`；
- 停止进程时没有未结束的子进程或脏退出。

成功时输出：

```text
PASS synchronous quickstart registration, discovery, call, and cleanup
```

任一 HTTP 状态、正文、RPC 调用或退出状态不符合预期，验证器返回非零。

## 执行

```bash
./examples/verify.sh --only quickstart
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

每次运行都会新建 `.logs/verify-<时间>-<编号>/`。验证器在 `provider/` 和
`consumer/` 子目录保存各自的 `stdout.log`、`stderr.log` 和 SDK 日志；
SDK 日志位于运行目录的 `polaris/log/provider/`、`polaris/log/consumer/`，cache 位于同级的
`polaris/backup/provider/`、`polaris/backup/consumer/`；外层保存 `console.log`、
`verification.log` 和 `result.json`。

该验证不连接外部注册中心。设置 `POLARIS_SERVER_ADDRESS` 也不会改变 fake stub
覆盖的注册中心边界；真实服务端联调应使用 `provider/run.sh` 和
`consumer/run.sh`。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 管理程序捕获的合并 stdout/stderr，包含场景顺序、HTTP 结果、`PASS`/`FAIL` 和异常。 |
| `result.json` | 记录 `exit_code`、`timed_out`、`interrupted` 和 `action`；只有退出码 0 且未超时、未中断才是正常成功。 |
| `verification.log` | 保存 Provider/Consumer 断言、JSON 汇总和 traceback；`run.sh` 和直接运行通常不生成。 |

运行目录还包含 `polaris/log/provider/`、`polaris/log/consumer/`、对应的 `polaris/backup/` 以及嵌套进程
`stdout.log`/`stderr.log`。先看 `result.json`，再看 `verification.log`。完整规则见
[测试产物说明](../README-zh.md#测试产物)。

## 注册服务与实例

验证器向 fake registry 注册一个服务实例：

| 项目 | 值 |
| --- | --- |
| namespace | `ns` |
| service | `svc` |
| 实例数 | 1 |
| Provider host | `127.0.0.1` |
| Provider port | 参数为 `0`，自动分配；实际端口在 `console.log` 的 `registered.port` |
| fake instance ID | `quickstart-provider` |
| TTL | 1 秒 |
| Consumer | 不注册服务实例，只监听一个自动选择的 HTTP 端口 |

Provider 和 Consumer 的两个实际 HTTP 端口都可在 JSON 输出的 `port` 或 `listen`
字段找到。fake registry 地址配置为 `127.0.0.1:8091`，但 gRPC stub 被验证器替换，
因此不会连接该地址。

手动执行时，Provider 默认注册 `default/DiscoverEchoServer`，`--port` 默认 `0`；
Provider host 是到注册中心建连时使用的本机 IP。Consumer 默认监听 `18080`，它不注册
实例，只发现 Provider。

## 真实服务端验证

```bash
POLARIS_SERVER_ADDRESS=<host>:8091 \
POLARIS_SERVICE_TOKEN=<service-token> \
./examples/verify_e2e.sh --only quickstart
```

脚本自动创建唯一服务 `polaris-python-e2e-quickstart-<年月日时分秒毫秒>`，在
`python-integration` 注册 1 个 Provider。Provider 使用动态端口，host 为 SDK 探测到的
本机 IP；Consumer 使用动态本机 HTTP 端口且不注册实例。

验证效果：Provider 注册成功、Consumer 从真实注册中心发现实例、`GET /echo` 返回 200，
Provider 最后反注册并销毁 context。成功输出 JSON 含 service、provider instance ID、
host、port、consumer_port、`http_status: 200` 和 `effect`。详细说明见
[真实服务验证说明](../README-zh.md#真实服务验证)。
