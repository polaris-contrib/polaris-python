# Route examples

这组示例参考 Polaris Go SDK，所有 provider 都向 Polaris 注册实例，所有
consumer 都通过同步 `get_one_instance` 完成发现、路由和负载均衡。路由规则
由 Polaris 服务端下发，示例不在客户端写死 `RouteRule`。

## 元数据路由

Provider 注册不同的实例 metadata，consumer 通过请求参数选择目标实例：

```bash
python examples/route/metadata/provider.py --port 19001 --metadata env=dev
python examples/route/metadata/provider.py --port 19002 --metadata env=prod
python examples/route/metadata/consumer.py --metadata env=dev
curl 'http://127.0.0.1:18090/echo?env=dev'
```

## 规则路由

Provider 注册不同的实例标签，在 Polaris 控制台为 `RouteEchoServer` 创建规则，
例如用请求头 `env` 或查询参数 `env` 将流量路由到对应标签：

```bash
python examples/route/rule/provider.py --port 19011 --metadata env=dev
python examples/route/rule/provider.py --port 19012 --metadata env=pre
python examples/route/rule/consumer.py
curl -H 'env: pre' 'http://127.0.0.1:18080/echo?env=pre'
```

Python SDK 会解析服务端下发的 `RuleRoutingConfig`，并把 `headers`、`query`、
`method` 和 `caller_ip` 传入规则匹配。

## 就近路由

Provider 注册 `region/zone/campus`，在 Polaris 控制台打开服务的就近路由，
consumer 使用自身地域信息选择最近实例：

```bash
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-1 \
python examples/route/nearby/provider.py --port 19021
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-2 \
python examples/route/nearby/provider.py --port 19022
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-1 \
python examples/route/nearby/consumer.py
curl http://127.0.0.1:18080/echo
```

就近规则由服务端下发；SDK 同时支持实例 protobuf 的 location 字段和 metadata
中的同名字段，便于和旧版本注册数据兼容。

自动验证会启动 provider/consumer，规则路由和就近路由还会创建服务端规则：

```bash
bash examples/route/metadata/verify_metadata_route.sh
bash examples/route/rule/verify_rule_route.sh
bash examples/route/nearby/verify_nearby_route.sh
```

每个子目录有自己的说明、用例和清理脚本：

| Demo | 说明 | 用例 | 清理 |
| --- | --- | --- | --- |
| metadata | [metadata/README.md](metadata/README.md) | [metadata/test.md](metadata/test.md) | [metadata/cleanup.sh](metadata/cleanup.sh) |
| rule | [rule/README.md](rule/README.md) | [rule/test.md](rule/test.md) | [rule/cleanup.sh](rule/cleanup.sh) |
| nearby | [nearby/README.md](nearby/README.md) | [nearby/test.md](nearby/test.md) | [nearby/cleanup.sh](nearby/cleanup.sh) |

三个 demo 的关系见 [test.md](test.md)。一次清理：

```bash
bash examples/route/cleanup_all.sh -f
```
