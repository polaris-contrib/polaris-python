# 调用监控

示例启动本地 HTTP echo 服务，通过 Polaris 注册和发现，实际调用三次
（200、503、200），并上报调用结果。支持 Prometheus 拉取和 Pushgateway 推送。

```bash
./examples/verify.sh --only monitoring
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/monitoring run ARGS="--mode pull"
```

拉取模式打印本机 `/metric` 地址，默认运行 31 秒，等待第一个 30 秒聚合周期后
打印指标；退出时显式反注册并销毁 context。

```bash
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/monitoring run ARGS="--mode push --push-address 127.0.0.1:9091"
```

不指定推送地址时发现 `Polaris/polaris.pushgateway`。离线验证启动真实本地 HTTP
接收器，不连接外部注册中心；仅缩短聚合等待时间，指标和调用走完整 SDK 流程。
推送模式在配置的间隔后输出成功上报次数 `pushes`，真实验证要求至少成功一次。
同步上报使用 `update_service_call_result`，异步使用 `async_update_service_call_result`。
SDK 不自动拦截业务调用。参数和产物见 [test.md](test.md)，指标说明见
[可观测性](../../docs/observability.md)。
