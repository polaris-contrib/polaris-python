# examples/route — 用例清单

路由示例分成三个独立 demo，各自有 `verify_*.sh`、`test.md` 和 `cleanup.sh`。

| Demo | 验证脚本 | 用例说明 | 清理 |
| --- | --- | --- | --- |
| 元数据路由 | [metadata/verify_metadata_route.sh](metadata/verify_metadata_route.sh) | [metadata/test.md](metadata/test.md) | [metadata/cleanup.sh](metadata/cleanup.sh) |
| 规则路由 | [rule/verify_rule_route.sh](rule/verify_rule_route.sh) | [rule/test.md](rule/test.md) | [rule/cleanup.sh](rule/cleanup.sh) |
| 就近路由 | [nearby/verify_nearby_route.sh](nearby/verify_nearby_route.sh) | [nearby/test.md](nearby/test.md) | [nearby/cleanup.sh](nearby/cleanup.sh) |

三个脚本都假设本机 Polaris 在 `127.0.0.1:8091`，管理端口 `8090`。地址和令牌用 `POLARIS_SERVER`、`POLARIS_TOKEN`，或各脚本的 `--polaris-server`、`--polaris-token`。

`rule` 和 `nearby` 的 consumer 默认都监听 `18080`，不要并行执行。`examples/verify_all.sh` 按 quickstart、metadata、rule、nearby、ratelimit、circuitbreaker 的顺序串行运行。

一次清理三个 demo：

```bash
bash examples/route/cleanup_all.sh -f
```

规则路由和就近路由会在服务端留下自动创建的规则，`cleanup_all.sh` 不删除这些规则。规则名见各自的 `test.md`。
