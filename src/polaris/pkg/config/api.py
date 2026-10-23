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

import ipaddress
from typing import Dict
from typing import List

from polaris.pkg.config.default import DefaultConf
from polaris.pkg.model import util
from polaris.pkg.model.core import ServiceKey
from polaris.pkg.model.error import ErrorCode
from polaris.pkg.model.error import SDKError
from polaris.pkg.model.service import RunMode
from polaris.pkg.config.stat_reporter import AdminConfig, prometheus_config
from polaris.pkg.config.event import pushgateway_event_config


# 默认集群类型
class ClusterType:
    BuiltinCluster = "builtin"
    DiscoverCluster = "discover"
    HealthCheckCluster = "healthCheck"
    MonitorCluster = "monitor"


class SelfVerifier:
    def verify(self):
        pass

    def set_default(self):
        pass


class ClusterService:
    def __init__(self, service_key: ServiceKey, cluster_type: str):
        self.service_key = service_key
        self.cluster_type = cluster_type


# 单个服务集群配置
class ServerClusterConfig:
    def __init__(self, namespace: str | None = None, service: str | None = None,
                 refresh_interval: int | None = None):
        # 	Namespace       string         `yaml:"namespace"`
        # 	Service         string         `yaml:"service"`
        # 	RefreshInterval *time.Duration `yaml:"refreshInterval"`
        self.namespace = namespace
        self.service = service
        self.refresh_interval = refresh_interval

    def get_namespace(self):
        return self.namespace

    def get_service(self):
        return self.service

    def get_refresh_interval(self):
        return self.refresh_interval

    def verify(self):
        if self.refresh_interval is None or self.refresh_interval < DefaultConf.DefaultMinTimingInterval:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServerClusterConfig: refreshInterval can not be empty and must greater than %d" %
                           DefaultConf.DefaultMinTimingInterval)

    def set_default(self):
        if self.namespace is None:
            self.namespace = ""
        if self.service is None:
            self.service = ""
        if self.refresh_interval is None:
            self.refresh_interval = DefaultConf.DefaultServerServiceRefreshInterval


def create_server_cluster_conf(service_key: ServiceKey):
    return ServerClusterConfig(service_key.get_namespace(), service_key.get_service())


# 系统配置
class SystemConfig(SelfVerifier):
    """System options with cluster fields matching the Java and Go SDK configuration."""

    def __init__(self, mode: int = 0, discover_cluster: ServerClusterConfig = None,
                 health_check_cluster: ServerClusterConfig = None, monitor_cluster: ServerClusterConfig = None):
        self.mode = mode
        self.discover_cluster = discover_cluster
        self.health_check_cluster = health_check_cluster
        self.monitor_cluster = monitor_cluster

    def get_mode(self) -> int:
        return self.mode

    def get_discover_cluster(self) -> ServerClusterConfig:
        """Return the discovery server cluster configuration."""
        return self.discover_cluster

    def get_health_check_cluster(self) -> ServerClusterConfig:
        """Return the health-check server cluster configuration."""
        return self.health_check_cluster

    def get_monitor_cluster(self) -> ServerClusterConfig:
        """Return the monitoring server cluster configuration."""
        return self.monitor_cluster

    def verify(self):
        if self.mode != RunMode.ModeNoAgent and self.mode != RunMode.ModeWithAgent:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "SystemConfig: global.system.mode=%d is invalid, you can use no-agent(%d) or with-agent(%d)" % (
                               self.mode, RunMode.ModeNoAgent, RunMode.ModeWithAgent))
        self.discover_cluster.verify()
        self.health_check_cluster.verify()
        self.monitor_cluster.verify()

    def set_default(self):
        if self.discover_cluster is None:
            self.discover_cluster = ServerClusterConfig()
        if self.health_check_cluster is None:
            self.health_check_cluster = ServerClusterConfig()
        if self.monitor_cluster is None:
            self.monitor_cluster = ServerClusterConfig()
        self.discover_cluster.set_default()
        self.health_check_cluster.set_default()
        self.monitor_cluster.set_default()


# API访问相关的配置
class APIConfig(SelfVerifier):
    """Configure API access and the SDK's own address, independently of instance hosts."""

    def __init__(self, timeout: int | None = None, bind_intf: str = "", bind_ip: str = "",
                 report_interval: int | None = None,
                 max_retry_times: int = 0,
                 retry_interval: int | None = None):
        # 	Timeout        *time.Duration `yaml:"timeout"`
        # 	BindIntf       string         `yaml:"bindIf"`
        # 	BindIP         string         `yaml:"bindIP"`
        # 	BindIPValue    string         `yaml:"_"`
        # 	ReportInterval *time.Duration `yaml:"reportInterval"`
        # 	MaxRetryTimes  int            `yaml:"maxRetryTimes"`
        # 	RetryInterval  *time.Duration `yaml:"retryInterval"`
        self.timeout = timeout
        self.bind_intf = bind_intf
        self.bind_ip = bind_ip
        self.bind_ip_value = ""
        self.report_interval = report_interval
        self.max_retry_times = max_retry_times
        self.retry_interval = retry_interval

    def get_timeout(self):
        return self.timeout

    def get_bind_intf(self):
        return self.bind_intf

    def get_bind_ip(self):
        """Return the explicit or startup-resolved SDK address, not an instance host."""
        return self.bind_ip_value

    def get_report_interval(self):
        return self.report_interval

    def get_max_retry_times(self):
        return self.max_retry_times

    def get_retry_interval(self):
        return self.retry_interval

    def verify(self):
        if self.max_retry_times < 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "APIConfig: global.api.maxRetryTimes must be greater than 0")
        if not isinstance(self.bind_ip, str) or not isinstance(self.bind_intf, str):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "APIConfig: global.api.bindIP and bindIf must be strings")
        self.bind_ip_value = self.bind_ip
        if not self.bind_ip and self.bind_intf:
            try:
                self.bind_ip_value = util.get_ip(self.bind_intf)
            except (OSError, ValueError) as error:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "APIConfig: can not get ip from provided bind interface %s" % self.bind_intf) from error
        if self.retry_interval < DefaultConf.DefaultAPIRetryInterval:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "APIConfig: global.api.retryInterval must be greater than %d" %
                           DefaultConf.DefaultAPIRetryInterval)

    def set_default(self):
        if self.timeout is None:
            self.timeout = DefaultConf.DefaultAPIInvokeTimeout
        if self.report_interval is None:
            self.report_interval = DefaultConf.DefaultReportClientIntervalDuration
        if self.retry_interval is None:
            self.retry_interval = DefaultConf.DefaultAPIRetryInterval
        if not self.max_retry_times:
            self.max_retry_times = DefaultConf.DefaultAPIMaxRetryTimes
        self.bind_ip_value = self.bind_ip


# global.statReporter
class StatReporterConfig:
    def __init__(self, enable: bool | None = None, chain: List[str] = None, plugin: Dict = None):
        # 	//是否启动上报
        # 	Enable *bool `yaml:"enable"`
        # 	//上报插件链
        # 	Chain []string `yaml:"chain"`
        # 	// 插件相关配置
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        self.enable = enable
        if chain is None:
            self.chain = []
        else:
            self.chain = chain
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    def is_enable(self):
        return bool(self.enable)

    def get_chain(self):
        return self.chain

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("statReporter", plugin_name, self.plugin, value)

    def get_prometheus(self):
        """Return the typed Prometheus options from YAML or code."""
        result = prometheus_config(self.plugin.get("prometheus", {}))
        self.plugin["prometheus"] = result
        return result

    def verify(self):
        if type(self.enable) is not bool or not isinstance(self.chain, list):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Invalid global.statReporter enable/chain")
        if not isinstance(self.plugin, dict):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "statReporter.plugin must be an object")
        if self.enable and (len(self.chain) != 1 or self.chain[0] not in ("prometheus", "pushgateway")):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                           "global.statReporter.chain must be [prometheus] or [pushgateway]")
        if self.enable and self.chain == ["pushgateway"] and self.get_prometheus().type != "push":
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                           "statReporter chain [pushgateway] requires prometheus.type=push")
        self.get_prometheus()


    def set_default(self):
        if self.enable is None:
            self.enable = DefaultConf.DefaultStatReportEnabled
        if len(self.chain) == 0:
            self.chain = [DefaultConf.DefaultStatReporter]
        self.get_prometheus()


class EventReporterConfig:
    """Configure the context-owned event reporter chain."""

    def __init__(self, enable: bool | None = None, chain: List[str] = None, plugin: Dict = None):
        self.enable = enable
        self.chain = [] if chain is None else chain
        self.plugin = {} if plugin is None else plugin

    def is_enable(self):
        return bool(self.enable)

    def get_chain(self):
        return self.chain

    def get_pushgateway(self):
        """Return the typed Pushgateway event options from YAML or code."""
        result = pushgateway_event_config(self.plugin.get("pushgateway", {}))
        self.plugin["pushgateway"] = result
        return result

    def verify(self):
        if type(self.enable) is not bool or not isinstance(self.chain, list):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Invalid global.eventReporter enable/chain")
        if not isinstance(self.plugin, dict):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "eventReporter.plugin must be an object")
        if self.enable and self.chain != ["pushgateway"]:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Only the pushgateway event reporter is supported")
        self.get_pushgateway()

    def set_default(self):
        if self.enable is None:
            self.enable = False
        if len(self.chain) == 0:
            self.chain = ["pushgateway"]
        self.get_pushgateway()


# 本地缓存配置
class LocalCacheConfig:
    def __init__(self, service_expire_time: int | None = None, service_refresh_interval: int | None = None, persist_dir: str = "",
                 type: str = "",
                 persist_max_write_retry: int = 0,
                 persist_max_read_retry: int = 0, persist_retry_interval: int | None = None, plugin: Dict = None):
        # 	// consumer.localCache.service.expireTime,
        # 	// 服务的超时淘汰时间
        # 	ServiceExpireTime *time.Duration `yaml:"serviceExpireTime"`
        # 	// consumer.localCache.service.refreshInterval
        # 	// 服务的定期刷新时间
        # 	ServiceRefreshInterval *time.Duration `yaml:"serviceRefreshInterval"`
        # 	// consumer.localCache.persistDir
        # 	// 本地缓存持久化路径
        # 	PersistDir string `yaml:"persistDir"`
        # 	// consumer.localCache.type
        # 	// 本地缓存类型，默认inmemory，可修改成具体的缓存插件名
        # 	Type string `yaml:"type"`
        # 	// consumer.localCache.persistMaxWriteRetry
        # 	PersistMaxWriteRetry int `yaml:"persistMaxWriteRetry"`
        # 	// consumer.localCache.persistReadRetry
        # 	PersistMaxReadRetry int `yaml:"persistMaxReadRetry"`
        # 	// consumer.localCache.persistRetryInterval
        # 	PersistRetryInterval *time.Duration `yaml:"persistRetryInterval"`
        # 	// 插件相关配置
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        self.service_expire_time = service_expire_time
        self.service_refresh_interval = service_refresh_interval
        self.persist_dir = persist_dir
        self.type = type
        self.persist_max_write_retry = persist_max_write_retry
        self.persist_max_read_retry = persist_max_read_retry
        self.persist_retry_interval = persist_retry_interval
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    # GetServiceExpireTime consumer.localCache.service.expireTime,
    # 服务的超时淘汰时间
    def get_service_expire_time(self):
        return self.service_expire_time

    # GetServiceRefreshInterval consumer.localCache.service.refreshInterval
    # 服务的定期刷新时间
    def get_service_refresh_interval(self):
        return self.service_refresh_interval

    # GetPersistPath consumer.localCache.persist.path
    # 本地缓存持久化路径
    def get_persist_dir(self):
        return self.persist_dir

    def get_type(self):
        return self.type

    def get_persist_max_write_retry(self):
        return self.persist_max_write_retry

    def get_persist_max_read_retry(self):
        return self.persist_max_read_retry

    def get_persist_retry_interval(self):
        """Return the delay between disk retries in milliseconds."""
        return self.persist_retry_interval

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("localCache", plugin_name, self.plugin, value)

    def verify(self):
        if self.service_expire_time < DefaultConf.DefaultMinServiceExpireTime:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "LocalCacheConfig: consumer.localCache.serviceExpireTime %d is less than the minimal "
                           "allowed duration %d" % (self.service_expire_time, DefaultConf.DefaultMinServiceExpireTime))
        for name in ("persist_max_write_retry", "persist_max_read_retry", "persist_retry_interval"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "LocalCacheConfig: %s must be non-negative integer" % name)

    def set_default(self):
        if self.service_expire_time is None:
            self.service_expire_time = DefaultConf.DefaultServiceExpireTime
        if self.service_refresh_interval is None:
            self.service_refresh_interval = DefaultConf.DefaultServiceRefreshIntervalDuration
        if len(self.persist_dir) == 0:
            self.persist_dir = DefaultConf.DefaultCachePersistDir
        if len(self.type) == 0:
            self.type = DefaultConf.DefaultLocalCache
        if self.persist_retry_interval is None:
            self.persist_retry_interval = DefaultConf.DefaultPersistRetryInterval
        if self.persist_max_read_retry == 0:
            self.persist_max_read_retry = DefaultConf.DefaultPersistMaxReadRetry
        if self.persist_max_write_retry == 0:
            self.persist_max_write_retry = DefaultConf.DefaultPersistMaxWriteRetry


# 服务路由配置
class ServiceRouterConfig:
    def __init__(self, before_chain: List[str] = None, chain: List[str] = None,
                 after_chain: List[str] = None, plugin: Dict = None, percent_of_min_instances: float = 0):
        # 	//服务路由责任链
        # 	Chain []string `yaml:"chain"`
        # 	// 插件相关配置
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        # 	// 进行过滤时的最大过滤比例
        # 	PercentOfMinInstances *float64 `yaml:"percentOfMinInstances"`
        self.before_chain = [] if before_chain is None else before_chain
        self.chain = [] if chain is None else chain
        self.after_chain = [] if after_chain is None else after_chain
        self.percent_of_min_instances = percent_of_min_instances
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    def get_chain(self):
        return self.chain

    def get_before_chain(self):
        return self.before_chain

    def get_after_chain(self):
        return self.after_chain

    def get_percent_of_min_instances(self):
        return self.percent_of_min_instances

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("serviceRouter", plugin_name, self.plugin, value)

    def verify(self):
        if self.percent_of_min_instances >= 1 or self.percent_of_min_instances < 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServiceRouterConfig: consumer.servicerouter.percentOfMinInstances "
                           "must be in range [0.0, 1.0)")
        for name in ("before_chain", "chain", "after_chain"):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "ServiceRouterConfig: %s must be a list of router names" % name)
        if len(self.before_chain) == 0 or len(self.after_chain) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServiceRouterConfig: beforeChain and afterChain cannot be empty")

    def set_default(self):
        if len(self.before_chain) == 0:
            self.before_chain = [DefaultConf.DefaultServiceRouterIsolated]
        if len(self.after_chain) == 0:
            self.after_chain = [DefaultConf.DefaultServiceRouterRecover]
        if not self.percent_of_min_instances:
            self.percent_of_min_instances = DefaultConf.DefaultPercentOfMinInstances


# 通用加载插件配置的方法，主要是进行一次序列化和反序列化的过程
# 一般只会在插件的Init过程调用
def load_plugin_config(typ: str, plugin_name: str, configs: Dict, value):
    if configs is None:
        return None

    if plugin_name not in configs:
        return None

    config_value = configs[plugin_name]
    # TODO
    # buf, err := yaml.Marshal(configValue)
    # 	if nil != err {
    # 		return model.NewSDKError(model.ErrCodeAPIInvalidConfig,
    # 			err, "fail to marshal plugin %s config", typ+":"+pluginName)
    # 	}
    # 	err = yaml.Unmarshal(buf, value)
    # 	if nil != err {
    # 		return model.NewSDKError(model.ErrCodeAPIInvalidConfig,
    # 			err, "fail to unmarshal plugin %s config to type %v", typ+":"+pluginName,
    # 			reflect.ValueOf(value))
    # 	}


# 负载均衡配置
class LoadBalancerConfig:
    def __init__(self, type: str = "", plugin: Dict = None):
        # 	//负载均衡类型
        # 	Type string `yaml:"type"`
        # 	// 插件相关配置
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        self.type = type
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    def get_type(self):
        return self.type

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("loadbalancer", plugin_name, self.plugin, value)

    def verify(self):
        pass

    def set_default(self):
        if len(self.type) == 0:
            self.type = DefaultConf.DefaultLoadBalancerWR
        elif self.type == "wr":
            self.type = DefaultConf.DefaultLoadBalancerWR


# 熔断相关配置
class CircuitBreakerConfig:
    """Configure local default instance circuit breaking; durations are milliseconds."""

    def __init__(self, enable: bool | None = None, check_period: int | None = None, chain: List[str] = None,
                 plugin: Dict = None, sleep_window: int | None = None,
                 success_count_after_half_open: int | None = None, default_rule_enable: bool | None = None,
                 default_error_count: int | None = None, default_error_percent: int | None = None,
                 default_interval: int | None = None, default_minimum_request: int | None = None):
        # 	//是否启动熔断
        # 	Enable *bool `yaml:"enable"`
        # 	//熔断器定时检查周期
        # 	CheckPeriod *time.Duration `yaml:"checkPeriod"`
        # 	//熔断插件链
        # 	Chain []string `yaml:"chain"`
        # 	// 插件相关配置
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        self.enable = enable
        self.check_period = check_period
        self.sleep_window = sleep_window
        self.success_count_after_half_open = success_count_after_half_open
        self.default_rule_enable = default_rule_enable
        self.default_error_count = default_error_count
        self.default_error_percent = default_error_percent
        self.default_interval = default_interval
        self.default_minimum_request = default_minimum_request
        if chain is None:
            self.chain = []
        else:
            self.chain = chain
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    def is_enable(self):
        return bool(self.enable)

    def get_chain(self):
        return self.chain

    def get_check_period(self):
        return self.check_period

    def get_sleep_window(self) -> int:
        """Return the open-to-half-open delay in milliseconds."""
        return self.sleep_window

    def get_success_count_after_half_open(self) -> int:
        """Return the recovery success threshold and half-open permit count."""
        return self.success_count_after_half_open

    def is_default_rule_enable(self) -> bool:
        """Return whether the local default instance rule is enabled."""
        return bool(self.default_rule_enable)

    def get_default_error_count(self) -> int:
        """Return the consecutive failure threshold."""
        return self.default_error_count

    def get_default_error_percent(self) -> int:
        """Return the error-rate threshold as an integer percentage."""
        return self.default_error_percent

    def get_default_interval(self) -> int:
        """Return the error-rate window and delayed check interval in milliseconds."""
        return self.default_interval

    def get_default_minimum_request(self) -> int:
        """Return the minimum sample count for an error-rate check."""
        return self.default_minimum_request

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("circuitbreaker", plugin_name, self.plugin, value)

    def verify(self):
        for name in ("enable", "default_rule_enable"):
            if not isinstance(getattr(self, name), bool):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "CircuitBreakerConfig: %s must be boolean" % name)
        for name, minimum in (
            ("check_period", DefaultConf.MinCircuitBreakerCheckPeriod),
            ("sleep_window", DefaultConf.MinSleepWindow),
            ("success_count_after_half_open", 1),
            ("default_error_count", 1),
            ("default_error_percent", 0),
            ("default_interval", 1),
            ("default_minimum_request", 1),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                               "CircuitBreakerConfig: %s must be integer >= %d" % (name, minimum))
        if self.default_error_percent > 100:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "CircuitBreakerConfig: default_error_percent must be in range [0, 100]")

    def set_default(self):
        defaults = {
            "enable": DefaultConf.DefaultCircuitBreakerEnabled,
            "check_period": DefaultConf.DefaultCircuitBreakerCheckPeriod,
            "sleep_window": DefaultConf.DefaultSleepWindow,
            "success_count_after_half_open": DefaultConf.DefaultSuccessCountAfterHalfOpen,
            "default_rule_enable": DefaultConf.DefaultRuleEnable,
            "default_error_count": DefaultConf.DefaultErrorCount,
            "default_error_percent": DefaultConf.DefaultErrorPercent,
            "default_interval": DefaultConf.DefaultInterval,
            "default_minimum_request": DefaultConf.DefaultMinimumRequest,
        }
        for name, value in defaults.items():
            if getattr(self, name) is None:
                setattr(self, name, value)
        if type(self.success_count_after_half_open) is int and self.success_count_after_half_open == 0:
            self.success_count_after_half_open = DefaultConf.DefaultSuccessCountAfterHalfOpen
        if len(self.chain) == 0:
            self.chain = [DefaultConf.DefaultCircuitBreaker]
        else:
            self.chain = [DefaultConf.DefaultCircuitBreaker if name == "err_count" else name for name in self.chain]


# 消费者配置
class ConsumerConfig(SelfVerifier):
    def __init__(self, local_cache: LocalCacheConfig = None, service_router: ServiceRouterConfig = None,
                 load_balance: LoadBalancerConfig = None,
                 circuit_breaker: CircuitBreakerConfig = None):
        # 	LocalCache       *LocalCacheConfigImpl       `yaml:"localCache"`
        # 	ServiceRouter    *ServiceRouterConfigImpl    `yaml:"serviceRouter"`
        # 	Loadbalancer     *LoadBalancerConfigImpl     `yaml:"loadbalancer"`
        # 	CircuitBreaker   *CircuitBreakerConfigImpl   `yaml:"circuitbreaker"`
        self.local_cache = local_cache
        self.service_router = service_router
        self.load_balance = load_balance
        self.circuit_breaker = circuit_breaker

    def get_service_router(self) -> ServiceRouterConfig:
        return self.service_router

    def get_load_balancer(self) -> LoadBalancerConfig:
        return self.load_balance

    def get_circuit_breaker(self) -> CircuitBreakerConfig:
        return self.circuit_breaker

    def get_local_cache(self) -> LocalCacheConfig:
        return self.local_cache

    def verify(self):
        try:
            self.local_cache.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ConsumerConfig: local_cache check err: %s" % err.msg)
        try:
            self.service_router.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ConsumerConfig: service_router check err: %s" % err.msg)
        try:
            self.load_balance.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ConsumerConfig: load_balance check err: %s" % err.msg)
        self.circuit_breaker.verify()

    def set_default(self):
        if not self.local_cache:
            self.local_cache = LocalCacheConfig()
        if not self.service_router:
            self.service_router = ServiceRouterConfig()
        if not self.load_balance:
            self.load_balance = LoadBalancerConfig()
        if not self.circuit_breaker:
            self.circuit_breaker = CircuitBreakerConfig()
        self.load_balance.set_default()
        self.service_router.set_default()
        self.local_cache.set_default()
        self.service_router.set_default()
        self.circuit_breaker.set_default()


# 对接注册中心相关配置
class ServerConnectorConfig:
    def __init__(self, addresses=None, protocol="", connect_timeout=None, message_time=None,
                 connection_idle_timeout: int | None = None, request_queue_size: int | None = None,
                 server_switch_interval: int | None = None, plugin: Dict = None, token: str = "",
                 trusted_ca_file: str = "", cert_file: str = "", key_file: str = ""):
        # 	Addresses []string `yaml:"addresses"`
        # 	Protocol string `yaml:"protocol"`
        # 	ConnectTimeout *time.Duration `yaml:"connectTimeout"`
        # 	//远程请求超时时间
        # 	MessageTimeout *time.Duration `yaml:"messageTimeout"`
        # 	ConnectionIdleTimeout *time.Duration `yaml:"connectionIdleTimeout"`
        # 	RequestQueueSize *int32 `yaml:"requestQueueSize"`
        # 	ServerSwitchInterval *time.Duration `yaml:"serverSwitchInterval"`
        # 	Plugin map[string]map[string]interface{} `yaml:"plugin"`
        self.addresses = addresses
        self.protocol = protocol
        self.connect_timeout = connect_timeout
        self.message_time = message_time
        self.connection_idle_timeout = connection_idle_timeout
        self.request_queue_size = request_queue_size
        self.server_switch_interval = server_switch_interval
        self.token = token
        self.trusted_ca_file = trusted_ca_file
        self.cert_file = cert_file
        self.key_file = key_file
        if plugin is None:
            self.plugin = {}
        else:
            self.plugin = plugin

    def get_protocol(self):
        return self.protocol

    def get_addresses(self):
        return self.addresses

    def get_token(self):
        return self.token

    def get_connect_timeout(self):
        return self.connect_timeout

    def get_message_timeout(self):
        return self.message_time

    def get_request_queue_size(self):
        return self.request_queue_size

    def get_server_switch_interval(self):
        return self.server_switch_interval

    def get_connect_idle_timeout(self):
        return self.connection_idle_timeout

    def get_plugin_config(self, plugin_name: str, value):
        return load_plugin_config("registry", plugin_name, self.plugin, value)

    def verify(self):
        for name in ("trusted_ca_file", "cert_file", "key_file"):
            if not isinstance(getattr(self, name), str):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"serverConnector.{name} must be a string")
        if bool(self.cert_file) != bool(self.key_file):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "TLS certFile and keyFile must be paired")
        if len(self.addresses) == 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServerConnectorConfig: global.serverConnector.addresses is empty")
        if self.request_queue_size < 0:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServerConnectorConfig: global.serverConnector.requestQueueSize %d is invalid" %
                           self.request_queue_size)
        if self.connection_idle_timeout < DefaultConf.DefaultMinTimingInterval:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServerConnectorConfig: global.serverConnector.connectionIdleTimeout %d is less than "
                           "minimal timing interval %d" % (
                               self.connection_idle_timeout, DefaultConf.DefaultMinTimingInterval))
        if self.server_switch_interval <= self.connection_idle_timeout:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "ServerConnectorConfig: global.serverConnector.serverSwitchInterval %d is "
                           "less than or equal to global. serverConnector.connectionIdleTimeout %d"
                           % (self.connection_idle_timeout, DefaultConf.DefaultMinTimingInterval))

    def set_default(self):
        if not self.addresses:
            self.addresses = [ip_from_int_with_port(ipstr) for ipstr in DefaultConf.DefaultBuiltInServer]
        if self.connect_timeout is None:
            self.connect_timeout = DefaultConf.DefaultServerConnectTimeout
        if self.message_time is None:
            self.message_time = DefaultConf.DefaultServerMessageTimeout
        if self.connection_idle_timeout is None:
            self.connection_idle_timeout = DefaultConf.DefaultServerConnectionIdleTimeout
        if self.request_queue_size is None:
            self.request_queue_size = DefaultConf.DefaultRequestQueueSize
        if self.server_switch_interval is None:
            self.server_switch_interval = DefaultConf.DefaultServerSwitchInterval
        if len(self.protocol) == 0:
            self.protocol = DefaultConf.DefaultServerConnector


def ip_from_int_with_port(ipstr):
    ip_parts = ipstr.split(":")
    try:
        host = str(ipaddress.IPv4Address(int(ip_parts[0])))
    except ValueError:
        host = ip_parts[0]
    return "%s:%s" % (host, ip_parts[1])


class GlobalConfig(SelfVerifier):
    def __init__(self, system_conf: SystemConfig = None, api_conf: APIConfig = None,
                 server_connector: ServerConnectorConfig = None, stat_reporter: StatReporterConfig = None,
                 admin: AdminConfig = None, event_reporter: EventReporterConfig = None):
        # 	System          *SystemConfigImpl          `yaml:"system"`
        # 	API             *APIConfigImpl             `yaml:"api"`
        # 	ServerConnector *ServerConnectorConfigImpl `yaml:"serverConnector"`
        # 	StatReporter    *StatReporterConfigImpl    `yaml:"statReporter"`
        self.system_conf = system_conf
        self.api_conf = api_conf
        self.server_connector = server_connector
        self.stat_reporter = stat_reporter
        self.admin = admin
        self.event_reporter = event_reporter

    def get_admin(self):
        """Return the context's metrics listener configuration."""
        return self.admin

    # 获取系统配置
    def get_system(self) -> SystemConfig:
        return self.system_conf

    # global.api前缀开头的所有配置项
    def get_api(self) -> APIConfig:
        return self.api_conf

    # global.registry前缀开头的所有配置项
    def get_server_connector(self) -> ServerConnectorConfig:
        return self.server_connector

    # cl5.global.statReporter前缀开头的所有配置项
    def get_stat_reporter(self) -> StatReporterConfig:
        return self.stat_reporter

    def get_event_reporter(self) -> EventReporterConfig:
        """Return the event reporter chain configuration."""
        return self.event_reporter

    def verify(self):
        self.admin.verify()
        self.stat_reporter.verify()
        self.event_reporter.verify()
        try:
            self.system_conf.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "GlobalConfig: system_conf check err: %s" % err.msg)
        try:
            self.api_conf.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "GlobalConfig: api_conf check err: %s" % err.msg)
        try:
            self.server_connector.verify()
        except SDKError as err:
            raise SDKError(ErrorCode.ErrCodeAPIInvalidArgument,
                           "GlobalConfig: server_connector check err: %s" % err.msg)

    def set_default(self):
        if self.admin is None:
            self.admin = AdminConfig()
        self.admin.set_default()
        if not self.api_conf:
            self.api_conf = APIConfig()
        if not self.system_conf:
            self.system_conf = SystemConfig()
        if not self.server_connector:
            self.server_connector = ServerConnectorConfig()
        if not self.stat_reporter:
            self.stat_reporter = StatReporterConfig()
        if not self.event_reporter:
            self.event_reporter = EventReporterConfig()
        self.api_conf.set_default()
        self.system_conf.set_default()
        self.server_connector.set_default()
        self.stat_reporter.set_default()
        self.event_reporter.set_default()


class ProviderConfig(SelfVerifier):
    """Configure the minimum interval before automatic instance re-registration."""

    def __init__(self, min_register_interval: int | None = None):
        self.min_register_interval = min_register_interval

    def get_min_register_interval(self) -> int:
        """Return the minimum re-registration interval in milliseconds."""
        return self.min_register_interval

    def set_default(self):
        if (self.min_register_interval is None
                or type(self.min_register_interval) is int and self.min_register_interval == 0):
            self.min_register_interval = 30000

    def verify(self):
        if (isinstance(self.min_register_interval, bool)
                or not isinstance(self.min_register_interval, int) or self.min_register_interval <= 0):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                           "ProviderConfig: minRegisterInterval must be positive integer milliseconds")


class SkillConnectorConfig(SelfVerifier):
    """Configure the independent Skill connection and persistent fallback."""

    def __init__(self, addresses=None, protocol="grpc", connector_type="polaris", token="",
                 message_timeout=5000, download_timeout=30000, persist_enable=True,
                 persist_dir="./polaris/backup/skill", persist_max_write_retry=1,
                 persist_max_read_retry=0, persist_retry_interval=500, fallback_to_local_cache=True,
                 trusted_ca_file="", cert_file="", key_file=""):
        self.addresses = addresses
        self.protocol = protocol
        self.connector_type = connector_type
        self.token = token
        self.message_timeout = message_timeout
        self.download_timeout = download_timeout
        self.persist_enable = persist_enable
        self.persist_dir = persist_dir
        self.persist_max_write_retry = persist_max_write_retry
        self.persist_max_read_retry = persist_max_read_retry
        self.persist_retry_interval = persist_retry_interval
        self.fallback_to_local_cache = fallback_to_local_cache
        self.trusted_ca_file = trusted_ca_file
        self.cert_file = cert_file
        self.key_file = key_file

    def set_default(self):
        """Use the standard local Skill endpoint when no address is assigned."""
        if self.addresses is None:
            self.addresses = ["127.0.0.1:8094"]

    def verify(self):
        """Validate the supported connector and persistence settings."""
        if (self.protocol != "grpc" or self.connector_type != "polaris"
                or not isinstance(self.addresses, (list, tuple)) or not self.addresses
                or any(not isinstance(address, str) or not address.strip() for address in self.addresses)):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "ai.skill requires polaris/grpc and nonempty addresses")
        for name in ("message_timeout", "download_timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"ai.skill.{name} must be positive milliseconds")
        for name in ("persist_max_write_retry", "persist_max_read_retry", "persist_retry_interval"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"ai.skill.{name} must be >=0")
        for name in ("persist_enable", "fallback_to_local_cache"):
            if not isinstance(getattr(self, name), bool):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"ai.skill.{name} must be boolean")
        if not isinstance(self.token, str):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "ai.skill.token must be a string")
        for name in ("trusted_ca_file", "cert_file", "key_file"):
            if not isinstance(getattr(self, name), str):
                raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, f"ai.skill.{name} must be a string")
        if bool(self.cert_file) != bool(self.key_file):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "Skill TLS certFile and keyFile must be paired")
        if self.persist_enable and (not isinstance(self.persist_dir, str) or not self.persist_dir):
            raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "ai.skill.persistDir must not be empty")


class SkillConfig(SelfVerifier):
    """Hold the Skill connector settings."""

    def __init__(self, server_connector=None):
        self.server_connector = server_connector

    def get_server_connector(self):
        """Return the independent Skill connector configuration."""
        return self.server_connector

    def set_default(self):
        """Fill missing connector settings."""
        if self.server_connector is None:
            self.server_connector = SkillConnectorConfig()
        self.server_connector.set_default()

    def verify(self):
        """Validate the Skill connector."""
        self.server_connector.verify()


class AIConfig(SelfVerifier):
    """Hold AI registry client settings."""

    def __init__(self, skill=None):
        self.skill = skill

    def get_skill(self):
        """Return the Skill client configuration."""
        return self.skill

    def set_default(self):
        """Fill missing AI configuration."""
        if self.skill is None:
            self.skill = SkillConfig()
        self.skill.set_default()

    def verify(self):
        """Validate configured AI capabilities."""
        self.skill.verify()


class Configuration(SelfVerifier):
    def __init__(self, global_config: GlobalConfig = None, consumer_config: ConsumerConfig = None,
                 provider_config: ProviderConfig = None, ai: AIConfig = None):
        # 	Global   *GlobalConfigImpl   `yaml:"global"`
        # 	Consumer *ConsumerConfigImpl `yaml:"consumer"`
        self.global_config = global_config
        self.consumer_config = consumer_config
        self.provider_config = provider_config
        self.ai = ai

    def get_ai(self):
        """Return AI registry settings for this configuration."""
        return self.ai

    def get_global(self) -> GlobalConfig:
        return self.global_config

    def get_consumer(self) -> ConsumerConfig:
        return self.consumer_config

    def get_provider(self) -> ProviderConfig:
        return self.provider_config

    def verify(self):
        self.global_config.verify()
        self.consumer_config.verify()
        self.provider_config.verify()
        self.ai.verify()

    def set_default(self):
        if not self.global_config:
            self.global_config = GlobalConfig()
        if not self.consumer_config:
            self.consumer_config = ConsumerConfig()
        if not self.provider_config:
            self.provider_config = ProviderConfig()
        self.global_config.set_default()
        self.consumer_config.set_default()
        self.provider_config.set_default()
        if self.ai is None:
            self.ai = AIConfig()
        self.ai.set_default()
        skill_connector = self.ai.get_skill().get_server_connector()
        global_connector = self.global_config.get_server_connector()
        if not skill_connector.token and global_connector.token:
            skill_connector.token = global_connector.token

    @classmethod
    def from_dict(cls, data: Dict, apply_env: bool = True) -> "Configuration":
        """Create a configuration from a mapping, with environment overrides by default."""
        from polaris.pkg.config.loader import build_configuration
        return build_configuration(data, apply_env=apply_env)

    @classmethod
    def from_file(cls, path: str, apply_env: bool = True) -> "Configuration":
        """Create a configuration from a YAML file."""
        from polaris.pkg.config.loader import build_configuration, load_config_file
        return build_configuration(load_config_file(path), apply_env=apply_env)

    @classmethod
    def from_env(cls) -> "Configuration":
        """Create a configuration from POLARIS_ environment variables."""
        from polaris.pkg.config.loader import build_configuration
        return build_configuration({}, apply_env=True)


# 服务集群信息转换为服务对象
def service_cluster_to_service_key(config: ServerClusterConfig) -> ServiceKey:
    return ServiceKey(namespace=config.get_namespace(), service=config.get_service())


def get_server_services(config: Configuration) -> Dict[str, ClusterService]:
    """Return configured system services, omitting unnamed clusters as the Go SDK does."""
    system = config.get_global().get_system()
    clusters = {
        ClusterType.DiscoverCluster: system.get_discover_cluster(),
        ClusterType.HealthCheckCluster: system.get_health_check_cluster(),
        ClusterType.MonitorCluster: system.get_monitor_cluster(),
    }
    return {
        cluster_type: ClusterService(service_cluster_to_service_key(cluster), cluster_type)
        for cluster_type, cluster in clusters.items()
        if cluster.get_namespace() and cluster.get_service()
    }
