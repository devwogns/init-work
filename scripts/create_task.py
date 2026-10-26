#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pydantic>=2.11",
#     "typer>=0.16",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run create_task.py --help
# 3. Or make executable and run:
#      chmod +x create_task.py && ./create_task.py --help
# ──────────────────

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

KOREA_TIMEZONE: Final = timezone(timedelta(hours=9), name="KST")
SLUG_PATTERN: Final = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
TOKEN_PATTERN: Final = re.compile(r"\{\{[A-Z0-9_]+\}\}")
REFERENCE_NEXT_ACTION: Final = (
    "해당 경로의 적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다"
)
PLANNING_NEXT_ACTION: Final = "업무 범위에서 필요한 작업 단위와 완료 기준을 구체화한다"


class TaskArguments(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    task_name: Annotated[str, Field(min_length=1)]
    task_slug: Annotated[str, Field(pattern=SLUG_PATTERN)]
    task_summary: Annotated[str, Field(min_length=1)]
    start_name: Annotated[str, Field(min_length=1)]
    reference_paths: Annotated[str, Field(min_length=1)]
    additional_edit_scope: Annotated[str, Field(min_length=1)]

    @field_validator(
        "start_name",
        "reference_paths",
        "additional_edit_scope",
        mode="before",
    )
    @classmethod
    def _normalize_optional_answer(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized.lower() == "none":
            return "없음"
        return normalized


@dataclass(frozen=True, slots=True)
class TaskCreationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_replacements(values: TaskArguments, now: datetime) -> dict[str, str]:
    korean_now = now.astimezone(KOREA_TIMEZONE)
    return {
        "{{TASK_NAME}}": values.task_name,
        "{{TASK_SLUG}}": values.task_slug,
        "{{TASK_SUMMARY}}": values.task_summary,
        "{{START_NAME}}": values.start_name,
        "{{START_DATE}}": korean_now.strftime("%Y-%m-%d"),
        "{{BASELINE_DATETIME}}": korean_now.strftime("%Y-%m-%d %H:%M"),
        "{{REFERENCE_PATHS_OR_NONE}}": values.reference_paths,
        "{{ADDITIONAL_EDIT_SCOPE_OR_NONE}}": values.additional_edit_scope,
        "{{INITIAL_NEXT_ACTION}}": (
            PLANNING_NEXT_ACTION
            if values.reference_paths == "없음"
            else REFERENCE_NEXT_ACTION
        ),
    }


def read_template_tokens(template_dir: Path) -> set[str]:
    tokens: set[str] = set()
    for path in template_dir.rglob("*.md"):
        tokens.update(TOKEN_PATTERN.findall(path.read_text(encoding="utf-8")))
    return tokens


def create_task(
    repo_root: Path,
    template_dir: Path,
    values: TaskArguments,
    now: datetime,
) -> Path:
    destination = repo_root / "tasks" / values.task_slug
    if not template_dir.is_dir():
        raise TaskCreationError(
            detail=f"template directory does not exist: {template_dir}",
        )
    if destination.exists():
        raise TaskCreationError(detail=f"task already exists: {destination}")

    replacements = build_replacements(values, now)
    template_tokens = read_template_tokens(template_dir)
    expected_tokens = set(replacements)
    if template_tokens != expected_tokens:
        missing = sorted(expected_tokens - template_tokens)
        unknown = sorted(template_tokens - expected_tokens)
        raise TaskCreationError(
            detail=f"template token mismatch; missing={missing}, unknown={unknown}",
        )

    git_path = subprocess.run(
        (
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "info/exclude",
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if git_path.returncode != 0:
        raise TaskCreationError(detail="repo-root must be inside a Git working tree")
    git_prefix = subprocess.run(
        ("git", "-C", str(repo_root), "rev-parse", "--show-prefix"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    exclude_path = Path(git_path.stdout.strip())
    existing = exclude_path.read_bytes() if exclude_path.exists() else b""
    rules = [
        f"/{git_prefix}tasks/{values.task_slug}/{name}".encode()
        for name in ("AGENTS.md", "CLAUDE.md")
    ]
    additions = [rule for rule in rules if rule not in existing.splitlines()]
    if additions:
        separator = b"\n" if existing and not existing.endswith(b"\n") else b""
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        with exclude_path.open("ab") as stream:
            stream.write(separator + b"\n".join(additions) + b"\n")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_dir, destination)
    for path in destination.rglob("*.md"):
        content = path.read_text(encoding="utf-8")
        for token, value in replacements.items():
            content = content.replace(token, value)
        path.write_text(content, encoding="utf-8")
    return destination


def main(
    task_name: Annotated[str, typer.Option()],
    task_slug: Annotated[str, typer.Option()],
    task_summary: Annotated[str, typer.Option()],
    start_name: Annotated[str, typer.Option()],
    reference_paths: Annotated[str, typer.Option()],
    additional_edit_scope: Annotated[str, typer.Option()],
    repo_root: Annotated[Path | None, typer.Option()] = None,
    template_dir: Annotated[Path | None, typer.Option()] = None,
) -> None:
    root = repo_root or Path.cwd()
    source = template_dir or Path(__file__).parents[1] / "assets" / "task-template"
    try:
        values = TaskArguments(
            task_name=task_name,
            task_slug=task_slug,
            task_summary=task_summary,
            start_name=start_name,
            reference_paths=reference_paths,
            additional_edit_scope=additional_edit_scope,
        )
        destination = create_task(
            repo_root=root.resolve(),
            template_dir=source.resolve(),
            values=values,
            now=datetime.now(KOREA_TIMEZONE),
        )
    except (
        TaskCreationError,
        ValidationError,
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(destination)


if __name__ == "__main__":
    typer.run(main)
