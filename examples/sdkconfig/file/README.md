# YAML 启动示例

`main.py` 使用 `init_context_by_file()` 从 YAML 创建共享 context。

## 运行

从仓库根目录执行：

```bash
make -C examples run DEMO=sdkconfig/file
make -C examples run DEMO=sdkconfig/file ARGS='--config "$PWD/examples/sdkconfig/file/polaris.yaml"'
make -C examples run DEMO=sdkconfig/file ARGS='--default'
make -C examples run DEMO=sdkconfig/file ARGS='--no-env'
```

- 不传 `--config` 时读取当前 demo 的 `polaris.yaml`。
- `--default` 使用 SDK 默认文件查找。
- `--no-env` 禁用环境变量覆盖和占位符展开。

默认文件查找顺序：

1. `POLARIS_CONFIG_FILE`
2. 当前目录 `polaris.yaml`
3. `~/.config/polaris/polaris.yaml`

## 配置

```yaml
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
    token: ${POLARIS_TOKEN:}
```

`${ENV:default}` 在环境变量未设置或为空时使用默认值。
完整字段见 [配置参数说明](../../../docs/config/configuration-reference.md)。

`global.api.bindIP` 是 SDK 自身地址，不是注册实例的业务 host。
注册请求仍必须显式设置 `host`。

## 输出

成功时输出一行 JSON，包含：

- 实际生效配置
- `bind_ip`
- `shared_context`
- `context_destroyed`
- `token_set`

可选真实发现：

```bash
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 \
  make -C examples run DEMO=sdkconfig/file ARGS='--service demo --namespace default'
```

## 日志与清理

从仓库根目录执行：

```bash
make -C examples logs ARGS='--only sdkconfig/file --latest --tail 30'
make -C examples cleanup ARGS='--only sdkconfig/file --dry-run'
make -C examples cleanup ARGS='--only sdkconfig/file'
```

示例日志保存在本目录 `.logs/run-<时间>-<id>/`，直接执行 `python main.py` 时使用
`.logs/manual/`。本目录 `make run ARGS='...'` 使用同一运行脚本。
默认清理先展示并确认，只停止记录的示例 PID 并清除本地生成产物，不删除远端服务。

## 集成验证

从仓库根目录执行 `./integration/verify.sh --only sdkconfig/file`；真实验证使用
`./integration/verify_e2e.sh --only sdkconfig/file`。测试步骤和集成测试产物见
[integration/scenarios/sdkconfig/file/test.md](../../../integration/scenarios/sdkconfig/file/test.md)。
