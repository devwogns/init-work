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

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Final, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

KOREA_TIMEZONE: Final = timezone(timedelta(hours=9), name="KST")
SLUG_PATTERN: Final = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
TOKEN_PATTERN: Final = re.compile(r"\{\{[A-Z0-9_]+\}\}")
REFERENCE_NEXT_ACTION: Final = (
    "해당 경로의 적용 지침과 진입 문서를 먼저 읽고 조사 증거를 남긴다"
)
PLANNING_NEXT_ACTION: Final = "업무 범위에서 필요한 작업 단위와 완료 기준을 구체화한다"
DOCUMENT_PATHS: Final = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "PROGRESS.md",
    "ROADMAP.md",
    "decisions.md",
    "evidence/README.md",
)
LOCAL_INSTRUCTION_PATHS: Final = ("AGENTS.md", "CLAUDE.md")
VARIANTS_DIRECTORY: Final = "variants"
GLOBAL_WORK_FOLDER: Final = "저장소 전체(저장소 루트 아래 모든 경로)"
GLOBAL_AGENT_POLICY: Final = (
    "에이전트 도구 운용 지침은 프로젝트 공식 지침인 `AGENTS.md`와 "
    "이를 참조하는 `CLAUDE.md`에 두며 두 파일도 커밋한다."
)
SUB_AGENT_POLICY: Final = (
    "에이전트 도구 운용 지침은 로컬 전용 `AGENTS.md`와 "
    "이를 참조하는 `CLAUDE.md`에 두며 두 파일은 커밋하지 않는다."
)

TemplateKind = Literal["global", "sub"]
PlacementMode = Literal["auto", "manual"]


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
    created: tuple[str, ...] = ()

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class RepositoryProbe:
    root: Path
    prefix: str
    exclude_file: Path


GIT_LOCATION_VARIABLES: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_INDEX_FILE",
)
# These override the pathspec magic written by this script: check-ignore rejects
# the forced magic outright, and ls-files reads ":(literal)…" as a file name.
GIT_PATHSPEC_VARIABLES: Final = (
    "GIT_LITERAL_PATHSPECS",
    "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
    "GIT_ICASE_PATHSPECS",
)
# git config alone reads GIT_CONFIG instead of the repository's configuration;
# no other command does, so settings read through it would not be the ones used.
GIT_CONFIG_FILE_VARIABLES: Final = ("GIT_CONFIG",)
_DROPPED_GIT_VARIABLES: Final = frozenset(
    (*GIT_LOCATION_VARIABLES, *GIT_PATHSPEC_VARIABLES, *GIT_CONFIG_FILE_VARIABLES),
)


def _git_environment(**overrides: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _DROPPED_GIT_VARIABLES
    }
    environment.update(overrides)
    return environment


def _git(
    *arguments: str,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(cwd), *arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=_git_environment() if env is None else env,
    )


def _looks_like_bare_repository(directory: Path) -> bool:
    return (
        (directory / "HEAD").is_file()
        and (directory / "objects").is_dir()
        and (directory / "refs").is_dir()
    )


def probe_repository(directory: Path) -> RepositoryProbe | None:
    location = _git(
        "rev-parse",
        "--is-inside-git-dir",
        "--is-inside-work-tree",
        cwd=directory,
    )
    if location.returncode != 0:
        real = Path(os.path.realpath(directory))
        candidates = dict.fromkeys(
            (directory, *directory.parents, real, *real.parents),
        )
        if any(
            os.path.lexists(candidate / ".git") or _looks_like_bare_repository(candidate)
            for candidate in candidates
        ):
            raise TaskCreationError(
                detail=f"Git could not inspect {directory}: {location.stderr.strip()}",
            )
        return None
    inside_git_dir, inside_work_tree = location.stdout.split()
    if inside_git_dir == "true" or inside_work_tree != "true":
        raise TaskCreationError(
            detail=f"path is inside Git metadata, not a working tree: {directory}",
        )
    details = _git(
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--show-prefix",
        "--git-path",
        "info/exclude",
        cwd=directory,
    )
    if details.returncode != 0:
        raise TaskCreationError(
            detail=f"Git could not resolve {directory}: {details.stderr.strip()}",
        )
    root, prefix, exclude_file = details.stdout.splitlines()
    return RepositoryProbe(root=Path(root), prefix=prefix, exclude_file=Path(exclude_file))


def normalize_target(raw: str, run_dir: Path) -> Path:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if not text:
        raise TaskCreationError(detail="target path is empty")
    if os.sep == "/":
        text = text.replace("\\", "/")
    try:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = run_dir / path
        return Path(os.path.abspath(path))
    except (RuntimeError, ValueError) as error:
        raise TaskCreationError(
            detail=f"target path cannot be resolved: {text}",
        ) from error


def is_protected_location(path: Path, home: Path) -> bool:
    for candidate in (path, Path(os.path.realpath(path))):
        if candidate == Path(candidate.anchor):
            return True
    if os.path.lexists(path) and os.path.lexists(home):
        try:
            return os.path.samefile(path, home)
        except OSError:
            pass
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(
        os.path.abspath(home),
    )


def escape_exclude_rule(relative_path: str) -> str:
    escaped = re.sub(r"([\\*?\[])", r"\\\1", relative_path)
    stripped = escaped.rstrip(" ")
    return "/" + stripped + "\\ " * (len(escaped) - len(stripped))


@dataclass(frozen=True, slots=True)
class Placement:
    mode: PlacementMode
    destination: Path
    repo_root: Path
    template: TemplateKind
    work_folder: str
    git_init: Path | None
    create_dirs: tuple[Path, ...]
    exclude_file: Path | None
    exclude_rules: tuple[str, ...]
    nested_repositories: tuple[Path, ...]
    ignored_documents: tuple[str, ...]

    def fingerprint(self) -> str:
        material = json.dumps(
            [
                str(self.destination),
                os.path.realpath(self.destination),
                str(self.repo_root),
                self.template,
                None if self.git_init is None else str(self.git_init),
                [str(path) for path in self.create_dirs],
                None if self.exclude_file is None else str(self.exclude_file),
                list(self.exclude_rules),
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_json(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "destination": str(self.destination),
            "repo_root": str(self.repo_root),
            "template": self.template,
            "work_folder": self.work_folder,
            "git_init": None if self.git_init is None else str(self.git_init),
            "create_dirs": [str(path) for path in self.create_dirs],
            "exclude_file": None if self.exclude_file is None else str(self.exclude_file),
            "exclude_rules": list(self.exclude_rules),
            "nested_repositories": [str(path) for path in self.nested_repositories],
            "ignored_documents": list(self.ignored_documents),
            "fingerprint": self.fingerprint(),
        }


def _existing_directory_anchor(destination: Path) -> tuple[Path, tuple[str, ...]]:
    missing: list[str] = []
    current = destination
    while not os.path.lexists(current):
        if current.parent == current:
            raise TaskCreationError(detail=f"no existing parent directory: {destination}")
        missing.append(current.name)
        current = current.parent
    if not current.is_dir():
        raise TaskCreationError(detail=f"path component is not a directory: {current}")
    return current, tuple(reversed(missing))


def _is_ignored(
    path: str,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    config: Sequence[str] = (),
) -> bool:
    config_arguments = tuple(item for entry in config for item in ("-c", entry))
    check = _git(*config_arguments, "check-ignore", "-q", "--", path, cwd=cwd, env=env)
    if check.returncode in (0, 1):
        return check.returncode == 0
    raise TaskCreationError(
        detail=f"Git could not check ignore rules for {path}: {check.stderr.strip()}",
    )


def _exclude_addition(existing: bytes, rules: Sequence[str]) -> bytes:
    if not rules:
        return b""
    separator = b"\n" if existing and not existing.endswith(b"\n") else b""
    return separator + b"\n".join(rule.encode("utf-8") for rule in rules) + b"\n"


IGNORE_SETTINGS: Final = (
    ("core.ignorecase", "bool", "false"),
    ("core.excludesFile", "path", None),
)


def _ignore_settings(repo_root: Path) -> dict[str, str]:
    # The scratch metadata directory below does not see the target repository's
    # own configuration, yet these two settings change what check-ignore reports:
    # case folding of patterns, and a lower-ranked excludes file that can hide a
    # whole parent folder, which no nested .gitignore can re-include. Values are
    # read NUL-terminated so a path's own leading or trailing spaces survive.
    # An unset core.ignorecase means Git's default, not the value git init
    # detected for the scratch directory, so the default is passed explicitly.
    mirrored: dict[str, str] = {}
    for key, value_type, default in IGNORE_SETTINGS:
        setting = _git(
            "config", "--null", f"--type={value_type}", "--get", key, cwd=repo_root
        )
        if setting.returncode == 0:
            mirrored[key] = setting.stdout.removesuffix("\0")
        elif setting.returncode == 1:
            if default is not None:
                mirrored[key] = default
        else:
            raise TaskCreationError(
                detail=f"Git could not read {key} for {repo_root}: {setting.stderr.strip()}",
            )
    return mirrored


def _reject_tracked_local_instructions(
    repo_root: Path,
    relative_prefix: str,
    *,
    ignore_case: bool,
) -> None:
    # Git applies no ignore rule to a tracked path, so a local instruction that
    # is still in the index (even when deleted from disk) could never stay local.
    # A case-insensitive repository treats work/agents.md as the same file.
    magic = ":(literal,icase)" if ignore_case else ":(literal)"
    for name in LOCAL_INSTRUCTION_PATHS:
        path = relative_prefix + name
        listed = _git("ls-files", "-z", "--", magic + path, cwd=repo_root)
        if listed.returncode != 0:
            raise TaskCreationError(
                detail=(
                    f"Git could not check whether ignore rules apply to {path}: "
                    f"{listed.stderr.strip()}"
                ),
            )
        if listed.stdout:
            raise TaskCreationError(
                detail=(
                    "local instruction is tracked by Git, so info/exclude cannot "
                    f"keep it local; remove it from the index first: {path}"
                ),
            )


def _reject_index_only_ignore_files(
    repo_root: Path,
    relative_prefix: str,
    *,
    ignore_case: bool,
) -> None:
    # Git reads a skip-worktree .gitignore (sparse checkout) from the index when
    # it is missing from disk. The scratch metadata directory has no index, so it
    # cannot see those rules; stop instead of guessing.
    magic = ":(literal,icase)" if ignore_case else ":(literal)"
    folders = [part for part in relative_prefix.split("/") if part]
    candidates = [
        "/".join([*folders[:depth], ".gitignore"]) for depth in range(len(folders) + 1)
    ]
    listed = _git(
        "ls-files", "-t", "-z", "--", *(magic + path for path in candidates), cwd=repo_root
    )
    if listed.returncode != 0:
        raise TaskCreationError(
            detail=(
                "Git could not check whether ignore rules apply to "
                f"{relative_prefix}: {listed.stderr.strip()}"
            ),
        )
    for entry in filter(None, listed.stdout.split("\0")):
        tag, path = entry[0], entry[2:]
        if tag == "S" and not os.path.lexists(repo_root / path):
            raise TaskCreationError(
                detail=(
                    "ignore rules for this folder are read from the Git index because a "
                    "sparse checkout left the file off disk, so they cannot be checked; "
                    f"check it out first: {path}"
                ),
            )


RUNTIME_CONFIG_VARIABLE: Final = re.compile(
    r"GIT_CONFIG_(?:PARAMETERS|COUNT|KEY_\d+|VALUE_\d+)",
)


def _scratch_environment(empty_config: Path, **overrides: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in _git_environment(**overrides).items()
        if not RUNTIME_CONFIG_VARIABLE.fullmatch(key)
    }
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty_config))
    return environment


def _verify_local_instructions_stay_ignored(
    repo_root: Path,
    relative_prefix: str,
    planned_exclude: bytes,
    settings: Mapping[str, str],
) -> None:
    # Git reads info/exclude above core.excludesFile and applies the last matching
    # line, so only an info/exclude holding the planned contents reproduces the
    # precedence the real append will have. A scratch metadata directory keeps
    # that simulation out of the repository; the target's ignore settings are
    # mirrored into it so both sides evaluate the same rules. Nothing else may
    # configure the scratch side: it is created without the user's Git template,
    # and system, global and environment-injected config are cut off, because their
    # conditional includes (onbranch, gitdir) can match the scratch repository and
    # not the target. The default global ignore file is not config and is still read.
    config = tuple(f"{key}={value}" for key, value in settings.items())
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        empty_config = Path(scratch) / "empty-config"
        empty_config.write_bytes(b"")
        probe_root = Path(scratch) / "probe"
        subprocess.run(
            ("git", "init", "-q", "--template=", str(probe_root)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=_scratch_environment(empty_config),
        )
        git_dir = probe_root / ".git"
        (git_dir / "info").mkdir(exist_ok=True)
        (git_dir / "info" / "exclude").write_bytes(planned_exclude)
        environment = _scratch_environment(
            empty_config,
            GIT_DIR=str(git_dir),
            GIT_WORK_TREE=str(repo_root),
        )
        for name in LOCAL_INSTRUCTION_PATHS:
            path = relative_prefix + name
            if not _is_ignored(path, cwd=repo_root, env=environment, config=config):
                raise TaskCreationError(
                    detail=(
                        "local instruction would not be ignored after updating "
                        f"info/exclude; a later ignore rule re-includes it: {path}"
                    ),
                )


def _ignored_documents(
    probe: RepositoryProbe | None,
    destination: Path,
    relative_prefix: str,
    documents: Sequence[str],
) -> tuple[str, ...]:
    if probe is not None:
        return tuple(
            document
            for document in documents
            if _is_ignored(relative_prefix + document, cwd=probe.root)
        )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        probe_root = Path(scratch) / "probe"
        subprocess.run(
            ("git", "init", "-q", str(probe_root)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=_git_environment(),
        )
        work_tree = destination if destination.is_dir() else probe_root
        environment = _git_environment(
            GIT_DIR=str(probe_root / ".git"),
            GIT_WORK_TREE=str(work_tree),
        )
        return tuple(
            document
            for document in documents
            if _is_ignored(document, cwd=work_tree, env=environment)
        )


def _assemble_placement(
    *,
    mode: PlacementMode,
    destination: Path,
    home: Path,
) -> Placement:
    anchor, missing = _existing_directory_anchor(destination)
    probe = probe_repository(anchor)
    relative_prefix = (
        ""
        if probe is None
        else probe.prefix + "".join(f"{name}/" for name in missing)
    )
    template: TemplateKind = "sub" if relative_prefix else "global"
    if template == "global" and is_protected_location(destination, home):
        raise TaskCreationError(
            detail=f"refusing home or filesystem root as a project root: {destination}",
        )
    create_dirs = [
        anchor.joinpath(*missing[: index + 1]) for index in range(len(missing))
    ]
    if not os.path.lexists(destination / "evidence"):
        create_dirs.append(destination / "evidence")
    exclude_file: Path | None = None
    exclude_rules: tuple[str, ...] = ()
    if probe is not None and template == "sub":
        exclude_file = probe.exclude_file
        if os.path.lexists(exclude_file.parent) and not exclude_file.parent.is_dir():
            raise TaskCreationError(
                detail=f"path component is not a directory: {exclude_file.parent}",
            )
        if os.path.lexists(exclude_file) and not exclude_file.is_file():
            raise TaskCreationError(
                detail=f"exclude file is not a regular file: {exclude_file}",
            )
        existing = exclude_file.read_bytes() if exclude_file.exists() else b""
        existing_lines = existing.splitlines()
        exclude_rules = tuple(
            rule
            for rule in (
                escape_exclude_rule(relative_prefix + name)
                for name in LOCAL_INSTRUCTION_PATHS
            )
            if rule.encode("utf-8") not in existing_lines
        )
        if exclude_rules and not os.path.lexists(exclude_file.parent):
            create_dirs.append(exclude_file.parent)
        if LOCAL_INSTRUCTION_PATHS:
            settings = _ignore_settings(probe.root)
            ignore_case = settings["core.ignorecase"] == "true"
            _reject_tracked_local_instructions(
                probe.root,
                relative_prefix,
                ignore_case=ignore_case,
            )
            _reject_index_only_ignore_files(
                probe.root,
                relative_prefix,
                ignore_case=ignore_case,
            )
            _verify_local_instructions_stay_ignored(
                probe.root,
                relative_prefix,
                existing + _exclude_addition(existing, exclude_rules),
                settings,
            )
    nested_repositories: tuple[Path, ...] = ()
    if probe is None and destination.is_dir():
        nested_repositories = tuple(
            sorted(
                child
                for child in destination.iterdir()
                if child.is_dir() and os.path.lexists(child / ".git")
            ),
        )
    committed_documents = tuple(
        document
        for document in DOCUMENT_PATHS
        if template == "global" or document not in LOCAL_INSTRUCTION_PATHS
    )
    return Placement(
        mode=mode,
        destination=destination,
        repo_root=destination if probe is None else probe.root,
        template=template,
        work_folder=GLOBAL_WORK_FOLDER if template == "global" else f"`{relative_prefix}`",
        git_init=destination if probe is None else None,
        create_dirs=tuple(create_dirs),
        exclude_file=exclude_file,
        exclude_rules=exclude_rules,
        nested_repositories=nested_repositories,
        ignored_documents=_ignored_documents(
            probe,
            destination,
            relative_prefix,
            committed_documents,
        ),
    )


def resolve_placement(
    *,
    run_dir: Path,
    target: str | None,
    slug: str,
    now: datetime,
    home: Path,
) -> Placement:
    if target is not None:
        destination = normalize_target(target, run_dir)
        if any(part.casefold() == ".git" for part in destination.parts):
            raise TaskCreationError(detail=f"target is inside Git metadata: {destination}")
        return _assemble_placement(mode="manual", destination=destination, home=home)
    if not run_dir.is_dir():
        raise TaskCreationError(detail=f"run directory does not exist: {run_dir}")
    probe = probe_repository(run_dir)
    if probe is None:
        return _assemble_placement(mode="auto", destination=run_dir, home=home)
    if any(os.path.lexists(probe.root / name) for name in LOCAL_INSTRUCTION_PATHS):
        folder = f"{now.astimezone(KOREA_TIMEZONE):%Y-%m-%d}-{slug}"
        return _assemble_placement(
            mode="auto",
            destination=probe.root / "docs" / folder,
            home=home,
        )
    return _assemble_placement(mode="auto", destination=probe.root, home=home)


def build_replacements(
    values: TaskArguments,
    now: datetime,
    *,
    template: TemplateKind,
    work_folder: str,
) -> dict[str, str]:
    korean_now = now.astimezone(KOREA_TIMEZONE)
    return {
        "{{TASK_NAME}}": values.task_name,
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
        "{{WORK_FOLDER}}": work_folder,
        "{{AGENT_INSTRUCTIONS_POLICY}}": (
            GLOBAL_AGENT_POLICY if template == "global" else SUB_AGENT_POLICY
        ),
    }


def render_documents(
    template_dir: Path,
    template: TemplateKind,
    replacements: Mapping[str, str],
) -> dict[str, str]:
    if not template_dir.is_dir():
        raise TaskCreationError(
            detail=f"template directory does not exist: {template_dir}",
        )
    sources: dict[str, str] = {}
    for relative in DOCUMENT_PATHS:
        variant = template_dir / VARIANTS_DIRECTORY / template / relative
        source = variant if variant.is_file() else template_dir / relative
        if not source.is_file():
            raise TaskCreationError(detail=f"template document is missing: {relative}")
        sources[relative] = source.read_text(encoding="utf-8")
    template_tokens = {
        token for content in sources.values() for token in TOKEN_PATTERN.findall(content)
    }
    expected_tokens = set(replacements)
    if template_tokens != expected_tokens:
        missing = sorted(expected_tokens - template_tokens)
        unknown = sorted(template_tokens - expected_tokens)
        raise TaskCreationError(
            detail=f"template token mismatch; missing={missing}, unknown={unknown}",
        )
    rendered: dict[str, str] = {}
    for relative, content in sources.items():
        for token, value in replacements.items():
            content = content.replace(token, value)
        rendered[relative] = content
    return rendered


def _is_link(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class _SideEffects:
    """What this run has created, plus the side effect that is still in progress."""

    __slots__ = ("created", "pending", "marker")

    def __init__(self) -> None:
        self.created: list[str] = []
        self.pending: str | None = None
        self.marker: Path | None = None

    def done(self, label: str) -> None:
        self.created.append(label)

    def begin(self, label: str, marker: Path | None = None) -> None:
        self.pending = label
        self.marker = marker

    def finish(self) -> None:
        if self.pending is not None:
            self.created.append(self.pending)
        self.pending = None
        self.marker = None

    def report(self) -> tuple[str, ...]:
        if self.pending is None:
            return tuple(self.created)
        if self.marker is not None and not os.path.lexists(self.marker):
            return tuple(self.created)
        return (*self.created, f"{self.pending} (incomplete)")


def _append_exclude_rules(
    exclude_file: Path,
    rules: Sequence[str],
    effects: _SideEffects,
) -> None:
    existing = exclude_file.read_bytes() if exclude_file.exists() else b""
    addition = _exclude_addition(existing, rules)
    with exclude_file.open("ab") as stream:
        effects.begin(f"exclude rules {exclude_file}: " + ", ".join(rules))
        stream.write(addition)
    effects.finish()


def _write_document(path: Path, content: str, effects: _SideEffects) -> None:
    with path.open("x", encoding="utf-8") as stream:
        effects.begin(f"document {path}")
        stream.write(content)
    effects.finish()


def create_task(
    *,
    placement: Placement,
    template_dir: Path,
    values: TaskArguments,
    now: datetime,
    confirmation: str,
) -> None:
    if confirmation != placement.fingerprint():
        raise TaskCreationError(
            detail="placement changed since confirmation; run --plan again and confirm it",
        )
    if placement.template == "global" and values.additional_edit_scope != "없음":
        raise TaskCreationError(
            detail="global placement covers the whole repository; additional edit scope must be 없음",
        )
    documents = render_documents(
        template_dir,
        placement.template,
        build_replacements(
            values,
            now,
            template=placement.template,
            work_folder=placement.work_folder,
        ),
    )
    destination = placement.destination
    evidence = destination / "evidence"
    if os.path.lexists(evidence) and (_is_link(evidence) or not evidence.is_dir()):
        raise TaskCreationError(
            detail=f"evidence must be a real directory, not a file or link: {evidence}",
        )
    conflicts = [
        relative for relative in documents if os.path.lexists(destination / relative)
    ]
    if conflicts:
        raise TaskCreationError(
            detail=f"documents already exist in {destination}: {', '.join(conflicts)}",
        )

    effects = _SideEffects()
    try:
        for directory in placement.create_dirs:
            directory.mkdir()
            effects.done(f"directory {directory}")
        if placement.git_init is not None:
            git_dir = placement.git_init / ".git"
            if os.path.lexists(git_dir):
                raise TaskCreationError(
                    detail=f"repository appeared since confirmation: {git_dir}",
                    created=effects.report(),
                )
            effects.begin(f"git repository {git_dir}", marker=git_dir)
            subprocess.run(
                ("git", "init", str(placement.git_init)),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                env=_git_environment(),
            )
            effects.finish()
        if placement.exclude_file is not None and placement.exclude_rules:
            _append_exclude_rules(placement.exclude_file, placement.exclude_rules, effects)
        for relative, content in documents.items():
            _write_document(destination / relative, content, effects)
    except (OSError, subprocess.CalledProcessError) as error:
        cause = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            stderr = error.stderr
            if isinstance(stderr, str) and stderr.strip():
                cause = f"{cause}: {stderr.strip()}"
        raise TaskCreationError(
            detail=f"generation stopped: {cause}",
            created=effects.report(),
        ) from error


def main(
    task_slug: Annotated[str, typer.Option()],
    task_name: Annotated[str | None, typer.Option()] = None,
    task_summary: Annotated[str | None, typer.Option()] = None,
    start_name: Annotated[str | None, typer.Option()] = None,
    reference_paths: Annotated[str | None, typer.Option()] = None,
    additional_edit_scope: Annotated[str | None, typer.Option()] = None,
    run_dir: Annotated[Path | None, typer.Option()] = None,
    target: Annotated[str | None, typer.Option()] = None,
    template_dir: Annotated[Path | None, typer.Option()] = None,
    plan: Annotated[bool, typer.Option("--plan")] = False,
    confirm: Annotated[str | None, typer.Option()] = None,
) -> None:
    source = template_dir or Path(__file__).parents[1] / "assets" / "task-template"
    now = datetime.now(KOREA_TIMEZONE)
    try:
        if re.fullmatch(SLUG_PATTERN, task_slug) is None:
            raise TaskCreationError(detail=f"invalid task slug: {task_slug}")
        placement = resolve_placement(
            run_dir=Path(os.path.abspath(run_dir or Path.cwd())),
            target=target,
            slug=task_slug,
            now=now,
            home=Path.home(),
        )
        if plan:
            typer.echo(json.dumps(placement.to_json(), ensure_ascii=False, indent=2))
            return
        if confirm is None:
            raise TaskCreationError(
                detail="run --plan first and pass its fingerprint with --confirm",
            )
        missing = [
            option
            for option, value in (
                ("--task-name", task_name),
                ("--task-summary", task_summary),
                ("--start-name", start_name),
                ("--reference-paths", reference_paths),
                ("--additional-edit-scope", additional_edit_scope),
            )
            if value is None
        ]
        if missing:
            raise TaskCreationError(
                detail=f"missing options for generation: {', '.join(missing)}",
            )
        values = TaskArguments(
            task_name=task_name,
            task_slug=task_slug,
            task_summary=task_summary,
            start_name=start_name,
            reference_paths=reference_paths,
            additional_edit_scope=additional_edit_scope,
        )
        create_task(
            placement=placement,
            template_dir=source.resolve(),
            values=values,
            now=now,
            confirmation=confirm,
        )
    except TaskCreationError as error:
        typer.echo(f"error: {error}", err=True)
        for item in error.created:
            typer.echo(f"created: {item}", err=True)
        raise typer.Exit(code=1) from error
    except (ValidationError, OSError, subprocess.CalledProcessError) as error:
        message = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            stderr = error.stderr
            if isinstance(stderr, str) and stderr.strip():
                message = f"{message}: {stderr.strip()}"
        typer.echo(f"error: {message}", err=True)
        raise typer.Exit(code=1) from error
    korean_now = now.astimezone(KOREA_TIMEZONE)
    report = {
        "status": "created",
        **placement.to_json(),
        "slug": values.task_slug,
        "start_date": korean_now.strftime("%Y-%m-%d"),
        "baseline_datetime": korean_now.strftime("%Y-%m-%d %H:%M"),
        "documents": list(DOCUMENT_PATHS),
    }
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    typer.run(main)
