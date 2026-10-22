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

"""Load configured TLS material once, refusing incomplete or invalid credentials."""

from pathlib import Path
import ssl

import grpc

from polaris.pkg.model.error import ErrorCode, SDKError


def channel_credentials(config):
    """Build validated gRPC credentials, or None only when no TLS files are configured."""
    ca, cert, key = config.trusted_ca_file, config.cert_file, config.key_file
    if not any((ca, cert, key)):
        return None
    if bool(cert) != bool(key):
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig, "TLS certFile and keyFile must be configured together")
    try:
        roots = Path(ca).read_bytes() if ca else None
        chain = Path(cert).read_bytes() if cert else None
        private_key = Path(key).read_bytes() if key else None
        validator = ssl.create_default_context()
        if roots is not None:
            validator.load_verify_locations(cadata=roots.decode("ascii"))
        if cert:
            validator.load_cert_chain(cert, key, password=lambda: "")
        return grpc.ssl_channel_credentials(roots, private_key, chain)
    except (OSError, ValueError, UnicodeError, grpc.RpcError) as error:
        raise SDKError(ErrorCode.ErrCodeAPIInvalidConfig,
                       f"Invalid TLS certificate configuration: {error}") from error
