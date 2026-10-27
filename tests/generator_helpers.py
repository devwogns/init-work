from __future__ import annotations

import functools
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

SKILL_DIR: Final = Path(__file__).parents[1] / "skills" / "init-work"
SCRIPT_PATH: Final = SKILL_DIR / "scripts" / "create_task.py"
BUNDLED_TEMPLATE_DIR: Final = SKILL_DIR / "assets" / "task-template"
EXPECTED_CORE_PATHS: Final = frozenset(
    {
        "AGENTS.md",
        "README.md",
        "CLAUDE.md",
        "ROADMAP.md",
        "PROGRESS.md",
        "decisions.md",
        "evidence/README.md",
    },
)
TOKEN_README: Final = """# {{TASK_NAME}}
{{TASK_SUMMARY}}
starter={{START_NAME}}
date={{START_DATE}}
baseline={{BASELINE_DATETIME}}
folder={{WORK_FOLDER}}
policy={{AGENT_INSTRUCTIONS_POLICY}}
refs={{REFERENCE_PATHS_OR_NONE}}
scope={{ADDITIONAL_EDIT_SCOPE_OR_NONE}}
next={{INITIAL_NEXT_ACTION}}"""


@functools.cache
def load_generator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_task", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def isolated_environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        HOME=str(home),
        USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_NOSYSTEM="1",
    )
    return environment


def git_init(path: Path, environment: Mapping[str, str]) -> None:
    subprocess.run(
        ("git", "init", str(path)),
        check=True,
        capture_output=True,
        env=dict(environment),
    )


def make_directory_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name != "nt":
        return False
    result = subprocess.run(
        ("cmd", "/c", "mklink", "/J", str(link), str(target)),
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def remove_directory_link(link: Path) -> None:
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def write_token_template(template: Path) -> Path:
    files = {
        "README.md": TOKEN_README,
        "CLAUDE.md": "@AGENTS.md",
        "PROGRESS.md": "progress",
        "ROADMAP.md": "roadmap",
        "decisions.md": "decisions",
        "evidence/README.md": "evidence",
        "variants/global/AGENTS.md": "global agents",
        "variants/sub/AGENTS.md": "sub agents",
    }
    for relative, content in files.items():
        path = template / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return template


@dataclass(frozen=True, slots=True)
class GeneratorInputs:
    task_name: str = "프로젝트 문서 정리"
    task_slug: str = "documentation"
    task_summary: str = "프로젝트 문서의 구조를 정리하고 참조 경로를 명확히 한다."
    start_name: str = "홍길동"
    reference_paths: str = "`docs/`, `src/`"
    additional_edit_scope: str = "없음"


DEFAULT_INPUTS: Final = GeneratorInputs()


def _invoke(
    arguments: Sequence[str],
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(SCRIPT_PATH), *arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(environment),
    )


def plan_generator(
    run_dir: Path,
    environment: Mapping[str, str],
    *,
    inputs: GeneratorInputs = DEFAULT_INPUTS,
    target: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = ["--plan", "--run-dir", str(run_dir), "--task-slug", inputs.task_slug]
    if target is not None:
        arguments += ["--target", target]
    return _invoke(arguments, environment)


def run_generator(
    run_dir: Path,
    template_dir: Path,
    environment: Mapping[str, str],
    *,
    inputs: GeneratorInputs = DEFAULT_INPUTS,
    target: str | None = None,
    confirm: str | None = None,
    omit_confirm: bool = False,
) -> subprocess.CompletedProcess[str]:
    if confirm is None and not omit_confirm:
        planned = plan_generator(run_dir, environment, inputs=inputs, target=target)
        if planned.returncode != 0:
            return planned
        confirm = json.loads(planned.stdout)["fingerprint"]
    arguments = [
        "--run-dir",
        str(run_dir),
        "--template-dir",
        str(template_dir),
        "--task-name",
        inputs.task_name,
        "--task-slug",
        inputs.task_slug,
        "--task-summary",
        inputs.task_summary,
        "--start-name",
        inputs.start_name,
        "--reference-paths",
        inputs.reference_paths,
        "--additional-edit-scope",
        inputs.additional_edit_scope,
    ]
    if confirm is not None:
        arguments += ["--confirm", confirm]
    if target is not None:
        arguments += ["--target", target]
    return _invoke(arguments, environment)


def destination_of(result: subprocess.CompletedProcess[str]) -> Path:
    return Path(json.loads(result.stdout)["destination"])


def generated_files(destination: Path) -> frozenset[str]:
    return frozenset(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(destination).parts
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
