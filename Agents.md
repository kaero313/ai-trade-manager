# AI-Trade-Manager Codex Guidelines

이 프로젝트는 2-AI 시스템(Gemini Architect + Codex Coder)으로 구축되고 있습니다. 
Codex는 세션을 시작하거나 코드를 수정할 때 반드시 아래의 **절대 원칙(Golden Rules)**을 준수해야 합니다.

## 1. 언어 및 커밋 규칙 (Language & Commits)
- **응답 언어:** 사용자에 대한 모든 응답과 코드 내 주석은 **한국어**로 작성합니다.
- **커밋 메시지:** Git 커밋은 반드시 **한국어 Conventional Commits** 규격을 따릅니다.
  - 예시: `feat(db): 봇 상태 관리를 위한 PostgreSQL 테이블 생성`
  - 예시: `refactor(slack): 슬랙 소켓 모듈의 인메모리 의존성 제거`

## 2. 아키텍처 및 코딩 원칙 (Architecture & Coding Standards)
- **Async-First (비동기 최우선):** DB 접근 및 외부 API 호출(Upbit 등)은 모두 `async/await` 구조로 작성되어야 합니다.
- **SQLAlchemy 2.0 강제:** ORM 질의 시 구형 1.x 스타일(`session.query()`)은 엄격히 금지되며, 반드시 2.0 스타일(`select()`, `execute()`)과 `AsyncSession`을 사용해야 합니다.
- **Alembic 의존성:** ORM 모델(`app/models/domain.py`)이 변경되면, 임의로 테이블을 수정하지 않고 반드시 `alembic` 마이그레이션 스크립트를 생성하여 반영합니다.
- **In-Memory State 금지:** 전역 변수나 싱글턴 인스턴스를 이용한 상태 관리를 완전히 배제하고, 모든 상태는 PostgreSQL을 유일한 신뢰 출처(SSOT)로 사용합니다.
- **프론트엔드 분리:** 백엔드(FastAPI)는 순수 REST API 데이터만 서빙하고, 웹 UI는 독립된 프론트엔드(React/Vite)가 렌더링하도록 철저히 분리합니다.
- **추상화 원칙 (Abstraction First):** 새로운 거래소 추가 시 반드시 `BaseBrokerClient` 인터페이스를 상속받습니다.
- **지표 무결성 (Indicator Safety):** 보조 지표 계산(MA, BB, RSI) 시 pandas-ta를 사용하되, 발생하는 `NaN` 값은 프론트엔드 전송 전 반드시 타 플랫폼(JSON) 호환 가능한 `null` / `None` 으로 예외 처리합니다.

## 3. 작업 수행 가이드 (Execution Workflow)
- **현재 컨텍스트 (Current Context):** 극초기 백엔드 구조(Phase 1~4), 프론트엔드 대시보드 연동(Phase 5), 코어 워커/메신져 연동(Phase 6~8), AI 에이전트 연동(Phase 9), 고도의 백테스팅/지표 시각화(Phase 15~16), **프론트엔드 실시간 봇 파라미터 제어(Phase 17)**, AI 성과 적중률 메타인지 채점(Phase 36), 분 단위 다이내믹 스케줄링(Phase 37), 가상 모의투자 시뮬레이터(Phase 38), LangGraph 멀티에이전트 AI 뱅커 채팅(Phase 39), Reviewer Agent 자가수정 루프(Phase 40)가 완료되고, **AI-Powered Portfolio Dashboard(Phase 41)**가 진행 중인 **고도화 단계**에 있습니다.
- **범위 엄수:** Gemini가 제공한 마스터 프롬프트의 지시 범위를 정확히 수행하되, 묻지 않은 과도한 리팩토링이나 오버엔지니어링을 자제하십시오.
- **안전 중단:** 워크트리에 알 수 없는 변경이 있거나, 지시를 수행하기에 앞서 아키텍처 결함이 예상되면 코딩을 중단하고 사용자에게 보고하십시오.
- **문서 최신화 규칙:** Phase 마스터 프롬프트의 마지막 Task에는 반드시 `docs/ARCHITECTURE.md`와 `docs/DATABASE.md` 업데이트를 포함하여, 구현과 문서의 싱크를 유지한다.

## 4. 권한과 한계 (Role Boundaries & Constraints)
이 프로젝트의 성공은 두 AI의 철저한 역할 분담에 달려있습니다.

- **Gemini (Architect & QA):** 시스템 설계, 기술 스택 결정, DB 스키마 점검 및 단계별 마스터 프롬프트 작성을 전담합니다.
- **Codex (Executor & Coder):** Gemini가 제공한 마스터 프롬프트의 요구사항을 오차 없이 100% 코드로 구현합니다.
- **[절대 금지 조항]** 
  1. Codex는 프롬프트에 명시되지 않은 코어 아키텍처를 독단적으로 변형해서는 안 됩니다.
  2. 작업 지시서에 치명적 결함(버그 우려)이 있다고 판단되는 경우, 임의로 우회 구현하지 말고 즉시 중단 후 "Gemini 재검토 및 프롬프트 갱신 요청"을 안내하십시오.
