# Skill 查询与下载

[English](README.md)

通过独立 8094 gRPC 连接获取 published Skill、搜索列表并下载完整 ZIP。
传 `--mounted-service` 时先发现该服务，再按挂载记录解析 Skill 版本并读取；
挂载版本优先于 `--version`，两者为空时使用服务端 active 版本。
离线验证再启动新的 context，断网后读取前一个 context 持久化的内容与 ZIP，列表不降级。
SDK 不创建、不上传、不发布 Skill。

```bash
./examples/verify.sh --only skill
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
POLARIS_SKILL_SERVER_ADDRESS=<host>:8094 POLARIS_SKILL_NAME=<已发布名称> \
POLARIS_SKILL_NAMESPACE=default \
./examples/verify_e2e.sh --only skill
```

POLARIS_SKILL_TOKEN 优先于 POLARIS_TOKEN；POLARIS_SKILL_VERSION 可指定已发布版本，空值使用 active。
这些 Skill 环境变量由示例显式读取，不是 SDK 的自动覆盖变量。
统一 E2E 入口沿用 POLARIS_SERVICE_TOKEN 前置检查，Skill 只读 RPC 本身使用接入 Token。

```bash
POLARIS_E2E=1 make -C examples/skill run \
  ARGS="--skill-server <host>:8094 --namespace default --name lookup"
```

备份放在该次运行 polaris/backup/skills，实例备份在 polaris/backup/instances，日志放在同级 polaris/log/。
详细判定见 [test.md](test.md)，公开配置和降级语义见 [AI registry](../../docs/ai-registry.md)。
