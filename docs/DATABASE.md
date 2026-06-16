# AI-Trade-Manager 데이터베이스 명세서 (Database Schema Specification)

본 문서는 **Phase 48** 기준 핵심 도메인 모델의 설계 의도와 데이터베이스 운용 수칙을 기재합니다.
**PostgreSQL + 비동기 SQLAlchemy 2.0** 스택으로 운영됩니다.

> **최종 갱신 기준:** Phase 48 (RAG 비용 절감 및 BUY 민감도 조정)
>
> 1~3장은 현재 데이터 모델 기준입니다. 하단의 버전 항목은 구현 발전 이력으로 보며, 스키마 판단은 현재 모델 정의와 Alembic migration을 우선합니다.

---

## 1. DB 환경 구성 원칙
*   **Alembic Migration 필수:** 새로운 테이블이나 컬럼을 만들었다면, **절대** 임의로 DB에 직접 수정하지 말 것. 반드시 `alembic revision --autogenerate`로 마이그레이션 스크립트를 생성하고, `alembic upgrade head`로 반영.
*   **비동기 세션 강제:** 쿼리는 반드시 `AsyncSession`과 `select()`, `execute()` 등 SQLAlchemy 2.0 스타일 구문만 사용. `session.query()` 같은 1.x 스타일은 전면 금지.

## 2. 테이블 설계 결정 사항 (Schema Decisions)
1.  **ID 타입:** 모든 PK는 `Autoincrement Integer` 방식 (UUID 배제).
2.  **Enum 타입 배제:** `status`, `side` 등은 DB Enum 대신 Pydantic/Python 단에서 검증하는 `String` 속성.
3.  **날짜/시간 자동 생성:** 모든 타임스탬프는 `server_default=func.now()`에 위임.

---

## 3. 핵심 도메인 모델 정의

### 3.1. `assets` (자산 정보)
거래소에서 지원하는 종목의 메타데이터.
*   `id`: (PK) 고유 번호
*   `symbol`: (String, Unique, Index) 암호화폐 티커 (예: `KRW-BTC`)
*   `asset_type`: (String) 자산 종류 (예: `CRYPTO`, `STOCK`)
*   `base_currency`: (String) 기축 통화 (예: `KRW`)
*   `is_active`: (Boolean) 봇 감시/작동 여부 스위치

### 3.2. `positions` (보유 포지션 상태)
현재 보유 중인 투자 진입 내역.
*   `id`: (PK) 고유 번호
*   `asset_id`: (FK → `assets`) 참조 인덱스 키
*   `avg_entry_price`: (Float) 매수 평단가
*   `quantity`: (Float) 보유 수량
*   `status`: (String) 포지션 상태 (`OPEN`, `CLOSED`, `HOLD`)
*   `is_paper`: (Boolean) 가상 모의투자 여부
*   `updated_at`: (DateTime, AutoNow)

### 3.3. `order_history` (매매 체결 히스토리)
매수/매도 체결 로그.
*   `id`: (PK) 고유 번호
*   `position_id`: (FK → `positions`) 종속 포지션
*   `ai_analysis_log_id`: (FK → `ai_analysis_logs`, Nullable) AI 분석과 연결
*   `side`: (String) `BUY` / `SELL`
*   `order_reason`: (String, Nullable) 주문 사유
*   `is_paper`: (Boolean) 가상 모의투자 여부
*   `price`: (Float) 체결 가격
*   `qty`: (Float) 체결 수량
*   `broker`: (String) 거래소 (예: `UPBIT`)
*   `executed_at`: (DateTime, AutoNow)

### 3.4. `bot_configs` (봇 설정)
매매 알고리즘의 파라미터 모음집. 프론트엔드 UI에서 실시간 수정 가능.
*   `id`: (PK) 고유 번호
*   `config_json`: (JSON) AI 매매 대상, 전략, 리스크, 스케줄 등 동적 설정
*   `is_active`: (Boolean) 설정 프로필 작동 여부

### 3.5. `system_configs` (시스템 설정)
스케줄러 간격, AI 설정 등 시스템 레벨 키-값(K/V) 설정 저장소.
*   `id`: (PK) 고유 번호
*   `config_key`: (String, Unique, Index) 설정 키 (예: `SENTIMENT_INTERVAL_MINUTES`)
*   `config_value`: (String) 설정 값
*   `description`: (String, Nullable) 설명
*   운영 예시: `news_interval_hours=12`, `ai_min_confidence_trade=75`, `ai_entry_score_threshold=60`, `rag_scheduled_openai_translation_fallback_enabled=false`, `rag_buy_precheck_news_refresh_enabled=true`

### 3.6. `favorites` (관심 종목)
사용자가 Watchlist에 등록한 관심 종목.
*   `id`: (PK) 고유 번호
*   `symbol`: (String, Unique) 종목 심볼
*   `broker`: (String) 거래소
*   `created_at`: (DateTime, AutoNow)

### 3.7. `ai_analysis_logs` (AI 분석 로그)
AI 자율 분석가가 생성한 매매 판단 로그. 정확도 메타인지 채점 대상.
*   `id`: (PK) 고유 번호
*   `symbol`: (String) 분석 대상 종목
*   `decision`: (String) AI 판단 (`BUY`, `SELL`, `HOLD`)
*   `confidence`: (Integer) 확신도 (0~100)
*   `recommended_weight`: (Integer) 추천 투자 비중
*   `reasoning`: (Text) 분석 근거 (자연어)
*   `created_at`: (DateTime, AutoNow) 분석 시각
*   `accuracy_label`: (String, Nullable) 정확도 레이블 (`SUCCESS`, `FAIL`)
*   `actual_price_diff_pct`: (Float, Nullable) 실제 가격 변동률
*   `accuracy_checked_at`: (DateTime, Nullable) 정확도 검증 시각

### 3.8. `chat_sessions` (AI 채팅 세션)
AI 뱅커와 포트폴리오 미니챗 세션 메타데이터.
*   `session_id`: (PK, String) 채팅 세션 식별자
*   `surface`: (String, Index) 세션 표면 (`ai_banker`, `portfolio`)
*   `created_at`: (DateTime, AutoNow)

### 3.9. `ai_chat_messages` (AI 채팅 메시지)
LangGraph 멀티에이전트 채팅 대화 내역 영구 저장. `chat_sessions`를 부모로 참조합니다.
*   `id`: (PK) 고유 번호
*   `session_id`: (FK → `chat_sessions.session_id`, Index) 채팅 세션 식별자
*   `role`: (String) 발화자 (`user`, `assistant`, `tool`)
*   `content`: (Text) 메시지 내용
*   `agent_name`: (String, Nullable) 에이전트 이름 (supervisor, rag_agent 등)
*   `is_tool_call`: (Boolean) 도구 호출 메시지 여부
*   `created_at`: (DateTime, AutoNow)
*   운영 규칙: 세션 삭제 시 동일 `session_id`를 가진 메시지와 tool-call 로그가 함께 하드 삭제됩니다.

### 3.10. `portfolio_snapshots` (포트폴리오 스냅샷)
매시 정각 자동 저장되는 자산 상태 시계열 데이터. 수익률 추이 차트에 사용.
*   `id`: (PK) 고유 번호
*   `total_net_worth`: (Float) 총 순자산 (KRW)
*   `total_pnl`: (Float) 총 평가손익 (KRW)
*   `snapshot_data`: (JSON, 배열) 코인별 상세 내역 `[{currency, balance, current_price, total_value, pnl_percentage}, ...]`
*   `created_at`: (DateTime, AutoNow)

## 4. 변경 이력
아래 버전은 실제 릴리즈 태그가 아니라, 데이터 모델이 어떤 방향으로 고도화됐는지 보여주기 위한 문서용 발전 단계입니다.

### v0.1 PostgreSQL 핵심 테이블
- `assets`, `positions`, `order_history`, `bot_configs`, `system_configs`로 거래 대상, 포지션, 주문, 봇 설정을 분리했습니다.
- 모든 상태는 PostgreSQL을 SSOT로 두고, SQLAlchemy 2.0 AsyncSession과 Alembic migration을 기준으로 관리합니다.

### v0.2 AI 판단 로그
- `ai_analysis_logs`를 추가해 AI 판단을 주문과 분리된 분석 기록으로 저장했습니다.
- 정확도 검증 필드를 확장해 과거 BUY/SELL 판단 성과를 이후 Entry Gate와 브리핑에 활용할 수 있게 했습니다.

### v0.3 채팅/포트폴리오 기록
- `chat_sessions`, `ai_chat_messages`로 AI 뱅커와 포트폴리오 미니챗 세션을 분리했습니다.
- `portfolio_snapshots`로 시간대별 총자산, 손익, 보유 상태를 저장해 기간 손익과 AI 브리핑 근거로 사용합니다.

### v0.4 운영 설정 K/V
- `system_configs`를 확장해 스케줄러 간격, trading mode, live BUY lock, shadow mode, Entry Gate, provider 설정을 관리합니다.
- API key는 `.env`에 두고, DB에는 모델명, provider 우선순위, 상태, 운영 스위치만 저장합니다.
- 비용 정책도 스키마 변경 없이 `system_configs`로 관리하며, 정기 RAG 번역 fallback과 BUY 직전 뉴스 갱신을 분리합니다.
- Slack 포트폴리오 알림은 별도 테이블 없이 `system_configs.slack_portfolio_alert_settings` JSON 하나에 `mode`, `preset`, `rules`를 저장합니다. 알림 섹션에는 포트폴리오, 공포지수, 관심종목 AI 신호, 가격 영향 후보 뉴스가 포함될 수 있으며, 백엔드는 이 값을 APScheduler job으로 정규화하므로 Alembic 변경은 없습니다.

### v0.5 OpenSearch RAG 캐시
- PostgreSQL 스키마 변경 없이 OpenSearch `market_news`를 parent/chunk 뉴스 캐시로 확장했습니다.
- `market_news_ingestion_runs`에는 수집, 크롤링, 임베딩, 번역, backfill, warning 관측 정보를 저장합니다.
- ingestion run에는 `context`와 `translation_openai_fallback_allowed`를 남겨 정기 수집과 BUY 직전 갱신의 비용 경로를 구분합니다.

### v0.6 모델 라우팅과 BUY 검증 로그
- `ai_provider_settings.models`로 `trade_analysis`, `buy_precheck`, `chat`, `news_translation` 등 목적별 모델을 선택할 수 있게 했습니다.
- live BUY 직전 2차 검증은 별도 `AIAnalysisLog`로 저장하고, 실제 주문 이력은 통과한 검증 로그를 참조합니다.
- 기존 DB에 `models`가 없거나 `null`이어도 기본 목적별 모델 맵을 보강해 `buy_precheck`가 `gpt-4.1-mini`로 라우팅되도록 유지합니다.

### v0.7 수동 AI Cycle
- 수동 AI Cycle은 별도 테이블을 만들지 않고 기존 `ai_analysis_logs`에 새 판단을 저장합니다.
- 조건을 통과해 주문이 발생하면 기존 `order_history.ai_analysis_log_id`가 해당 분석 로그를 참조합니다. PostgreSQL/Alembic 변경은 없습니다.
