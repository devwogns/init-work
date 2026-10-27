from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from generator_helpers import (
    BUNDLED_TEMPLATE_DIR,
    EXPECTED_CORE_PATHS,
    destination_of,
    generated_files,
    git_init,
    make_directory_link,
    plan_generator,
    remove_directory_link,
    run_generator,
    snapshot,
)


def ignored_documents(directory: Path, environment: dict[str, str]) -> set[str]:
    return {
        name
        for name in EXPECTED_CORE_PATHS
        if subprocess.run(
            ("git", "-C", str(directory), "check-ignore", "-q", "--", name),
            capture_output=True,
            check=False,
            env=environment,
        ).returncode
        == 0
    }


def test_manual_repository_root_creates_global_documents(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an empty repository root and a run directory somewhere else.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    run_dir = tmp_path / "elsewhere"
    run_dir.mkdir()

    # When: the root is entered manually from another folder.
    result = run_generator(run_dir, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(repo))

    # Then: global documents are written at that root.
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert (report["mode"], report["template"]) == ("manual", "global")
    assert destination_of(result) == repo
    assert generated_files(repo) == EXPECTED_CORE_PATHS


@pytest.mark.parametrize("existing", [True, False])
def test_manual_repository_subfolder_creates_sub_documents(
    tmp_path: Path,
    isolated_env: dict[str, str],
    existing: bool,
) -> None:
    # Given: a repository subfolder that is empty or does not exist yet.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    target = repo / "work" / "notes"
    if existing:
        target.mkdir(parents=True)

    # When: the subfolder is entered as a path relative to the run directory.
    result = run_generator(
        repo,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        target="work/notes",
    )

    # Then: sub documents are written and only the instructions are excluded.
    assert result.returncode == 0, result.stderr
    assert destination_of(result) == target
    assert json.loads(result.stdout)["template"] == "sub"
    assert generated_files(target) == EXPECTED_CORE_PATHS
    assert ignored_documents(target, isolated_env) == {"AGENTS.md", "CLAUDE.md"}
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "- 작업 폴더: `work/notes/`" in readme
    assert str(tmp_path) not in readme


def test_manual_outside_repository_initializes_missing_folder(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a missing folder outside any repository, typed with quotes.
    target = tmp_path / "new project" / "app"

    # When: it is entered manually.
    result = run_generator(
        tmp_path,
        BUNDLED_TEMPLATE_DIR,
        isolated_env,
        target=f'"{target}"',
    )

    # Then: the folder is created, Git is initialized, and global documents are written.
    assert result.returncode == 0, result.stderr
    assert destination_of(result) == target
    assert (target / ".git").is_dir()
    assert generated_files(target) == EXPECTED_CORE_PATHS
    assert json.loads(result.stdout)["template"] == "global"


def test_manual_special_character_folder_excludes_only_instructions(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository subfolder with spaces, Korean, brackets, and #.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    target = repo / "a b" / "한글 [x] #y"

    # When: it is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(target))

    # Then: Git ignores exactly AGENTS.md and CLAUDE.md there.
    assert result.returncode == 0, result.stderr
    assert ignored_documents(target, isolated_env) == {"AGENTS.md", "CLAUDE.md"}


def test_manual_nested_repository_uses_its_own_exclude_file(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository nested inside another repository.
    outer = tmp_path / "outer"
    git_init(outer, isolated_env)
    inner = outer / "vendor" / "inner"
    git_init(inner, isolated_env)
    outer_exclude = (outer / ".git" / "info" / "exclude").read_bytes()

    # When: a folder inside the nested repository is entered.
    target = inner / "work [1]"
    result = run_generator(outer, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(target))

    # Then: the nested repository's exclude file receives the rules.
    assert result.returncode == 0, result.stderr
    assert ignored_documents(target, isolated_env) == {"AGENTS.md", "CLAUDE.md"}
    assert (outer / ".git" / "info" / "exclude").read_bytes() == outer_exclude
    assert b"/work \\[1]/AGENTS.md" in (inner / ".git" / "info" / "exclude").read_bytes()


def test_manual_rejects_invalid_paths_without_changes(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an existing file, a path below that file, a .git path, and home.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    existing_file = tmp_path / "file.txt"
    existing_file.write_text("keep", encoding="utf-8")
    home = Path(isolated_env["HOME"])
    before = snapshot(tmp_path)

    # When / Then: each manual path is rejected and nothing changes.
    for target in (
        str(existing_file),
        str(existing_file / "child"),
        str(repo / ".git" / "work"),
        str(home),
    ):
        result = run_generator(tmp_path, BUNDLED_TEMPLATE_DIR, isolated_env, target=target)
        assert result.returncode != 0, target
        assert result.stderr.startswith("error:"), target
        assert snapshot(tmp_path) == before
    assert not (home / ".git").exists()


def test_manual_rejects_link_into_broken_repository_without_changes(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a link whose real path lies under a repository with a broken .git file.
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    (project / ".git").write_text("gitdir: nowhere", encoding="utf-8")
    alias = tmp_path / "alias"
    if not make_directory_link(alias, project / "sub"):
        pytest.skip("directory links are unavailable in this environment")

    try:
        before = snapshot(tmp_path)

        # When: the planner targets the link.
        result = plan_generator(tmp_path, isolated_env, target=str(alias))

        # Then: Git's error stops the run and nothing is initialized or written.
        assert result.returncode == 1
        assert result.stderr.startswith("error:")
        assert snapshot(tmp_path) == before
        assert not (project / "sub" / ".git").exists()
    finally:
        remove_directory_link(alias)


def test_manual_rejects_gitignore_that_reincludes_local_instructions(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an existing folder whose .gitignore re-includes both local instructions.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    before = snapshot(repo)

    # When: the folder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(folder))

    # Then: the run stops with nothing written and the .gitignore untouched.
    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert "re-includes" in result.stderr
    assert snapshot(repo) == before


def test_manual_unrelated_gitignore_still_keeps_instructions_local(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an existing folder whose .gitignore does not touch the instructions.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"*.log\n")

    # When: the folder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(folder))

    # Then: generation succeeds, the .gitignore is unchanged, and both instructions are ignored.
    assert result.returncode == 0, result.stderr
    assert (folder / ".gitignore").read_bytes() == b"*.log\n"
    assert ignored_documents(folder, isolated_env) == {"AGENTS.md", "CLAUDE.md"}


def test_manual_info_exclude_negation_does_not_block_generation(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: no .gitignore, but info/exclude already re-includes both instructions.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    folder = repo / "work"

    # When: the folder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(folder))

    # Then: generation succeeds and the appended rules keep both instructions local.
    assert result.returncode == 0, result.stderr
    assert exclude.read_bytes().startswith(b"!AGENTS.md\n!CLAUDE.md\n")
    assert ignored_documents(folder, isolated_env) == {"AGENTS.md", "CLAUDE.md"}


def test_manual_target_excludes_file_keeps_instructions_local(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the target's excludes file hides the folder despite a .gitignore negation.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    excludes = tmp_path / "excludes"
    excludes.write_bytes(b"work/\n")
    subprocess.run(
        ("git", "-C", str(repo), "config", "core.excludesFile", str(excludes)),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When: the folder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(folder))

    # Then: generation succeeds; the folder-wide exclusion keeps every document
    # ignored, the two instructions included.
    assert result.returncode == 0, result.stderr
    assert {"AGENTS.md", "CLAUDE.md"} <= ignored_documents(folder, isolated_env)


def test_manual_rejects_tracked_local_instruction_without_changes(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: work/CLAUDE.md was committed earlier and only deleted from disk.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    folder = repo / "work"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(repo), "add", "--", "work/CLAUDE.md"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    (folder / "CLAUDE.md").unlink()
    before = snapshot(repo)

    # When: the folder is entered manually.
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env, target=str(folder))

    # Then: the run stops before any side effect because the instruction is tracked.
    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert "tracked" in result.stderr
    assert snapshot(repo) == before
