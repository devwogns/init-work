from __future__ import annotations

import re
from pathlib import Path

import pytest

from generator_helpers import (
    BUNDLED_TEMPLATE_DIR,
    EXPECTED_CORE_PATHS,
    GeneratorInputs,
    destination_of,
    generated_files,
    git_init,
    run_generator,
)


@pytest.fixture
def repo_root(tmp_path: Path, isolated_env: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    return repo


def make_sub_repository(repo_root: Path) -> Path:
    (repo_root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    return repo_root


def test_creates_initialized_task_when_arguments_are_valid(
    repo_root: Path,
    template_dir: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository root and a template containing every supported token.
    # When: the cross-platform generator creates a task.
    result = run_generator(repo_root, template_dir, isolated_env)

    # Then: the generated task contains every initialized template value.
    assert result.returncode == 0, result.stderr
    content = (destination_of(result) / "README.md").read_text(encoding="utf-8")
    assert "프로젝트 문서 정리" in content
    assert "프로젝트 문서의 구조를 정리하고 참조 경로를 명확히 한다." in content
    assert "starter=홍길동" in content
    assert "folder=저장소 전체(저장소 루트 아래 모든 경로)" in content
    assert "refs=`docs/`, `src/`" in content
    assert "scope=없음" in content
    assert "next=해당 경로의 적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다" in content
    assert re.search(r"date=\d{4}-\d{2}-\d{2}", content)
    assert re.search(r"baseline=\d{4}-\d{2}-\d{2} \d{2}:\d{2}", content)
    assert "+09:00" not in content
    assert "{{" not in content


def test_normalizes_empty_optional_answers_to_none(
    repo_root: Path,
    template_dir: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the user submitted blank or whitespace-only optional answers.
    inputs = GeneratorInputs(start_name="", reference_paths="   ", additional_edit_scope="")

    # When: the generator receives those answers as empty arguments.
    result = run_generator(repo_root, template_dir, isolated_env, inputs=inputs)

    # Then: every optional answer is stored as the canonical Korean empty value.
    assert result.returncode == 0, result.stderr
    content = (destination_of(result) / "README.md").read_text(encoding="utf-8")
    assert "starter=없음" in content
    assert "refs=없음" in content
    assert "scope=없음" in content


def test_rejects_non_ascii_slug_before_creating_task(
    repo_root: Path,
    template_dir: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a slug containing Korean characters.
    inputs = GeneratorInputs(task_slug="보안-문서")

    # When: the generator receives the invalid slug.
    result = run_generator(repo_root, template_dir, isolated_env, inputs=inputs)

    # Then: it rejects the slug without creating any document.
    assert result.returncode != 0
    assert generated_files(repo_root) == frozenset()


def test_does_not_overwrite_existing_documents(
    repo_root: Path,
    template_dir: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the destination already contains a user README.md.
    marker = repo_root / "README.md"
    marker.write_text("keep", encoding="utf-8")

    # When: the generator targets the same folder.
    result = run_generator(repo_root, template_dir, isolated_env)

    # Then: it refuses to overwrite and creates nothing else.
    assert result.returncode != 0
    assert "README.md" in result.stderr
    assert marker.read_text(encoding="utf-8") == "keep"
    assert generated_files(repo_root) == frozenset({"README.md"})


@pytest.mark.parametrize("variant", ["global", "sub"])
def test_bundled_template_creates_exact_default_core(
    repo_root: Path,
    isolated_env: dict[str, str],
    variant: str,
) -> None:
    # Given: the repository's bundled task template.
    if variant == "sub":
        make_sub_repository(repo_root)

    # When: the generator initializes a task from that template.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: it creates the shared documents and agent instructions.
    assert result.returncode == 0, result.stderr
    destination = destination_of(result)
    if variant == "global":
        assert destination == repo_root
    else:
        assert destination.parent == repo_root / "docs"
    assert generated_files(destination) == EXPECTED_CORE_PATHS


def test_bundled_template_initializes_reference_driven_work(
    repo_root: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a task with explicit reference paths.
    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: ROADMAP briefs the same active work and next action owned by PROGRESS.
    assert result.returncode == 0, result.stderr
    task_dir = destination_of(result)
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
    repo_root: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a task without a reference path.
    inputs = GeneratorInputs(reference_paths="없음")

    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env, inputs=inputs)

    # Then: the next action starts by defining work units and completion criteria.
    assert result.returncode == 0, result.stderr
    task_dir = destination_of(result)
    roadmap = (task_dir / "ROADMAP.md").read_text(encoding="utf-8")
    progress = (task_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "필요한 작업 단위와 완료 기준을 구체화한다" in roadmap
    assert "필요한 작업 단위와 완료 기준을 구체화한다" in progress
    assert "적용 지침과 진입 문서를 먼저 읽고" not in progress


def test_bundled_roadmap_is_a_single_briefing_view(
    repo_root: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a generated workspace that has only its initial work unit.
    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: ROADMAP answers the briefing questions without becoming a ledger.
    assert result.returncode == 0, result.stderr
    roadmap = (destination_of(result) / "ROADMAP.md").read_text(encoding="utf-8")
    assert "30초" in roadmap
    assert "지금 어디까지" in roadmap
    assert "무엇을 어떤 순서로" in roadmap
    assert "나는 지금 무엇을" in roadmap
    assert "변경 이력" not in roadmap
    assert len(roadmap.splitlines()) <= 80


def test_bundled_progress_is_the_detailed_status_ledger(
    repo_root: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a generated workspace with one active work unit.
    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: PROGRESS owns work status, active detail, outcomes, and resumability.
    assert result.returncode == 0, result.stderr
    progress = (destination_of(result) / "PROGRESS.md").read_text(encoding="utf-8")
    assert "작업 단위 상태 장부" in progress
    assert "진행 중 작업 상세" in progress
    assert "완료 결과" in progress
    assert "보류·재개" in progress
    assert "변경 이력" in progress


def test_bundled_roadmap_defers_mermaid_until_flow_is_complex(
    repo_root: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a generated workspace with a single linear work unit.
    # When: the bundled template is rendered.
    result = run_generator(repo_root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: it explains the flowchart trigger without generating an empty chart.
    assert result.returncode == 0, result.stderr
    roadmap = (destination_of(result) / "ROADMAP.md").read_text(encoding="utf-8")
    assert "flowchart" in roadmap
    assert "분기" in roadmap
    assert "병렬" in roadmap
    assert "게이트" in roadmap
    assert "원복" in roadmap
    assert "```mermaid" not in roadmap
