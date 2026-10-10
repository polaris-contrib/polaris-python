from polaris_python.api.context import SDKContext
from polaris_python.core.error import PolarisError


class SkillAPI:
    """Read-only Skill client. Maps to ``PolarisSkill`` in specification."""

    def __init__(self, context: SDKContext) -> None:
        self._context = context

    def _check_available(self) -> None:
        if self._context.destroyed:
            raise PolarisError("SDKContext has been destroyed")

    async def get_skill(self) -> None:
        self._check_available()
        raise NotImplementedError

    async def get_skill_list(self) -> None:
        self._check_available()
        raise NotImplementedError

    async def download_skill(self) -> None:
        self._check_available()
        raise NotImplementedError
