# 纯代码启动示例

`main.py` 直接构造 `Configuration`，不读取 YAML，也不自动应用 SDK 环境变量；
示例显式读取 `POLARIS_SERVER_ADDRESS` 作为 `--server` 的默认值。

## 运行

从仓库根目录执行：

```bash
make -C examples run DEMO=sdkconfig/code
```

示例演示：

- 服务端地址和 Token
- 连接、API 和消息超时
- 重试与缓存刷新
- 本地实例熔断参数
- 系统集群配置
- 独立 `LogOptions`

代码中的时长单位为整数毫秒，字段使用 snake_case：

```python
config = Configuration()
config.set_default()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]
config.get_global().get_api().timeout = 5000
config.get_consumer().get_circuit_breaker().sleep_window = 15000
```

`init_context_by_config()` 会复制配置并校验。初始化后的修改不会热更新已有 context。

完整字段见 [配置参数说明](../../../docs/config/configuration-reference.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only sdkconfig/code --latest --tail 30'
make -C examples cleanup ARGS='--only sdkconfig/code --dry-run'
make -C examples cleanup ARGS='--only sdkconfig/code'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。本目录 `make run ARGS='...'` 使用同一运行脚本。
默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only sdkconfig/code`；真实验证使用
`./integration/verify_e2e.sh --only sdkconfig/code`。测试步骤和集成测试产物见
[integration/scenarios/sdkconfig/code/test.md](../../../integration/scenarios/sdkconfig/code/test.md)。
