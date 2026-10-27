from __future__ import annotations

import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).parents[1]
README: Final = (ROOT / "README.md").read_text(encoding="utf-8")


def readme_export_list() -> set[str]:
    block = re.search(r"\$skillFiles = @\((.*?)\n\)", README, re.DOTALL)
    assert block is not None
    return set(re.findall(r"'([^']+)'", block.group(1)))


def distribution_files() -> set[str]:
    files = {".gitignore", "SKILL.md", "README.md"}
    for folder in ("agents", "scripts", "assets", "tests"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files.add(path.relative_to(ROOT).as_posix())
    return files


def test_readme_export_list_matches_distribution_files() -> None:
    # Given: the README export list and the files that make up the skill.
    # When / Then: they are identical, so a local install copies every needed file.
    assert readme_export_list() == distribution_files()


def test_readme_describes_path_selection_instead_of_fixed_tasks_folder() -> None:
    # Given / When / Then: the removed fixed location and option are gone.
    assert "tasks/<" not in README
    assert "--repo-root" not in README
    for marker in ("--plan", "--confirm", "--run-dir", "--target", "{{WORK_FOLDER}}"):
        assert marker in README, marker
    assert "{{TASK_SLUG}}" not in README
