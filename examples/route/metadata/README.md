# 元数据路由

Provider 把 `env` 写进实例 metadata。Consumer 用请求参数里的 `env` 做元数据匹配，只访问标签相同的实例。这个 demo 不创建服务端路由规则。

## 目录

```text
examples/route/metadata/
├── provider.py
├── consumer.py
├── verify_metadata_route.sh
├── cleanup.sh
├── test.md
└── README.md
```

## 手动运行

先起四个 provider，再起 consumer：

```bash
python examples/route/metadata/provider.py --port 19001 --metadata env=dev
python examples/route/metadata/provider.py --port 19002 --metadata env=prod
python examples/route/metadata/consumer.py --metadata env=dev
curl 'http://127.0.0.1:18090/echo?env=dev'
```

手动端口和自动验证端口不同。自动验证使用 `28071`–`28074`。

## 自动验证

```bash
bash examples/route/metadata/verify_metadata_route.sh
```

用例、端口和通过条件见 [test.md](test.md)。

## 清理

```bash
bash examples/route/metadata/cleanup.sh
bash examples/route/metadata/cleanup.sh -f
bash examples/route/metadata/cleanup.sh --dry-run
```

三个路由 demo 一起清：

```bash
bash examples/route/cleanup_all.sh -f
```
