# Polaris Python 云端 E2E 打包与回传

[English](README.md)

这套脚本参考 `polaris-limiter/test/integration/io-hang` 的云端验收方式：

1. 本地构建包含源码、示例、集成测试和可选 Python 运行时的部署包。
2. 上传并解压到云端测试机。
3. 云端执行真实 E2E，日志写入独立运行目录。
4. 云端打包运行日志。
5. 下载日志包到本地，安全解压并读取结果摘要。

默认部署包面向 **Linux x86_64、Python 3.12**，并携带解析后的依赖运行时。
云端只要求 Python 3.12 和基础系统命令，不要求在云端访问 PyPI。使用
`--without-runtime` 可生成较小源码包，此时云端需要 `uv` 和网络。

## 本地构建

在仓库根目录执行：

```bash
./integration/cloud/build-package.sh
```

默认输出：

```text
integration/cloud/dist/polaris-python-cloud-<version>-<commit>-<time>.tar.gz
integration/cloud/dist/polaris-python-cloud-<version>-<commit>-<time>.tar.gz.sha256
```

也可以从示例入口构建：

```bash
./examples/cloud-package.sh
```

常用选项：

```bash
# 云端使用 aarch64 Linux
./integration/cloud/build-package.sh \
  --python-platform aarch64-manylinux_2_28

# 不携带依赖运行时，包更小；云端必须有 uv 且可访问依赖源
./integration/cloud/build-package.sh --without-runtime

# 指定输出目录和包名
./integration/cloud/build-package.sh \
  --output-dir /tmp/polaris-dist \
  --name polaris-python-cloud-test

# 清理本地打包产物
./integration/cloud/build-package.sh --clean
```

包内包含：

```text
run-e2e.sh
pack-logs.sh
import-logs.sh
summarize-results.py
manifest.json
requirements.txt
wheels/
runtime/                # --without-runtime 时不包含
src/
examples/
integration/
CLOUD-README-zh.md
```

`manifest.json` 记录版本、Git commit、工作区是否 dirty、Python 版本、目标平台和
构建时间。`SHA256SUMS` 用于包内文件完整性检查。

## 上传与部署

```bash
scp integration/cloud/dist/<package>.tar.gz \
    integration/cloud/dist/<package>.tar.gz.sha256 \
    <user>@<cloud-host>:~/
```

云端：

```bash
sha256sum -c <package>.tar.gz.sha256
tar xzf <package>.tar.gz
cd <package>
```

macOS 没有 `sha256sum` 时可在云端使用 `shasum -a 256 -c`。

## 云端运行

全部场景：

```bash
POLARIS_SERVICE_TOKEN=<optional-token> \
./run-e2e.sh --server 1.14.219.4:8091
```

指定场景和超时：

```bash
./run-e2e.sh \
  --server 1.14.219.4:8091 \
  --only quickstart,circuitbreaker \
  --timeout 600
```

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `POLARIS_E2E_NAMESPACE` | 默认 `polaris-python-integration`，不能使用 `default` |
| `POLARIS_TOKEN` | SDK 连接层鉴权 |
| `POLARIS_SERVICE_TOKEN` | 注册、心跳和反注册的服务级 token |
| `POLARIS_E2E_SERVICE_TOKEN` | E2E service token，优先于 `POLARIS_SERVICE_TOKEN` |
| `POLARIS_SKILL_NAME` / `POLARIS_SKILL_NAMESPACE` | Skill 场景覆盖值 |
| `POLARIS_SKILL_SERVER_ADDRESS` | Skill API 地址 |

`run-e2e.sh` 不会把 token 写入日志，只在 `environment.txt` 中记录是否设置。

每次运行创建：

```text
cloud-runs/<run-id>/
├── manifest.json
├── environment.txt
├── run.log
├── analysis.txt
├── logs/
│   └── <scenario>/verify-e2e-.../
└── runtime-records/       # 保留进程记录快照，存在时
```

脚本默认保留云端进程和服务，与服务端直接运行
`integration/verify_e2e.sh` 的语义一致。需要人工排查时先保留，确认后再执行部署包内的：

```bash
./integration/cleanup.sh --force --delete-services
```

## 云端打包日志

`run-e2e.sh` 结束时会自动生成：

```text
cloud-runs/<run-id>-logs.tar.gz
cloud-runs/<run-id>-logs.tar.gz.sha256
```

也可以手动打包：

```bash
# 最近一次或指定运行
./pack-logs.sh --run-dir cloud-runs/<run-id>

# 所有运行
./pack-logs.sh --all

# 直接打包 integration/.logs
./pack-logs.sh --log-dir integration/.logs

# 指定输出
./pack-logs.sh \
  --run-dir cloud-runs/<run-id> \
  --output /root/polaris-python-e2e-logs.tar.gz
```

日志包包含 `analysis.txt`，汇总 passed/failed 和每个场景的退出码。

## 下载与本地分析

```bash
scp <user>@<cloud-host>:~/cloud-runs/<run-id>-logs.tar.gz .
scp <user>@<cloud-host>:~/cloud-runs/<run-id>-logs.tar.gz.sha256 .

./integration/cloud/import-logs.sh ./<run-id>-logs.tar.gz
```

默认解压到：

```text
integration/.logs/imported/<archive-name>/
```

脚本会：

- 校验相邻 `.sha256` 文件；
- 拒绝绝对路径、`..` 路径和符号链接；
- 生成或刷新 `analysis.txt`；
- 打印场景通过/失败摘要。

建议排查顺序：

1. `analysis.txt`
2. `logs/verify-e2e-summary-*/summary.json`
3. 场景目录中的 `result.json`
4. `verification.log`
5. `console.log`
6. `polaris/log/`
7. `polaris/backup/`

## 安全与限制

- 部署包不得包含 token、`.env`、`.venv`、`.git`、历史 `.logs` 或 `.runtime`。
- 本地构建脚本会排除测试缓存和历史运行产物。
- 运行时包按目标平台下载二进制依赖；在 macOS 本地无法直接执行 Linux runtime。
- 跨平台部署优先在相同 CPU 架构和 glibc 版本族上构建；当前默认
  `x86_64-manylinux_2_28`。
- 云端日志可能包含业务地址、实例 ID 和请求内容，回传和保存时应按内部数据要求处理。
