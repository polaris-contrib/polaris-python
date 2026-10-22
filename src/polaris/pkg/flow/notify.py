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


# 上下文表示
class ContextKey:
    def __init__(self, service_key: ServiceKey, operation: str):
        # 服务信息
        self.service_key = service_key
        # 操作信息
        self.operation = operation

    def string(self):
        return "ServiceKey:{service_key}. Operation:{opratrion}".format(service_key=self.service_key,
                                                                        opratrion=self.operation)


class SingleNotifyContext:
    def __int__(self, name: ContextKey):
        pass


class CombineNotifyContext:
    def __init__(self, service_key: ServiceKey, awit_count: int, ):
        pass


KeySourceRoute = "sourceRoute"
KeyDstRoute = "destinationRoute"
KeyDstInstances = "destinationInstances"
KeyServiceRoute = "serviceRoute"
KeyServiceInstance = "serviceInstance"
