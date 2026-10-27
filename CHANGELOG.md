# 변경 기록

`init-work` 스킬의 버전별 변경을 기록한다. 버전은 [유의적 버전](https://semver.org/lang/ko/)을 따르고, 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 참고한다. 날짜는 KST다. 버전 규칙과 배포 절차는 README의 [버전 관리](README.md#버전-관리)를 따른다.

## [Unreleased]

### 변경

- README 설치 안내의 `OWNER/REPO` 자리표시자를 실제 저장소 `devwogns/init-work`로 바꾸고, `vX.Y.Z` 태그 주소로 특정 버전을 설치하는 방법을 추가했다.

## [0.1.0] - 2026-10-27

### 추가

- `$init-work` 호출로 작업 하나의 한국어 문서 7개(공통 5개 + 로컬 지침 `AGENTS.md`·`CLAUDE.md`)를 번들 템플릿에서 생성한다.
- 생성 위치를 자동 또는 직접 입력으로 고르고, 위치에 따라 템플릿을 정한다. 저장소 루트는 전역용(공식 지침), 저장소 안 폴더는 서브용(로컬 지침을 `info/exclude`로 Git에서 제외), 저장소가 아닌 폴더는 `git init` 뒤 전역용이다.
- 생성기는 `--plan`으로 배치·부수 효과·경고·fingerprint를 먼저 보여 주고, 같은 fingerprint를 `--confirm`에 넘겨야 생성한다.
- 부수 효과 전에 추적 중이거나 다시 포함되는 로컬 지침, 확인할 수 없는 ignore 규칙, Git 메타데이터 경로, 홈·드라이브 루트, 기존 문서를 거부한다. 실패하면 이번 실행이 만든 것을 보고하고 되돌리지 않는다.
