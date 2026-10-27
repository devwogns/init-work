# 저장소 지침

## 프로젝트 구조와 구성

`assets/task-template/AGENTS.md`는 생성할 작업의 지침 템플릿이며, 현재 기여자 안내 문서와 구분한다. `.remember/`는 로컬 인계 기록을 보관하며 배포에서 제외한다.

## 빌드·테스트·개발 명령

Git과 `uv`를 사용하며, 스킬 설치에는 Node.js/npm도 필요하다.

```text
uv run scripts/create_task.py --help
uv run --with pytest --with typer --with pydantic pytest tests -q
npx skills add . --list
```

위 명령은 순서대로 생성기 옵션 조회, 전체 테스트 실행, 스킬 검색 확인을 수행한다. 저장소 루트에서 실행한다. 비공개 설치 검증에서는 `DISABLE_TELEMETRY=1`을 설정한다. PowerShell에서는 `$env:DISABLE_TELEMETRY = '1'`을 사용한다. 작업 생성 검증은 README의 전체 실행 예제를 따라 임시 Git 저장소에서 수행한다.

## 코드 스타일과 이름 규칙

파일 인코딩은 UTF-8을 사용한다. 생성 문서는 한국어로 작성하고 날짜·시각은 KST를 유지한다. 작업 슬러그는 `log-level`처럼 소문자 ASCII kebab-case로 작성한다. 스킬 메타데이터와 문서에서 이름·호출·표시명을 `init-work`, `$init-work`, `Init Work`로 일관되게 사용한다. 템플릿 토큰을 변경할 때는 생성기·스킬 지침·관련 테스트를 함께 갱신한다.

## 테스트 지침

pytest를 사용하고 테스트 이름은 `test_<behavior>` 형식으로 작성한다. 임시 디렉터리와 Git 저장소에서 실제 CLI 동작을 검증한다. 정상 생성, 잘못된 슬러그 거부, 덮어쓰기 방지, 선택값 정규화, 미치환 토큰 잔존 여부, 로컬 지침 제외를 확인한다. 배포 구성 변경 시에는 배포용으로 추출한 스킬의 설치와 문서 7개 생성을 검증한다.

## 커밋과 풀 리퀘스트 지침

후속 명시적 지시 없이 커밋·푸시·원격 저장소 생성·공개를 수행하지 않는다. 커밋이 허용되면 제목을 간결한 명령형으로 작성한다. 풀 리퀘스트에는 문제, 변경 내용, 검증 결과, 설치나 템플릿에 미치는 영향을 설명하고 관련 이슈를 연결한다.

## 버전 관리

스킬 버전의 기준은 `SKILL.md` frontmatter의 `metadata.version` 하나이며 유의적 버전(`MAJOR.MINOR.PATCH`)을 따른다. 호출 계약(질문 순서·필수 입력), 생성 문서의 구성·이름, 템플릿 토큰, 생성기 CLI 옵션을 제거하거나 호환되지 않게 바꾸면 MAJOR, 기존 사용법을 유지한 기능 추가는 MINOR, 버그 수정·문구 정리·동작이 같은 내부 변경은 PATCH를 올린다. 1.0.0 전에는 호환을 깨는 변경도 MINOR로 올릴 수 있으나 `CHANGELOG.md`에 `변경` 항목으로 밝힌다. 배포 파일이 바뀌지 않는 변경(`AGENTS.md`·`CLAUDE.md`·`.remember/`)은 버전을 올리지 않는다.

작업 브랜치에서는 변경마다 `CHANGELOG.md`의 `[Unreleased]`에 항목을 추가한다. main 반영 전에 작업 브랜치에서 `metadata.version`을 올리고 `[Unreleased]` 항목을 `## [X.Y.Z] - YYYY-MM-DD`(KST) 절로 옮긴다. main 반영 커밋에는 주석 태그 `vX.Y.Z`를 붙이고 main과 태그를 함께 push한다. 태그 생성·push도 커밋·푸시와 같이 사용자 지시가 있을 때만 수행한다. push한 태그는 옮기거나 지우지 않으며, 배포 후 결함은 새 PATCH 버전으로 고친다. 상세 절차는 README의 「버전 관리」를 따르고, `tests/test_distribution.py`가 버전과 변경 기록의 일치를 검사한다.

## 배포 시 주의 사항

로컬 설치는 Git에서 제외한 파일도 복사할 수 있으므로 README에 명시된 배포 파일 목록을 사용한다. 인계 기록·생성된 작업·캐시는 제외하되, 번들 `AGENTS.md`와 `CLAUDE.md` 템플릿은 포함한다.
