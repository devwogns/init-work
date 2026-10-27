from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from generator_helpers import (
    BUNDLED_TEMPLATE_DIR,
    EXPECTED_CORE_PATHS,
    load_generator_module,
)

generator = load_generator_module()
NOW = datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)
VALUES = generator.TaskArguments(
    task_name="로그 레벨 조정",
    task_slug="log-level",
    task_summary="로그 레벨 기준을 정리한다.",
    start_name="홍길동",
    reference_paths="`src/`",
    additional_edit_scope="없음",
)
WORK_FOLDERS = {
    "global": "저장소 전체(저장소 루트 아래 모든 경로)",
    "sub": "`docs/2026-10-26-log-level/`",
}


def render(template: str, template_dir: Path = BUNDLED_TEMPLATE_DIR) -> dict[str, str]:
    return generator.render_documents(
        template_dir,
        template,
        generator.build_replacements(
            VALUES,
            NOW,
            template=template,
            work_folder=WORK_FOLDERS[template],
        ),
    )


@pytest.mark.parametrize("template", ["global", "sub"])
def test_bundled_variants_render_seven_documents_without_tokens(template: str) -> None:
    # Given: the bundled template and one variant.
    # When: every document is rendered.
    documents = render(template)

    # Then: the seven documents exist and no token remains.
    assert frozenset(documents) == EXPECTED_CORE_PATHS
    for content in documents.values():
        assert "{{" not in content


def test_variants_differ_only_in_instruction_policy_and_work_folder() -> None:
    # Given: both rendered variants.
    global_documents = render("global")
    sub_documents = render("sub")

    # When / Then: AGENTS.md and README policy lines follow the variant.
    assert "로컬 전용" in sub_documents["AGENTS.md"]
    assert "로컬 전용" not in global_documents["AGENTS.md"]
    assert "공식 에이전트 지침" in global_documents["AGENTS.md"]
    assert "- 작업 폴더: 저장소 전체(저장소 루트 아래 모든 경로)" in global_documents["README.md"]
    assert "- 작업 폴더: `docs/2026-10-26-log-level/`" in sub_documents["README.md"]
    assert generator.GLOBAL_AGENT_POLICY in global_documents["README.md"]
    assert generator.SUB_AGENT_POLICY in sub_documents["README.md"]
    for documents in (global_documents, sub_documents):
        assert "- 위 편집 허용 범위 밖의 경로는 참조 대상을 포함해 읽기 전용이다." in documents["README.md"]
        assert "참조 대상과 그 밖의 명시되지 않은 경로는 읽기 전용이다" not in documents["README.md"]
    assert global_documents["CLAUDE.md"].strip() == "@AGENTS.md"
    assert sub_documents["CLAUDE.md"].strip() == "@AGENTS.md"
    for shared in ("PROGRESS.md", "ROADMAP.md", "decisions.md", "evidence/README.md"):
        assert global_documents[shared] == sub_documents[shared]


@pytest.mark.parametrize("template", ["global", "sub"])
def test_token_mismatch_is_rejected_for_each_variant(
    tmp_path: Path,
    template_dir: Path,
    template: str,
) -> None:
    # Given: a template whose variant AGENTS.md carries an unknown token.
    (template_dir / "variants" / template / "AGENTS.md").write_text(
        "{{UNKNOWN_TOKEN}}",
        encoding="utf-8",
    )

    # When / Then: rendering that variant is refused.
    with pytest.raises(generator.TaskCreationError, match="UNKNOWN_TOKEN"):
        render(template, template_dir)


def test_missing_template_document_is_rejected(template_dir: Path) -> None:
    # Given: a template without ROADMAP.md.
    (template_dir / "ROADMAP.md").unlink()

    # When / Then: rendering is refused.
    with pytest.raises(generator.TaskCreationError, match="ROADMAP.md"):
        render("global", template_dir)

