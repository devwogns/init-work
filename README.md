# init-work 스킬

작업 공간과 초기 문서를 생성하고, 계획·진행·결정 기록의 기본 구조를 설정하는 스킬이다. 사용자가 지정한 대상 Git 저장소의 `tasks/<english-slug>/`에 한국어 문서를 생성하며 날짜·시각은 KST를 사용한다. [skills.sh의 CLI](https://skills.sh/docs/cli)로 다른 프로젝트나 사용자 전역 위치에 설치할 수 있다. 일반 사용자는 생성 스크립트보다 `$init-work`를 호출하는 방식을 사용한다.

## 설치

설치에는 Node.js와 npm(`npx`), Git이 필요하다. 작업 생성에는 [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요하며, Python 3.11+와 스크립트 의존성은 `uv`가 준비한다.

아래 `OWNER/REPO`는 배포할 GitHub 저장소로 바꾸는 자리표시자다. 아직 배포 주소가 정해지지 않았으므로 현재는 로컬 원본 설치로 확인한다.

### 다른 프로젝트에 설치

**설치할 대상 프로젝트 루트에서** 실행한다. 아래 명령은 Codex와 Claude Code에 `init-work` 하나만 설치한다. 한 에이전트만 사용한다면 `--agent codex` 또는 `--agent claude-code`로 바꾼다.

```text
npx skills add OWNER/REPO --skill init-work --agent codex claude-code --yes
```

여러 프로젝트에서 공통으로 사용하려면 같은 명령에 `--global`을 추가한다.

```text
npx skills add OWNER/REPO --skill init-work --agent codex claude-code --global --yes
```

비공개 저장소도 같은 명령을 사용하며, 해당 GitHub 저장소를 clone할 수 있도록 Git 인증을 먼저 설정한다. 원격 명령은 서버에 반영된 버전을 설치한다. 아직 반영하지 않은 변경은 아래 로컬 설치로 확인한다.

### 로컬 원본에서 설치

대상 프로젝트 루트에서 실행한다. `<skill-source>`를 `SKILL.md`, `scripts/`, `assets/` 등 배포 파일만 들어 있는 폴더의 절대 경로로 바꾼다. 로컬 작업 기록이나 캐시가 있는 관리 저장소에서는 먼저 아래 [로컬 설치용 원본 준비](#로컬-설치용-원본-준비)를 따른다.

```text
npx skills add "<skill-source>" --skill init-work --agent codex claude-code --yes
```

원본과 설치 대상은 별도 폴더를 사용한다. 이미 스킬 원본을 포함한 프로젝트에서는 재설치 없이 사용한다. 로컬 설치는 복사한 시점의 내용이며, 원본 변경 후에는 설치 명령을 다시 실행한다.

### 설치 확인과 구조

```text
npx skills list
```

전역 설치는 `npx skills list --global`로 확인한다. 실행 중인 에이전트에서 보이지 않으면 새 세션에서 스킬을 호출한다. Windows 등에서 심볼릭 링크를 사용할 수 없으면 설치 명령에 `--copy`를 추가한다.

CLI는 대상 에이전트에 맞는 설치 위치와 연결을 관리한다. 별도 npm 패키지나 설치 스크립트는 필요하지 않다. 다른 파일을 참조하는 진입점만 복사하지 말고, 아래의 완전한 스킬 폴더를 설치 원본으로 사용한다.

명령 옵션과 설치 범위는 [공식 CLI 문서](https://github.com/vercel-labs/skills/blob/main/docs/commands.md#skills-add)를 따른다.

## 독립 GitHub 저장소 구성

이 폴더를 `init-work` 스킬의 관리 저장소로 사용한다. 아래 배포 파일을 저장소 루트에서 관리하며, 원래 프로젝트의 문서·작업 기록·Git 이력·에이전트 설정은 포함하지 않는다.

```text
<repository>/
├── .gitignore
├── SKILL.md
├── README.md
├── agents/openai.yaml
├── scripts/create_task.py
├── assets/task-template/
└── tests/
```

`assets/task-template/` 아래의 `AGENTS.md`와 `CLAUDE.md`는 배포에 필요한 범용 템플릿이다. 작업 생성 뒤 대상 저장소에서 로컬 지침으로 제외되는 파일과 구분한다. 관리 저장소의 `.gitignore`는 `.remember/`, `tasks/`, Python 캐시·가상환경, `node_modules/`를 Git 추적 대상에서 제외한다. 이 파일들은 배포 원본에도 포함하지 않는다. 대상 프로젝트에 작업을 생성할 때는 기존과 같이 `.gitignore`를 변경하지 않고 Git의 `info/exclude`에 로컬 지침 경로만 추가한다.

비공개 저장소에서 먼저 설치를 확인하고 공개 여부는 별도로 결정한다. 공개 전에는 저장소 주소를 실제 값으로 교체하고 배포할 파일과 라이선스를 확인한다. 이 스킬의 작업 생성 절차는 저장소 생성·커밋·푸시·공개 전환을 수행하지 않는다.

### 로컬 설치용 원본 준비

`skills` 1.7.4에서 로컬 설치가 `.gitignore`에 등록된 파일도 복사하는 것을 확인했다. `.gitignore`만으로 설치 파일을 제한할 수 없으므로, 관리 저장소에서 설치할 때는 아래처럼 배포 파일만 별도 임시 폴더로 복사한다. 파일 목록은 새 배포 파일을 추가할 때 함께 갱신한다.

관리 저장소 루트에서 실행하는 PowerShell 예시다. 원본을 수정하거나 Git에 파일을 추가하지 않는다.

```powershell
$skillSource = (Get-Location).Path
$skillExport = Join-Path ([System.IO.Path]::GetTempPath()) ('init-work-export-' + [guid]::NewGuid().ToString('N'))
$skillFiles = @(
    '.gitignore', 'SKILL.md', 'README.md', 'agents/openai.yaml',
    'scripts/create_task.py',
    'assets/task-template/AGENTS.md', 'assets/task-template/CLAUDE.md',
    'assets/task-template/README.md', 'assets/task-template/ROADMAP.md',
    'assets/task-template/PROGRESS.md', 'assets/task-template/decisions.md',
    'assets/task-template/evidence/README.md',
    'tests/test_create_task.py', 'tests/test_local_instructions.py'
)
foreach ($skillFile in $skillFiles) {
    $skillDestination = Join-Path $skillExport $skillFile
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $skillDestination) -ErrorAction Stop | Out-Null
    Copy-Item -LiteralPath (Join-Path $skillSource $skillFile) -Destination $skillDestination -ErrorAction Stop
}
$skillExport
```

출력된 경로를 로컬 설치 명령의 `<skill-source>`로 사용한다. 다른 셸에서도 같은 파일 목록을 빈 폴더에 복사한다. 저장소 전체를 재귀 복사하거나 설치 대상 프로젝트 안에 원본 폴더를 두지 않는다.

## 사용 방법

```text
$init-work
```

스킬은 요청이나 현재 대화에서 이미 제공한 값을 사용하고, 다음 항목 중 빠진 것만 한 번에 하나씩 묻는다. 모두 제공했다면 바로 생성한다.

| 순서 | 항목 | 값이 없을 때 |
|---|---|---|
| 1 | 작업 이름 | 허용하지 않음 |
| 2 | 착수자 이름 | `없음` 입력 |
| 3 | 조사·참조 경로 | `없음` 입력 |
| 4 | 작업 폴더 밖의 추가 편집 허용 경로 | `없음` 입력 |

선택 항목에 값이 없으면 `없음`이라고 답한다. 생성기를 직접 실행할 때 전달된 빈 문자열, 공백, `none`, `없음`도 모두 `없음`으로 저장된다. 제공한 내용만으로 목적과 기대 결과가 불명확하면 작업 요약을 한 번 더 묻는다. 참조 경로는 추가 편집 권한으로 간주하지 않는다.

## 자동 생성값

| 값 | 생성 규칙 |
|---|---|
| `TASK_SLUG` | 핵심 주제를 영어 1~2단어로 표현한 소문자 kebab-case. 주제 구분에 꼭 필요할 때만 3단어 사용. 전체 작업명 번역과 일반적인 작업 동사(`organize`, `improve`, `implement`)는 생략 |
| `TASK_SUMMARY` | 작업 내용과 기대 결과를 설명하는 한국어 1~2문장 |
| `START_DATE` | 한국 현지 날짜 `YYYY-MM-DD` |
| `BASELINE_DATETIME` | 한국 현지 시각 `YYYY-MM-DD HH:mm` |
| `INITIAL_NEXT_ACTION` | 참조 경로가 있으면 적용 지침·진입 문서 조사, 없으면 작업 단위·완료 기준 구체화 |

## 생성 결과

폴더명 예: `로그 레벨 조정` → `log-level`, `문서 구조 정리` → `documentation`, `사용자 인증 토큰 갱신 기능 개선` → `token-refresh`. 상세 의미는 작업명과 요약에 보존한다. 글자 잘라내기나 알아보기 어려운 약어로 줄이지 않는다. 이름이 충돌하면 임의 접미사를 붙이지 않고 사용자에게 확인한다.

```text
tasks/<task-slug>/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── ROADMAP.md
├── PROGRESS.md
├── decisions.md
└── evidence/
    └── README.md
```

원본 템플릿은 `assets/task-template/`에 있으며 생성 결과에는 스킬 문서나 실행 스크립트가 포함되지 않는다. 기존 `tasks/<task-slug>/`가 있으면 덮어쓰지 않는다.

## 기본 코어 문서 역할

- `README.md`는 업무 개요·문서 지도·작업 범위·팀 규칙의 공통 진입점이다.
- `AGENTS.md`는 로컬 에이전트 운용 지침이며 `CLAUDE.md`는 `@AGENTS.md` 한 줄로 연결한다. 생성기는 Git이 해석한 `info/exclude`에 두 파일의 정확한 경로를 추가한다. 기존 제외 규칙과 `.gitignore`는 유지한다. Git 작업 트리 안에서 실행해야 하며 연결된 worktree도 지원한다.
- 생성 결과는 공통 산출물 5개와 로컬 지침 2개다. 로컬 지침은 커밋하지 않는다.
- 작업 내용·하위 트랙이 늘어나면 README의 확장 규칙에 따라 결정과 영향 기록 → 기존 ID·완료 이력 보존 → 범위·완료 기준·의존성·실행 순서 갱신을 수행한다. 편집 허용 경로는 자동으로 늘어나지 않는다. 세부 문서는 필요할 때 만들고 문서 지도에 연결한다.

- `ROADMAP.md`는 “지금 어디까지 왔고, 무엇을 어떤 순서로 진행하며, 나는 무엇을 하면 되는가”를 보여주는 한 장 브리핑이다.
- `PROGRESS.md`는 작업 ID별 상세 상태, 완료 기준, 결과, 증거와 다음 행동을 관리하는 SSOT다.
- 상세 상태를 먼저 `PROGRESS.md`에 갱신하고, 단계·순서·게이트·현재 행동이 바뀌면 `ROADMAP.md` 요약과 `PROGRESS 기준일`을 함께 맞춘다.
- ROADMAP의 순서 표는 항상 유지한다. 분기·병렬·게이트·원복 경로가 생길 때만 표 아래에 같은 작업 ID를 쓰는 Mermaid `flowchart`를 추가한다.

## 생성기 직접 실행

자동 생성값을 직접 준비할 수 있을 때만 사용한다. `<skill-dir>`는 실제로 로드한 `SKILL.md`가 있는 폴더의 절대 경로이고, `<repo-root>`는 작업을 생성할 대상 Git 저장소 루트다. 전역 설치에서도 두 경로를 구분한다. Windows PowerShell과 macOS 셸에서 같은 `uv run` 명령을 사용한다.

```text
uv run "<skill-dir>/scripts/create_task.py" --repo-root "<repo-root>" --task-name '<TASK_NAME>' --task-slug '<TASK_SLUG>' --task-summary '<TASK_SUMMARY>' --start-name '<START_NAME>' --reference-paths '<REFERENCE_PATHS_OR_NONE>' --additional-edit-scope '<ADDITIONAL_EDIT_SCOPE_OR_NONE>'
```

## 템플릿 토큰

| 토큰 | 값 |
|---|---|
| `{{TASK_NAME}}` | 사람이 읽는 작업명 |
| `{{START_NAME}}` | 착수자 이름 또는 `없음` |
| `{{TASK_SLUG}}` | `tasks/` 아래의 영문 소문자 kebab-case 폴더명 |
| `{{TASK_SUMMARY}}` | 작업 내용과 기대 결과를 담은 요약 |
| `{{START_DATE}}` | 착수일 `YYYY-MM-DD` |
| `{{BASELINE_DATETIME}}` | 한국 현지 기준 일시 `YYYY-MM-DD HH:mm` |
| `{{REFERENCE_PATHS_OR_NONE}}` | 조사·참조 대상 경로 또는 `없음` |
| `{{ADDITIONAL_EDIT_SCOPE_OR_NONE}}` | 작업 폴더 밖의 편집 허용 경로 또는 `없음` |
| `{{INITIAL_NEXT_ACTION}}` | 참조 경로 유무에 따라 파생한 최초 다음 행동 |

템플릿 토큰을 추가하거나 제거할 때는 `SKILL.md`, `scripts/create_task.py`, 테스트를 함께 갱신한다.

## 검증

`SKILL.md`가 있는 원본 스킬 폴더에서 실행한다.

```text
uv run --with pytest --with typer --with pydantic pytest tests -q
uv run scripts/create_task.py --help
```

설치 검색은 `npx skills add . --list`로 확인하며, 표시되는 이름은 `init-work`여야 한다. 위 절차로 준비한 배포 파일만 별도 임시 Git 저장소에 로컬 설치한 뒤, 설치된 스크립트로 작업을 생성하여 템플릿이 함께 배포되는지도 확인한다. 설치 폴더에 `.remember/`, 실제 작업 폴더, 캐시가 없는지도 확인한다.

비공개 배포 준비나 로컬 설치 검증에서는 [CLI 문서](https://skills.sh/docs/cli#telemetry)에 따라 `DISABLE_TELEMETRY=1`을 설정한다. PowerShell에서는 실행 전에 `$env:DISABLE_TELEMETRY = '1'`을 사용한다.

생성된 작업 폴더에는 초기화 토큰이 남지 않아야 한다.
생성 결과는 선택 모듈 없이 7개 문서(공통 5개 + 로컬 지침 2개)를 포함한다.

```text
rg -n '\{\{[A-Z0-9_]+\}\}' "<repo-root>/tasks/<task-slug>" -g '*.md'
```
