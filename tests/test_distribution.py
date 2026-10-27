from __future__ import annotations

import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).parents[1]
README: Final = (ROOT / "README.md").read_text(encoding="utf-8")
SEMVER: Final = r"\d+\.\d+\.\d+"


def readme_export_list() -> set[str]:
    block = re.search(r"\$skillFiles = @\((.*?)\n\)", README, re.DOTALL)
    assert block is not None
    return set(re.findall(r"'([^']+)'", block.group(1)))


def distribution_files() -> set[str]:
    files = {".gitignore", "SKILL.md", "README.md", "CHANGELOG.md"}
    for folder in ("agents", "scripts", "assets", "tests"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files.add(path.relative_to(ROOT).as_posix())
    return files


def test_readme_export_list_matches_distribution_files() -> None:
    # Given: the README export list and the files that make up the skill.
    # When / Then: they are identical, so a local install copies every needed file.
    assert readme_export_list() == distribution_files()


def skill_version() -> str:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = re.match(r"---\n(.*?)\n---\n", skill, re.DOTALL)
    assert frontmatter is not None
    version = re.search(
        rf'^metadata:\n(?:  .*\n)*?  version: "({SEMVER})"$',
        frontmatter.group(1) + "\n",
        re.MULTILINE,
    )
    assert version is not None
    return version.group(1)


def test_skill_version_matches_latest_changelog_release() -> None:
    # Given: the version in SKILL.md and the release headings in CHANGELOG.md.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = re.findall(rf"^## \[({SEMVER})\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)

    # When / Then: the newest release is the version the skill declares.
    assert "## [Unreleased]" in changelog
    assert releases, "CHANGELOG.md has no release heading"
    assert releases[0] == skill_version()


def test_readme_installs_from_repository_address() -> None:
    # Given / When / Then: install commands name the real repository, not a placeholder.
    assert "OWNER/REPO" not in README
    assert "npx skills add devwogns/init-work --skill init-work" in README
    assert "github.com/devwogns/init-work/tree/v" in README


def test_readme_describes_path_selection_instead_of_fixed_tasks_folder() -> None:
    # Given / When / Then: the removed fixed location and option are gone.
    assert "tasks/<" not in README
    assert "--repo-root" not in README
    for marker in ("--plan", "--confirm", "--run-dir", "--target", "{{WORK_FOLDER}}"):
        assert marker in README, marker
    assert "{{TASK_SLUG}}" not in README
