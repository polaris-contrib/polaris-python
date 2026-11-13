# Skill 查询与下载

[English](README.md)

通过独立 8094 gRPC 连接获取 published Skill、搜索列表并下载完整 ZIP。
传 `--mounted-service` 时先发现该服务，再按挂载记录解析 Skill 版本并读取；
挂载版本优先于 `--version`，两者为空时使用服务端 active 版本。
断网后可读取已持久化的完整内容与 ZIP，列表不降级。
SDK 不创建、不上传、不发布 Skill。

POLARIS_SKILL_TOKEN 优先于 POLARIS_TOKEN；POLARIS_SKILL_VERSION 可指定已发布版本，空值使用 active。
这些 Skill 环境变量由示例显式读取，不是 SDK 的自动覆盖变量。
该场景不注册实例，无需 POLARIS_SERVICE_TOKEN；Skill 只读 RPC 使用
POLARIS_SKILL_TOKEN，未设置时继承 POLARIS_TOKEN。
Skill 地址通过 `--skill-server` 或 `POLARIS_SKILL_SERVER_ADDRESS` 指定，
本示例默认使用 `127.0.0.1:8094`。用 `--namespace`、`--name` 和可选的 `--version`
选择已有 published 资源。

从仓库根目录执行：

```bash
make -C examples run DEMO=skill ARGS='--skill-server 127.0.0.1:8094 --namespace default --name lookup'
```

备份放在该次运行 polaris/backup/skills，实例备份在 polaris/backup/instances，日志放在同级 polaris/log/。
公开配置和降级语义见 [AI registry](../../docs/guides/ai-registry.md)。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only skill --latest --tail 30'
make -C examples cleanup ARGS='--only skill --dry-run'
make -C examples cleanup ARGS='--only skill'
```

示例日志和备份保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务或已发布 Skill。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only skill`；真实验证使用
`./integration/verify_e2e.sh --only skill`。测试步骤、E2E fixture 行为和集成测试产物见
[integration/scenarios/skill/test.md](../../integration/scenarios/skill/test.md)。
