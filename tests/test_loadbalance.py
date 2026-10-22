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

from google.protobuf import wrappers_pb2 as wrappers
from polaris.plugin.load_balancer import random, weighted_random
from polaris.pkg.model.service import ServiceInstances, Instance
from polaris.pkg.model.core import ServiceKey
from polarismesh_specification.api.v1.service_manage import service_pb2


def get_service_instances():
    sr_namespace = "polaris"
    sr_service = "polaris-server"

    instance1 = service_pb2.Instance()
    instance1.id.CopyFrom(wrappers.StringValue(value='123456'))
    instance1.service.CopyFrom(wrappers.StringValue(value=sr_service))
    instance1.namespace.CopyFrom(wrappers.StringValue(value=sr_namespace))
    instance1.host.CopyFrom(wrappers.StringValue(value='localhost'))
    instance1.port.CopyFrom(wrappers.UInt32Value(value=10086))
    instance1.weight.CopyFrom(wrappers.UInt32Value(value=100))

    instance2 = service_pb2.Instance()
    instance2.id.CopyFrom(wrappers.StringValue(value='78908'))
    instance2.service.CopyFrom(wrappers.StringValue(value=sr_service))
    instance2.namespace.CopyFrom(wrappers.StringValue(value=sr_namespace))
    instance2.host.CopyFrom(wrappers.StringValue(value='localhost'))
    instance2.port.CopyFrom(wrappers.UInt32Value(value=10086))
    instance2.weight.CopyFrom(wrappers.UInt32Value(value=100))

    service_key = ServiceKey(sr_namespace, sr_service)

    service = service_pb2.Service()
    service.namespace.CopyFrom(wrappers.StringValue(value=sr_namespace))
    service.name.CopyFrom(wrappers.StringValue(value=sr_service))

    instances = [Instance(instance1, service_key), Instance(instance2, service_key)]
    service_instances = ServiceInstances(service, instances)
    return service_instances


def test_random():
    service_instances = get_service_instances()
    random_lb = random.RandomLoadBalancer()
    instance = random_lb.choose_instance(service_instances)
    assert str(type(instance)) == "<class 'polaris.pkg.model.service.Instance'>"


def test_wr():
    service_instances = get_service_instances()
    wr_lb = weighted_random.WeightedRandomLoadBalancer()
    instance = wr_lb.choose_instance(service_instances)
    assert str(type(instance)) == "<class 'polaris.pkg.model.service.Instance'>"
