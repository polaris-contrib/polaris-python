# 多 Context 隔离示例

`main.py` 使用代码配置创建两个 `SDKContext`，分别设置接入地址、Token、`persistDir`、
日志根目录与级别。两个客户端注册并自动心跳；第一个反注册并销毁后，第二个继续心跳和发现，
最后也反注册并销毁。每个客户端的 Provider 和 Consumer 共用该客户端的 context。

## 离线验证

在仓库根目录执行，无需注册中心，也不会连接外部地址：

```bash
uv run --locked python examples/multicontext/verify.py
```

验证在本 demo 的 `.logs/` 工作目录、独立进程运行真实示例，只替换 gRPC channel / stub 边界。
检查不同 clientId、owner loop、连接、请求 Token、实例 ID、自动心跳、反注册、
销毁后的 API 拒绝，以及另一个 context 持续可用；退出时检查日志句柄、文件缓存写线程、
文件锁、插件和心跳任务均已释放。

## 真实注册中心

`main.py` 默认跳过网络验证。仅在设置 `POLARIS_E2E=1` 后连接显式指定的注册中心：

```bash
export POLARIS_E2E=1
export POLARIS_FIRST_SERVER=127.0.0.1:8091
export POLARIS_SECOND_SERVER=127.0.0.1:8091
export POLARIS_FIRST_TOKEN=
export POLARIS_SECOND_TOKEN=
export POLARIS_FIRST_SERVICE_TOKEN=service-token
export POLARIS_SECOND_SERVICE_TOKEN=service-token
uv run --locked python examples/multicontext/main.py \
  --namespace default --service multicontext-example
```

先在两个注册中心准备对应服务和服务令牌；地址相同时会注册不同端口的两个实例。
`--ttl` 单位为秒，默认 5；`--seconds` 是销毁第一个客户端之前和之后的各段等待时间，
默认 6，必须大于 TTL。`--backup-dir`（兼容旧参数名 `--work-dir`）默认本 demo 的
`.logs/manual/polaris/backup/`，下面的 `first/`、`second/` 分别保存各自的缓存。
日志位于同级 `polaris/log/first/`、`polaris/log/second/`，再按 `base`、`network`、`cache` 等类别划分，
每类文件独立滚动。JSON 输出包含发现结果、独立 clientId 和销毁标记，
不会输出令牌。

配置在启动时复制为私有快照，不保证初始化后修改配置会热更新连接。
SDK 直接沿用 `consumer.localCache.persistDir`，不会自动追加随机目录；
连接不同注册中心时，应用应显式选择不同目录。每个活动 context 的显式日志路径必须不同。
SDK 销毁只停止自己的资源，不隐式反注册；示例在销毁之前显式反注册。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only multicontext
make -C examples/multicontext run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
`run.sh` 转发 `main.py` 参数。默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../README-zh.md)。
