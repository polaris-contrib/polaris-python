# YAML 启动示例

`main.py` 使用 `init_context_by_file()` 从 YAML 创建共享 context。

## 运行

```bash
./run.sh
./run.sh --config ./polaris.yaml
./run.sh --default
./run.sh --no-env
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
POLARIS_E2E=1 ./run.sh --service demo --namespace default
```

## 验证与清理

```bash
./verify.sh
./logs.sh --latest --tail 30
./cleanup.sh --force
```
