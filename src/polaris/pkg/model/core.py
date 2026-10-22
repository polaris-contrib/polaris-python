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

class EventType:
    Unknown = 0

    Instance = 0x2001

    Routing = 0x2002


# 服务的唯一标识key
class ServiceKey:
    def __init__(self, namespace: str, service: str):
        self.namespace: str = namespace
        self.service: str = service

    def __hash__(self):
        return hash(self.namespace + self.service)

    def get_namespace(self):
        return self.namespace

    def get_service(self):
        return self.service


class ServiceEventKey(ServiceKey):
    def __init__(self, namespace: str, service: str, event_type: int):
        ServiceKey.__init__(self, namespace, service)
        self.event_type = event_type

    def __eq__(self, other):
        return (self.service == other.service and
                self.namespace == other.namespace and
                self.event_type == other.event_type)

    def __hash__(self):
        return hash(self.namespace + self.service + str(self.event_type))
