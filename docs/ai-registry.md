# AI 注册发现

MCP 服务和普通业务服务共用 `Instance`、实例缓存、Discover 流、路由和负载均衡。
注册表只缓存 INSTANCE 资源；服务契约和 Skill 使用独立 RPC。

## 实例快照

实例快照保留服务端返回的全部实例，包括隔离、零权重和不健康实例，按 host、port 排序。
刷新时按实例 ID 复用本地熔断状态，新 ID 使用独立状态。
`get_all_instances()` 返回全部缓存实例；`get_instances()` 返回本地路由过滤后的候选，
不执行负载均衡、不消耗半开配额。`get_healthy_instances()` 只执行前置隔离和后置恢复过滤，
默认包含已熔断实例，不执行中间 metadata 链。`get_one_instance()` 过滤后选择一个实例。
上述入口均提供 `async_` 形式，列表结果使用 `.instances` 或 `.get_instances()`。

服务快照提供 `get_service_type()`、`get_service_status()` 和 `get_extended_metadata()`。
扩展元数据中的 `agent_skill` 包含挂载 Skill 的名称、版本、说明、标签和输入输出模式。
`is_loaded_from_file()` 标识备份来源。首次请求先等待远端，网络失败或 API 超时后可使用备份；
后台重连继续，远端成功后更新快照。备份加载不检查文件年龄。
400301 服务不存在会清理内存、Discover 和备份，不降级；相同 revision / DATA_NO_CHANGE
保留当前快照。服务状态 OFFLINE 不自动过滤，成功的空快照替换原有实例。
需要排除下线服务时，在 `GetInstancesRequest` 或 `GetOneInstanceRequest` 设置
`exclude_offline_service=True`；该选项作用于候选、健康和单实例查询，
`get_all_instances()` 仍返回完整快照。默认值保持 `False`，不改变既有查询语义。

## MCP 注册与发现

```python
from polaris import Configuration, ConsumerAPI, ProviderAPI, SDKError, init_context_by_config
from polaris.pkg.model.contract import ServiceContract, ServiceFeature, ServiceFeatureType
from polaris.pkg.model.server import InstanceDeRegisterRequest, InstanceRegisterRequest
from polaris.pkg.model.service import GetOneInstanceRequest

config = Configuration()
config.set_default()
config.get_global().get_server_connector().addresses = ["127.0.0.1:8091"]
context = init_context_by_config(config)
provider, consumer = ProviderAPI(context), ConsumerAPI(context)
metadata = {
    "mcp-server-name": "search-mcp",
    "mcp-protocol-version": "2025-06-18",
    "mcp-endpoint-path": "/mcp",
}
response = None
try:
    response = provider.register_instance(InstanceRegisterRequest(
        "search-mcp", "service-token", "default", "127.0.0.1", 8000,
        protocol="mcp-streamable-http", version="v1", metadata=metadata, ttl=5,
    ))
    try:
        provider.report_service_contract(ServiceContract(
            namespace="default", service="search-mcp", name="search-mcp",
            protocol="mcp-streamable-http", version="v1",
            service_features=[ServiceFeature(
                ServiceFeatureType.MCP_TOOL, "search", content='{"name":"search","inputSchema":{"type":"object"}}',
            )],
        ))
    except SDKError as error:
        context.get_value_context().logger.warning("Startup contract report failed: %s", error)
    instance = consumer.get_one_instance(GetOneInstanceRequest(
        namespace="default", service="search-mcp",
    ))
    print(instance.get_host(), instance.get_port(),
          instance.get_metadata()["mcp-endpoint-path"])
finally:
    try:
        if response is not None:
            provider.deregister(InstanceDeRegisterRequest(
                "search-mcp", "service-token", "default", "127.0.0.1", 8000,
                response.instance_id,
            ))
    finally:
        context.destroy()
```

SDK 不提供 MCP 专用 API、请求模型或创建工厂。MCP 注册、心跳、发现和路由复用
`ProviderAPI`、`ConsumerAPI`、`InstanceRegisterRequest`、`GetInstancesRequest`
和 `GetOneInstanceRequest`。
示例支持 `mcp-streamable-http` 和 `mcp-sse`，默认路径分别为 `/mcp` 和 `/sse`。
`Instance.version` 表示 MCP Server 版本；协议版本放在 `mcp-protocol-version`。
应用在注册请求中填写标准 `mcp-server-name`、`mcp-protocol-version`、`mcp-endpoint-path` metadata。
实例注册协议没有 service_type 字段，服务类型由注册中心识别并在发现响应中返回。

`register_instance()` 注册成功后启动自动心跳，复用 Provider 的持续上报和重注册策略。
契约上报是独立操作，失败抛 SDKError，不回滚已注册实例；是否告警并继续由应用决定。
示例组装并上报一次 Tool、Resource、Prompt 的 JSON 定义，初始状态为 enabled；上报失败只告警。
SDK 不自动组装契约或监听能力变更。

`ConsumerAPI.get_all_instances()` 返回完整实例快照，包括不健康、隔离、零权重实例。
`get_instances()` 返回本地候选；服务 OFFLINE 状态不属于默认过滤条件。
`get_one_instance()` 执行普通路由链和负载均衡，不附加 MCP 协议、版本或 metadata 过滤。
需要元数据路由时显式配置 `metadataRouter`；协议版本交集等 MCP 策略由应用实现。
应用可由实例 host、port 与 `mcp-endpoint-path` 构造 HTTP/HTTPS URL，IPv6 host 需加方括号。

`examples/mcp/main.py` 在注册前检查第一个健康、未隔离、非零权重实例的 transport 和协议版本交集。
默认差异只告警；`--strict-compatible` 拒绝明确不兼容的注册，发现检查失败仍告警并继续。
发现后示例检查所选实例的状态、协议、Server 版本和标准 metadata；这些检查不修改 SDK 缓存。
URL 拼装、兼容检查、能力组装和退出反注册都在示例层，不是 SDK 专用接口。

`provider.deregister()` 停止该实例心跳并反注册；context 销毁只停止心跳，不隐式反注册。
普通 Provider / Consumer 的 `destroy()` 仍销毁所属 context；多个 API 共用 context 时由应用统一管理。
应用退出先反注册，再销毁自己持有的 context；反注册失败也应通过 finally 完成销毁。
强制终止进程无法执行清理，网络中断或取消时尚未确认的注册结果无法保证反注册。
普通方法为同步，异步使用 `async_register_instance`、`async_get_instances`、`async_get_one_instance`、
`async_report_service_contract`、`async_get_service_contract` 和 `async_deregister`。

本层不依赖 MCP、AgentScope 或 LangGraph 包，也未提供 tools/list、Tool 调用、MCP Client 池或外部 watch。
具体 MCP Server 在完成自身 HTTP 启动后调用注册入口，实例 host/port 由应用指定。

## A2A 元数据

Agent 端点同样使用普通 Provider / Consumer 和 Instance，不提供 A2AAPI。
应用在注册请求携带 `ai-agent-name`、`a2a.agent.card`、`a2a.transport`、`a2a.path`。
Card 为序列化 JSON，解析、端点拼装、兼容检查和实际 Agent 调用属于应用或扩展层。
`examples/a2a` 验证普通注册、自动心跳、发现 metadata 和显式反注册；不启动 Agent Server，
不提供远程 AgentCard 获取或框架注册器。

调用数据上报使用普通 `ServiceCallResult`，可指定 `instance_type="mcp"` 或 `"a2a"`。
MCP Tool 调用的 `method` 使用 Tool 名；A2A 调用的 `method` 使用 Agent 操作或消息路径。
Agent、环境等附加维度通过 `caller_service` 与 `labels` 传递。
同步入口 `update_service_call_result`，异步入口 `async_update_service_call_result`，
指标导出见 [可观测性](observability.md)，安全连接见 [TLS](tls.md)。

## 服务契约

`ProviderAPI.report_service_contract()` / `async_report_service_contract()` 接受
`ServiceContract`，包含 service_features 和 interfaces。
`ConsumerAPI.get_service_contract()` / `async_get_service_contract()` 接受
`GetServiceContractRequest(namespace, service, protocol, version)`，返回公开 Python 模型。
它们使用 8091 连接的服务契约 RPC，不增加注册表事件类型。

## Skill 只读接口

```python
from polaris import Configuration, SkillAPI, init_context_by_config
from polaris.pkg.model.skill import SkillDownloadRequest, SkillGetRequest, SkillListRequest

config = Configuration()
config.set_default()
skill_config = config.get_ai().get_skill().get_server_connector()
skill_config.addresses = ["127.0.0.1:8094"]
skill_config.token = "access-token"
skill_config.persist_dir = "./polaris/backup/skill"
context = init_context_by_config(config)
try:
    api = SkillAPI(context)
    skill = api.get_skill(SkillGetRequest("default", "search"))
    page = api.list_skills(SkillListRequest(namespace="default", tag="search", keyword="document"))
    package = api.download_skill(SkillDownloadRequest("default", "search", version=skill.version.version, format="zip"))
    print(skill.content, page.total, len(package.data))
finally:
    context.destroy()
```

`get_skill` 获取 published 内容及版本信息；version 为空时由服务端解析 active 版本。
`list_skills` 支持 name/tag/owner/scope/keyword、order_by/order_type 和 offset/limit。
`download_skill` 支持 markdown 和 zip；Markdown 在 content，ZIP 字节在 data。
ZIP 流按分片拼成一个完整包，校验 total_size；半途失败重试从空缓冲区重新开始。
SDK 返回字节而不自动解压或执行下载的内容。
结果包含 code/info；0 和 200000 为成功，未找到资源的 400202 作为结果返回，其他业务错误抛 SDKError。
异步入口为 `async_get_skill`、`async_list_skills`、`async_download_skill`。

配置位于 `ai.skill.serverConnector`，支持 polaris.yaml 和纯代码赋值。
完整字段见 [配置参考](config/polaris.yaml)。Skill 的地址、超时与连接独立于普通服务发现；
Token 为空时在默认配置阶段继承 `global.serverConnector.token`，显式配置优先。
默认查询超时 5 秒、ZIP 下载超时 30 秒；请求 timeout 可覆盖，代码单位为毫秒。

查询和下载成功后异步写入版本化备份；version 为空时更新最后看到的 active 指针。
NETWORK_ERROR 且 fallbackToLocalCache=true 时读取相同命名空间、名称、版本和格式的备份。
不限制备份文件年龄；业务错误不会触发降级；列表查询不持久化也不降级。
`loaded_from_file=True` 标识本地结果。
持久化沿用原子替换、FIFO 写队列、文件锁和读写重试，额外重试次数不包含首次操作。
销毁 context 会排空已接受写入并关闭线程、锁和独立 gRPC 通道。
备份目录初始化失败只告警并继续远端读取，此时禁用本地持久化和降级。
同一目录有意共享备份；不同注册中心应显式使用不同 persistDir。

SkillAPI(context) 借用 context，destroy 只关闭该 API；工厂创建的 API 负责关闭其 context。
`resolve_mounted_skill_request()` 从 Service 快照解析挂载 Skill，版本优先级为：
挂载记录 version、调用方 requested_version、留空取服务端 active。
`get_mounted_skill()` / `download_mounted_skill()` 及 `async_` 变体直接完成解析和读取；
一个服务挂载多个 Skill 时必须指定 `skill_name`。
Skill 写接口和框架适配不在当前接口中。

## 验证

```bash
./examples/verify.sh --only mcp,skill,a2a,monitoring
./examples/verify_e2e.sh --only mcp
./examples/verify_e2e.sh --only skill
```

离线验证不连接外部服务。真实验证需要环境变量，具体要求见
[MCP 示例](../examples/mcp/README-zh.md) 和 [Skill 示例](../examples/skill/README-zh.md)。
