# quickstart Provider 测试说明

本目录的验证入口执行完整的 quickstart 场景，验证 Provider 注册、Consumer 发现和
本机 HTTP 往返。虽然脚本位于 Provider 目录，`verify.py` 属于父目录
`examples/quickstart`，因此结果会同时覆盖 Provider 和 Consumer。

## 脚本作用

下列入口都在仓库的 `examples/` 目录，命令从仓库根目录执行。

| 脚本 | 作用 |
| --- | --- |
| `verify.sh` | 调用父级 quickstart 完整验证，并把结果保存在本目录。 |
| `run.sh` | 在当前目录启动 `main.py`，原样转发 Provider 参数。 |
| `logs.sh` | 查看本目录下保留的 console、验证和 SDK 分类日志。 |
| `cleanup.sh` | 只清理本目录下的进程记录、`.logs/` 和 `.runtime/`；支持 `--keep-logs` 和 `--delete-services`。 |

## run.sh 的作用

`main.py` 会启动 HTTP Provider、注册实例、自动心跳，并在收到 SIGTERM 或 SIGINT
时反注册和销毁 context。常用参数包括：

```bash
make -C examples/quickstart/provider run ARGS="--namespace default --service DiscoverEchoServer"\
  --service-token <service-token> --port 0 --ttl 1
```

- `--port 0` 让操作系统选择临时端口；
- `--service-token` 是 Provider 注册服务所需的令牌；
- `--config` 选择 Provider 的 YAML 配置；
- `run.sh` 会记录 PID、创建时间和命令，便于安全清理。

真实远端联调需要设置：

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_TOKEN=<access-token>
```

quickstart 入口不检查 `POLARIS_E2E`；设置它不会改变该 demo 的行为。

## 离线验证

`verify.sh` 通过共享管理程序定位父级 `quickstart/verify.py`。验证器：

1. 配置 fake gRPC stub，替代注册中心 RPC。
2. 以 `--port 0 --ttl 1` 启动真实 Provider HTTP 服务。
3. 以另一个临时端口启动真实 Consumer HTTP 服务。
4. 通过 `/echo` 和 `/echo-with-body` 完成两次 HTTP 往返。
5. 检查 Provider 地址、响应正文、HTTP 200 和请求路径。
6. 发送终止信号，检查 Provider 反注册。
7. 检查 Consumer 已执行发现和调用结果上报。

验证覆盖的是完整 Provider/Consumer 生命周期，不是只导入 `main.py`。失败时
`verify.sh` 返回非零，日志仍保留。

## 查看结果

```bash
./examples/verify.sh --only quickstart/provider
./examples/logs.sh --latest --tail 50
./examples/logs.sh --latest --category network --tail 50
./examples/cleanup.sh --dry-run
```

每次验证的 `result.json` 记录退出码；`console.log` 保存管理程序输出；
验证目录下的 `provider/`、`consumer/` 子目录保存两边进程输出和 SDK 日志。

## 执行产物与解读

| 产物 | 内容 |
| --- | --- |
| `console.log` | 管理程序捕获的 Provider/Consumer 启动、HTTP 调用、反注册和异常输出。 |
| `result.json` | 记录动作、退出码、超时和中断状态。手动 Ctrl+C 停止常驻 Provider 时 `interrupted` 非空，顶层会显示 `FAIL`，但不代表注册或 HTTP 断言失败。 |
| `verification.log` | 父级验证器的断言和 traceback；该文件只在 `verify.sh` 或直接执行验证器时生成。 |

`run.sh` 通常只有 `console.log` 和管理器生成的 `result.json`，没有
`verification.log`。完整字段说明见
[测试产物说明](../../README-zh.md#测试产物)。

## 注册服务与实例

父级离线验证会注册一个 Provider：

- namespace/service：`ns/svc`；
- 实例数：1；
- host：`127.0.0.1`；
- 配置端口：`0`，由操作系统分配；
- 实际端口：查看 `console.log` 的 `registered.port`；
- fake instance ID：`quickstart-provider`；
- TTL：1 秒；
- registry 地址：配置为 `127.0.0.1:8091`，实际使用 fake stub。

`run.sh` 默认注册 `default/DiscoverEchoServer`，`--port 0` 同样会选择动态端口。
Provider host 是连接到 Polaris gRPC 地址时取得的本机 IP。Consumer 在本验证中不注册
业务实例。

## 远端验证

`--only quickstart/provider` 不只跑 Provider。它和父目录跑同一套场景：本目录注册，父目录 Consumer 调用。日志写在本目录的 `.logs/verify-e2e-<时间>-<编号>/`。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_TOKEN=<sdk-token>   # 注册中心要求接入鉴权时才需要
./examples/verify_e2e.sh --only quickstart/provider
```

命名空间默认 `python-integration`。服务名是 `polaris-python-e2e-quickstart-<年月日时分秒毫秒>`。

步骤：

1. 本目录 `main.py` 读旁边的 `polaris.yaml`，`${POLARIS_SERVER_ADDRESS}` 换成上面的地址。监听 `0.0.0.0` 的动态端口，注册 host 取建连时的本机 IP，TTL 1 秒，协议 http，版本 `1.0.0`。
2. 打印 `instance_id` 后进程继续心跳。验证器每 0.5 秒发现一次，最多 20 秒，直到列表里有这个 id。
3. 启动 Consumer，验证器请求它的 `/echo`。Consumer 必须从注册中心发现到这个 host 和 port，并拿到 HTTP 200，正文含服务名。
4. 两个进程保持运行。验证器不反注册。

通过条件是 `http_status` 为 200。JSON 含 service、instance id、host、Provider 端口和 Consumer 端口。离线验证使用的 fake id `quickstart-provider` 和退出反注册不在这一路。`./examples/cleanup.sh --force` 停进程，`--delete-services` 删服务。
