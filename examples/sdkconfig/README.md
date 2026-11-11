# SDK 启动配置示例

- [file](file/README.md)：从 `polaris.yaml` 启动。
- [code](code/README.md)：直接给 `Configuration` 赋值。

完整字段见 [配置参数说明](../../docs/config/configuration-reference.md)。

## 运行

从仓库根目录执行：

```bash
make -C examples run DEMO=sdkconfig/file
make -C examples run DEMO=sdkconfig/code
make -C examples/sdkconfig run DEMO=file
```

各子示例保留独立配置、日志和缓存。

## 真实注册中心

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=sdkconfig/file ARGS='--service demo --namespace default'
```

示例只发现已有服务。配置启动成功不代表远端连接或鉴权成功。

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only sdkconfig --latest --tail 30'
make -C examples cleanup ARGS='--only sdkconfig --dry-run'
make -C examples cleanup ARGS='--only sdkconfig'
```

示例日志保存在各子 demo 的 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时
使用 `.logs/manual/`。默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，
不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only sdkconfig`；也可用
`--only sdkconfig/file` 或 `--only sdkconfig/code`。真实验证使用
`./integration/verify_e2e.sh --only sdkconfig`。测试覆盖和集成测试产物见
[integration/scenarios/sdkconfig/test.md](../../integration/scenarios/sdkconfig/test.md)。
