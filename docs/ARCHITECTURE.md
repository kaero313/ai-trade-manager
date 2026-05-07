# AI-Trade-Manager 아키텍처 명세서 (Architecture Specification)

본 설계 문서는 **AI-Trade-Manager** 프로젝트의 시스템 구조와 기술 스택 선택의 의도를 설명합니다.
모든 개발(특히 Codex)은 이 문서를 최우선 기준으로 삼아 구조적 일관성을 유지해야 합니다.

> **최종 갱신 기준:** Phase 41 (AI Portfolio Dashboard) 완료

---

## 1. 핵심 철학 (Core Philosophy)
1. **관심사의 완벽한 분리 (Decoupling):** 백엔드(FastAPI)는 오직 JSON 데이터만 서빙하며, 모든 UI 렌더링은 프론트엔드(React)가 전담합니다.
2. **비동기 최우선 (Async-First):** 네트워크 병목 현상(거래소 API 호출)과 DB I/O가 잦은 트레이딩 봇의 특성을 고려하여 모든 I/O 작업은 `async/await` 구조를 따릅니다.
3. **무중단 운영 (Fault Tolerance):** 거래소 API에 장애가 생겨도 워커나 슬랙 봇이 멈추지 않도록 마이크로서비스 관점으로 컴포넌트를 분리합니다.
4. **AI-First 설계:** LLM 기반 멀티에이전트 오케스트레이션을 통해 자율 매매 판단, 시장 분석, 포트폴리오 관리를 지능적으로 수행합니다.

## 2. 시스템 아키텍처 (System Architecture)
애플리케이션은 **Docker Compose**를 기반으로 격리된 컨테이너 레이어 및 프론트엔드 클라이언트로 동작합니다.

```mermaid
graph TD
    UI["Frontend (React/Vite Dashboard)"] -->|REST API + SSE| API
    Slack["Slack Workspace"] <-->|Socket Mode| Bot

    subgraph Docker Network
        API["FastAPI Server"]
        Worker["Trading Worker Engine"]
        Bot["Slack & AI Control Bot"]
        Scheduler["APScheduler (AsyncIO)"]
        VectorDB["OpenSearch 3.5.0 (RAG Vector DB)"]

        API -->|Async Session| DB[("PostgreSQL")]
        Worker -->|Async Session| DB
        Bot -->|Async Session| DB
        Scheduler -->|Async Session| DB
        API -->|Vector Search| VectorDB
    end

    API -->|HTTP Broker| Broker(("Upbit"))
    Worker -->|HTTP Broker| Broker
    API -->|LLM API| LLM(("Gemini / OpenAI"))
```

### 2.1. 독립된 프로세스 레이어
1. **API Server Container (`app/api/`)**
   - 역할: REST 엔드포인트 제공. 프론트엔드 대시보드, 채팅, 백테스팅, 포트폴리오 관리 등 전반적인 기능 처리.
   - 특징: 트레이딩 자체는 수행하지 않는 "명령 하달 및 데이터 제공 인터페이스" 역할.
2. **Trading Worker Container (`app/services/trading/`)**
   - 역할: 24시간 백그라운드에서 주기적(Tick)으로 가격을 감시하고 조건 매매를 수행. AI 포트폴리오 매니저와 연동되어 지능적으로 동작.
   - 특징: API 서버 가동 여부와 무관하게 독자적인 DB 세션을 가지고 루프(Loop)를 돕니다.
3. **Messenger Bot Container (`app/services/slack_socket.py`)**
   - 역할: 사용자가 모바일에서 슬랙으로 내리는 명령어(`/잔고`, `긴급정지`, `/추천`)를 실시간으로 받아 DB/거래소에 반영하고, AI 에이전트를 통해 시장 분석 리포트를 제공.
4. **Scheduler (`app/core/scheduler.py`)**
   - 역할: `AsyncIOScheduler`(APScheduler)로 뉴스 수집, 시장 감성 분석, AI 자율분석, 포트폴리오 스냅샷 저장 등 주기적 잡을 관리.
   - 주요 잡: 뉴스 수집(4h), 시장 감성 갱신(5m), AI 자율분석(관심종목 순회), 포트폴리오 스냅샷(매시 정각)

### 2.2. 개발 운영 아키텍처 (AI Delivery Workflow)
런타임 멀티에이전트와 별개로, 개발 과정은 **Gemini / IDE 설계 + Codex 앱 적응형 멀티 에이전트 실행** 구조를 사용합니다.

```mermaid
graph LR
    Gemini["Gemini / IDE<br/>(설계·승인)"] --> App["Codex App<br/>(Main Orchestrator)"]
    App --> Explorer["Explorer"]
    App --> Backend["Backend Worker"]
    App --> Frontend["Frontend Worker"]
    App --> Reviewer["Reviewer"]
    App --> Docs["Docs Curator"]
    CLI["Codex CLI<br/>(보조)"] --> App
    App --> Repo["Repository / Docs / Git History"]
```

- **Gemini / IDE:** 기능 설계, 범위 확정, 수용 기준 작성, 코어 아키텍처/DB/외부 계약 변경 승인
- **Codex 앱:** 현재 리포지토리와의 Delta 판정, 작업 분해, 병렬 조사/구현, 통합, 검증, 커밋 수행
- **Codex CLI:** 좁은 단일 확인이나 반복 명령이 필요할 때만 쓰는 보조 채널
- **Main Orchestrator:** 항상 존재하며 최종 통합과 커밋의 유일한 주체
- **Explorer / Worker / Reviewer / Docs Curator:** 작업 크기와 포트폴리오 가치에 따라 선택적으로 활성화

작업 크기별 기본 토폴로지는 아래와 같습니다.
- **작은 작업:** `Main` 단독
- **표준 작업:** `Main + Explorer + Worker 1명 + Reviewer`
- **크로스스택/포트폴리오 시그널이 큰 작업:** `Main + Explorer + Backend Worker + Frontend Worker + Reviewer`
- **문서/설명 가치가 큰 작업:** 위 조합 + `Docs Curator`

## 3. AI 멀티에이전트 아키텍처 (Phase 36~40)

```mermaid
graph TD
    User["사용자 질문"] --> Supervisor
    
    subgraph LangGraph Orchestrator
        Supervisor["Supervisor Agent<br/>(라우팅 판단)"]
        RAG["RAG Agent<br/>(문서 기반 분석)"]
        Quant["Quant Agent<br/>(실시간 기술지표)"]
        Reviewer["Reviewer Agent<br/>(할루시네이션 검수)"]
        
        Supervisor -->|rag_agent| RAG
        Supervisor -->|quant_agent| Quant
        RAG --> Reviewer
        Quant --> Reviewer
        Reviewer -->|통과| Supervisor
        Reviewer -->|반려| RAG
        Reviewer -->|반려| Quant
    end
    
    RAG -->|벡터 검색| OpenSearch["OpenSearch market_news"]
    Quant -->|시세 조회| Upbit["Upbit API"]
    Supervisor -->|최종 답변| User
```

### 3.1. 에이전트 구성
- **Supervisor:** 사용자 질문을 분류하여 적절한 전문 에이전트로 라우팅. 최종 답변 종합.
- **RAG Agent:** OpenSearch 3.5.0 `market_news` 인덱스에서 Gemini 임베딩 기반 kNN 검색을 수행해 뉴스 문맥을 제공.
- **Quant Agent:** 실시간 시세, 기술지표(RSI, MACD, BB), 호가, 체결 내역을 분석하는 도구(Tool) 보유.
- **Reviewer Agent (Phase 40):** RAG/Quant의 답변을 검수. 할루시네이션 검출 + 투자 면책 조항 강제. 최대 2회 재작업 지시(순환형 Self-Correction Loop).

### 3.2. SSE 스트리밍
- AI 채팅은 **Server-Sent Events(SSE)** 방식으로 실시간 스트리밍.
- 이벤트 타입: `agent_start`, `tool_start`, `tool_end`, `agent_end`, `final_answer`
- 프론트엔드에서 Activity Card(에이전트별 작업 상태)를 실시간 표시.

## 4. 백엔드 디렉토리 구조 (Directory Structure)

```text
ai-trade-manager/
├── app/
│   ├── api/              # 라우터 및 엔드포인트 정의 (표현 계층)
│   │   └── routes/       # 개별 엔드포인트 파일 (dashboard, chat, ai, portfolio 등)
│   ├── core/             # 프로젝트 전역 설정 (Config, Logging, Scheduler)
│   ├── db/               # 비동기 세션, 커넥션 풀, Repository 함수
│   ├── models/           # SQLAlchemy 2.0 도메인 ORM 모델 및 Pydantic 스키마
│   └── services/         # 실제 비즈니스 로직 (Service Layer)
│       ├── ai/           # LLM 연동 분석기 (Gemini/OpenAI provider router)
│       ├── backtesting/  # 과거 데이터 기반 시뮬레이션 엔진
│       ├── brokers/      # 거래소 통신 클라이언트 (Upbit)
│       ├── chat/         # LangGraph 멀티에이전트 오케스트레이터
│       ├── indicators/   # MA, BB, RSI 등 기술적 지표 계산
│       ├── market/       # 시장 감성 분석 (Fear & Greed Index)
│       ├── portfolio/    # 자산 집계 서비스
│       ├── rag/          # RAG 벡터 DB 수집/검색 파이프라인
│       └── trading/      # 매매 엔진, AI 분석가, 정확도 검증 워커
├── docs/                 # 핵심 문서 아카이브
├── frontend/             # React/Vite 기반 대시보드 UI
├── migrations/           # Alembic DB 마이그레이션 스크립트
└── docker-compose-dev.yml
```

## 5. 프론트엔드 (Frontend) 구성
**React 18 + Vite + TypeScript** 기반으로 개발되었으며, `Recharts`와 `lightweight-charts`를 이용해 다양한 차트를 구현합니다.

- **대시보드 (Dashboard):** 실시간 시세 캔들 차트, 포트폴리오 도넛 차트, 시장 심리/뉴스 패널, AI 인사이트 브리핑, 봇 제어 패널, 최근 체결 내역.
- **AI 뱅커 (Chat):** LangGraph 멀티에이전트와 SSE 실시간 대화. Activity Card로 에이전트 작업 상태를 시각화하고, 세션 목록에서 대화 세션을 즉시 삭제할 수 있습니다.
- **연구소 (Laboratory):** AI 매매 정책 백테스트 엔진과 연동하여 EMA/RSI/TP/SL/비중 정책을 검증하고, 가격 차트·자산 곡선·드로다운·거래 내역·AI 결과 브리핑을 시각화.
- **설정 (Settings):** AI 매매 대상, 리스크, 스케줄, AI provider 우선순위와 모델을 실시간 조정.
- **포트폴리오 (완료, Phase 41):** AI 기반 자산 관리 대시보드.

## 6. 거래소 추상화 (Broker Abstraction) 전략
어댑터 패턴(Adapter Pattern)을 사용하여 모든 거래소 클라이언트는 반드시 `BaseBrokerClient` 인터페이스를 상속합니다. `BrokerFactory`를 통해 동작하여, 단일 코드베이스로 다수 거래소를 원활하게 지원합니다.
## Phase 42 업데이트
- AI 채팅 세션 메타데이터를 `chat_sessions` 테이블로 분리하고, 각 세션에 `surface`(`ai_banker` 또는 `portfolio`)를 부여했습니다.
- AI 뱅커 메인 화면은 `ai_banker` 세션만 생성·조회합니다.
- 포트폴리오 미니챗은 `portfolio` 세션을 사용하지만, AI 뱅커 세션 목록에는 노출되지 않습니다.
- `ai_chat_messages`는 계속 메시지 본문을 저장하되, 모든 메시지는 `chat_sessions.session_id`를 부모로 참조합니다.
## Phase 42.1 업데이트
- AI 뱅커 화면 상단에 기존 `/api/dashboard` 요약 데이터를 재사용한 포트폴리오 스냅샷 카드와 질문 유도 칩을 추가했습니다.
## Phase 42.2 업데이트
- AI 뱅커 화면의 포트폴리오 정보는 별도 대형 카드가 아니라, 대화창 헤더 아래에 붙는 읽기 전용 compact bar로 축소했습니다.
## Phase 42.3 업데이트
- AI 뱅커 상단 소개 카드(`AI Banker Chat`, 설명 문구)는 제거하고, 그 자리를 얕은 포트폴리오 요약 bar로 대체했습니다.
- AI 뱅커 화면 구조는 `상단 포트폴리오 bar + 좌측 세션 목록 + 우측 대화`로 정리했습니다.
- 포트폴리오 요약은 기존 `/api/dashboard` 데이터를 재사용하며, `총 자산`, `KRW 잔고`, `상위 보유 종목 3개`만 읽기 전용으로 노출합니다.

## Phase 42.4 업데이트
- RAG 벡터 저장소는 OpenSearch 3.5.0의 `market_news` 인덱스를 유지합니다.
- `embedding` 필드는 `knn_vector`, `dimension=1536`, `method=hnsw`, `engine=lucene`, `space_type=cosinesimil` 조합을 사용합니다.
- 뉴스 파이프라인은 `뉴스 수집 -> Gemini 임베딩 -> OpenSearch 저장 -> kNN 검색 -> Gemini 분석` 순서로 동작하며, kNN 실패 시 텍스트 검색과 RSS 폴백으로 전환합니다.
- 런타임 LLM provider는 `SystemConfig`의 AI provider 우선순위에 따라 Gemini/OpenAI 자동 fallback을 사용합니다.
- AI 매수 기본 종목 비중 한도는 `max_allocation_pct=30`으로 운영합니다.

## Phase 42.5 업데이트
- AI 텍스트 생성 경로는 공통 `AIProviderRouter`를 통해 실행됩니다.
- `ai_provider_priority`, `ai_provider_settings`, `ai_provider_status` SystemConfig JSON 값으로 provider 순서, 모델명, 쿼터 차단 상태를 관리합니다.
- Gemini 일일 쿼터 소진은 Pacific time 자정까지 차단 상태로 저장하고, OpenAI rate limit은 응답 reset 힌트 또는 기본 쿨다운을 사용합니다.
- 포트폴리오 브리핑, AI 채팅, `/api/ai/analyze`, 뉴스 감성 분석, 트레이딩 구조화 분석은 같은 우선순위 fallback을 공유합니다.
- RAG 임베딩은 OpenSearch 벡터 차원 호환성을 위해 기존 Gemini embedding 경로를 유지합니다.

## Phase 42.6 업데이트
- 포트폴리오 상단 자동 브리핑은 LangGraph 채팅 세션을 생성하지 않고 `/api/portfolio/briefing` 전용 REST API를 호출합니다.
- `/api/portfolio/briefing`은 현재 포트폴리오, 기간 손익 스냅샷, 최근 AI 판단, 캐시된 시장 심리를 하나의 compact prompt로 묶어 `AIProviderRouter`에 단일 호출합니다.
- 포트폴리오 미니챗은 기존 LangGraph/SSE 채팅 경로를 유지해 사용자의 후속 질문만 멀티에이전트로 처리합니다.

## Phase 42.7 업데이트
- AI 자율매매 실행부는 `live_buy_enabled=false`를 기본값으로 사용해 live 모드 신규 BUY를 차단합니다. 기존 보유분의 SELL, TP/SL 청산 로직은 유지합니다.
- AI가 `recommended_weight=100`을 반환하더라도 실행부는 `ai_max_buy_weight_pct` 상한을 적용해 신규 매수 예산을 제한합니다.
- 자동 체결 최소 확신도 기본값은 `ai_min_confidence_trade=85`로 상향해 낮은 확신도 신호가 live 주문으로 이어지지 않게 합니다.
- Upbit 시장가 매수(`side=bid`, `ord_type=price`) 응답의 `price`는 주문 KRW 금액이므로 체결가로 사용하지 않습니다. 주문 상세의 체결 목록 VWAP 또는 현재가 fallback으로 `order_history.price`를 기록합니다.
- live 체결 기록 시 `positions.quantity`, `positions.avg_entry_price`, `positions.status`를 함께 갱신해 로컬 성과 집계 단위가 실제 체결 단위와 맞도록 유지합니다.
- 2026-04-30 07:00 UTC 이전의 의심 시장가 매수 기록은 체결 단위가 혼재된 레거시 데이터로 보고 AI 실현손익/최근 AI 체결 집계에서 제외합니다.
- AI 분석 프롬프트에는 커스텀 페르소나보다 우선하는 리스크 안전 규칙을 추가해 단일 RSI 조건이나 단편 뉴스만으로 고확신 BUY/100% 비중을 강제하지 못하게 했습니다.

## Phase 43 업데이트
- AI 자동매매의 신규 BUY 경로 앞에 `entry_policy` 게이트를 추가했습니다. AI는 단독 매수 결정권자가 아니라 최종 검토자로 동작하며, 실제 주문 전 `기술적 조건 + 변동성 + 시장심리 + 실제 뉴스/RAG + 심볼별 과거 AI BUY 적중률 보정 confidence` 점수를 통과해야 합니다.
- 자동 분석/매매 대상은 기본적으로 `KRW-BTC`, `KRW-ETH`, `KRW-XRP`로 제한하고 `KRW-DOGE`는 제외합니다. 스케줄러 watchlist도 같은 정책으로 필터링합니다.
- `live_buy_enabled=false`와 별개로 `ai_entry_shadow_mode=true`를 기본값으로 추가했습니다. shadow mode에서는 BUY 후보가 모든 조건을 통과해도 주문을 내지 않고 로그로만 남깁니다.
- OpenSearch `market_news` 결과가 `dummy://` 또는 fallback 문서뿐이면 실제 뉴스 근거로 보지 않습니다. AI 분석 컨텍스트에는 뉴스 없음으로 전달되고, 진입 점수의 뉴스 항목은 0점입니다.
- 백테스트 기본 정책은 보수형 BUY 기준에 맞춰 `min_confidence=85`, `rsi_min=45`, `take_profit_pct=5`, `stop_loss_pct=-3`, `trailing_stop_pct=0.03` 조합을 사용합니다.

## Phase 44 업데이트
- RAG 뉴스 수집 파이프라인은 CryptoPanic/Naver API 문서와 함께 RSS 피드 문서를 정식 수집 소스로 사용합니다.
- RSS 또는 외부 API에서 실제 문서가 1건 이상 확보되면 `dummy://` fallback 문서는 OpenSearch 인덱싱 대상에서 제외합니다.
- `/api/news/rag/status`는 `market_news` 인덱스 존재 여부, 실문서/fallback/임베딩 누락 수, 최신 발행 시각, 소스별 문서 수를 반환합니다.
- 1차 범위에서는 기사 본문 크롤링과 청크 오버랩을 도입하지 않고, RSS 제목/요약 단위 문서를 Gemini 임베딩으로 저장합니다.

## Phase 45 업데이트
- RAG 뉴스 저장소 `market_news`는 문서 단위 저장에서 parent 기사 + chunk 문서 구조로 확장되었습니다.
- ingestion 경로는 RSS/API 원문을 `parent_id` 기준으로 식별하고, 짧은 문서는 1청크, 긴 문서는 `900`자 최대 길이와 `120`자 overlap 기준으로 분할합니다.
- 기존 `market_news` 매핑에 청크 필드가 없으면 ingestion 경로에서만 인덱스를 삭제/재생성합니다. 조회 경로는 인덱스를 임의 재생성하지 않습니다.
- AI 분석의 뉴스 검색은 Gemini query embedding 기반 kNN 후보와 BM25 후보를 각각 조회한 뒤 `0.55 * vector + 0.35 * keyword + 0.10 * recency` 점수로 병합합니다.
- 병합 결과는 `parent_id` 기준으로 중복 제거되어 같은 기사에서 여러 청크가 검색되어도 가장 높은 점수의 청크 1개만 AI 컨텍스트에 전달됩니다.
