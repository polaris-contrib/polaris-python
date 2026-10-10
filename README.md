# Polaris Python SDK

Polaris Python SDK 是 AI 注册中心的 Python 客户端，供 Python AI 应用完成 Agent、MCP Server 与 Skill 的注册、发现、生命周期管理和治理。

能力范围包含两类：与 Java SDK 已落地能力对齐的存量能力，以及 AI 注册中心规划中的新能力。当前版本 `0.1.0`，第一期已提供基础框架和服务实例注册发现能力，治理插件也已接入本地调用链。

要求 Python 3.12+，使用 [uv](https://docs.astral.sh/uv/) 管理依赖。本地安装：

```bash
uv sync
```

同步接口与 `asyncio` 接口会成对提供，以适配主流 Python AI 框架的异步模型。

## 协议

客户端与注册中心的接口以 [polarismesh/specification](https://github.com/polarismesh/specification) 中的 protobuf 为准，源文件在该仓库的 `api/v1`。Python 桩代码由其中的 `source/python` 生成，本仓库通过依赖 `polarismesh-specification` 使用这些桩，不在本仓库内重复定义协议。

与本 SDK 直接相关的协议包括：

| 目录 | 内容 |
| --- | --- |
| `api/v1/service_manage` | 服务、实例、心跳与发现，Agent / MCP 的注册和探活复用这套接口 |
| `api/v1/model` | 命名空间、公共模型与错误码 |
| `api/v1/security` | 访问注册中心的鉴权 |
| `api/v1/skill_manage` | Skill 资源模型，以及客户端只读服务 `PolarisSkill` |

`PolarisSkill` 当前暴露三个只读接口：

- `GetSkill`：按名称、命名空间获取指定版本；版本为空时返回当前 active 版本，仅 published。
- `GetSkillList`：按命名空间、标签、关键词等查询 published Skill。
- `DownloadSkill`：下载 Skill。`markdown` 一次返回正文，`zip` 按分片流式返回。

## SDK 基础框架

公共基础能力，优先级 P1。

| 能力 | 说明 |
| --- | --- |
| 工程脚手架与发布 | 项目结构、依赖管理、打包发布（PyPI / 内部源）、CI 流水线、版本规范 |
| 配置 | 配置文件、代码、环境变量多种来源，覆盖服务端地址、命名空间、超时等 |
| 服务端通信 | 与注册中心的 gRPC / HTTP 通信、连接管理、超时重试、服务端地址发现与切换 |
| 本地缓存与变更监听 | 服务、Tool、Skill 数据的本地缓存；长轮询或推送变更监听；磁盘持久化容灾 |
| 同步 / 异步双 API | `sync` 与 `asyncio` 两套接口 |
| 鉴权 | 访问注册中心的 Token / AK-SK 鉴权 |
| 日志、异常与错误码 | 统一日志、异常体系与错误码 |
| 测试与文档 | 单元测试、集成测试、使用文档与 Quick Start 示例 |

## Agent 管理

### 存量能力对齐

与 Java SDK 已实现能力对齐，优先级 P1。

- **服务注册 / 反注册**：注册 Agent 服务及元数据（地址、版本、能力声明），退出时反注册。
- **心跳与健康上报**：实例心跳续约，配合服务端探活实现异常下线、恢复上线。
- **发现与实例过滤**：按服务名、命名空间查询 Agent 实例，支持按健康状态、协议、版本等属性过滤。
- **AgentCard**：获取 A2A 格式 AgentCard，包含挂载的 Skill 列表。
- **Skill 挂载加载**：获取 Agent 挂载的 Skill 及绑定版本，并下载加载。
- **命名空间隔离**：按命名空间注册、发现 Agent。
- **AgentScope 集成**：对接 AgentScope，自动完成注册与发现。

### 规划能力

- **注册与服务管理**（P1）：注册时自动生成或更新 AgentCard，并提供标准发现接口；支持流式传输、推送通知、状态历史等输入输出模式配置。
- **语义搜索**（P2）：关键词与语义混合检索，按能力、标签、协议、团队等维度发现 Agent。
- **生命周期**（P1）：Draft → Approve → Publish 审批流的客户端接口与状态感知；废弃 Agent 安全下线，发现时过滤已下线实例；预置客服、代码审查、RAG 等模板，从模板创建 Agent。
- **Skill 挂载灰度**（P1）：Agent 加载 Skill 时按灰度规则选择版本。
- **治理**（P2）：按版本灰度路由；Bearer / API Key 鉴权；访问限流；实例异常自动熔断，恢复后自动接入。
- **可观测**（P1）：采集并上报请求量、成功率、延迟等调用指标。
- **身份与认证**（P2）：
  - 为 Agent 分配独立身份凭证（Agent-as-Principal）。
  - OAuth 2.0 / OIDC，支持 OBO 委派流。
  - 短时效 JWT，内嵌 Agent ID 与用户 ID。
  - RFC 8693 Token 交换，支持多跳委派的链式交换。
  - 多跳调用后保留完整委托链，调用链路可追溯。
  - API Key 签发、轮换、吊销。
  - Agent 间 mTLS 双向证书认证。
  - Federated Identity（FIC）：通过托管身份获取云凭证。
- **访问控制与授权**（P2）：
  - RBAC，按角色控制 Agent、工具、模型的使用权限。
  - 按 scope / tool name 白名单控制可调用的 MCP Tool 与 API。
  - 默认无权限，仅授予最小能力集。
  - 按调用上下文动态调整权限。
  - 敏感操作的人机协同审批（HITL）。
  - 访问策略代码化定义，并纳入版本控制。

## MCP 管理

### 存量能力对齐

与 Java SDK 已实现能力对齐，优先级 P1。

- **注册 / 反注册**：将 Python MCP Server 注册到注册中心，统一纳管服务发现与健康检查。
- **心跳与健康上报**：实例心跳续约，异常下线后恢复接入。
- **发现与端点**：查询 MCP 服务及实例（过滤隔离实例），获取统一访问端点。
- **Tools 查询与变更监听**：获取已启用 Tool 的名称、描述、参数；启用、禁用、编辑后实时感知。
- **版本**：按版本获取 MCP Server 配置。
- **命名空间隔离**：按命名空间注册、发现 MCP 服务。
- **官方 MCP Python SDK 集成**：对接 FastMCP，自动注册与发现。

### 规划能力

- **可观测**（P1）：采集并上报各 Tool 的调用频次与成功率，形成 Top Tool 统计。
- **安全传输**（P2）：
  - mTLS 双向认证，证书到期预警。
  - Tool 定义签名，运行时校验完整性。
  - 长期凭证置换为短期临时令牌。
  - 获取 Tool 安全风险评估结果，并标记高风险 Tool。

## Skill 管理

存量能力对齐，优先级 P1。

- **查询与搜索**：按命名空间、标签、关键词查询在线 Skill。
- **下载与缓存**：下载 ZIP 包并解压，本地缓存与更新。
- **按版本获取**：指定版本拉取 Skill，配合 Agent 关联版本。
- **创建 / 上传**：通过 SDK 创建 Skill，或上传包含 `SKILL.md` 的 ZIP 包。
- **上线 / 下线**：草稿、在线、离线状态管理。
- **业务标签**：按 Tags 筛选 Skill。
- **SkillHub**：市场浏览，以及 Skill 的发布与下架。

## 目录

对齐 polaris-java 的分层，并将路由、负载均衡、限流、熔断等治理能力放在
`plugin/` 中，由 `SDKContext` 统一装配。

```
polaris_python/
  api/          # SDKContext、ProviderAPI、ConsumerAPI、SkillAPI
  core/         # Config、PolarisError
  plugin/       # ServerConnector、LocalRegistry 抽象；实现放 plugin/grpc、plugin/registry
tests/
```

## 第一期 Quick Start

```python
from polaris_python import Config, SDKContext, ServiceInstance
from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.provider import ProviderAPI

config = Config(
    server_addresses=["127.0.0.1:8091"],
    namespace="default",
    token="your-token",
    cache_file="~/.cache/polaris-python/instances.json",
)
context = SDKContext(config)
provider = ProviderAPI(context)
consumer = ConsumerAPI(context)

instance = ServiceInstance(
    service="my-agent",
    host="127.0.0.1",
    port=8080,
    resource_type="agent",
    protocol="http",
    version="v1",
    metadata={"team": "ai"},
)

# Async code: await provider.async_register_instance(instance)
# Sync code:  provider.register_instance(instance)
```

`ConsumerAPI` 提供 `async_get_all_instances`、`async_get_healthy_instances` 和
`async_get_one_instance`，以及对应的同步包装。发现结果会先读本地缓存，再通过
`Discover(INSTANCE)` 长连接异步更新；`isolate=true` 的实例默认不会被返回。

配置也支持 `Config.from_env()`（如 `POLARIS_SERVER_ADDRESSES`、
`POLARIS_NAMESPACE`、`POLARIS_TOKEN`）和 JSON/TOML 文件。

## 治理插件

`SDKContext` 默认装配 metadata 路由、优先级/权重负载均衡、令牌桶/并发限流和
熔断器。规则通过 `Discover` 的 `ROUTING`、`RATE_LIMIT`、`CIRCUIT_BREAKER`
响应更新，也可以通过 `MetadataRouter`、`RateLimiter` 和 `CircuitBreaker`
注入自定义规则。

基础调用只需要使用 `get_one_instance` 或 `async_get_one_instance`，实例选择阶段会
执行健康过滤、路由和负载均衡。若业务需要把真实请求结果反馈给熔断器，可在请求
结束后调用 `update_service_call_result(instance, success=True/False)`；
`before_call` / `after_call` 仅用于需要显式控制本地限流和熔断生命周期的高级场景。

Skill 读接口、FastMCP/AgentScope 适配仍按方案放在后续阶段。
