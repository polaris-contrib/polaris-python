# 规则路由

Provider 注册带 `env` 标签的实例。Polaris 上的规则把查询参数 `env` 映到同名实例标签。示例只消费服务端下发的 `RuleRoutingConfig`，不在客户端写规则。

## 目录

```text
examples/route/rule/
├── provider.py
├── consumer.py
├── verify_rule_route.sh
├── cleanup.sh
├── test.md
└── README.md
```

## 手动运行

先启动 provider，再在控制台为 `RouteEchoServer` 配置规则，然后启动 consumer：

```bash
python examples/route/rule/provider.py --port 19011 --metadata env=dev
python examples/route/rule/provider.py --port 19012 --metadata env=pre
python examples/route/rule/consumer.py
curl -H 'env: pre' 'http://127.0.0.1:18080/echo?env=pre'
```

SDK 会把 `headers`、`query`、`method` 和 `caller_ip` 交给规则匹配。自动验证只构造 query `env` 这一维。

## 自动验证

```bash
bash examples/route/rule/verify_rule_route.sh
```

用例见 [test.md](test.md)。脚本会调用 `/naming/v2/routings` 创建规则。

## 清理

```bash
bash examples/route/rule/cleanup.sh -f
```

`cleanup.sh` 不删除已经创建的路由规则。规则名默认是 `RouteEchoServer-auto-rule`。
