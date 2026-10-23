# AI Registry

Python SDK 通过普通实例、服务契约和独立 Skill 连接支持 AI Registry。
MCP、A2A 和 Agent 框架适配不增加专用 SDK 依赖。

## 实例快照

- `get_all_instances()`：完整缓存，包括隔离、零权重和不健康实例。
- `get_instances()`：本地路由后的候选实例，不执行负载均衡。
- `get_healthy_instances()`：只执行隔离和恢复路由，默认包含熔断实例。
- `get_one_instance()`：路由后执行负载均衡。

以上方法均有 `async_` 形式，列表结果使用 `.instances` 或 `.get_instances()`。

服务快照提供 `get_service_type()`、`get_service_status()` 和
`get_extended_metadata()`。默认不过滤 `OFFLINE` 服务；需要时设置
`exclude_offline_service=True`。

首次发现等待远端；网络失败或超时后可使用磁盘备份。`400301` 会清理内存、
Discover 和备份。相同 revision 保留当前快照，成功的空响应替换快照。

## MCP

MCP 复用 `ProviderAPI`、`ConsumerAPI`、`Instance`、Discover 和路由，不提供
MCP 专用请求模型。

注册 metadata：

```python
metadata = {
    "mcp-server-name": "search-mcp",
    "mcp-protocol-version": "2025-06-18",
    "mcp-endpoint-path": "/mcp",
}
```

注册协议支持 `mcp-streamable-http` 和 `mcp-sse`，默认路径分别为
`/mcp` 和 `/sse`。`Instance.version` 表示 MCP Server 版本。

服务契约通过：

```python
provider.report_service_contract(contract)
consumer.get_service_contract(request)
```

契约上报失败不会回滚已注册实例。SDK 不自动生成 Tool、Resource 或 Prompt 定义，
也不实现 MCP Client、`tools/list`、Tool 调用或协议过滤。

应用发现实例后，用 `host`、`port` 和 `mcp-endpoint-path` 自行构造 URL。
IPv6 host 需要加方括号。

## A2A

A2A Agent 使用普通实例。推荐 metadata：

```text
ai-agent-name
a2a.agent.card
a2a.transport
a2a.path
```

AgentCard 的序列化、解析、兼容检查和端点调用由应用或扩展层完成。
SDK 不提供 A2A Server、远程 AgentCard 获取或框架注册器。

## 调用指标

`ServiceCallResult` 可带：

- `method`
- `instance_type="mcp"` 或 `"a2a"`
- `caller_service`
- `labels`

同步上报使用 `update_service_call_result()`，异步使用
`async_update_service_call_result()`。详见 [可观测性](observability.md)。

## Skill

Skill 使用独立 gRPC 连接：

```python
from polaris import Configuration, SkillAPI, init_context_by_config
from polaris.pkg.model.skill import SkillGetRequest

config = Configuration()
config.set_default()
config.get_ai().get_skill().get_server_connector().addresses = ["127.0.0.1:8094"]

context = init_context_by_config(config)
try:
    api = SkillAPI(context)
    skill = api.get_skill(SkillGetRequest("default", "search"))
    print(skill.content)
finally:
    context.destroy()
```

接口：

- `get_skill()`：读取 published 内容和版本。
- `list_skills()`：按名称、tag、owner、scope、keyword 分页查询。
- `download_skill()`：支持 Markdown 和 ZIP；ZIP 分片会拼成完整字节流。
- `get_mounted_skill()` / `download_mounted_skill()`：从服务挂载记录解析 Skill。

均有 `async_` 形式。未找到资源 `400202` 作为结果返回，其他业务错误抛
`SDKError`。SDK 不自动解压或执行下载内容。

默认查询超时 5 秒，ZIP 下载超时 30 秒。请求自带 `timeout` 时优先。

配置位于 `ai.skill.serverConnector`。完整字段见
[配置参数说明](config/configuration-reference.md)。Skill token 为空时可继承主注册中心 token。

查询和下载成功后异步写入版本化备份。网络错误且
`fallbackToLocalCache=true` 时读取同命名空间、名称、版本和格式的备份。
业务错误不降级；列表查询不持久化。

`loaded_from_file=True` 表示本地结果。备份写入使用原子替换、FIFO 队列和读写重试；
销毁 context 会排空已接受写入并关闭独立 gRPC 通道。

## TLS

主注册中心和 Skill 连接分别支持 `trustedCAFile`、`certFile` 和 `keyFile`。
证书配置错误会拒绝启动，不降级为明文。详见 [TLS](tls.md)。

## 示例

```bash
./examples/verify.sh --only mcp,skill,a2a,monitoring
./examples/verify_e2e.sh --only mcp
./examples/verify_e2e.sh --only skill
```

真实服务验证要求 `POLARIS_E2E=1`。
