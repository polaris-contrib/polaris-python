# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
#
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

from pathlib import Path

import pytest


from polaris.pkg.config.api import (
    APIConfig,
    CircuitBreakerConfig,
    ClusterType,
    Configuration,
    GlobalConfig,
    ProviderConfig,
    ServerClusterConfig,
    ServerConnectorConfig,
    SystemConfig,
    get_server_services,
)
from polaris.pkg.config.loader import (
    build_configuration,
    find_default_config_file,
    load_config_file,
    parse_config_stream,
)
from polaris.pkg.model.error import ErrorCode, SDKError
from polaris.pkg.model import util


@pytest.mark.parametrize("field", ["persist_max_write_retry", "persist_max_read_retry", "persist_retry_interval"])
@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_local_cache_rejects_invalid_disk_retry_config(field, value):
    config = Configuration()
    config.set_default()
    setattr(config.get_consumer().get_local_cache(), field, value)
    with pytest.raises(SDKError, match=field):
        config.verify()


def test_default_connector_uses_grpc() -> None:
    config = Configuration()
    config.set_default()

    assert config.get_global().get_server_connector().get_protocol() == "grpc"
    assert config.get_global().get_server_connector().get_addresses() == ["127.0.0.1:8091"]


@pytest.mark.parametrize("value", [None, 0, 30000])
def test_provider_min_register_interval_uses_go_default(value):
    config = Configuration(provider_config=ProviderConfig(value))
    config.set_default()
    config.verify()
    assert config.get_provider().get_min_register_interval() == 30000


def test_provider_min_register_interval_supports_yaml_and_code():
    config = Configuration.from_dict({"provider": {"minRegisterInterval": "45s"}}, apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_provider().get_min_register_interval() == 45000
    config.get_provider().min_register_interval = 1000
    config.verify()
    assert config.get_provider().get_min_register_interval() == 1000


@pytest.mark.parametrize("value", [-1, True, False, "30s", 1.5, 0.0])
def test_provider_min_register_interval_rejects_invalid_code_values(value):
    config = Configuration(provider_config=ProviderConfig(value))
    config.set_default()
    with pytest.raises(SDKError):
        config.verify()


def test_explicit_server_addresses_and_token_are_preserved() -> None:
    connector = ServerConnectorConfig(addresses=["10.0.0.1:8091"], token="secret")
    config = Configuration(global_config=GlobalConfig(server_connector=connector))
    config.set_default()

    assert connector.get_addresses() == ["10.0.0.1:8091"]
    assert connector.get_token() == "secret"


@pytest.mark.parametrize("data", [
    {"namespace": "default"},
    {"global": {"system": {"logPath": "./polaris.log"}}},
    {"global": {"system": {"logLevel": "warn"}}},
    {"global": {"system": {"log_path": "./polaris.log"}}},
    {"global": {"system": {"log_level": "warn"}}},
    {"global": {"statReporter": {"addresses": ["127.0.0.1:9091"]}}},
    {"global": {"api": {"bindIPValue": "127.0.0.1"}}},
    {"global": {"api": {"bind_ip_value": "127.0.0.1"}}},
])
def test_configuration_rejects_nonstandard_or_derived_fields(data):
    with pytest.raises(SDKError, match="Unknown configuration keys"):
        Configuration.from_dict(data, apply_env=False)


def test_environment_does_not_add_removed_sdk_fields(monkeypatch):
    monkeypatch.setenv("POLARIS_STAT_REPORTER_ADDRESSES", "127.0.0.1:9091")
    monkeypatch.setenv("POLARIS_NAMESPACE", "env-namespace")
    monkeypatch.setenv("POLARIS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("POLARIS_LOG_PATH", "./env.log")
    config = Configuration.from_env()
    config.set_default()
    config.verify()
    assert not hasattr(config, "namespace")
    assert not hasattr(config.get_global().get_system(), "log_level")
    assert not hasattr(config.get_global().get_system(), "log_path")
    assert not hasattr(config.get_global().get_stat_reporter(), "addresses")


def test_load_yaml_configuration_with_camel_case_keys(tmp_path) -> None:
    path = tmp_path / "polaris.yaml"
    path.write_text(
        """
global:
  serverConnector:
    addresses: [10.0.0.1:8091]
    token: secret
    connectTimeout: 1000ms
    messageTimeout: 7s
  api:
    bindIP: 127.0.0.1
  statReporter:
    enable: true
consumer:
  localCache:
    serviceRefreshInterval: 5s
    persistDir: ./cache
  loadbalancer:
    type: random
        """,
        encoding="utf-8",
    )

    config = Configuration.from_file(str(path), apply_env=False)
    config.set_default()
    config.verify()

    connector = config.get_global().get_server_connector()
    assert connector.get_addresses() == ["10.0.0.1:8091"]
    assert connector.get_token() == "secret"
    assert connector.get_connect_timeout() == 1000
    assert connector.get_message_timeout() == 7000
    assert config.get_global().get_stat_reporter().is_enable() is True
    assert config.get_consumer().get_local_cache().get_service_refresh_interval() == 5000
    assert config.get_consumer().get_load_balancer().get_type() == "random"


def test_load_go_provider_yaml_environment_placeholders(tmp_path, monkeypatch) -> None:
    path = tmp_path / "polaris.yaml"
    path.write_text(
        """
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER}:8091
    token: ${POLARIS_TOKEN}
    connectTimeout: 1000ms
        """,
        encoding="utf-8",
    )

    monkeypatch.setenv("POLARIS_SERVER", "10.0.0.2")
    monkeypatch.setenv("POLARIS_TOKEN", "token:with#yaml\ncharacters")
    monkeypatch.delenv("POLARIS_SERVER_ADDRESSES", raising=False)
    monkeypatch.delenv("POLARIS_SERVER_ADDRESS", raising=False)
    config = Configuration.from_file(str(path))
    config.set_default()

    assert config.get_global().get_server_connector().get_addresses() == ["10.0.0.2:8091"]
    assert config.get_global().get_server_connector().get_token() == "token:with#yaml\ncharacters"
    assert config.get_global().get_server_connector().get_connect_timeout() == 1000


@pytest.mark.parametrize(
    ("environment_value", "expected_address"),
    [
        (None, "127.0.0.1:8091"),
        ("", "127.0.0.1:8091"),
        ("10.0.0.2:8092", "10.0.0.2:8092"),
    ],
)
def test_yaml_placeholders_use_default_when_environment_is_empty(
    tmp_path, monkeypatch, environment_value, expected_address,
) -> None:
    path = tmp_path / "polaris.yaml"
    path.write_text(
        """
global:
  serverConnector:
    addresses:
      - ${POLARIS_SERVER_ADDRESS:127.0.0.1:8091}
    protocol: ${POLARIS_PROTOCOL:grpc}
    plugin:
      custom:
        mode: ${APP_MODE:development}
        endpoints:
          - ${APP_ENDPOINT:127.0.0.1:9091}
        """,
        encoding="utf-8",
    )

    if environment_value is None:
        monkeypatch.delenv("POLARIS_SERVER_ADDRESS", raising=False)
    else:
        monkeypatch.setenv("POLARIS_SERVER_ADDRESS", environment_value)
    monkeypatch.setenv("POLARIS_PROTOCOL", "")
    monkeypatch.setenv("APP_MODE", "")
    monkeypatch.setenv("APP_ENDPOINT", "")
    monkeypatch.delenv("POLARIS_SERVER_ADDRESSES", raising=False)
    monkeypatch.delenv("POLARIS_SERVER", raising=False)

    config = Configuration.from_file(str(path))
    config.set_default()
    config.verify()

    connector = config.get_global().get_server_connector()
    assert connector.get_addresses() == [expected_address]
    assert connector.get_protocol() == "grpc"
    assert connector.plugin == {
        "custom": {
            "mode": "development",
            "endpoints": ["127.0.0.1:9091"],
        }
    }


def test_environment_overrides_file_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("POLARIS_SERVER_ADDRESSES", raising=False)
    monkeypatch.delenv("POLARIS_SERVER_ADDRESS", raising=False)
    path = tmp_path / "polaris.yaml"
    path.write_text(
        """
global:
  serverConnector:
    addresses: [10.0.0.1:8091]
    token: file-token
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("POLARIS_SERVER", "10.0.0.2:8091,10.0.0.3:8091")
    monkeypatch.setenv("POLARIS_TOKEN", "env-token")
    monkeypatch.setenv("POLARIS_TIMEOUT", "3000")
    monkeypatch.setenv("POLARIS_MAX_RETRY_TIMES", "2")
    monkeypatch.setenv("POLARIS_CACHE_PERSIST_DIR", "./env-cache")
    monkeypatch.setenv("POLARIS_STAT_REPORTER_ENABLE", "false")

    config = Configuration.from_file(str(path))
    config.set_default()

    connector = config.get_global().get_server_connector()
    assert connector.get_addresses() == ["10.0.0.2:8091", "10.0.0.3:8091"]
    assert connector.get_token() == "env-token"
    assert config.get_global().get_api().get_timeout() == 3000
    assert config.get_global().get_api().get_max_retry_times() == 2
    assert config.get_consumer().get_local_cache().get_persist_dir() == "./env-cache"
    assert config.get_global().get_stat_reporter().is_enable() is False


@pytest.mark.parametrize(
    "global_key,connector_key,system_key,consumer_key,cache_key,refresh_key,message_key",
    [
        ("global", "serverConnector", "system", "consumer", "localCache", "serviceRefreshInterval", "messageTimeout"),
        ("global_config", "server_connector", "system_conf", "consumer_config", "local_cache", "service_refresh_interval", "message_timeout"),
        ("global", "server-connector", "system", "consumer", "local-cache", "service-refresh-interval", "message-timeout"),
    ],
    ids=["camel-case", "snake-case", "kebab-case"],
)
def test_environment_overrides_preserve_other_section_values(
    global_key, connector_key, system_key, consumer_key, cache_key, refresh_key, message_key,
) -> None:
    plugin = {"customPlugin": {"caseSensitiveKey": "unchanged"}}
    config = build_configuration(
        {
            global_key: {
                connector_key: {
                    "addresses": ["127.0.0.1:8091"],
                    "token": "file-token",
                    message_key: 7000,
                    "plugin": plugin,
                },
                system_key: {"mode": 0},
            },
            consumer_key: {
                cache_key: {"persist-dir": "./file-cache", refresh_key: 5000},
            },
        },
        environ={
            "POLARIS_SERVER": "127.0.0.1:8092",
            "POLARIS_SERVICE_REFRESH_INTERVAL": "3000",
        },
    )
    config.set_default()

    connector = config.get_global().get_server_connector()
    assert connector.get_addresses() == ["127.0.0.1:8092"]
    assert connector.get_token() == "file-token"
    assert connector.get_message_timeout() == 7000
    assert connector.plugin == plugin
    assert config.get_global().get_system().mode == 0
    cache = config.get_consumer().get_local_cache()
    assert cache.get_service_refresh_interval() == 3000
    assert cache.get_persist_dir() == "./file-cache"


def test_unknown_configuration_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "polaris.yaml"
    path.write_text("global:\n  serverConnector:\n    address: [127.0.0.1:8091]\n", encoding="utf-8")

    try:
        Configuration.from_file(str(path), apply_env=False)
    except SDKError as exc:
        assert exc.err_code == ErrorCode.ErrCodeAPIInvalidConfig
        assert "address" in exc.msg
    else:
        raise AssertionError("expected SDKError")


def test_find_default_config_file_prefers_environment_path(tmp_path, monkeypatch) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("POLARIS_CONFIG_FILE", str(path))

    assert find_default_config_file() == path
    assert load_config_file(path) == {}


def test_explicit_default_config_file_must_exist(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("POLARIS_CONFIG_FILE", str(missing))

    assert find_default_config_file() == missing


def test_parse_config_stream_rejects_invalid_document() -> None:
    with pytest.raises(SDKError) as raised:
        parse_config_stream("global: [invalid")
    assert raised.value.err_code == ErrorCode.ErrCodeAPIInvalidConfig


@pytest.mark.parametrize(
    "value,expected",
    [(1000, 1000), ("1000ms", 1000), ("1s", 1000), ("1.5s", 1500), ("1m30s", 90000)],
)
def test_yaml_durations_convert_to_integer_milliseconds(value, expected) -> None:
    config = Configuration.from_dict({"global": {"api": {"timeout": value}}}, apply_env=False)
    assert config.get_global().get_api().get_timeout() == expected


@pytest.mark.parametrize("value", ["", "+", "--1s", "10seconds", "0.5ms", True])
def test_invalid_duration_is_rejected(value) -> None:
    with pytest.raises(SDKError) as raised:
        Configuration.from_dict({"global": {"api": {"timeout": value}}}, apply_env=False)
    assert raised.value.err_code == ErrorCode.ErrCodeAPIInvalidConfig


@pytest.mark.parametrize("suffix", ["json", "toml", "yml"])
def test_only_yaml_file_extension_is_supported(tmp_path, suffix) -> None:
    path = tmp_path / f"polaris.{suffix}"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(SDKError, match="Only .yaml"):
        Configuration.from_file(str(path), apply_env=False)


@pytest.mark.parametrize("document", ["- item", "global: [invalid", "!!python/object:builtins.object {}", b"\xff"])
def test_invalid_yaml_returns_sdk_error(document) -> None:
    with pytest.raises(SDKError) as raised:
        parse_config_stream(document)
    assert raised.value.err_code == ErrorCode.ErrCodeAPIInvalidConfig


def test_non_mapping_configuration_section_is_rejected() -> None:
    with pytest.raises(SDKError) as raised:
        Configuration.from_dict({"global": {"serverConnector": "invalid"}}, apply_env=False)
    assert raised.value.err_code == ErrorCode.ErrCodeAPIInvalidConfig


def test_code_configuration_does_not_read_files_or_apply_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("POLARIS_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLARIS_SERVER", "env-server:8091")
    config = Configuration()
    config.set_default()
    config.get_global().get_server_connector().addresses = ["code-server:8091"]
    config.get_global().get_server_connector().token = "code-token"
    config.get_global().get_api().bind_ip = "127.0.0.1"
    config.get_global().get_api().timeout = 5000
    config.get_consumer().get_local_cache().service_refresh_interval = 3000
    config.set_default()
    config.verify()

    assert config.get_global().get_server_connector().get_addresses() == ["code-server:8091"]
    assert config.get_global().get_server_connector().get_token() == "code-token"
    assert config.get_global().get_api().get_timeout() == 5000
    assert config.get_consumer().get_local_cache().get_service_refresh_interval() == 3000


def test_defaults_match_java_configuration() -> None:
    config = Configuration()
    config.set_default()
    config.verify()
    global_config = config.get_global()
    system = global_config.get_system()
    assert system.mode == 0
    assert vars(system.get_discover_cluster()) == {"namespace": "", "service": "", "refresh_interval": 60000}
    assert vars(system.get_health_check_cluster()) == {"namespace": "", "service": "", "refresh_interval": 60000}
    assert vars(system.get_monitor_cluster()) == {
        "namespace": "", "service": "", "refresh_interval": 60000,
    }
    assert vars(global_config.get_api()) == {
        "timeout": 1000, "bind_intf": "", "bind_ip": "", "bind_ip_value": "",
        "report_interval": 60000, "max_retry_times": 1, "retry_interval": 500,
    }
    assert vars(global_config.get_server_connector()) == {
        "addresses": ["127.0.0.1:8091"], "protocol": "grpc", "token": "", "connect_timeout": 500,
        "message_time": 5000, "connection_idle_timeout": 60000, "request_queue_size": 1000,
        "server_switch_interval": 600000, "plugin": {},
        "trusted_ca_file": "", "cert_file": "", "key_file": "",
    }
    assert vars(global_config.get_stat_reporter()) == {
        "enable": True, "chain": ["prometheus"],
        "plugin": {"prometheus": global_config.get_stat_reporter().get_prometheus()},
    }

    consumer = config.get_consumer()
    assert vars(consumer.get_local_cache()) == {
        "type": "inmemory", "service_expire_time": 86400000, "service_refresh_interval": 2000,
        "persist_dir": "./polaris/backup", "persist_max_write_retry": 1, "persist_max_read_retry": 0,
        "persist_retry_interval": 500, "plugin": {},
    }
    assert vars(consumer.get_service_router()) == {
        "before_chain": ["isolatedRouter"], "chain": ["metadataRouter"],
        "after_chain": ["recoverRouter"], "percent_of_min_instances": 0.0, "plugin": {},
    }
    assert vars(consumer.get_load_balancer()) == {"type": "weightedRandom", "plugin": {}}
    assert vars(consumer.get_circuit_breaker()) == {
        "enable": True, "check_period": 60000, "chain": ["composite"], "plugin": {},
        "sleep_window": 30000, "success_count_after_half_open": 3, "default_rule_enable": True,
        "default_error_count": 10, "default_error_percent": 50, "default_interval": 60000,
        "default_minimum_request": 10,
    }
    assert get_server_services(config) == {}


def test_skill_token_inherits_from_global_when_empty(monkeypatch):
    config = Configuration.from_dict({"global": {"serverConnector": {"token": "global-token"}}},
                                     apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_ai().get_skill().get_server_connector().token == "global-token"

    explicit = Configuration.from_dict({
        "global": {"serverConnector": {"token": "global-token"}},
        "ai": {"skill": {"serverConnector": {"token": "skill-token"}}},
    }, apply_env=False)
    explicit.set_default()
    assert explicit.get_ai().get_skill().get_server_connector().token == "skill-token"

    monkeypatch.setenv("POLARIS_TOKEN", "environment-token")
    environment = Configuration.from_dict({})
    environment.set_default()
    assert environment.get_ai().get_skill().get_server_connector().token == "environment-token"


def test_service_router_chain_defaults_to_metadata_router():
    omitted = Configuration.from_dict({"consumer": {"serviceRouter": {}}}, apply_env=False)
    omitted.set_default()
    assert omitted.get_consumer().get_service_router().get_chain() == ["metadataRouter"]

    specified = Configuration.from_dict(
        {"consumer": {"serviceRouter": {"chain": ["metadataRouter"]}}}, apply_env=False)
    specified.set_default()
    assert specified.get_consumer().get_service_router().get_chain() == ["metadataRouter"]


def test_bind_ip_takes_priority_over_invalid_interface(monkeypatch):
    def resolve(name):
        raise AssertionError("explicit bindIP must skip interface lookup")

    monkeypatch.setattr(util, "get_ip", resolve)
    api = APIConfig(bind_ip="192.0.2.1", bind_intf="missing")
    api.set_default()
    api.verify()
    assert api.get_bind_ip() == "192.0.2.1"


def test_bind_if_resolves_sdk_address_without_changing_explicit_field(monkeypatch):
    names = []

    def resolve(name):
        names.append(name)
        return "192.0.2.2"

    monkeypatch.setattr(util, "get_ip", resolve)
    config = Configuration.from_dict({"global": {"api": {"bindIf": "test0"}}}, apply_env=False)
    config.set_default()
    config.verify()
    assert names == ["test0"]
    assert config.get_global().get_api().get_bind_ip() == "192.0.2.2"
    assert config.get_global().get_api().bind_ip == ""


def test_bind_if_lookup_failure_is_configuration_error(monkeypatch):
    def resolve(name):
        raise OSError("no interface")

    monkeypatch.setattr(util, "get_ip", resolve)
    config = Configuration(global_config=GlobalConfig(api_conf=APIConfig(bind_intf="missing")))
    config.set_default()
    with pytest.raises(SDKError, match="provided bind interface missing"):
        config.verify()


def test_verify_clears_stale_derived_sdk_ip():
    api = APIConfig(bind_ip="192.0.2.1")
    api.set_default()
    api.verify()
    api.bind_ip = ""
    api.verify()
    assert api.get_bind_ip() == ""


@pytest.mark.parametrize("field,value", [("bind_ip", None), ("bind_ip", 1), ("bind_intf", False)])
def test_sdk_address_fields_reject_non_string_code_values(field, value):
    api = APIConfig(**{field: value})
    api.set_default()
    with pytest.raises(SDKError, match="must be strings"):
        api.verify()


@pytest.mark.parametrize(
    "cluster_key,refresh_key",
    [("discoverCluster", "refreshInterval"), ("discover_cluster", "refresh_interval"),
     ("discover-cluster", "refresh-interval")],
)
def test_system_clusters_use_java_go_hierarchy(cluster_key, refresh_key) -> None:
    config = build_configuration(
        {"global": {"system": {cluster_key: {
            "namespace": "custom", "service": "discovery", refresh_key: "10m",
        }}}},
        environ={"POLARIS_SERVER": "10.0.0.1:8091"},
    )
    config.set_default()
    config.verify()
    system = config.get_global().get_system()
    assert vars(system.get_discover_cluster()) == {
        "namespace": "custom", "service": "discovery", "refresh_interval": 600000,
    }
    assert system.get_health_check_cluster().get_namespace() == ""
    assert system.get_monitor_cluster().get_service() == ""
    assert not hasattr(system, "server_clusters")


def test_system_clusters_can_be_assigned_directly_in_code() -> None:
    system = SystemConfig(discover_cluster=ServerClusterConfig("custom", "discover", 2000))
    config = Configuration(global_config=GlobalConfig(system_conf=system))
    config.set_default()
    system.health_check_cluster = ServerClusterConfig("custom", "health", 3000)
    system.get_monitor_cluster().namespace = "custom"
    config.set_default()
    config.verify()
    clusters = get_server_services(config)
    assert set(clusters) == {ClusterType.DiscoverCluster, ClusterType.HealthCheckCluster}
    for cluster_type, service in clusters.items():
        assert service.cluster_type == cluster_type
        assert service.service_key.get_namespace() == "custom"
    assert system.get_discover_cluster().get_refresh_interval() == 2000
    assert system.get_health_check_cluster().get_refresh_interval() == 3000


def test_partial_monitor_cluster_defaults_to_empty_identity() -> None:
    config = Configuration.from_dict({"global": {"system": {
        "monitorCluster": {"refreshInterval": "10m"},
    }}}, apply_env=False)
    config.set_default()
    assert vars(config.get_global().get_system().get_monitor_cluster()) == {
        "namespace": "", "service": "", "refresh_interval": 600000,
    }


def test_explicit_empty_monitor_service_is_preserved() -> None:
    config = Configuration.from_dict({"global": {"system": {
        "monitorCluster": {"service": ""},
    }}}, apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_global().get_system().get_monitor_cluster().get_service() == ""
    assert get_server_services(config) == {}


def test_old_server_clusters_wrapper_is_rejected() -> None:
    with pytest.raises(SDKError, match="server_clusters"):
        Configuration.from_dict({"global": {"system": {"serverClusters": {}}}}, apply_env=False)


@pytest.mark.parametrize(
    "section",
    [
        {"global": {"system": {"discoverCluster": {"refreshInterval": 0}}}},
        {"global": {"api": {"retryInterval": 0}}},
        {"global": {"serverConnector": {"connectionIdleTimeout": 0}}},
        {"consumer": {"localCache": {"serviceExpireTime": 0}}},
        {"consumer": {"circuitBreaker": {"checkPeriod": 0}}},
    ],
)
def test_explicit_invalid_zero_duration_is_not_replaced_with_default(section) -> None:
    config = Configuration.from_dict(section, apply_env=False)
    config.set_default()
    with pytest.raises(SDKError):
        config.verify()


def test_go_zero_value_defaults_and_explicit_queue_size() -> None:
    config = Configuration.from_dict({
        "global": {"api": {"maxRetryTimes": 0}, "serverConnector": {"requestQueueSize": 0}},
        "consumer": {"localCache": {"persistMaxReadRetry": 0, "persistMaxWriteRetry": 0}},
    }, apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_global().get_api().get_max_retry_times() == 1
    assert config.get_global().get_server_connector().get_request_queue_size() == 0
    assert config.get_consumer().get_local_cache().get_persist_max_read_retry() == 0
    assert config.get_consumer().get_local_cache().get_persist_max_write_retry() == 1


def test_circuit_breaker_minimum_period_is_not_its_default() -> None:
    config = Configuration.from_dict({"consumer": {"circuitBreaker": {"checkPeriod": "1s"}}}, apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_consumer().get_circuit_breaker().get_check_period() == 1000


def test_local_circuit_rule_fields_load_from_yaml_file(tmp_path):
    path = tmp_path / "polaris.yaml"
    path.write_text("""consumer:
  circuitBreaker:
    sleepWindow: 1500ms
    successCountAfterHalfOpen: 2
    defaultRuleEnable: false
    defaultErrorCount: 4
    defaultErrorPercent: 25
    defaultInterval: 2.5s
    defaultMinimumRequest: 8
""", encoding="utf-8")
    cfg = Configuration.from_file(path, apply_env=False)
    cfg.set_default()
    cfg.verify()
    cb = cfg.get_consumer().get_circuit_breaker()
    assert cb.get_sleep_window() == 1500
    assert cb.get_success_count_after_half_open() == 2
    assert cb.is_default_rule_enable() is False
    assert cb.get_default_error_count() == 4
    assert cb.get_default_error_percent() == 25
    assert cb.get_default_interval() == 2500
    assert cb.get_default_minimum_request() == 8


def test_local_circuit_rule_supports_constructor_and_code_assignment():
    cb = CircuitBreakerConfig(sleep_window=1000, success_count_after_half_open=1,
                              default_rule_enable=False, default_error_count=2, default_error_percent=0,
                              default_interval=1, default_minimum_request=1)
    cfg = Configuration()
    cfg.set_default()
    cfg.get_consumer().circuit_breaker = cb
    cfg.set_default()
    cfg.verify()
    assert cb.get_sleep_window() == 1000
    assert cb.get_success_count_after_half_open() == 1
    assert cb.is_default_rule_enable() is False
    assert cb.get_default_error_count() == 2
    assert cb.get_default_error_percent() == 0
    assert cb.get_default_interval() == 1
    assert cb.get_default_minimum_request() == 1
    cb.sleep_window = 45000
    cb.success_count_after_half_open = 5
    cb.default_rule_enable = True
    cb.default_error_count = 20
    cb.default_error_percent = 100
    cb.default_interval = 90000
    cb.default_minimum_request = 30
    cfg.verify()
    assert cb.get_sleep_window() == 45000
    assert cb.get_success_count_after_half_open() == 5
    assert cb.is_default_rule_enable() is True
    assert cb.get_default_error_count() == 20
    assert cb.get_default_error_percent() == 100
    assert cb.get_default_interval() == 90000
    assert cb.get_default_minimum_request() == 30


def test_local_circuit_rule_snake_case_yaml_and_millisecond_values():
    cfg = Configuration.from_dict({"consumer": {"circuit_breaker": {
        "sleep_window": 1000, "success_count_after_half_open": 0, "default_rule_enable": False,
        "default_error_count": 1, "default_error_percent": 0, "default_interval": 1,
        "default_minimum_request": 1,
    }}}, apply_env=False)
    cfg.set_default()
    cfg.verify()
    cb = cfg.get_consumer().get_circuit_breaker()
    assert cb.get_success_count_after_half_open() == 3
    assert cb.get_default_interval() == 1
    assert cb.get_default_error_percent() == 0
    assert cb.is_default_rule_enable() is False


@pytest.mark.parametrize("field, value", [
    ("sleep_window", 0), ("sleep_window", 999), ("sleep_window", -1),
    ("success_count_after_half_open", -1),
    ("default_error_count", 0), ("default_error_count", -1),
    ("default_error_percent", -1), ("default_error_percent", 101),
    ("default_interval", 0), ("default_interval", -1),
    ("default_minimum_request", 0), ("default_minimum_request", -1),
])
def test_local_circuit_rule_rejects_out_of_range_values(field, value):
    cfg = Configuration.from_dict({"consumer": {"circuitBreaker": {field: value}}}, apply_env=False)
    cfg.set_default()
    with pytest.raises(SDKError, match=field):
        cfg.verify()


@pytest.mark.parametrize("field", ["sleep_window", "success_count_after_half_open", "default_error_count",
                                  "default_error_percent", "default_interval", "default_minimum_request"])
@pytest.mark.parametrize("value", [True, False, 1.5, "1000", [], {}])
def test_local_circuit_rule_rejects_non_integer_code_values(field, value):
    cfg = Configuration()
    cfg.set_default()
    setattr(cfg.get_consumer().get_circuit_breaker(), field, value)
    cfg.set_default()
    with pytest.raises(SDKError, match=field):
        cfg.verify()


@pytest.mark.parametrize("value", [0, 1, "false", 1.5, [], {}])
def test_local_circuit_rule_requires_boolean_switch(value):
    cfg = Configuration.from_dict({"consumer": {"circuitBreaker": {"defaultRuleEnable": value}}}, apply_env=False)
    cfg.set_default()
    with pytest.raises(SDKError, match="default_rule_enable"):
        cfg.verify()


@pytest.mark.parametrize("field", ["sleepWindow", "defaultInterval"])
@pytest.mark.parametrize("value", [True, 1.5, "bad", "0.1ms"])
def test_local_circuit_rule_rejects_invalid_yaml_duration(field, value):
    with pytest.raises(SDKError):
        Configuration.from_dict({"consumer": {"circuitBreaker": {field: value}}}, apply_env=False)


def test_legacy_plugin_names_normalize_to_java_go_names() -> None:
    config = Configuration.from_dict({"consumer": {
        "loadbalancer": {"type": "wr"}, "circuitBreaker": {"chain": ["err_count"]},
    }}, apply_env=False)
    config.set_default()
    assert config.get_consumer().get_load_balancer().get_type() == "weightedRandom"
    assert config.get_consumer().get_circuit_breaker().get_chain() == ["composite"]


def test_minimal_configuration_reference_loads_with_defaults() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "config" / "polaris.yaml"
    config = Configuration.from_file(str(path), apply_env=False)
    config.set_default()
    config.verify()
    assert config.get_global().get_server_connector().get_addresses() == ["127.0.0.1:8091"]
    assert config.get_global().get_system().get_discover_cluster().get_refresh_interval() == 60000
    assert config.get_consumer().get_load_balancer().get_type() == "weightedRandom"


def test_minimal_configuration_reference_only_contains_required_address() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "config" / "polaris.yaml"
    document = load_config_file(path)
    assert document == {"global": {"serverConnector": {"addresses": ["127.0.0.1:8091"]}}}
