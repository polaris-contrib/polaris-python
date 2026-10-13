from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from polaris_python.core.log import _reset_logging


@pytest.fixture(autouse=True)
def isolate_sdk_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Run each test in its own directory so the default ``./polaris`` log and backup paths stay out of the repo."""
    monkeypatch.chdir(tmp_path)
    yield
    _reset_logging()
