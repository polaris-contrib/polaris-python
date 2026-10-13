# Circuit breaker example

启动两个相同服务的 provider，其中一个初始返回 500，另一个返回 200。先在
Polaris 控制台为 `CircuitBreakerCallee` 配置熔断规则，再启动 client；client
不会创建本地熔断规则，第一次 `get_one_instance` 会订阅服务端的
`CIRCUIT_BREAKER` 规则。

```bash
POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
python examples/circuitbreaker/provider.py --port 19101

POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
python examples/circuitbreaker/provider.py --port 19102 --initial-error

POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
python examples/circuitbreaker/client.py --service CircuitBreakerCallee
```

运行期间可以切换某个 provider 的错误状态：

```bash
curl 'http://127.0.0.1:19102/switch?openError=false'
curl 'http://127.0.0.1:19102/switch?openError=true'
```

client 只负责发现、请求和上报结果；熔断是否打开、恢复窗口和阈值均来自
Polaris 服务端规则。

自动验证会创建连续失败规则，并确认 client 先看到 500，随后报告熔断打开：

```bash
bash examples/circuitbreaker/verify_circuitbreaker.sh
```

用例和通过条件见 [test.md](test.md)。残留进程和 `.logs/`：

```bash
bash examples/circuitbreaker/cleanup.sh
bash examples/circuitbreaker/cleanup.sh -f
bash examples/circuitbreaker/cleanup.sh --dry-run
```

`cleanup.sh` 不删除脚本创建的熔断规则。
