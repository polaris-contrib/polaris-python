# TLS 连接

普通注册发现连接和 Skill 连接各自支持 TLS，可通过 YAML 或代码配置。
未配置任何证书文件时使用明文；配置后只使用安全通道，不静默降级。

```yaml
global:
  serverConnector:
    addresses: [registry.example.com:8091]
    trustedCAFile: /path/to/ca.pem
    certFile: /path/to/client.pem
    keyFile: /path/to/client-key.pem
ai:
  skill:
    serverConnector:
      addresses: [skill.example.com:8094]
      trustedCAFile: /path/to/skill-ca.pem
      certFile: /path/to/skill-client.pem
      keyFile: /path/to/skill-client-key.pem
```

trustedCAFile 为信任根 PEM 文件；仅配置它时验证服务端证书。
certFile 与 keyFile 必须成对，用于客户端证书 / mTLS；不配置 CA 时使用系统信任根。
SDK 初始化读取并解析证书，缺失文件、无效 PEM、私钥不匹配或不完整配置直接报 SDKError。
证书链验证、主机名与有效期由安全通道握手执行，握手失败只按网络错误重试安全通道。
不提供关闭证书验证或回退明文的选项。

```python
from polaris import Configuration

config = Configuration()
config.set_default()
transport = config.get_global().get_server_connector()
transport.addresses = ["registry.example.com:8091"]
transport.trusted_ca_file = "/path/to/ca.pem"
transport.cert_file = "/path/to/client.pem"
transport.key_file = "/path/to/client-key.pem"
skill_transport = config.get_ai().get_skill().get_server_connector()
skill_transport.trusted_ca_file = "/path/to/skill-ca.pem"
```

路径按启动进程的当前目录解析，支持绝对路径。证书在创建 context 时读取一次；
更新文件不会热更新已有通道，需要创建新 context。
Skill 不继承普通连接的 CA、证书或地址；Token 为空时按 Java 行为继承
`global.serverConnector.token`。分别配置才能分别启用 TLS / mTLS。
证书路径没有专用 SDK 环境变量，可用 YAML 的 `${APP_CA_FILE}` 等占位符。
日志配置与证书配置相互独立。AK-SK 和证书自动轮换不在当前范围。
