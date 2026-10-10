"""Factories for constructing the SDK runtime and public APIs."""

from __future__ import annotations

from polaris_python.api.consumer import ConsumerAPI
from polaris_python.api.context import SDKContext
from polaris_python.api.limiter import LimitAPI
from polaris_python.api.provider import ProviderAPI
from polaris_python.api.skill import SkillAPI
from polaris_python.core.config import Config


class APIFactory:
    """Create one shared context and the APIs that use it."""

    @staticmethod
    def create_context(config: Config | None = None) -> SDKContext:
        """Create an SDK context from configuration."""
        return SDKContext(config)

    @staticmethod
    def create_provider_api(context: SDKContext) -> ProviderAPI:
        """Create a provider API bound to a context."""
        return ProviderAPI(context)

    @staticmethod
    def create_consumer_api(context: SDKContext) -> ConsumerAPI:
        """Create a consumer API bound to a context."""
        return ConsumerAPI(context)

    @staticmethod
    def create_limit_api(context: SDKContext) -> LimitAPI:
        """Create a rate-limit API bound to a context."""
        return LimitAPI(context)

    @staticmethod
    def create_skill_api(context: SDKContext) -> SkillAPI:
        """Create the reserved Skill API bound to a context."""
        return SkillAPI(context)
