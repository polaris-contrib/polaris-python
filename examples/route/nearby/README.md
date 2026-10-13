# 就近路由

Provider 注册 `region`、`zone`、`campus`。服务端下发就近规则后，Consumer 按自身位置选择同 campus 的实例。SDK 同时认实例 location 字段和 metadata 里的同名字段。

## 目录

```text
examples/route/nearby/
├── provider.py
├── consumer.py
├── verify_nearby_route.sh
├── cleanup.sh
├── test.md
└── README.md
```

## 手动运行

```bash
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-1 \
python examples/route/nearby/provider.py --port 19021
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-2 \
python examples/route/nearby/provider.py --port 19022
REGION=china ZONE=ap-guangzhou CAMPUS=ap-guangzhou-1 \
python examples/route/nearby/consumer.py
curl http://127.0.0.1:18080/echo
```

控制台需要为该服务打开就近路由。自动验证会自己创建规则。

## 自动验证

```bash
bash examples/route/nearby/verify_nearby_route.sh
```

用例见 [test.md](test.md)。

## 清理

```bash
bash examples/route/nearby/cleanup.sh -f
```

`cleanup.sh` 不删除就近规则。规则名默认是 `RouteNearbyEchoServer-auto-nearby`。
