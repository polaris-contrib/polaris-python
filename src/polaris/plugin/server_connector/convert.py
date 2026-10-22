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
from polarismesh_specification.api.v1.service_manage.client_pb2 import Client
from polarismesh_specification.api.v1.service_manage.request_pb2 import DiscoverRequest
from polarismesh_specification.api.v1.service_manage.service_pb2 import (
    HealthCheck,
    HeartbeatHealthCheck,
    Instance,
    Service,
)

from polaris.pkg.model.server import *
from dataclasses import asdict
from polarismesh_specification.api.v1.service_manage import contract_pb2
from polaris.pkg.model.contract import InterfaceDescriptor, ServiceContract, ServiceFeature


# 注册服务请求转成proto
def register_request_to_proto(request: InstanceRegisterRequest):
    pb_register_instance = Instance()
    pb_register_instance.service.CopyFrom(wrappers.StringValue(value=request.service))
    pb_register_instance.namespace.CopyFrom(wrappers.StringValue(value=request.namespace))
    pb_register_instance.host.CopyFrom(wrappers.StringValue(value=request.host))
    pb_register_instance.port.CopyFrom(wrappers.UInt32Value(value=request.port))
    pb_register_instance.service_token.CopyFrom(wrappers.StringValue(value=request.service_token))
    if request.protocol != '':
        pb_register_instance.protocol.CopyFrom(wrappers.StringValue(value=request.protocol))
    if request.weight is not None:
        pb_register_instance.weight.CopyFrom(wrappers.UInt32Value(value=request.weight))
    if request.priority is not None:
        pb_register_instance.priority.CopyFrom(wrappers.UInt32Value(value=request.priority))
    if request.version != '':
        pb_register_instance.version.CopyFrom(wrappers.StringValue(value=request.version))
    if len(request.metadata) > 0:
        for k, v in request.metadata.items():
            pb_register_instance.metadata[k] = v
    if request.healthy is not None:
        pb_register_instance.healthy.CopyFrom(wrappers.BoolValue(value=request.healthy))
    if request.ttl is not None:
        heartbeat = HeartbeatHealthCheck(ttl=wrappers.UInt32Value(value=request.ttl))
        health_check = HealthCheck(type=HealthCheck.HEARTBEAT, heartbeat=heartbeat)
        pb_register_instance.health_check.CopyFrom(health_check)
    return pb_register_instance


# 反注册服务请求转成proto
def deregister_request_to_proto(request: InstanceDeRegisterRequest):
    pb_deregister_instance = Instance()
    pb_deregister_instance.service.CopyFrom(wrappers.StringValue(value=request.service))
    pb_deregister_instance.namespace.CopyFrom(wrappers.StringValue(value=request.namespace))
    pb_deregister_instance.host.CopyFrom(wrappers.StringValue(value=request.host))
    pb_deregister_instance.port.CopyFrom(wrappers.UInt32Value(value=request.port))
    pb_deregister_instance.service_token.CopyFrom(wrappers.StringValue(value=request.service_token))
    if request.instance_id != '':
        pb_deregister_instance.id.CopyFrom(wrappers.StringValue(value=request.instance_id))
    return pb_deregister_instance


# service转成proto
def service_to_proto(name, namespace, revision=""):
    pb_service_instance = Service()
    pb_service_instance.name.CopyFrom(wrappers.StringValue(value=name))
    pb_service_instance.namespace.CopyFrom(wrappers.StringValue(value=namespace))
    pb_service_instance.revision.CopyFrom(wrappers.StringValue(value=revision))
    return pb_service_instance


# discover请求转成proto
def discover_request_to_proto(request: InstanceDiscoverRequest):
    pb_discover_instance = DiscoverRequest()
    pb_discover_instance.type = request.type
    pb_discover_instance.service.CopyFrom(service_to_proto(request.name, request.namespace, request.revision))
    return pb_discover_instance


# # location转成proto
# def location_to_proto(region, zone, campus):
#     pb_location = Location()
#     pb_location.region.CopyFrom(wrappers.StringValue(value=region))
#     pb_location.zoneCopyFrom(wrappers.StringValue(value=zone))
#     pb_location.campus.CopyFrom(wrappers.StringValue(value=campus))
#     return pb_location


# report_client请求转成proto
def report_client_to_proto(request: ReportClientRequest):
    pb_client_instance = Client()
    pb_client_instance.host.CopyFrom(wrappers.StringValue(value=request.host))
    pb_client_instance.id.CopyFrom(wrappers.StringValue(value=request.client_id))
    pb_client_instance.type = Client.SDK
    pb_client_instance.version.CopyFrom(wrappers.StringValue(value=request.version))
    for info in request.reporter_meta_infos:
        stat = pb_client_instance.stat.add()
        stat.target.value = info["target"]
        stat.port.value = info["port"]
        stat.path.value = info["path"]
        stat.protocol.value = info["protocol"]
    # pb_client_instance.location = location_to_proto(request.region, request.zone, request.campus)
    return pb_client_instance


# hearbeat请求转成proto
def heartbeat_request_to_proto(request: InstanceHeartbeatRequest):
    pb_heartbeat = Instance()
    pb_heartbeat.service.CopyFrom(wrappers.StringValue(value=request.service))
    pb_heartbeat.namespace.CopyFrom(wrappers.StringValue(value=request.namespace))
    pb_heartbeat.host.CopyFrom(wrappers.StringValue(value=request.host))
    pb_heartbeat.port.CopyFrom(wrappers.UInt32Value(value=request.port))
    pb_heartbeat.service_token.CopyFrom(wrappers.StringValue(value=request.service_token))
    if request.instance_id != '':
        pb_heartbeat.id.CopyFrom(wrappers.StringValue(value=request.instance_id))

    return pb_heartbeat


def contract_request_to_proto(request):
    """Convert public contract models into the specification request."""
    values = {key: getattr(request, key) for key in ("namespace", "service", "protocol", "version")}
    values["name"] = getattr(request, "name", "") or request.service
    if isinstance(request, ServiceContract):
        values.update(name=request.name or request.service, revision=request.revision, content=request.content,
                      service_features=[asdict(feature) for feature in request.service_features],
                      interfaces=[asdict(interface) for interface in request.interfaces])
    return contract_pb2.ServiceContract(**values)


def contract_response_from_proto(response):
    """Expose a contract without protobuf objects in the public result."""
    return ServiceContract(
        namespace=response.namespace, service=response.service, protocol=response.protocol,
        version=response.version, name=response.name, revision=response.revision, content=response.content,
        service_features=[ServiceFeature(item.type, item.name, item.description, item.content, item.status)
                          for item in response.service_features],
        interfaces=[InterfaceDescriptor(item.name, item.method, item.path, item.content) for item in response.interfaces],
    )
