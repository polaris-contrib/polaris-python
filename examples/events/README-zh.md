# SDK 事件

[English](README.md)

订阅当前 SDK 已实现能力发出的事件：实例缓存新增 / 更新 / 删除，以及本地实例熔断状态转换。
同时验证可选 Pushgateway 事件上报。不提供限流、无损上下线、配置中心或 watch 事件。

```bash
./examples/verify.sh --only events
```

连接真实注册中心：

```bash
POLARIS_E2E=1 make -C examples/events run \
  ARGS="--server 127.0.0.1:8091 --namespace default --service DiscoverEchoServer"
```

离线验证与事件序列见 [test.md](test.md)，监听接口和字段见
[事件中心](../../docs/events.md)。
