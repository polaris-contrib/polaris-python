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

from polaris.pkg.config.default import DefaultConf


class DefaultOptions:
    # 连续错误数统计周期, 默认1分钟
    DefaultContinuousWindow = 60000
    # 触发熔断的连续错误数，默认10
    DefaultContinuousErrorThreshold = DefaultConf.DefaultErrorCount
    # 窗口时长(ms)
    DefaultMetricStatWindow = DefaultConf.DefaultInterval
    # 滑桶数量
    DefaultMetricBucketCount = 10
    DefaultSleepTime = DefaultConf.DefaultSleepWindow

    # composite 默认规则按恢复成功数分配半开请求。
    DefaultRequestCountAfterHalfOpen = DefaultConf.DefaultSuccessCountAfterHalfOpen
    # 半开状态后默认3个成功请求则恢复
    DefaultSuccessCountAfterHalfOpen = DefaultConf.DefaultSuccessCountAfterHalfOpen

    DefaultErrRateThreshold = DefaultConf.DefaultErrorPercent / 100
    DefaultErrRateRequestThreshold = DefaultConf.DefaultMinimumRequest
