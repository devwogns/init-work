from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from generator_helpers import (
    git_init,
    load_generator_module,
    make_directory_link,
    remove_directory_link,
)

generator = load_generator_module()
NOW = datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)


def resolve(
    run_dir: Path,
    home: Path,
    *,
    target: str | None = None,
    slug: str = "log-level",
):
    return generator.resolve_placement(
        run_dir=run_dir,
        target=target,
        slug=slug,
        now=NOW,
        home=home,
    )


@pytest.mark.parametrize("instruction", ["AGENTS.md", "CLAUDE.md"])
def test_auto_uses_dated_docs_folder_when_root_has_instructions(
    tmp_path: Path,
    isolated_env: dict[str, str],
    instruction: str,
) -> None:
    # Given: a repository whose root already has one agent instruction file.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / instruction).write_text("existing", encoding="utf-8")
    (repo / "src").mkdir()

    # When: auto mode runs from a nested folder.
    placement = resolve(repo / "src", Path(isolated_env["HOME"]))

    # Then: the sub template goes to docs/<KST date>-<slug>/ with local exclusions.
    destination = repo / "docs" / "2026-10-26-log-level"
    assert placement.mode == "auto"
    assert placement.destination == destination
    assert placement.repo_root == repo
    assert placement.template == "sub"
    assert placement.work_folder == "`docs/2026-10-26-log-level/`"
    assert placement.git_init is None
    assert placement.create_dirs == (
        repo / "docs",
        destination,
        destination / "evidence",
    )
    assert placement.exclude_rules == (
        "/docs/2026-10-26-log-level/AGENTS.md",
        "/docs/2026-10-26-log-level/CLAUDE.md",
    )


def test_auto_uses_repository_root_when_instructions_are_absent(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository without root agent instructions.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)

    # When: auto mode runs at the root.
    placement = resolve(repo, Path(isolated_env["HOME"]))

    # Then: the global template goes to the root without exclusions.
    assert placement.destination == repo
    assert placement.template == "global"
    assert placement.work_folder == generator.GLOBAL_WORK_FOLDER
    assert placement.exclude_file is None
    assert placement.exclude_rules == ()
    assert placement.create_dirs == (repo / "evidence",)


def test_auto_initializes_git_when_run_directory_is_not_a_repository(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a plain folder that contains another repository one level down.
    run_dir = tmp_path / "plain"
    git_init(run_dir / "inner", isolated_env)

    # When: auto mode runs there.
    placement = resolve(run_dir, Path(isolated_env["HOME"]))

    # Then: Git is initialized there for the global template, with a warning.
    assert placement.destination == run_dir
    assert placement.template == "global"
    assert placement.git_init == run_dir
    assert placement.repo_root == run_dir
    assert placement.nested_repositories == (run_dir / "inner",)


def test_manual_root_subfolder_and_outside_paths_follow_the_decision_table(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository, an existing subfolder, and a missing outside folder.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "work").mkdir()
    outside = tmp_path / "outside" / "new"

    # When: each path is entered manually.
    at_root = resolve(tmp_path, home, target=str(repo))
    in_subfolder = resolve(tmp_path, home, target=str(repo / "work"))
    missing_in_repo = resolve(tmp_path, home, target="repo/new/sub")
    outside_repo = resolve(tmp_path, home, target=str(outside))

    # Then: root is global, subfolders are sub, outside paths initialize Git.
    assert (at_root.mode, at_root.template, at_root.git_init) == ("manual", "global", None)
    assert in_subfolder.template == "sub"
    assert in_subfolder.work_folder == "`work/`"
    assert missing_in_repo.template == "sub"
    assert missing_in_repo.work_folder == "`new/sub/`"
    assert missing_in_repo.create_dirs == (
        repo / "new",
        repo / "new" / "sub",
        repo / "new" / "sub" / "evidence",
    )
    assert outside_repo.template == "global"
    assert outside_repo.git_init == outside
    assert outside_repo.create_dirs == (
        tmp_path / "outside",
        outside,
        outside / "evidence",
    )


def test_manual_rejects_files_git_metadata_and_protected_locations(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a file, a path below a file, a .git path, and the home folder.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    existing_file = tmp_path / "file.txt"
    existing_file.write_text("keep", encoding="utf-8")

    # When / Then: every invalid target is rejected before any side effect.
    for target in (
        str(existing_file),
        str(existing_file / "child"),
        str(repo / ".git" / "work"),
        str(home),
        "~",
    ):
        with pytest.raises(generator.TaskCreationError):
            resolve(tmp_path, home, target=target)
    assert not (home / ".git").exists()


def test_auto_rejects_home_as_project_root(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: auto mode started from the home folder.
    home = Path(isolated_env["HOME"])

    # When / Then: Git is not initialized in home.
    with pytest.raises(generator.TaskCreationError):
        resolve(home, home)


def test_auto_rejects_docs_file_in_parent_path(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository with root instructions and a regular file named docs.
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    (repo / "docs").write_text("not a folder", encoding="utf-8")

    # When / Then: the parent path check refuses the dated folder.
    with pytest.raises(generator.TaskCreationError):
        resolve(repo, Path(isolated_env["HOME"]))


def test_placement_warns_about_ignored_committed_documents(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository ignoring docs/ and a plain folder ignoring README.md.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    (repo / ".gitignore").write_text("docs/\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".gitignore").write_text("README.md\n", encoding="utf-8")

    # When: both placements are resolved.
    sub = resolve(repo, home)
    initialized = resolve(plain, home)

    # Then: only committed documents that Git would ignore are reported.
    assert sub.ignored_documents == (
        "README.md",
        "PROGRESS.md",
        "ROADMAP.md",
        "decisions.md",
        "evidence/README.md",
    )
    assert initialized.ignored_documents == ("README.md", "evidence/README.md")


def test_exclude_rules_are_escaped_and_skip_existing_lines(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a subfolder with pattern characters and one rule already present.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text("/a b/한글 \\[x] #y/AGENTS.md\n", encoding="utf-8")

    # When: the subfolder is entered manually.
    placement = resolve(tmp_path, home, target=str(repo / "a b" / "한글 [x] #y"))

    # Then: only the missing escaped rule is planned.
    assert placement.exclude_file == exclude
    assert placement.exclude_rules == ("/a b/한글 \\[x] #y/CLAUDE.md",)


def test_fingerprint_is_stable_and_tracks_placement_changes(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository without root instructions.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)

    # When: the placement is resolved twice, then again after AGENTS.md appears.
    first = resolve(repo, home)
    second = resolve(repo, home)
    (repo / "AGENTS.md").write_text("new", encoding="utf-8")
    changed = resolve(repo, home)

    # Then: identical judgments share a fingerprint and changed ones do not.
    assert first.fingerprint() == second.fingerprint()
    assert changed.fingerprint() != first.fingerprint()
    assert first.to_json()["fingerprint"] == first.fingerprint()


def test_git_ignore_check_failure_stops_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository whose index is corrupt, so check-ignore fails while rev-parse works.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    (repo / ".git" / "index").write_bytes(b"corrupt")
    exclude = repo / ".git" / "info" / "exclude"
    before = (sorted(repo.iterdir()), exclude.read_bytes())

    # When / Then: the Git error stops the judgment instead of reading as "not ignored".
    for target in (None, str(repo / "work")):
        with pytest.raises(generator.TaskCreationError, match="ignore"):
            resolve(repo, home, target=target)
    assert (sorted(repo.iterdir()), exclude.read_bytes()) == before


def test_missing_exclude_parent_is_planned_as_a_directory(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository whose .git/info folder has been removed.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    shutil.rmtree(repo / ".git" / "info")
    (repo / "work").mkdir()

    # When: a subfolder placement is resolved.
    placement = resolve(tmp_path, home, target=str(repo / "work"))

    # Then: the exclude parent is an approved folder (and so part of the fingerprint), not created yet.
    assert placement.exclude_file == repo / ".git" / "info" / "exclude"
    assert placement.create_dirs == (repo / "work" / "evidence", repo / ".git" / "info")
    assert not (repo / ".git" / "info").exists()


def test_plan_ignores_external_git_location_variables(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: GIT_DIR and GIT_OBJECT_DIRECTORY pointing at paths that do not exist.
    home = Path(isolated_env["HOME"])
    external = tmp_path / "external"
    monkeypatch.setenv("GIT_DIR", str(external / "repo.git"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(external / "objects"))
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / ".gitignore").write_text("README.md\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()

    # When: a repository and a plain folder are judged.
    in_repo = resolve(repo, home)
    initialized = resolve(plain, home)

    # Then: the repository is still seen, the probe stays in the temp folder, nothing external appears.
    assert in_repo.git_init is None
    assert in_repo.ignored_documents == ("README.md", "evidence/README.md")
    assert initialized.git_init == plain
    assert not external.exists()
    assert not (plain / ".git").exists()


@pytest.mark.parametrize(
    "variable",
    [
        "GIT_LITERAL_PATHSPECS",
        "GIT_GLOB_PATHSPECS",
        "GIT_NOGLOB_PATHSPECS",
        "GIT_ICASE_PATHSPECS",
    ],
)
def test_plan_ignores_external_pathspec_variables(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    # Given: an inherited pathspec variable that would override the magic the
    # generator writes, and work/AGENTS.md tracked but deleted from disk.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    tracked = repo / "tracked"
    tracked.mkdir()
    (tracked / "AGENTS.md").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(repo), "add", "--", "tracked/AGENTS.md"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    (tracked / "AGENTS.md").unlink()
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv(variable, "1")

    # When: a plain folder and a fresh subfolder are planned.
    initialized = resolve(plain, home)
    sub = resolve(tmp_path, home, target=str(repo / "work"))

    # Then: both succeed, and the tracked instruction is still found.
    assert initialized.git_init == plain
    assert sub.template == "sub"
    with pytest.raises(generator.TaskCreationError, match="tracked"):
        resolve(tmp_path, home, target=str(tracked))


def test_fingerprint_changes_when_destination_link_is_retargeted(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a link used as the manual target, first pointing at repository A.
    home = Path(isolated_env["HOME"])
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    git_init(repo_a, isolated_env)
    git_init(repo_b, isolated_env)
    link = tmp_path / "link"
    if not make_directory_link(link, repo_a):
        pytest.skip("directory links are unavailable in this environment")
    try:
        approved = resolve(tmp_path, home, target=str(link))
        remove_directory_link(link)
        assert make_directory_link(link, repo_b)

        # When: the same target is judged again after the link moved to repository B.
        retargeted = resolve(tmp_path, home, target=str(link))
    finally:
        if os.path.lexists(link):
            remove_directory_link(link)

    # Then: the fingerprint differs even though the typed destination did not.
    assert approved.destination == retargeted.destination == link
    assert approved.fingerprint() != retargeted.fingerprint()


def test_exclude_parent_that_is_a_file_is_rejected_before_side_effects(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a repository whose .git/info is a regular file.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    shutil.rmtree(repo / ".git" / "info")
    (repo / ".git" / "info").write_text("not a folder", encoding="utf-8")
    before = sorted(repo.iterdir())

    # When / Then: the subfolder placement is refused and nothing is created.
    with pytest.raises(generator.TaskCreationError):
        resolve(tmp_path, home, target=str(repo / "work"))
    assert sorted(repo.iterdir()) == before


def test_gitignore_reinclude_of_local_instructions_stops_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: an existing folder whose .gitignore re-includes both local instructions.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    folder = repo / "work"
    folder.mkdir()
    gitignore = folder / ".gitignore"
    gitignore.write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    exclude = repo / ".git" / "info" / "exclude"
    exclude_before = exclude.read_bytes() if exclude.exists() else None

    # When / Then: planning stops because info/exclude could not keep them local.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))
    assert gitignore.read_bytes() == b"!AGENTS.md\n!CLAUDE.md\n"
    assert (exclude.read_bytes() if exclude.exists() else None) == exclude_before


def test_info_exclude_negation_is_overridden_by_appended_rules(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: no .gitignore, but info/exclude already re-includes both instructions.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When: a subfolder is planned.
    placement = resolve(tmp_path, home, target=str(repo / "work"))

    # Then: planning succeeds because the appended rules come last in info/exclude.
    assert placement.template == "sub"
    assert placement.exclude_rules == (
        generator.escape_exclude_rule("work/AGENTS.md"),
        generator.escape_exclude_rule("work/CLAUDE.md"),
    )
    assert exclude.read_bytes() == b"!AGENTS.md\n!CLAUDE.md\n"


def test_later_info_exclude_negation_still_stops_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: info/exclude already holds the planned rules, followed by a negation.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    content = (
        generator.escape_exclude_rule("work/AGENTS.md").encode("utf-8")
        + b"\n"
        + generator.escape_exclude_rule("work/CLAUDE.md").encode("utf-8")
        + b"\n!AGENTS.md\n"
    )
    exclude.write_bytes(content)

    # When / Then: nothing new would be appended, so the negation wins and planning stops.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(repo / "work"))
    assert exclude.read_bytes() == content


def git_config(repo: Path, environment: dict[str, str], *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(repo), "config", *arguments),
        check=True,
        capture_output=True,
        env=dict(environment),
    )


@pytest.mark.parametrize(
    ("ignore_case", "expect_refusal"),
    [("true", True), ("false", False)],
)
def test_verification_mirrors_target_ignorecase(
    tmp_path: Path,
    isolated_env: dict[str, str],
    ignore_case: str,
    expect_refusal: bool,
) -> None:
    # Given: a .gitignore negation that only matches when the target ignores case.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    git_config(repo, isolated_env, "core.ignorecase", ignore_case)
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!agents.md\n!claude.md\n")

    # When / Then: the planning verdict follows the target repository's setting.
    if expect_refusal:
        with pytest.raises(generator.TaskCreationError, match="re-includes"):
            resolve(tmp_path, home, target=str(folder))
    else:
        placement = resolve(tmp_path, home, target=str(folder))
        assert placement.template == "sub"


def test_verification_mirrors_target_excludes_file(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the target's own excludes file hides the whole folder, so the
    # .gitignore negation inside it can never re-include anything.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    excludes = tmp_path / "excludes"
    excludes.write_bytes(b"work/\n")
    git_config(repo, isolated_env, "core.excludesFile", str(excludes))
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When: the folder is planned.
    placement = resolve(tmp_path, home, target=str(folder))

    # Then: planning succeeds exactly like the real check-ignore would.
    assert placement.template == "sub"


def test_verification_does_not_inherit_global_excludes_the_target_overrides(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a global excludes file hides the folder, but the target repository
    # overrides it with an empty file, so its .gitignore negation applies.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    global_excludes = tmp_path / "global-excludes"
    global_excludes.write_bytes(b"work/\n")
    git_config(repo, isolated_env, "--global", "core.excludesFile", str(global_excludes))
    local_excludes = tmp_path / "local-excludes"
    local_excludes.write_bytes(b"")
    git_config(repo, isolated_env, "--local", "core.excludesFile", str(local_excludes))
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When / Then: planning stops because the real repository would not ignore them.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))


def test_tracked_local_instruction_deleted_from_work_tree_stops_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: work/AGENTS.md is tracked by Git but no longer on disk, so no ignore
    # rule could ever keep a regenerated file local.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    folder = repo / "work"
    folder.mkdir()
    (folder / "AGENTS.md").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(repo), "add", "--", "work/AGENTS.md"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    (folder / "AGENTS.md").unlink()
    exclude = repo / ".git" / "info" / "exclude"
    exclude_before = exclude.read_bytes() if exclude.exists() else None

    # When / Then: planning stops and nothing is written.
    with pytest.raises(generator.TaskCreationError, match="tracked"):
        resolve(tmp_path, home, target=str(folder))
    assert (exclude.read_bytes() if exclude.exists() else None) == exclude_before
    assert sorted(folder.iterdir()) == []


def test_verification_keeps_leading_space_in_excludes_file_path(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the target's excludes file name starts with a space and hides the
    # folder, while its space-stripped twin is empty.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / " excludes").write_bytes(b"work/\n")
    (repo / "excludes").write_bytes(b"")
    git_config(repo, isolated_env, "core.excludesFile", " excludes")
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When: the folder is planned.
    placement = resolve(tmp_path, home, target=str(folder))

    # Then: the real excludes file was consulted, so planning succeeds.
    assert placement.template == "sub"


@pytest.mark.parametrize(
    ("ignore_case", "expect_refusal"),
    [("true", True), ("false", False)],
)
def test_tracked_instruction_lookup_follows_target_ignorecase(
    tmp_path: Path,
    isolated_env: dict[str, str],
    ignore_case: str,
    expect_refusal: bool,
) -> None:
    # Given: a lower-case work/agents.md is tracked but deleted from disk.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    git_config(repo, isolated_env, "core.ignorecase", ignore_case)
    folder = repo / "work"
    folder.mkdir()
    (folder / "agents.md").write_text("tracked\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(repo), "add", "--", "work/agents.md"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    (folder / "agents.md").unlink()

    # When / Then: only a case-insensitive repository treats it as the same file.
    if expect_refusal:
        with pytest.raises(generator.TaskCreationError, match="tracked"):
            resolve(tmp_path, home, target=str(folder))
    else:
        assert resolve(tmp_path, home, target=str(folder)).template == "sub"


def test_verification_uses_git_default_when_target_ignorecase_is_unset(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: the target has no core.ignorecase, so Git matches case-sensitively and
    # a lower-case negation never re-includes AGENTS.md, even where git init
    # would detect a case-insensitive file system.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    subprocess.run(
        ("git", "-C", str(repo), "config", "--unset", "core.ignorecase"),
        capture_output=True,
        env=dict(isolated_env),
        check=False,
    )
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!agents.md\n!claude.md\n")

    # When: the folder is planned.
    placement = resolve(tmp_path, home, target=str(folder))

    # Then: planning succeeds exactly like the real check-ignore would.
    assert placement.template == "sub"


def test_verification_ignores_settings_from_the_users_init_template(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a Git template whose config hides work/, set up after the target was
    # created, so only a fresh scratch repository would pick it up.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    hide = tmp_path / "hide"
    hide.write_bytes(b"work/\n")
    template = tmp_path / "git-template"
    template.mkdir()
    (template / "config").write_text(
        f"[core]\n\texcludesFile = {hide.as_posix()}\n",
        encoding="utf-8",
    )
    git_config(repo, isolated_env, "--global", "init.templateDir", str(template))
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When / Then: planning stops because the target itself would re-include them.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))


def test_verification_ignores_conditional_settings_that_match_only_the_scratch_side(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a global includeIf that hides work/ on branch main, a fresh repository
    # defaulting to main, and a target on another branch with no excludes file.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    subprocess.run(
        ("git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/feature"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    hide = tmp_path / "hide"
    hide.write_bytes(b"work/\n")
    include = tmp_path / "include"
    include.write_text(f"[core]\n\texcludesFile = {hide.as_posix()}\n", encoding="utf-8")
    git_config(repo, isolated_env, "--global", "init.defaultBranch", "main")
    git_config(repo, isolated_env, "--global", "includeIf.onbranch:main.path", str(include))
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When / Then: planning stops because the target itself would re-include them.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))


@pytest.mark.parametrize("injection", ["count", "parameters"])
def test_verification_ignores_runtime_config_that_matches_only_the_scratch_side(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    injection: str,
) -> None:
    # Given: settings injected through the environment that hide work/ on branch
    # main, a fresh repository defaulting to main, and a target on another branch.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    subprocess.run(
        ("git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/feature"),
        check=True,
        capture_output=True,
        env=dict(isolated_env),
    )
    hide = tmp_path / "hide"
    hide.write_bytes(b"work/\n")
    include = tmp_path / "include"
    include.write_text(f"[core]\n\texcludesFile = {hide.as_posix()}\n", encoding="utf-8")
    settings = [
        ("init.defaultBranch", "main"),
        ("includeIf.onbranch:main.path", include.as_posix()),
    ]
    if injection == "count":
        monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(settings)))
        for index, (key, value) in enumerate(settings):
            monkeypatch.setenv(f"GIT_CONFIG_KEY_{index}", key)
            monkeypatch.setenv(f"GIT_CONFIG_VALUE_{index}", value)
    else:
        monkeypatch.setenv(
            "GIT_CONFIG_PARAMETERS",
            " ".join(f"'{key}={value}'" for key, value in settings),
        )
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When / Then: planning stops because the target itself would re-include them.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))


def test_target_settings_are_read_from_the_target_despite_git_config_variable(
    tmp_path: Path,
    isolated_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: GIT_CONFIG names a file that hides work/; git config would read only
    # that file, while check-ignore in the target ignores the variable entirely.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    hide = tmp_path / "hide"
    hide.write_bytes(b"work/\n")
    other_config = tmp_path / "other-config"
    other_config.write_text(f"[core]\n\texcludesFile = {hide.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG", str(other_config))
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    exclude = repo / ".git" / "info" / "exclude"
    exclude_before = exclude.read_bytes() if exclude.exists() else None

    # When / Then: planning stops because the target itself would re-include them.
    with pytest.raises(generator.TaskCreationError, match="re-includes"):
        resolve(tmp_path, home, target=str(folder))
    assert (exclude.read_bytes() if exclude.exists() else None) == exclude_before


def test_verification_keeps_the_default_global_ignore_file(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: no core.excludesFile anywhere, and Git's default global ignore file
    # hides work/, so the .gitignore negation inside it can never re-include.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    default_ignore = Path(isolated_env["XDG_CONFIG_HOME"]) / "git" / "ignore"
    default_ignore.parent.mkdir(parents=True)
    default_ignore.write_bytes(b"work/\n")
    folder = repo / "work"
    folder.mkdir()
    (folder / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")

    # When: the folder is planned.
    placement = resolve(tmp_path, home, target=str(folder))

    # Then: planning succeeds exactly like the real check-ignore would.
    assert placement.template == "sub"


def skip_worktree(repo: Path, environment: dict[str, str], path: str) -> None:
    for arguments in (("add", "--", path), ("update-index", "--skip-worktree", "--", path)):
        subprocess.run(
            ("git", "-C", str(repo), *arguments),
            check=True,
            capture_output=True,
            env=dict(environment),
        )
    (repo / path).unlink()


def test_index_only_gitignore_above_the_folder_stops_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: work/.gitignore re-includes both instructions but is skip-worktree and
    # missing from disk, so Git reads it from the index (as sparse checkout does).
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "work").mkdir()
    (repo / "work" / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    skip_worktree(repo, isolated_env, "work/.gitignore")
    exclude = repo / ".git" / "info" / "exclude"
    exclude_before = exclude.read_bytes() if exclude.exists() else None

    # When / Then: planning stops and nothing is written.
    with pytest.raises(generator.TaskCreationError, match="sparse"):
        resolve(tmp_path, home, target=str(repo / "work" / "new"))
    assert (exclude.read_bytes() if exclude.exists() else None) == exclude_before
    assert sorted((repo / "work").iterdir()) == []


def test_index_only_gitignore_elsewhere_does_not_stop_placement(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    # Given: a skip-worktree .gitignore missing from disk in an unrelated folder.
    home = Path(isolated_env["HOME"])
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    (repo / "other").mkdir()
    (repo / "other" / ".gitignore").write_bytes(b"!AGENTS.md\n!CLAUDE.md\n")
    skip_worktree(repo, isolated_env, "other/.gitignore")

    # When: a folder outside it is planned.
    placement = resolve(tmp_path, home, target=str(repo / "work" / "new"))

    # Then: Git never reads that file for the folder, so planning succeeds.
    assert placement.template == "sub"
