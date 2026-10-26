from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "create_task.py"
BUNDLED_TEMPLATE_DIR = Path(__file__).parents[1] / "assets" / "task-template"

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


@dataclass(frozen=True, slots=True)
class _GeneratorInputs:
    task_slug: str = "documentation"
    start_name: str = "홍길동"
    reference_paths: str = "`docs/`, `src/`"
    additional_edit_scope: str = "없음"


_DEFAULT_GENERATOR_INPUTS: Final = _GeneratorInputs()


@pytest.fixture
def template_dir(tmp_path: Path) -> Path:
    template = tmp_path / "template"
    template.mkdir()
    (template / "AGENTS.md").write_text(
        """# {{TASK_NAME}}
{{TASK_SUMMARY}}
starter={{START_NAME}}
date={{START_DATE}}
baseline={{BASELINE_DATETIME}}
slug={{TASK_SLUG}}
refs={{REFERENCE_PATHS_OR_NONE}}
scope={{ADDITIONAL_EDIT_SCOPE_OR_NONE}}
next={{INITIAL_NEXT_ACTION}}""",
        encoding="utf-8",
    )
    return template


def run_generator(
    repo_root: Path,
    template_dir: Path,
    *,
    inputs: _GeneratorInputs = _DEFAULT_GENERATOR_INPUTS,
) -> subprocess.CompletedProcess[str]:
    if not (repo_root / ".git").exists():
        subprocess.run(("git", "init", str(repo_root)), check=True, capture_output=True)
    return subprocess.run(
        (
            sys.executable,
            str(SCRIPT_PATH),
            "--repo-root",
            str(repo_root),
            "--template-dir",
            str(template_dir),
            "--task-name",
            "프로젝트 문서 정리",
            "--task-slug",
            inputs.task_slug,
            "--task-summary",
            "프로젝트 문서의 구조를 정리하고 참조 경로를 명확히 한다.",
            "--start-name",
            inputs.start_name,
            "--reference-paths",
            inputs.reference_paths,
            "--additional-edit-scope",
            inputs.additional_edit_scope,
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def test_creates_initialized_task_when_arguments_are_valid(
    tmp_path: Path,
    template_dir: Path,
) -> None:
    # Given: a repository root and a template containing every supported token.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the cross-platform generator creates a task.
    result = run_generator(repo_root, template_dir)

    # Then: the generated task contains every initialized template value.
    assert result.returncode == 0, result.stderr
    task_dir = repo_root / "tasks" / "documentation"
    content = (task_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert "프로젝트 문서 정리" in content
    assert "프로젝트 문서의 구조를 정리하고 참조 경로를 명확히 한다." in content
    assert "starter=홍길동" in content
    assert "slug=documentation" in content
    assert "refs=`docs/`, `src/`" in content
    assert "scope=없음" in content
    assert "next=해당 경로의 적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다" in content
    assert re.search(r"date=\d{4}-\d{2}-\d{2}", content)
    assert re.search(r"baseline=\d{4}-\d{2}-\d{2} \d{2}:\d{2}", content)
    assert "+09:00" not in content
    assert "{{" not in content


def test_normalizes_empty_optional_answers_to_none(
    tmp_path: Path,
    template_dir: Path,
) -> None:
    # Given: the user submitted blank or whitespace-only optional answers.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the generator receives those answers as empty arguments.
    result = run_generator(
        repo_root,
        template_dir,
        inputs=_GeneratorInputs(
            start_name="",
            reference_paths="   ",
            additional_edit_scope="",
        ),
    )

    # Then: every optional answer is stored as the canonical Korean empty value.
    assert result.returncode == 0, result.stderr
    content = (repo_root / "tasks" / "documentation" / "AGENTS.md").read_text(
        encoding="utf-8",
    )
    assert "starter=없음" in content
    assert "refs=없음" in content
    assert "scope=없음" in content


def test_rejects_non_ascii_slug_before_creating_task(
    tmp_path: Path,
    template_dir: Path,
) -> None:
    # Given: a slug containing Korean characters.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the generator receives the invalid slug.
    result = run_generator(
        repo_root,
        template_dir,
        inputs=_GeneratorInputs(task_slug="보안-문서"),
    )

    # Then: it rejects the slug without creating a task directory.
    assert result.returncode != 0
    assert not (repo_root / "tasks" / "보안-문서").exists()


def test_does_not_overwrite_existing_task(
    tmp_path: Path,
    template_dir: Path,
) -> None:
    # Given: a task directory that already contains user data.
    repo_root = tmp_path / "repo"
    task_dir = repo_root / "tasks" / "documentation"
    task_dir.mkdir(parents=True)
    marker = task_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    # When: the generator is invoked with the same slug.
    result = run_generator(repo_root, template_dir)

    # Then: it refuses to overwrite the existing task.
    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "keep"


def test_bundled_template_creates_exact_default_core(tmp_path: Path) -> None:
    # Given: the repository's bundled task template.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the generator initializes a task from that template.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR)

    # Then: it creates the shared documents and local agent instructions.
    assert result.returncode == 0, result.stderr
    task_dir = repo_root / "tasks" / "documentation"
    generated_paths = frozenset(
        path.relative_to(task_dir).as_posix()
        for path in task_dir.rglob("*")
        if path.is_file()
    )
    assert generated_paths == EXPECTED_CORE_PATHS


def test_bundled_template_initializes_reference_driven_work(tmp_path: Path) -> None:
    # Given: a task with explicit reference paths.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR)

    # Then: ROADMAP briefs the same active work and next action owned by PROGRESS.
    assert result.returncode == 0, result.stderr
    task_dir = repo_root / "tasks" / "documentation"
    roadmap = (task_dir / "ROADMAP.md").read_text(encoding="utf-8")
    progress = (task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "W1" in roadmap
    assert "W1" in progress
    assert "적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다" in roadmap
    assert "적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다" in progress
    roadmap_baseline = re.search(
        r"PROGRESS 기준일: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        roadmap,
    )
    progress_baseline = re.search(
        r"\*\*기준일\*\*: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        progress,
    )
    assert roadmap_baseline is not None
    assert progress_baseline is not None
    assert roadmap_baseline.group(1) == progress_baseline.group(1)


def test_bundled_template_initializes_planning_when_references_are_absent(
    tmp_path: Path,
) -> None:
    # Given: a task without a reference path.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inputs = _GeneratorInputs(reference_paths="없음")

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, inputs=inputs)

    # Then: the next action starts by defining work units and completion criteria.
    assert result.returncode == 0, result.stderr
    task_dir = repo_root / "tasks" / "documentation"
    roadmap = (task_dir / "ROADMAP.md").read_text(encoding="utf-8")
    progress = (task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "필요한 작업 단위와 완료 기준을 구체화한다" in roadmap
    assert "필요한 작업 단위와 완료 기준을 구체화한다" in progress
    assert "적용 지침과 진입 문서를 먼저 읽고" not in progress


def test_bundled_roadmap_is_a_single_briefing_view(tmp_path: Path) -> None:
    # Given: a generated workspace that has only its initial work unit.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR)

    # Then: ROADMAP answers the briefing questions without becoming a ledger.
    assert result.returncode == 0, result.stderr
    roadmap = (
        repo_root / "tasks" / "documentation" / "ROADMAP.md"
    ).read_text(encoding="utf-8")
    assert "30초" in roadmap
    assert "지금 어디까지" in roadmap
    assert "무엇을 어떤 순서로" in roadmap
    assert "나는 지금 무엇을" in roadmap
    assert "변경 이력" not in roadmap
    assert len(roadmap.splitlines()) <= 80


def test_bundled_progress_is_the_detailed_status_ledger(tmp_path: Path) -> None:
    # Given: a generated workspace with one active work unit.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR)

    # Then: PROGRESS owns work status, active detail, outcomes, and resumability.
    assert result.returncode == 0, result.stderr
    progress = (
        repo_root / "tasks" / "documentation" / "PROGRESS.md"
    ).read_text(encoding="utf-8")
    assert "작업 단위 상태 장부" in progress
    assert "진행 중 작업 상세" in progress
    assert "완료 결과" in progress
    assert "보류·재개" in progress
    assert "변경 이력" in progress


def test_bundled_roadmap_defers_mermaid_until_flow_is_complex(tmp_path: Path) -> None:
    # Given: a generated workspace with a single linear work unit.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR)

    # Then: it explains the flowchart trigger without generating an empty chart.
    assert result.returncode == 0, result.stderr
    roadmap = (
        repo_root / "tasks" / "documentation" / "ROADMAP.md"
    ).read_text(encoding="utf-8")
    assert "flowchart" in roadmap
    assert "분기" in roadmap
    assert "병렬" in roadmap
    assert "게이트" in roadmap
    assert "원복" in roadmap
    assert "```mermaid" not in roadmap


