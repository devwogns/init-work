from __future__ import annotations

import os
from pathlib import Path

import pytest

from generator_helpers import isolated_environment, write_token_template


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    environment = isolated_environment(tmp_path)
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    return environment


@pytest.fixture
def template_dir(tmp_path: Path) -> Path:
    return write_token_template(tmp_path / "template")

