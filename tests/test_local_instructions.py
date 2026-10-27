from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from generator_helpers import (
    BUNDLED_TEMPLATE_DIR,
    destination_of,
    git_init,
    run_generator,
)


def test_only_agent_instructions_are_ignored(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    git_init(tmp_path / "repo", isolated_env)
    repo = tmp_path / "repo"
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text("# keep existing rule\nlocal.txt", encoding="utf-8")
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)
    assert result.returncode == 0, result.stderr
    task = destination_of(result)
    ignored = subprocess.run(
        (
            "git",
            "-C",
            str(task),
            "check-ignore",
            "--",
            *[path.name for path in task.glob("*.md")],
        ),
        capture_output=True,
        text=True,
        check=False,
        env=isolated_env,
    )
    assert {Path(line).name for line in ignored.stdout.splitlines()} == {
        "AGENTS.md",
        "CLAUDE.md",
    }
    assert exclude.read_text(encoding="utf-8").startswith(
        "# keep existing rule\nlocal.txt\n"
    )
    assert (task / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    before = exclude.read_bytes()
    assert run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env).returncode != 0
    assert exclude.read_bytes() == before


@pytest.mark.parametrize("variant", ["global", "sub"])
def test_shared_document_links_do_not_depend_on_local_instructions(
    tmp_path: Path,
    isolated_env: dict[str, str],
    variant: str,
) -> None:
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    if variant == "sub":
        (repo / "AGENTS.md").write_text("existing", encoding="utf-8")
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)
    assert result.returncode == 0, result.stderr
    task = destination_of(result)
    for name in ("README.md", "PROGRESS.md", "ROADMAP.md", "decisions.md", "evidence/README.md"):
        document = task / name
        for link in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = (document.parent / link).resolve()
            assert target.exists(), (document, link)
            assert target.name not in {"AGENTS.md", "CLAUDE.md"}


def test_global_instructions_are_not_excluded(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    repo = tmp_path / "repo"
    git_init(repo, isolated_env)
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)
    assert result.returncode == 0, result.stderr
    assert exclude.read_bytes() == before
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "공식 에이전트 지침" in agents
    assert "로컬 전용" not in agents


def test_git_file_resolves_exclusions_without_changing_gitignore(
    tmp_path: Path,
    isolated_env: dict[str, str],
) -> None:
    repo = tmp_path / "repo"
    metadata = tmp_path / "git-data"
    subprocess.run(
        ("git", "init", "--separate-git-dir", str(metadata), str(repo)),
        check=True,
        capture_output=True,
        env=isolated_env,
    )
    (repo / ".gitignore").write_text("local.txt\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR, isolated_env)
    assert result.returncode == 0, result.stderr
    assert (repo / ".git").is_file()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "local.txt\n"
    folder = destination_of(result).name
    assert (
        f"/docs/{folder}/AGENTS.md".encode()
        in (metadata / "info/exclude").read_bytes()
    )
