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

from typing import Any, Iterable


class ErrorCode:
    # 正常
    ErrCodeSuccess = 0
    # 接口参数错误，API接口调用时，对接口参数进行校验失败后的错误码
    ErrCodeAPIInvalidArgument = 1001
    # 配置参数校验失败
    ErrCodeAPIInvalidConfig = 1002
    # 注册插件、初始化插件、获取插件、销毁插件时发生的错误
    ErrCodePluginError = 1003
    # API调用超时无正确返回
    ErrCodeAPITimeoutError = 1004
    # SDK状态错误，出现在SDK已经销毁还进行API调用
    ErrCodeInvalidStateError = 1005
    # 连接server成功，但是server返回了报错信息
    ErrCodeServerError = 1006
    # 连接服务端出现网络异常
    ErrCodeNetworkError = 1007
    # 服务熔断发生错误
    ErrCodeCircuitBreakerError = 1008
    # 一个实例中包含的信息不合法，如host信息无法正常解析
    ErrCodeInstanceInfoError = 1009
    # 当今行负载均衡、服务路由时，传入的服务没有实例信息
    ErrCodeAPIInstanceNotFound = 1010
    # 路由规则不合法
    ErrCodeInvalidRouteRule = 1011
    # 路由规则无法匹配
    ErrCodeRouteRuleNotMatch = 1012
    # server返回的信息不合法
    ErrCodeInvalidResponse = 1013
    # 获取MaxQueuingTime失败
    ErrCodeMaxQueuingTimeInvalid = 1015
    # server返回的信息不合法
    ErrCodeDataNotChange = 1016


class ServerCode:
    """Polaris response codes used by SDK control flow."""

    ExecuteSuccess = 200000
    DataNotChange = 200001
    NoNeedUpdate = 200002
    ExistedResource = 400201
    NotFoundResource = 400202
    NotFoundService = 400301


class SDKError(Exception):
    """SDK failure with a stable local code and optional server response code."""

    def __init__(self, err_code: int, msg: str, server_code: int | None = None):
        super().__init__(err_code, msg)
        self.err_code = err_code
        self.msg = msg
        self.server_code = server_code


def response_code(response: Any) -> int:
    """Return an integer code from a specification response."""
    code = getattr(response, "code", None)
    return int(getattr(code, "value", code or 0))


def response_info(response: Any) -> str:
    """Return response information from a protobuf wrapper."""
    info = getattr(response, "info", None)
    return str(getattr(info, "value", info or "Polaris server request failed"))


def ensure_response(response: Any, accepted: Iterable[int] = (ServerCode.ExecuteSuccess,)) -> Any:
    """Validate a Polaris response and preserve data-not-change semantics."""
    code = response_code(response)
    if code in accepted:
        return response
    if code in {ServerCode.DataNotChange, ServerCode.NoNeedUpdate}:
        raise SDKError(ErrorCode.ErrCodeDataNotChange, response_info(response), server_code=code)
    raise SDKError(ErrorCode.ErrCodeServerError, response_info(response), server_code=code)
