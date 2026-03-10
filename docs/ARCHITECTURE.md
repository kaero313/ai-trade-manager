# AI-Trade-Manager 아키텍처 명세서 (Architecture Specification)

본 설계 문서는 **AI-Trade-Manager** 프로젝트의 거시적인 시스템 구조와 기술 스택 선택의 의도를 설명합니다.
모든 개발(특히 Codex)은 이 문서를 최우선 기준으로 삼아 구조적 일관성을 유지해야 합니다.

---

## 1. 핵심 철학 (Core Philosophy)
1. **관심사의 완벽한 분리 (Decoupling):** 백엔드(FastAPI)는 오직 JSON 데이터만 서빙하며, 모든 UI 렌더링은 프론트엔드(React)가 전담합니다.
2. **비동기 최우선 (Async-First):** 네트워크 병목 현상(거래소 API 호출)과 DB I/O가 잦은 트레이딩 봇의 특성을 고려하여 모든 I/O 작업은 `async/await` 구조를 따릅니다.
3. **무중단 운영 (Fault Tolerance):** 거래소 API에 장애가 생겨도 워커나 슬랙 봇이 멈추지 않도록 마이크로서비스 관점으로 컴포넌트를 분리합니다.

## 2. 시스템 아키텍처 (System Architecture)
애플리케이션은 **Docker Compose**를 기반으로 격리된 컨테이너 레이어 및 프론트엔드 클라이언트로 동작합니다.

```mermaid
graph TD
    UI[Frontend (React/Vite Dashboard)] -->|REST API| API
    Slack[(Slack Workspace)] <-->|Socket Mode| Bot
    
    subgraph Docker Network
        API[FastAPI Server]
        Worker[Trading Worker Engine]
        Bot[Slack & AI Control Bot]
        
        API -->|Async Session| DB[(PostgreSQL)]
        Worker -->|Async Session| DB
        Bot -->|Async Session| DB
    end
    
    API -->|HTTP Broker| Broker((Upbit / Korea Investment))
    Worker -->|HTTP Broker| Broker
```

### 2.1. 독립된 프로세스 레이어
1. **API Server Container (`app/api/`)**
   - 역할: REST 엔드포인트 제공. 프론트엔드 대시보드에서 조회/수정하는 데이터, 백테스팅, 지표 시각화 등 전반적인 기능 처리.
   - 특징: 트레이딩 자체는 수행하지 않는 "명령 하달 및 데이터 제공 인터페이스" 역할.
2. **Trading Worker Container (`app/services/trading/`)**
   - 역할: 24시간 백그라운드에서 주기적(Tick)으로 가격을 감시하고 조건 매매를 수행. AI 포트폴리오 매니저와 연동되어 지능적으로 동작.
   - 특징: API 서버 가동 여부와 무관하게 독자적인 DB 세션을 가지고 루프(Loop)를 돕니다.
3. **Messenger Bot Container (`app/services/slack_socket.py`)**
   - 역할: 사용자가 모바일에서 슬랙으로 내리는 명령어(`/잔고`, `긴급정지`, `/추천`)를 실시간으로 받아 DB/거래소에 반영하고, AI 에이전트를 통해 시장 분석 리포트를 제공.

## 3. 백엔드 디렉토리 구조 (Directory Structure)
FastAPI 앱의 폴더 구조는 철저한 레이어드 아키텍처(Layered Architecture)를 따릅니다.

```text
ai-trade-manager/
├── app/
│   ├── api/          # 라우터 및 엔드포인트 정의 (표현 계층)
│   ├── core/         # 프로젝트 전역 설정 (Config, Logging, Security)
│   ├── db/           # 비동기 세션 및 커넥션 풀 관리
│   ├── models/       # SQLAlchemy 2.0 도메인 ORM 모델 정의
│   ├── schemas/      # Pydantic 기반 입출력 데이터 유효성 검사
│   └── services/     # 실제 비즈니스 로직(CQRS/Service Layer)
│       ├── brokers/  # 거래소 통신 클라이언트 (Upbit, 주식)
│       ├── trading/  # 매매 엔진 워커 로직
│       ├── ai/       # LLM 연동 포트폴리오 분석 및 에이전트 서비스
│       ├── backtesting/ # 과거 데이터 기반 봇 시뮬레이션 엔진
│       └── indicators/  # MA, BB, RSI 등 기술적 지표 계산 처리
├── docs/             # 핵심 문서 아카이브
├── frontend/         # React/Vite 기반 대시보드 및 연구소 UI
├── migrations/       # Alembic DB 마이그레이션 스크립트
├── .env.local        # 로컬 서버용 비밀번호 및 API 키 관리
├── pyproject.toml    # 의존성 패키지 관리
└── docker-compose-dev.yml
```

## 4. 프론트엔드 (Frontend) 구성
**React 18 + Vite** 기반으로 개발되었으며, `lightweight-charts`를 사용해 트레이딩뷰 수준의 강력한 차트를 구현했습니다.
* **대시보드 (Dashboard):** 실시간 시장 가격, 내 포지션, 체결 내역, 기술적 지표 오버레이(MA, BB, RSI) 제공.
* **동적 제어 패널 (Config Panel):** 봇 가동/정지, 종목 배분 비율, 리스크, 그리드 파라미터 등을 웹 UI 모달에서 수정하면 실시간으로 Backend DB에 반영되어 봇 동작에 즉각 적용됩니다. (Phase 17)
* **연구소 (Laboratory):** 백테스트 엔진과 연동하여 전략 파라미터를 시뮬레이션하고, 차트 상에 타점(Buy/Sell Marker)을 시각화.

## 5. 거래소 추상화 (Broker Abstraction) 전략
어댑터 패턴(Adapter Pattern)을 사용하여 모든 거래소 클라이언트는 반드시 `BaseBrokerClient` 인터페이스를 상속합니다. `BrokerFactory`를 통해 동작하여, 단일 코드베이스로 다수 거래소(Upbit, 한국투자증권 등)를 원활하게 지원합니다.
