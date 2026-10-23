# 异常重启恢复示例

[English](README.md)

演示进程在缓存写入期间被终止后，如何从最后一次完整备份恢复。

## 验证

```bash
./verify.sh
```

脚本会：

1. 启动本地临时 gRPC 服务。
2. 发现实例并写入磁盘备份。
3. 在下一次写入期间终止 SDK 子进程。
4. 关闭服务，并用同一缓存目录重新发现。
5. 验证同步和异步降级。
6. 恢复服务，验证新 revision 替换备份。

只加载完整备份，中断写入留下的临时文件不会参与加载。

备份名称与 Go 一致：

```text
svc#<namespace>#<service>#instance.json
```

## 真实注册中心

```bash
POLARIS_E2E=1 ./run.sh default demo \
  --persist-dir .logs/manual/polaris/backup/restart
```

示例只发现已有服务。不同注册中心或独立缓存生命周期应使用不同目录。

`global.api.timeout` 限制首次远端等待。网络失败或超时后可返回完整备份，
后台发现继续运行，服务恢复后更新缓存。

## 日志与清理

```bash
./logs.sh --latest --category cache --tail 30
./cleanup.sh --force
```
