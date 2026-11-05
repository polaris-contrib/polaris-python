# TLS

普通注册发现连接和 Skill 连接分别支持 TLS / mTLS。
未配置证书时使用明文；配置错误时拒绝启动，不回退明文。

## YAML

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

## 字段

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `trustedCAFile` | string | 信任根 PEM；为空时使用系统信任根 |
| `certFile` | string | 客户端证书，用于 mTLS |
| `keyFile` | string | 客户端私钥 |

`certFile` 和 `keyFile` 必须同时配置或同时为空。
Skill 和主注册中心不继承彼此的地址、证书或私钥。

## 代码配置

```python
config = Configuration()
config.set_default()

connector = config.get_global().get_server_connector()
connector.trusted_ca_file = "/path/to/ca.pem"
connector.cert_file = "/path/to/client.pem"
connector.key_file = "/path/to/client-key.pem"
```

代码字段使用 snake_case，YAML 使用 camelCase。

## 行为

- 文件缺失、PEM 无效、私钥不匹配或证书不完整会报 `SDKError`。
- 证书在创建 context 时读取一次；更新文件不会热更新已有连接。
- 主机名、有效期和证书链由 gRPC 安全握手校验。
- 网络重试只重试安全连接，不会降级到明文。
- 证书路径可通过 YAML 的 `${APP_CA_FILE}` 等占位符配置。

AK-SK 和证书自动轮换不在当前范围。
