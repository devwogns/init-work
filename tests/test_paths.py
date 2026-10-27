from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from generator_helpers import (
    git_init,
    load_generator_module,
    make_directory_link,
    remove_directory_link,
)

generator = load_generator_module()


def test_normalize_target_strips_quotes_and_resolves_relative_paths(
    tmp_path: Path,
) -> None:
    # Given: a quoted relative path typed by the user.
    run_dir = tmp_path / "run"

    # When: the path is normalized against the run directory.
    normalized = generator.normalize_target('  "child\\nested"  ', run_dir)

    # Then: quotes are removed, both separators work, and the result is absolute.
    assert normalized == run_dir / "child" / "nested"
    assert normalized.is_absolute()


def test_normalize_target_expands_home_but_not_environment_variables(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a home-relative path and a path containing an environment variable.
    run_dir = tmp_path / "run"
    home = Path(isolated_env["HOME"])

    # When: both inputs are normalized.
    from_home = generator.normalize_target("~/project", run_dir)
    with_variable = generator.normalize_target("$HOME/project", run_dir)

    # Then: only the tilde is expanded.
    assert from_home == home / "project"
    assert with_variable == run_dir / "$HOME" / "project"


def test_normalize_target_rejects_empty_input(tmp_path: Path) -> None:
    # Given: a target made only of quotes and spaces.
    # When / Then: normalization refuses it.
    with pytest.raises(generator.TaskCreationError):
        generator.normalize_target(' "  " ', tmp_path)


def test_is_protected_location_detects_home_and_filesystem_root(
    tmp_path: Path,
) -> None:
    # Given: a home folder, a child of it, and the filesystem root.
    home = tmp_path / "home"
    home.mkdir()

    # When / Then: only home itself and the root are protected.
    assert generator.is_protected_location(home, home)
    assert generator.is_protected_location(Path(tmp_path.anchor), home)
    assert not generator.is_protected_location(home / "project", home)
    assert not generator.is_protected_location(tmp_path, home)


def test_is_protected_location_follows_links_to_filesystem_root(
    tmp_path: Path,
) -> None:
    # Given: a directory link whose target is the filesystem root.
    home = tmp_path / "home"
    home.mkdir()
    alias = tmp_path / "root-alias"
    if not make_directory_link(alias, Path(tmp_path.anchor)):
        pytest.skip("directory links are unavailable in this environment")

    try:
        # When / Then: the alias is protected like the root itself.
        assert generator.is_protected_location(alias, home)
        assert not generator.is_protected_location(alias / "Windows-like-child", home)
    finally:
        # Remove only the link; never recurse into the root it points to.
        remove_directory_link(alias)


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("docs/2026-10-26-log-level/AGENTS.md", "/docs/2026-10-26-log-level/AGENTS.md"),
        ("a b/한글 [x] #y/AGENTS.md", "/a b/한글 \\[x] #y/AGENTS.md"),
        ("star*/q?/back\\slash/CLAUDE.md", "/star\\*/q\\?/back\\\\slash/CLAUDE.md"),
        ("trailing  ", "/trailing\\ \\ "),
    ],
)
def test_escape_exclude_rule_escapes_gitignore_metacharacters(
    relative_path: str,
    expected: str,
) -> None:
    # Given: a repository-relative path that may contain pattern characters.
    # When: it is converted to an anchored exclude rule.
    rule = generator.escape_exclude_rule(relative_path)

    # Then: wildcard, bracket, backslash, and trailing spaces are escaped.
    assert rule == expected


def test_probe_repository_reports_root_and_prefix(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository with a nested folder.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    nested = repo / "a b" / "c"
    nested.mkdir(parents=True)

    # When: the root and the nested folder are probed.
    root_probe = generator.probe_repository(repo)
    nested_probe = generator.probe_repository(nested)

    # Then: Git reports an empty prefix only at the root.
    assert root_probe is not None and nested_probe is not None
    assert root_probe.prefix == ""
    assert nested_probe.prefix == "a b/c/"
    assert nested_probe.root == root_probe.root
    assert nested_probe.exclude_file.name == "exclude"


def test_probe_repository_returns_none_only_for_confirmed_non_repository(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a plain folder with no .git anywhere above it.
    plain = tmp_path / "plain"
    plain.mkdir()

    # When / Then: the folder is reported as a non-repository.
    assert generator.probe_repository(plain) is None


def test_probe_repository_rejects_git_metadata_and_broken_repositories(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a .git directory, a bare repository, and a broken .git file.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ("git", "init", "--bare", str(bare)),
        check=True,
        capture_output=True,
        env=isolated_env,
    )
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: nowhere", encoding="utf-8")

    # When / Then: none of them is treated as a non-repository.
    for directory in (repo / ".git", bare, broken):
        with pytest.raises(generator.TaskCreationError):
            generator.probe_repository(directory)


def test_probe_repository_rejects_link_into_broken_repository(
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
        # When / Then: the broken repository above the real path is not hidden.
        with pytest.raises(generator.TaskCreationError):
            generator.probe_repository(alias)
    finally:
        remove_directory_link(alias)


def test_probe_repository_ignores_external_git_location_variables(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: GIT_DIR and related variables pointing at paths that do not exist.
    external = tmp_path / "external"
    monkeypatch.setenv("GIT_DIR", str(external / "repo.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(external / "tree"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(external / "objects"))
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    plain = tmp_path / "plain"
    plain.mkdir()

    # When: a repository and a plain folder are probed.
    probe = generator.probe_repository(repo)
    none = generator.probe_repository(plain)

    # Then: the variables neither hide the repository nor turn the plain folder into an error.
    assert probe is not None and probe.root == repo
    assert none is None
    assert not external.exists()


def test_probe_repository_rejects_bare_repository_even_when_git_refuses_it(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    # When / Then: rev-parse fails, but the bare metadata still blocks a non-repository verdict.
    for directory in (bare, bare / "refs"):
        with pytest.raises(generator.TaskCreationError):
            generator.probe_repository(directory)

