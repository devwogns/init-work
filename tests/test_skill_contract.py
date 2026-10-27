from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

from generator_helpers import SCRIPT_PATH, SKILL_DIR

SKILL: Final = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
AGENT_CONFIG: Final = (SKILL_DIR / "agents" / "openai.yaml").read_text(
    encoding="utf-8",
)


def test_skill_uses_current_generator_options() -> None:
    # Given: the generator help text.
    help_text = subprocess.run(
        (sys.executable, str(SCRIPT_PATH), "--help"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "200"},
    ).stdout

    # When / Then: every option the skill relies on exists, and removed ones are gone.
    for option in ("--plan", "--confirm", "--run-dir", "--target", "--task-slug"):
        assert option in SKILL, option
        assert option in help_text, option
    assert "--repo-root" not in SKILL
    assert "tasks/<" not in SKILL


def test_skill_asks_path_mode_first_and_skips_scope_for_global() -> None:
    # Given: the conversation contract.
    path_question = SKILL.index("저장 경로를 자동으로 정할까요, 직접 입력할까요?")
    name_question = SKILL.index("작업 이름은 무엇인가요?")

    # When / Then: the path question comes first and question 4 is sub-only.
    assert path_question < name_question
    assert "Ask this only when the plan's `template` is `sub`" in SKILL
    assert "Never skip the final confirmation" in SKILL


def test_skill_documents_confirmation_reentry_and_report() -> None:
    # Given / When / Then: the final confirmation, re-entry, and report rules are present.
    for marker in (
        "agent session's working directory",
        "never expands environment variables",
        "`nested_repositories`",
        "`ignored_documents`",
        "`repo_root` differs",
        "`created:`",
        "`baseline_datetime`",
    ):
        assert marker in SKILL, marker


def test_agent_prompt_no_longer_requires_git_repository() -> None:
    # Given / When / Then: the default prompt matches path selection.
    assert "target Git repository" not in AGENT_CONFIG
    assert "output path" in AGENT_CONFIG
