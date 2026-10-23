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

from polaris.pkg.model.core import ServiceKey


class DefaultConf:
    HomeVar = "$HOME"
    DefaultServerConnector = "grpc"
    DefaultLocalCache = "inmemory"
    DefaultServiceRouterIsolated = "isolatedRouter"
    DefaultServiceRouterMetadata = "metadataRouter"
    DefaultServiceRouterRecover = "recoverRouter"
    DefaultLoadBalancer = "weightedRandom"

    DefaultAPIInvokeTimeout = 1 * 1000
    DefaultAPIMaxRetryTimes = 1
    DefaultAPIRetryInterval = 500
    DefaultDiscoverServiceRetryInterval = 5 * 1000
    DefaultServiceExpireTime = 24 * 60 * 60 * 1000
    DefaultServerConnectTimeout = 500
    DefaultServerConnectionIdleTimeout = 60 * 1000
    DefaultBuiltInServerConnectionCloseTimeout = 2 * DefaultServerConnectionIdleTimeout
    DefaultRequestQueueSize = 1000
    DefaultServerSwitchInterval = 10 * 60 * 1000
    DefaultAgentListenAddress = "127.0.0.1:8888"
    DefaultCachePersistDir = "./polaris/backup"
    DefaultPersistMaxWriteRetry = 1
    DefaultPersistMaxReadRetry = 0
    DefaultPersistRetryInterval = 500
    DefaultCircuitBreakerCheckPeriod = 60 * 1000
    MinCircuitBreakerCheckPeriod = 1 * 1000
    DefaultCircuitBreakerEnabled = True
    DefaultRequestCountAfterHalfOpen = 10
    DefaultSuccessCountAfterHalfOpen = 3
    DefaultSleepWindow = 30 * 1000
    MinSleepWindow = 1 * 1000
    DefaultRuleEnable = True
    DefaultErrorCount = 10
    DefaultErrorPercent = 50
    DefaultInterval = 60 * 1000
    DefaultMinimumRequest = 10
    DefaultPercentOfMinInstances = 0.0
    DefaultReportClientIntervalDuration = 60 * 1000
    MaxRedirectTimes = 1
    DefaultServiceRefreshIntervalDuration = 2 * 1000
    DefaultStatReportEnabled = True
    DefaultStatReporter = "prometheus"
    DefaultBuiltInServer = ["127.0.0.1:8091"]
    ServerNamespace = "Polaris"
    ServerDiscoverService = "polaris.discover"
    ServerHeartBeatService = "polaris.healthcheck"
    ServerMonitorService = "polaris.monitor"
    SvcKeyDiscoverService = ServiceKey(ServerNamespace, ServerDiscoverService)
    SvcKeyHeartBeatService = ServiceKey(ServerNamespace, ServerHeartBeatService)
    SvcKeyMonitorService = ServiceKey(ServerNamespace, ServerMonitorService)
    DefaultLoadBalancerWR = "weightedRandom"
    DefaultServerMessageTimeout = 5 * 1000

    BuiltinCluster = "builtin"
    DiscoverCluster = "discover"
    HealthCheckCluster = "healthCheck"
    MonitorCluster = "monitor"

    DefaultServerServiceToLoadBalancer = {
        BuiltinCluster: DefaultLoadBalancerWR,
        DiscoverCluster: DefaultLoadBalancerWR,
        HealthCheckCluster: DefaultLoadBalancerWR,
        MonitorCluster: DefaultLoadBalancerWR
    }

    # System services use the global before/after chains; only override the core chain.
    DefaultServerServiceRouterChain = []
    DefaultCircuitBreaker = "composite"
    DefaultCircuitBreakerErrCount = "errorCount"
    DefaultCircuitBreakerErrRate = "errorRate"

    DefaultMinServiceExpireTime = 5 * 1000  # 5 seconds
    DefaultMinTimingInterval = 0.1 * 1000  # 100 ms
    DefaultServerServiceRefreshInterval = 60 * 1000  # 1 minute
