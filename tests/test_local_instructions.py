from __future__ import annotations

import re
import subprocess
from pathlib import Path

from test_create_task import BUNDLED_TEMPLATE_DIR, run_generator


def test_only_agent_instructions_are_ignored(tmp_path: Path) -> None:
    subprocess.run(("git", "init", str(tmp_path)), check=True, capture_output=True)
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.write_text("# keep existing rule\nlocal.txt", encoding="utf-8")
    result = run_generator(tmp_path, BUNDLED_TEMPLATE_DIR)
    assert result.returncode == 0, result.stderr
    task = tmp_path / "tasks" / "documentation"
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
    assert run_generator(tmp_path, BUNDLED_TEMPLATE_DIR).returncode != 0
    assert exclude.read_bytes() == before


def test_shared_document_links_do_not_depend_on_local_instructions(
    tmp_path: Path,
) -> None:
    result = run_generator(tmp_path, BUNDLED_TEMPLATE_DIR)
    assert result.returncode == 0, result.stderr
    task = tmp_path / "tasks" / "documentation"
    for document in task.rglob("*.md"):
        if document.name in {"AGENTS.md", "CLAUDE.md"}:
            continue
        for link in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = (document.parent / link).resolve()
            assert target.exists(), (document, link)
            assert target.name not in {"AGENTS.md", "CLAUDE.md"}


def test_git_file_resolves_exclusions_without_changing_gitignore(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    metadata = tmp_path / "git-data"
    subprocess.run(
        ("git", "init", "--separate-git-dir", str(metadata), str(repo)),
        check=True,
        capture_output=True,
    )
    (repo / ".gitignore").write_text("local.txt\n", encoding="utf-8")
    result = run_generator(repo, BUNDLED_TEMPLATE_DIR)
    assert result.returncode == 0, result.stderr
    assert (repo / ".git").is_file()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "local.txt\n"
    assert (
        b"/tasks/documentation/AGENTS.md"
        in (metadata / "info/exclude").read_bytes()
    )
