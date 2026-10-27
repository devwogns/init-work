from __future__ import annotations

import json
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
    plan_generator,
    run_generator,
    snapshot,
)


@pytest.mark.parametrize("instruction", ["AGENTS.md", "CLAUDE.md"])
def test_auto_creates_sub_documents_under_dated_docs_folder(
    tmp_path: Path,
    isolated_env: dict[str, str],
    instruction: str,
) -> None:
    # Given: a repository whose root has one agent instruction file.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / instruction).write_text("existing", encoding="utf-8")

    # When: auto mode generates the task.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: seven sub documents live in docs/<KST date>-<slug>/ and are excluded.
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    destination = destination_of(result)
    assert report["status"] == "created"
    assert report["template"] == "sub"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-documentation", destination.name)
    assert destination.name.startswith(report["start_date"])
    assert destination.parent == repo / "docs"
    assert generated_files(destination) == EXPECTED_CORE_PATHS
    assert "로컬 전용" in (destination / "AGENTS.md").read_text(encoding="utf-8")
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert f"/docs/{destination.name}/AGENTS.md" in exclude
    assert f"/docs/{destination.name}/CLAUDE.md" in exclude
    readme = (destination / "README.md").read_text(encoding="utf-8")
    assert f"- 작업 폴더: `docs/{destination.name}/`" in readme
    assert str(tmp_path) not in readme
    assert (repo / instruction).read_text(encoding="utf-8") == "existing"


def test_auto_creates_global_documents_at_repository_root(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an empty repository.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()

    # When: auto mode generates the task from a nested folder.
    (repo / "src").mkdir()
    result = run_generator(repo / "src", BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: global documents are written at the root and exclusions are untouched.
    assert result.returncode == 0, result.stderr
    assert destination_of(result) == repo
    assert json.loads(result.stdout)["template"] == "global"
    assert generated_files(repo) == EXPECTED_CORE_PATHS
    assert exclude.read_bytes() == before
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert "- 작업 폴더: 저장소 전체(저장소 루트 아래 모든 경로)" in readme
    assert "- 추가 편집 허용 범위: 없음" in readme


def test_auto_initializes_git_in_non_repository_folder(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a plain folder.
    plain = tmp_path / "plain"
    plain.mkdir()

    # When: auto mode generates the task there.
    result = run_generator(plain, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: Git is initialized and global documents are written at its root.
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert (plain / ".git").is_dir()
    assert Path(report["git_init"]) == plain
    assert generated_files(plain) == EXPECTED_CORE_PATHS


def test_auto_reuses_existing_empty_dated_folder(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the dated docs folder already exists but holds none of the documents.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    planned = plan_generator(repo, isolated_env)
    destination = Path(json.loads(planned.stdout)["destination"])
    (destination / "evidence").mkdir(parents=True)

    # When: auto mode generates the task.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: the documents are written into the existing folder.
    assert result.returncode == 0, result.stderr
    assert destination_of(result) == destination
    assert generated_files(destination) == EXPECTED_CORE_PATHS


@pytest.mark.parametrize("repository", [True, False])
def test_auto_conflict_changes_nothing(
    tmp_path: Path,
    isolated_env: dict[str, str],
    repository: bool,
) -> None:
    # Given: the root destination already has one of the seven documents.
    root = tmp_path / "root"
    if repository:
        git_init(root, isolated_env)
    else:
        root.mkdir()
    (root / "ROADMAP.md").write_text("keep", encoding="utf-8")
    before = snapshot(root)

    # When: auto mode tries to generate there.
    result = run_generator(root, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: it stops, lists the conflict, and changes nothing (no git init either).
    assert result.returncode != 0
    assert "ROADMAP.md" in result.stderr
    assert snapshot(root) == before
    assert not (root / "evidence").exists()
    assert (root / ".git").exists() == repository


def test_auto_stops_when_docs_is_a_file(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository with root instructions and a regular file named docs.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    (repo / "docs").write_text("not a folder", encoding="utf-8")
    before = snapshot(repo)

    # When: auto mode tries to generate under docs/.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: it stops and changes nothing, including info/exclude.
    assert result.returncode != 0
    assert "docs" in result.stderr
    assert snapshot(repo) == before


def test_auto_rejects_home_folder(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: auto mode started from the (isolated) home folder.
    home = Path(isolated_env["HOME"])
    before = snapshot(home)

    # When: generation is attempted.
    result = run_generator(home, BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: home is not initialized or written.
    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert not (home / ".git").exists()
    assert snapshot(home) == before


def test_auto_rejects_run_directory_inside_git_metadata(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a run directory inside .git.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    before = snapshot(repo)

    # When: auto mode runs from .git.
    result = run_generator(repo / ".git", BUNDLED_TEMPLATE_DIR, isolated_env)

    # Then: nothing is initialized or written.
    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert snapshot(repo) == before
    assert not (repo / ".git" / ".git").exists()


def test_create_stops_when_placement_changed_after_confirmation(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a sub placement confirmed while CLAUDE.md existed at the root.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "CLAUDE.md").write_text("existing", encoding="utf-8")
    fingerprint = json.loads(plan_generator(repo, isolated_env).stdout)["fingerprint"]
    (repo / "CLAUDE.md").unlink()
    before = snapshot(repo)

    # When: generation runs with the stale confirmation.
    result = run_generator(
        repo,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        confirm=fingerprint,
    )

    # Then: it stops before any side effect.
    assert result.returncode != 0
    assert "--plan" in result.stderr
    assert snapshot(repo) == before
    assert not (repo / "docs").exists()


def test_create_requires_confirmation(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an empty repository.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)

    # When: generation runs with a fingerprint that was never planned.
    result = run_generator(
        repo,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        inputs=GeneratorInputs(),
        confirm="0000000000000000",
    )

    # Then: nothing is written.
    assert result.returncode != 0
    assert generated_files(repo) == frozenset()


def test_create_without_confirm_option_is_rejected(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an empty repository.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    before = snapshot(repo)

    # When: generation runs with every option except --confirm.
    result = run_generator(
        repo,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        omit_confirm=True,
    )

    # Then: it fails cleanly and the tree is unchanged.
    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert "--confirm" in result.stderr
    assert snapshot(repo) == before
    assert generated_files(repo) == frozenset()


def test_auto_initializes_git_ignoring_external_git_dir(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a plain folder and an environment whose GIT_DIR points elsewhere.
    plain = tmp_path / "plain"
    plain.mkdir()
    external = tmp_path / "external"
    environment = {**isolated_env, "GIT_DIR": str(external / "repo.git")}

    # When: auto mode generates the task there.
    result = run_generator(plain, BUNDLED_TEMPLATE_DIR, environment)

    # Then: Git is initialized in the folder itself and the external path stays untouched.
    assert result.returncode == 0, result.stderr
    assert (plain / ".git").is_dir()
    assert not external.exists()
    assert generated_files(plain) == EXPECTED_CORE_PATHS
