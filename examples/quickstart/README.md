# Quickstart

这是对应 Polaris Go `examples/quickstart` 的 Python 版本，包含异步和同步
Consumer 调用方式。

```bash
python examples/quickstart/provider.py --service polaris-python-demo
python examples/quickstart/consumer.py --service polaris-python-demo
curl http://127.0.0.1:18080/echo
```

如果只需要一次同步发现和调用：

```bash
python examples/quickstart/consumer_sync.py --service polaris-python-demo
```

自动验证（需要本地 Polaris）：

```bash
bash examples/quickstart/verify_quickstart.sh
```

Provider 启动时注册 HTTP 端口，退出时反注册；Consumer 通过 Polaris 发现实例，
调用方只需要调用 `async_get_one_instance` 或同步的 `get_one_instance`。
实例选择内部会执行健康过滤、路由和负载均衡。
