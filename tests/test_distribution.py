from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from generator_helpers import SKILL_DIR

ROOT: Final = Path(__file__).parents[1]
README: Final = (ROOT / "README.md").read_text(encoding="utf-8")
SEMVER: Final = r"\d+\.\d+\.\d+"


def readme_export_list() -> set[str]:
    block = re.search(r"\$skillFiles = @\((.*?)\n\)", README, re.DOTALL)
    assert block is not None
    return set(re.findall(r"'([^']+)'", block.group(1)))


def distribution_files() -> set[str]:
    return {
        path.relative_to(SKILL_DIR).as_posix()
        for path in SKILL_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_readme_export_list_matches_distribution_files() -> None:
    # Given: the README export list and the files that make up the skill.
    # When / Then: they are identical, so a local install copies every needed file.
    assert readme_export_list() == distribution_files()


def test_skill_folder_carries_no_repository_instructions() -> None:
    # Given: installers copy the whole folder that holds SKILL.md.
    # When / Then: only the skill folder holds SKILL.md, so the repository's own
    # AGENTS.md and CLAUDE.md never reach an install.
    assert not (ROOT / "SKILL.md").exists()
    assert (ROOT / "AGENTS.md").exists()
    for name in ("AGENTS.md", "CLAUDE.md", "README.md", "CHANGELOG.md", ".gitignore"):
        assert not (SKILL_DIR / name).exists(), name


def skill_version() -> str:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
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
    assert "npx skills add https://github.com/devwogns/init-work --skill init-work" in README
    assert "github.com/devwogns/init-work/tree/v" in README


def test_readme_describes_path_selection_instead_of_fixed_tasks_folder() -> None:
    # Given / When / Then: the removed fixed location and option are gone.
    assert "tasks/<" not in README
    assert "--repo-root" not in README
    for marker in ("--plan", "--confirm", "--run-dir", "--target", "{{WORK_FOLDER}}"):
        assert marker in README, marker
    assert "{{TASK_SLUG}}" not in README
