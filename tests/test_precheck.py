from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from generator_helpers import (
    BUNDLED_TEMPLATE_DIR,
    GeneratorInputs,
    git_init,
    load_generator_module,
    make_directory_link,
    run_generator,
    snapshot,
)

if TYPE_CHECKING:
    from click.testing import Result

generator = load_generator_module()


def generate_in_process(run_dir: Path, target: Path) -> Result:
    """Plan and generate through typer's CliRunner so module monkeypatches apply."""
    app = typer.Typer()
    app.command()(generator.main)
    runner = CliRunner()
    common = ["--run-dir", str(run_dir), "--target", str(target), "--task-slug", "documentation"]
    planned = runner.invoke(app, ["--plan", *common])
    assert planned.exit_code == 0, planned.output
    fingerprint = json.loads(planned.output)["fingerprint"]
    return runner.invoke(
        app,
        [
            *common,
            "--template-dir",
            str(BUNDLED_TEMPLATE_DIR),
            "--task-name",
            "문서 정리",
            "--task-summary",
            "문서를 정리한다.",
            "--start-name",
            "없음",
            "--reference-paths",
            "없음",
            "--additional-edit-scope",
            "없음",
            "--confirm",
            fingerprint,
        ],
    )


def test_evidence_file_stops_before_git_init(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a non-repository folder holding a regular file named evidence.
    target = tmp_path / "project"
    target.mkdir()
    (target / "evidence").write_text("keep", encoding="utf-8")
    before = snapshot(target)

    # When: the folder is entered manually.
    result = run_generator(tmp_path, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(target))

    # Then: generation stops without git init or any new file.
    assert result.returncode != 0
    assert "evidence" in result.stderr
    assert not (target / ".git").exists()
    assert snapshot(target) == before


@pytest.mark.parametrize("points_to_self", [False, True])
def test_evidence_link_stops_generation(
    tmp_path: Path,
    isolated_env: dict[str, str],
    points_to_self: bool,
) -> None:
    # Given: an existing repository subfolder whose evidence/ is a directory link.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    target = repo / "work"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link_target = target if points_to_self else outside
    if not make_directory_link(target / "evidence", link_target):
        pytest.skip("directory links are unavailable in this environment")
    exclude = repo / ".git" / "info" / "exclude"
    before_exclude = exclude.read_bytes()
    before_outside = snapshot(outside)

    # When: the subfolder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(target))

    # Then: nothing is written through or around the link.
    assert result.returncode != 0
    assert "evidence" in result.stderr
    assert sorted(path.name for path in target.iterdir()) == ["evidence"]
    assert snapshot(outside) == before_outside
    assert exclude.read_bytes() == before_exclude


def test_global_placement_rejects_additional_edit_scope(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an empty repository that resolves to the global template.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    before = snapshot(repo)

    # When: an additional edit scope other than 없음 is passed.
    result = run_generator(
        repo,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        inputs=GeneratorInputs(additional_edit_scope="`src/`"),
    )

    # Then: generation is refused without changes.
    assert result.returncode != 0
    assert "additional edit scope" in result.stderr
    assert snapshot(repo) == before
    assert not (repo / "evidence").exists()


def test_failure_after_side_effects_reports_without_rollback(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a missing outside folder and a writer that creates the third document,
    # writes part of it, and then fails. It follows the writer contract: begin only
    # after the exclusive open succeeded.
    target = tmp_path / "project"
    original_write = generator._write_document
    calls: list[Path] = []

    def failing_write(path: Path, content: str, effects: object) -> None:
        calls.append(path)
        if len(calls) == 3:
            with path.open("x", encoding="utf-8") as stream:
                effects.begin(f"document {path}")
                stream.write(content[:10])
            raise OSError("injected write failure")
        original_write(path, content, effects)

    monkeypatch.setattr(generator, "_write_document", failing_write)

    # When: generation runs and the injected failure happens mid-write.
    result = generate_in_process(tmp_path, target)

    # Then: it exits non-zero, lists what it created, and deletes nothing.
    assert result.exit_code == 1
    assert "injected write failure" in result.output
    assert f"created: directory {target}" in result.output
    assert f"created: git repository {target / '.git'}" in result.output
    assert f"created: document {calls[0]}" in result.output
    assert f"created: document {calls[1]}" in result.output
    assert f"created: document {calls[2]} (incomplete)" in result.output
    assert len(calls) == 3
    assert (target / ".git").is_dir()
    assert calls[0].is_file() and calls[1].is_file() and calls[2].is_file()


def test_file_created_by_another_process_is_not_reported_as_created(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a writer that lets another process win the race for the third document.
    target = tmp_path / "project"
    original_write = generator._write_document
    calls: list[Path] = []

    def racing_write(path: Path, content: str, effects: object) -> None:
        calls.append(path)
        if len(calls) == 3:
            path.write_text("theirs", encoding="utf-8")
        original_write(path, content, effects)

    monkeypatch.setattr(generator, "_write_document", racing_write)

    # When: the exclusive open of the third document fails.
    result = generate_in_process(tmp_path, target)

    # Then: the other process's file is neither listed nor touched.
    assert result.exit_code == 1
    assert "File exists" in result.output
    assert f"created: document {calls[0]}" in result.output
    assert f"created: document {calls[1]}" in result.output
    assert f"created: document {calls[2]}" not in result.output
    assert len(calls) == 3
    assert calls[2].read_text(encoding="utf-8") == "theirs"


def test_unwritable_exclude_file_is_not_reported_as_created(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository with root instructions whose info/exclude cannot be opened for writing.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    os.chmod(exclude, stat.S_IREAD)
    if os.access(exclude, os.W_OK):
        os.chmod(exclude, stat.S_IREAD | stat.S_IWRITE)
        pytest.skip("info/exclude cannot be made read-only in this environment")

    # When: generation reaches the exclude step after creating the folders.
    try:
        result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)
    finally:
        os.chmod(exclude, stat.S_IREAD | stat.S_IWRITE)

    # Then: the folders are listed, the untouched exclude file is not, and no document exists.
    assert result.returncode != 0
    assert "Permission denied" in result.stderr
    assert f"created: directory {repo / 'docs'}" in result.stderr
    assert "exclude rules" not in result.stderr
    assert "(incomplete)" not in result.stderr
    assert exclude.read_bytes() == before
    assert not any(path.is_file() for path in (repo / "docs").rglob("*"))


def test_exclude_parent_folder_is_reported_when_generation_fails(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a repository without .git/info and a writer that fails before opening anything.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    shutil.rmtree(repo / ".git" / "info")
    target = repo / "work"

    def failing_write(path: Path, content: str, effects: object) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr(generator, "_write_document", failing_write)

    # When: generation fails after the folders and the exclude rules were written.
    result = generate_in_process(tmp_path, target)

    # Then: the info folder made by this run and the exclude rules are both reported.
    info = repo / ".git" / "info"
    assert result.exit_code == 1
    assert f"created: directory {target}" in result.output
    assert f"created: directory {info}" in result.output
    assert (
        f"created: exclude rules {info / 'exclude'}: /work/AGENTS.md, /work/CLAUDE.md"
        in result.output
    )
    assert "(incomplete)" not in result.output
    assert (info / "exclude").read_text(encoding="utf-8") == "/work/AGENTS.md\n/work/CLAUDE.md\n"


def test_bare_repository_target_changes_nothing_when_git_refuses_it(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a bare repository and a global config under which Git refuses to open it.
    bare = tmp_path / "bare.git"
    subprocess.run(
        ("git", "init", "--bare", str(bare)),
        check=True,
        capture_output=True,
        env=isolated_env,
    )
    config = tmp_path / "gitconfig"
    config.write_text("[safe]\n\tbareRepository = explicit\n", encoding="utf-8")
    environment = {**isolated_env, "GIT_CONFIG_GLOBAL": str(config)}
    before = snapshot(bare)

    # When: the bare repository is entered manually.
    result = run_generator(tmp_path, BUNDLED_TEMPLATE_DIR, environment, target=str(bare))

    # Then: generation stops without git init or any new file.
    assert result.returncode != 0
    assert not (bare / ".git").exists()
    assert not (bare / "evidence").exists()
    assert snapshot(bare) == before
