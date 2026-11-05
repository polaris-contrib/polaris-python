# 版本管理与发布

## 1. 版本源

`polaris-python` 是一个独立发布的 distribution，distribution 名称和 import 包名
分别为：

```text
distribution: polaris-python
import:       polaris
```

项目使用 setuptools 动态版本，唯一有效版本来源是：

```text
src/polaris/_version.py
```

```python
__version__ = "0.2.0"
```

`pyproject.toml` 只声明动态版本及读取位置，不保存具体版本号：

```toml
[project]
name = "polaris-python"
dynamic = ["version"]

[tool.setuptools.dynamic]
version = {attr = "polaris._version.__version__"}
```

运行时版本从同一个文件导出：

```python
# src/polaris/__init__.py
from polaris._version import __version__
```

因此 wheel metadata 和 `polaris.__version__` 始终来自同一处，不能再手工维护第二份
版本号。

## 2. 与 polaris-python-ai 的关系

`polaris-python` 和 `polaris-python-ai` 是两个独立 PyPI distribution，分别维护版本：

```text
polaris-python
polaris-python-ai
```

`polaris-python-ai` 将 A2A、AgentScope、MCP 和 LangGraph 适配放在同一个 wheel
中，通过 extras 安装可选框架依赖：

```bash
pip install "polaris-python-ai[a2a]"
pip install "polaris-python-ai[agentscope]"
pip install "polaris-python-ai[mcp]"
pip install "polaris-python-ai[langgraph]"
pip install "polaris-python-ai[all]"
```

不再发布 `polaris-python-ai-a2a`、`polaris-python-ai-agentscope` 或
`polaris-python-ai-langgraph`。两个项目使用各自的版本文件、`uv.lock` 和 tag：

```text
polaris-python==<version>
polaris-python-ai==<version>
```

先发布兼容的 `polaris-python`，再发布依赖它的 `polaris-python-ai`。

## 3. 发布时需要修改哪些文件

### 3.1 普通版本发布

只修改：

```text
src/polaris/_version.py
```

例如从 `0.2.0` 发布 `0.2.1`：

```python
__version__ = "0.2.1"
```

以下文件不需要仅因版本变化而修改：

- `pyproject.toml`
- `src/polaris/__init__.py`
- `uv.lock`

`uv.lock` 在依赖或依赖来源变化时必须更新；普通版本号变化不会改变锁定的第三方依赖。

### 3.2 依赖或打包配置变化

如果本次发布同时修改了运行依赖、开发依赖、包发现规则、Python 版本范围或构建后端，
还需要修改：

```text
pyproject.toml
uv.lock
```

提交前执行：

```bash
uv lock
uv lock --check
```

版本号仍只写在 `src/polaris/_version.py`，不要在 `pyproject.toml` 中增加静态
`project.version`。

## 4. 版本格式

版本必须符合 PEP 440。常规发布使用：

```text
X.Y.Z
```

当前 `0.x` 阶段建议：

- `patch`：兼容性修复。
- `minor`：可能包含 breaking change。
- `major`：进入稳定期后的不兼容变化。

需要使用 PEP 440 预发布或 post release 时可使用：

```text
X.Y.ZaN
X.Y.ZbN
X.Y.ZrcN
X.Y.Z.postN
```

Snapshot 使用：

```text
X.Y.Z.devN
X.Y.ZaN.devM
X.Y.ZrcN.devM
```

PyPI Snapshot 禁止带 local version label：

```text
X.Y.Z.devN+local    # 不允许
```

## 5. Snapshot 版本

Snapshot workflow：

```text
.github/workflows/python-snapshot.yaml
```

会在 `main`、`release/*` 和 `develop` 分支上，因源码、测试、`pyproject.toml`、
`uv.lock` 或 workflow 变化而触发，也支持手动执行。

需要生成 Snapshot 时，在目标分支提交一个 `.dev0` 版本，例如：

```python
# src/polaris/_version.py
__version__ = "0.2.1.dev0"
```

workflow 会生成：

```text
0.2.1.dev<GITHUB_RUN_NUMBER>
```

例如第 42 次 workflow：

```text
0.2.1.dev42
```

这条改写只发生在 CI 构建工作区，不会回写仓库。相同 workflow 重跑使用相同
`GITHUB_RUN_NUMBER`，已存在的同一版本会通过 `skip-existing` 跳过。

只有 `.dev` 版本会进入 Snapshot 构建和发布。当前正式版本 `0.2.0` 会跳过 Snapshot。
发布正式版前，应把 `_version.py` 改为不含 `.dev` 的目标版本。

## 6. 正式发布

正式发布由以下 workflow 执行：

```text
.github/workflows/release.yml
```

推荐流程：

1. 确认要发布的内容已合并到目标 release commit。
2. 只修改 `src/polaris/_version.py` 为正式版本，例如 `0.2.1`。
3. 如需改变依赖，再同步 `pyproject.toml` 和 `uv.lock`。
4. 执行 `uv lock --check`、`uv build` 和安装后版本校验。
5. 提交版本变更。
6. 创建 Git tag 和 GitHub Release。

新 tag 推荐统一使用：

```text
polaris-python==<version>
```

例如：

```text
polaris-python==0.2.1
```

Release workflow 当前还兼容以下历史写法：

```text
vX.Y.Z
X.Y.Z
```

新版本应优先使用带 distribution 前缀的 tag，避免与其他仓库或包的 tag 冲突。

workflow 会从 tag 中移除可选的 `v` 或 `polaris-python==` 前缀，并要求结果与
`src/polaris/_version.py` 完全一致。标签与源码版本不一致时，构建直接失败。

严格校验示例：

```text
tag:                        polaris-python==0.2.1
_version.py __version__:    0.2.1
```

## 7. 构建与发布校验

本地发布前可执行：

```bash
uv lock --check
uv build
```

在干净环境中安装 wheel 后必须满足：

```python
from importlib.metadata import version
import polaris

assert version("polaris-python") == polaris.__version__
assert polaris.__file__  # 必须来自已安装环境，而不是源码目录
```

Release 和 Snapshot workflow 还会执行：

- 校验 `uv.lock`。
- 构建 wheel 和 sdist。
- 在独立虚拟环境安装 wheel。
- 校验 distribution metadata 与运行时 `__version__`。
- 运行非 E2E 测试。
- 只上传验证成功的产物。

两条发布流水线使用 GitHub `Release` 环境和 PyPI Trusted Publisher（OIDC）发布，
publish job 需要 `id-token: write`，不再依赖 `PYPI_API_TOKEN`。该环境的分支保护和
审核策略继续生效。

PyPI 项目需要分别授权 `python-snapshot.yaml` 和 `release.yml` 两个 workflow，环境名
均为 `Release`。如果项目尚未创建，可以先用 `python-snapshot.yaml` 的 pending
publisher 完成首次发布；项目创建后，再把 `release.yml` 作为正式 publisher 添加到该项
目。

## 8. 使用开发版本

需要安装 Snapshot 时：

```bash
uv pip install --prerelease allow 'polaris-python>=0.2.1.dev0,<0.3'
```

注意 PEP 440 的预发布排序：

```text
0.2.0.dev42 < 0.2.0
```

所以 `polaris-python>=0.2.0,<0.3` 不会匹配 `0.2.0.dev42`。要使用以
`0.2.0.devN` 为基础构建的 Snapshot，依赖下限必须明确写到
`0.2.0.dev0`，并允许预发布版本。

## 9. 发布检查清单

- [ ] `src/polaris/_version.py` 已是目标版本。
- [ ] `pyproject.toml` 没有静态 `project.version`。
- [ ] `src/polaris/__init__.py` 仍从 `_version.py` 导入版本。
- [ ] 版本变化本身没有无意义地改动 `uv.lock`。
- [ ] 依赖变化时已同步 `pyproject.toml` 和 `uv.lock`。
- [ ] `uv lock --check` 通过。
- [ ] wheel metadata 与 `polaris.__version__` 一致。
- [ ] Release tag 与 `_version.py` 一致。
- [ ] 已发布版本号未被重复使用。
