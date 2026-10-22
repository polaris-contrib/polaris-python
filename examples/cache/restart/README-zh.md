# 缓存重启恢复

在仓库根目录执行，不需要外部 Polaris 服务端：

```bash
uv run --locked python examples/cache/restart/verify.py
```

验证程序会启动临时的本机回环 gRPC 服务和一个 SDK 子进程。子进程发现服务并把实例响应写入磁盘后，验证程序在另一次快照写入过程中用 `SIGKILL` 结束它，然后停止服务端。新的 SDK 进程复用同一个 `persistDir`。首次远端等待超时后，同步 / 异步发现都返回最后完整备份，覆盖新文件和 120 秒旧文件。验证程序随后用新的 revision 重新启动服务端，并检查两次调用都返回这个远端 revision。临时文件不会被加载，被打断的那次写入之前，最后一份完整快照仍然可用。子进程在结束后关闭；验证文件保留在本 demo 的 `.logs/` 下，可查看和清理。

备份文件按 Go SDK 的 `svc#<namespace>#<service>#instance.json` 命名，并以缩进
JSON 写入，可直接查看实例响应。

实例备份会读入内存，但不看文件修改时间，`remote_updated` 仍为 false。默认读取继续等待远端。首次等待受 `global.api.timeout` 限制；网络失败或超时后返回合法备份，但不标记远端已更新；服务不存在会清理备份而不是降级。后台发现继续运行，服务端恢复后会替换快照。这和 `serviceExpireTime` 是两件事：后者控制内存闲置淘汰，并删除对应备份。

`persistMaxReadRetry` 和 `persistMaxWriteRetry` 是首次读或写失败之后的额外次数。`persistRetryInterval` 是失败尝试之间的间隔。锁冲突、I/O 失败和 JSON 解析失败会重试；文件缺失或过期则直接视为缓存未命中。删除使用写重试额度。读取由 context 自己的读取线程执行，写入和删除进入它的先进先出写线程。关闭时会打断读重试等待，并写完已经接受的写任务，因此很大的写重试额度会延长关闭时间。

要从真实注册中心生成备份，需要显式开启：

```bash
POLARIS_E2E=1 POLARIS_SERVER=127.0.0.1:8091 \
  uv run --locked python examples/cache/restart/main.py default demo \
  --persist-dir examples/cache/restart/.logs/manual/polaris/backup/restart
```

`--persist-dir` 省略时默认使用与 SDK 日志同级的 `.logs/manual/polaris/backup/restart`。
`--config path/to/polaris.yaml` 选择 YAML 启动配置。注册中心不可用时，用同一目录再运行可在首次等待超时后返回已保存的实例。示例只发现已有服务，不注册或反注册实例。互相独立的 context 或注册中心要使用不同目录。进程重启恢复依赖已经写完的备份；它不保证恢复尚未写完的队列，也不保证操作系统崩溃、断电、磁盘丢失或临时容器文件系统上的数据还在。

英文说明见 [README.md](README.md)。

## 验证、日志和清理

在本目录可以直接执行以下脚本；从仓库根目录按相应路径执行同样有效。

```bash
./examples/verify.sh --only cache/restart
make -C examples/cache/restart run ARGS="--help"
./examples/logs.sh --latest --tail 30
./examples/logs.sh --latest --category network --tail 30
./examples/cleanup.sh --dry-run
./examples/cleanup.sh --force
```

`verify.sh` 验证当前场景；包含多种场景的汇总目录依次验证子 demo，日志保存在各自目录的 `.logs/` 下。
`./examples/logs.sh --follow` 可持续查看日志。每次执行保留独立目录、控制台输出和 SDK 分类日志；
`run.sh` 转发 `main.py` 参数。默认清理先展示并确认，`--force` 跳过确认，
只停止本目录及子 demo 的已记录进程并删除 `.logs/`、`.runtime/`。
完整运行和目录规则见 [示例总览](../../README-zh.md)。
