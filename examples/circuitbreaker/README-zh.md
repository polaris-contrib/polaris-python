# 本地实例熔断示例

[English](README.md)

演示 Python SDK 的本地 `composite` 实例规则：连续失败、错误率、半开配额、
路由及全死全活兜底。

## 离线验证

```bash
./verify.sh
```

脚本启动本机 HTTP Provider，使用真实 SDK 路由、上报、熔断定时器、缓存和发现，
不连接外部注册中心。覆盖：

- HTTP 成功 / 失败判错
- 连续失败与健康实例路由
- 半开失败、恢复和请求配额
- 错误率窗口与最小样本数
- 全死全活回退
- 同步 / 异步流程
- 自动心跳、反注册和资源清理

## 真实注册中心

设置 `POLARIS_E2E=1`，启动两个 Provider 和一个 Caller：

```bash
export POLARIS_E2E=1
export POLARIS_SERVER_ADDRESS=127.0.0.1:8091
export POLARIS_TOKEN=
export POLARIS_SERVICE_TOKEN=

./provider/run.sh --port 18081 --status 200
./provider/run.sh --port 18082 --status 500
./consumer/run.sh --port 18080
```

Caller 不注册。Provider 默认用 `get_local_host(POLARIS_SERVER_ADDRESS)` 作为业务注册
地址；显式 `--host` 可覆盖，SDK `bindIP` 与注册 IP 独立。

观察实例状态和恢复：

```bash
curl http://127.0.0.1:18080/instances
curl 'http://127.0.0.1:18082/switch?openError=false'
```

故障切换接口仅用于测试，不要暴露到不可信网络。

## 日志与清理

```bash
./logs.sh --latest --tail 30
./logs.sh --latest --category circuitbreaker --follow
./cleanup.sh --force
```

规则说明见 [本地实例熔断](../../docs/circuitbreaker.md)。
