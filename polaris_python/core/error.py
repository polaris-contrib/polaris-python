"""SDK exception types and protocol error handling."""

from __future__ import annotations

from typing import Any

# Response codes from specification ``api/v1/model/code.proto``.
DATA_NO_CHANGE = 200001
NO_NEED_UPDATE = 200002
NOT_FOUND_RESOURCE = 400202
NOT_FOUND_SERVICE = 400301


class PolarisError(Exception):
    """Base SDK error with an optional Polaris response code."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class PolarisTransportError(PolarisError):
    """Raised when the client cannot reach any configured server."""


class PolarisResponseError(PolarisError):
    """Raised when a server returns a non-success Polaris response code."""


class CircuitOpenError(PolarisError):
    """Raised when an instance is currently blocked by a circuit breaker."""


class RateLimitExceededError(PolarisError):
    """Raised when a local rate or concurrency limit is exceeded."""


def response_code(response: Any) -> int:
    """Read a response code from generated protobuf wrappers."""
    code = getattr(response, "code", None)
    return int(getattr(code, "value", code or 0))


def ensure_success(response: Any) -> Any:
    """Raise ``PolarisResponseError`` for a non-success server response."""
    code = response_code(response)
    if code and code not in {200000, 200001, 200002}:
        info = getattr(response, "info", None)
        message = getattr(info, "value", info or "Polaris server request failed")
        raise PolarisResponseError(str(message), code=code)
    return response
