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
- **In-Memory State 금지:** 전역 변수나 싱글턴 인스턴스(`app/core/state.py` 등)를 이용한 상태 관리를 완전히 배제하고, 모든 상태는 PostgreSQL(`bot_configs`, `positions`)을 신뢰할 수 있는 단일 출처(SSOT)로 사용합니다.
- **프론트엔드 분리:** FastAPI 라우터는 순수한 JSON 데이터만 서빙(`dict` 또는 `Pydantic Model` 반환)해야 합니다. `Jinja2` 템플릿과 같은 서버 사이드 웹 렌더링 로직의 추가를 금지합니다.
- **추상화 원칙 (Abstraction First):** 새로운 거래소(주식, 코인 등) 로직을 추가할 때는 반드시 `BaseBrokerClient` 와 같은 공통 인터페이스를 상속받아 구현해야 하며, 특정 거래소에 종속된 코드를 비즈니스 로직(Service/API) 레이어에 하드코딩하지 않습니다.
- **포트폴리오 집계 (단일 진실 공급원):** 거래소 잔고와 수익률 등 자산 정보 조회는 오직 `app/services/portfolio/aggregator.py`의 `PortfolioService`를 통해서만 접근하며, 파편화된 개별 API 호출을 금지합니다.

## 3. 작업 수행 가이드 (Execution Workflow)
- **현재 컨텍스트 (Current Context):** Phase 1(DB 설계), Phase 2(상태 마이그레이션), Phase 3(거래소 추상화), Phase 4(포트폴리오 통합)가 **100% 완료된 상태**입니다. 이제 백엔드의 핵심 구조는 불변으로 취급하며, 프론트엔드 분리 작업(Phase 5)으로 나아갑니다.
- **범위 엄수:** Gemini가 제공한 [Task] 지시서의 목표를 정확히 수행하되, 묻지 않은 과도한 리팩토링이나 오버엔지니어링(Over-engineering)을 자제하십시오.
- **안전 중단:** 워크트리에 알 수 없는 변경이 있거나, 지시를 수행하기에 앞서 심각한 아키텍처 결함이 예상되면 코딩을 즉각 멈추고 사용자에게 보고하십시오.

## 4. 권한과 한계 (Role Boundaries & Constraints)
이 프로젝트의 성공은 두 AI의 철저한 역할 분담에 달려있습니다.

- **Gemini (Architect & QA):** 전체 시스템 설계, 기술 스택 결정, DB 스키마 점검 및 단계별 마스터 프롬프트 작성을 전담합니다.
- **Codex (Executor & Coder):** Gemini가 제공한 마스터 프롬프트의 요구사항을 오름차 없이 100% 코드로 구현하는 데에만 집중합니다.
- **[절대 금지 조항]** 
  1. Codex는 프롬프트에 명시되지 않은 코어 아키텍처(예: DB 테이블 구조, 폴더 구조 등)를 독단적으로 재설계하거나 수정해서는 안 됩니다.
  2. 작업 지시서의 내용에 심각한 논리적 결함(버그 유발, 의존성 충돌 등)이 있다고 판단되는 경우, 임의로 우회 구현하지 말고 즉시 프로세스를 멈추고 사용자에게 **"Gemini 재검토 및 프롬프트 갱신 요청"**을 안내하십시오.
