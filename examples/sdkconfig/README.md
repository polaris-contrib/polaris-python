# SDK 启动配置示例

- [file](file/README.md)：从 `polaris.yaml` 启动。
- [code](code/README.md)：直接给 `Configuration` 赋值。

完整字段见 [配置参数说明](../../docs/config/configuration-reference.md)。

## 验证

```bash
./verify.sh
./verify.sh --only file
./verify.sh --only code
```

验证覆盖：

- YAML、环境变量和默认文件查找
- `${ENV:default}` 占位符
- 最小配置参考和默认值填充
- 纯代码配置和 context 销毁
- SDK 自身 IP 解析
- 本地熔断参数

每个场景使用独立工作目录、日志和缓存。

## 真实注册中心

```bash
POLARIS_E2E=1 ./file/run.sh --service demo --namespace default
```

示例只发现已有服务。配置启动成功不代表远端连接或鉴权成功。

## 日志与清理

```bash
../logs.sh --latest --tail 30
../cleanup.sh --force
```
