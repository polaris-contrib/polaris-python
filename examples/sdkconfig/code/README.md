# 纯代码启动示例

`main.py` 直接构造 `Configuration`，不读取 YAML，也不自动应用 SDK 环境变量。

## 运行

```bash
./run.sh
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

## 验证与清理

```bash
./verify.sh
./logs.sh --latest --tail 30
./cleanup.sh --force
```
