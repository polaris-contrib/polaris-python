# 包发布

## 正式版本

`.github/workflows/release.yml` 在 GitHub Release 发布时执行。
Release tag 去掉 `v` 或 `polaris-python==` 前缀后，必须与
`src/polaris/_version.py` 的 `__version__` 一致。
构建 wheel / sdist 并通过安装验证和测试后，上传 PyPI。

## 开发版本

`.github/workflows/python-snapshot.yaml` 支持 `main`、`release/*`、`develop`。
源码、测试、`pyproject.toml`、`uv.lock` 或该流水线发生变更时自动执行；
也可在这些分支上手动执行。只有 `__version__` 含 `.dev` 时才构建和发布。
当前 `0.2.0` 是正式版本标记，会跳过开发包发布。

需要发布开发包时，在目标分支设置预期版本，例如：

```python
__version__ = "0.2.1.dev0"
```

流水线将其改为 `0.2.1.dev<GITHUB_RUN_NUMBER>`，只修改构建工作区，不回写仓库。
同一流水线重跑时保持版本不变，已上传的文件会被跳过。
开发包同样经过锁文件校验、wheel / sdist 构建、独立安装和非 E2E 测试，
只有验证成功的产物才进入发布任务。

两条发布流水线共用 GitHub `Release` 环境中的 `PYPI_API_TOKEN`。
该环境的分支策略需允许要发布的分支，已有审核策略仍然生效。
`uv.lock` 必须与配置一起提交。

## 使用开发包

```bash
uv pip install --prerelease allow 'polaris-python>=0.2.1.dev0,<0.3'
```

项目也可以显式声明开发版本下限或固定已发布版本。
`0.2.0.devN` 小于 `0.2.0`，因此原有 `polaris-python>=0.2.0,<0.3`
不能匹配 `0.2.0.devN`，即使开启预发布版本安装也是如此。
