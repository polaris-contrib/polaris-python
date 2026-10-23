# Skill 验证

本目录验证 published Skill 的只读查询、列表过滤、ZIP 拼接及本地持久化降级。
默认离线验证不访问外部注册中心；只有 specification RPC 被替换，SDK 配置、独立连接、
owner loop、模型转换、分片组装、文件写队列、原子替换、读重试和销毁都使用真实实现。

## 脚本作用

从仓库根目录执行 `./examples/verify.sh --only skill`。
统一入口运行 verify.py 并记录 console.log、result.json 与 verification.log。
通过 `./examples/logs.sh --latest --category cache --tail 30` 查看备份相关日志，
`./examples/cleanup.sh --dry-run` 预览清理范围。
清理支持 `--keep-logs` 和 `--delete-services`。
main.py 仅在 POLARIS_E2E=1 时连接指定 Skill 服务；默认只打印启用提示。
Makefile 提供 build/run/package/clean 目标，参数通过 ARGS 传入。

## 离线验证

1. 使用独立 fake Skill stub 返回 namespace/name 与 published v1 版本，并在服务快照挂载 lookup/v1。
2. 通过 Consumer 获取 agent 服务快照，使用同步 mounted-skill 入口解析挂载版本并读取 SKILL.md。
3. 使用同步 list_skills 搜索 Skill 列表，检查匹配资源数量。
4. 使用实际 ZIP 文件字节，分成多个帧通过同步 download_skill 返回。
5. 校验总字节数与分片拼接，持久化完整版本化 payload。
6. 销毁首个 context，排空写队列后创建新的 context，共用本次备份目录。
7. 查询和下载 RPC 返回网络错误，检查 loaded_from_file=true 和最后 active 版本。
8. 使用标准 zipfile 读取内存中的 SKILL.md，确认 ZIP 正文与查询 content 相同。
9. 列表 RPC 同样断网，确认直接抛网络错误，没有本地列表降级。
10. 最终销毁 context，检查事件线程与 Skill 备份写线程均停止。

单元测试另覆盖指定版本未命中、不同命名空间隔离、业务错误不降级、空流/大小不匹配、
帧版本冲突、半途断流重试丢弃旧字节、同步入口、独立 Token 与连接，以及 YAML/纯代码配置。
下载返回完整字节，SDK 不自动解压、执行或安装 Skill。

## 执行产物与解读

每次运行保存 `.logs/verify-<时间>-<编号>/console.log`、result.json 和 verification.log。
console.log 包含 name、version、mounted_service=agent、zip_size 和 restart_fallback=true。
result.json 的 exit_code 为 0，且未超时/中断时才通过；失败断言可在 verification.log 查看。
polaris/log/ 保存分类日志，polaris/backup/skills 保留版本化查询/下载 JSON 与 active 指针。
polaris/backup/instances 是同 context 的独立实例备份目录，Skill 不写入实例注册表事件资源。
备份包含完整正文和 ZIP 的 protobuf JSON 字节字段，运行结束不删除。

## 注册服务与实例

本示例不注册服务或实例，只读取现有 published Skill。
离线 Skill 使用 ns/lookup、v1；fake endpoint 为 offline:8094。
真实 Skill 端口通常为 8094；普通发现连接默认 8091，两条连接分别持有。
POLARIS_SERVICE_TOKEN 是统一 E2E 脚本的前置参数，Skill RPC 使用接入 Token。

## 远端验证

这一路不替换 gRPC，也不注册临时服务。它只读已经发布的 Skill。发现连接和 Skill 连接是两条，端口通常是同一主机的 8091 和 8094。

```bash
export POLARIS_SERVER_ADDRESS=<host>:8091
export POLARIS_SERVICE_TOKEN=<service-token>
export POLARIS_SKILL_SERVER_ADDRESS=<host>:8094
export POLARIS_SKILL_NAME=<已发布名称>
export POLARIS_SKILL_NAMESPACE=default
./examples/verify_e2e.sh --only skill
```

`POLARIS_SKILL_SERVER_ADDRESS` 和 `POLARIS_SKILL_NAME` 缺一不可，否则验证器在启动示例前就失败。`POLARIS_SKILL_VERSION` 可选。`POLARIS_SKILL_TOKEN` 未设置时，Skill 连接使用 `POLARIS_TOKEN`。`POLARIS_SERVICE_TOKEN` 仍是脚本的前置参数，但这个场景不会拿它去注册实例。

步骤：

1. 用 `POLARIS_SERVER_ADDRESS` 建发现连接，用 `POLARIS_SKILL_SERVER_ADDRESS` 建 Skill 连接。
2. `get_skill` 读取指定命名空间和名称的 published 内容。
3. `download_skill` 把该版本打成 ZIP 下载到本地。
4. `list_skills` 按同一名称搜索，记录 `total`。
5. 查询或下载的返回码不是 0 或 200000 时，示例抛出 “the requested published Skill was not found”。

通过条件是标准输出里有一行 JSON，且含 `zip_size`。验证器不检查 ZIP 内容、不对比离线用的 ns/lookup 分片，也不上传、发布或删除服务端 Skill。

运行目录是 `.logs/verify-e2e-<时间>-<编号>/`。`skill.stdout.log` 是示例 JSON，`result.json` 的 `exit_code` 为 0 才通过。名称在服务端不存在时非零退出。
