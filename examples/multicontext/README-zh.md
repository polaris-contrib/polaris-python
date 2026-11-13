# 多 Context 示例

[English](README.md)

创建两个相互独立的 SDK context，分别拥有：

- 地址和 Token
- client ID 和事件循环
- 注册与心跳任务
- 缓存和日志目录

示例反注册并销毁第一个 context，第二个 context 继续心跳和发现；最后再清理第二个 context。

## 真实注册中心

从仓库根目录执行：

```bash
export POLARIS_FIRST_SERVER=127.0.0.1:8091
export POLARIS_SECOND_SERVER=127.0.0.1:8091
export POLARIS_FIRST_SERVICE_TOKEN=service-token
export POLARIS_SECOND_SERVICE_TOKEN=service-token

make -C examples run DEMO=multicontext ARGS='--namespace default --service multicontext-example'
```

同一进程中的两个 context 使用各自的 `consumer.localCache.persistDir` 和日志目录。
销毁一个 context 不会关闭另一个。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only multicontext --latest --tail 30'
make -C examples cleanup ARGS='--only multicontext --dry-run'
make -C examples cleanup ARGS='--only multicontext'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`；直接执行 `python main.py` 时使用
`.logs/manual/`。清理默认需要确认，只停止记录的示例 PID 并删除本地产物，不删除远端
服务。

## 验证

从仓库根目录执行 `./integration/verify.sh --only multicontext`；连接真实注册中心时执行
`./integration/verify_e2e.sh --only multicontext`。测试覆盖和集成测试产物见
[integration/scenarios/multicontext/test.md](../../integration/scenarios/multicontext/test.md)。
