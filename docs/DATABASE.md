# AI-Trade-Manager 데이터베이스 명세서 (Database Schema Specification)

본 문서는 **Phase 1~41**까지 발전해온 핵심 도메인 모델의 설계 의도와 데이터베이스 운용 수칙을 기재합니다.
**PostgreSQL + 비동기 SQLAlchemy 2.0** 스택으로 운영됩니다.

> **최종 갱신 기준:** Phase 41 완료

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

### 3.5. `system_configs` (시스템 설정) [Phase 14 추가]
스케줄러 간격, AI 설정 등 시스템 레벨 키-값(K/V) 설정 저장소.
*   `id`: (PK) 고유 번호
*   `config_key`: (String, Unique, Index) 설정 키 (예: `SENTIMENT_INTERVAL_MINUTES`)
*   `config_value`: (String) 설정 값
*   `description`: (String, Nullable) 설명

### 3.6. `favorites` (관심 종목) [Phase 14 추가]
사용자가 Watchlist에 등록한 관심 종목.
*   `id`: (PK) 고유 번호
*   `symbol`: (String, Unique) 종목 심볼
*   `broker`: (String) 거래소
*   `created_at`: (DateTime, AutoNow)

### 3.7. `ai_analysis_logs` (AI 분석 로그) [Phase 9 추가]
AI 자율 분석가가 생성한 매매 판단 로그. 정확도 메타인지 채점 대상.
*   `id`: (PK) 고유 번호
*   `symbol`: (String) 분석 대상 종목
*   `decision`: (String) AI 판단 (`BUY`, `SELL`, `HOLD`)
*   `confidence`: (Integer) 확신도 (0~100)
*   `recommended_weight`: (Integer) 추천 투자 비중
*   `reasoning`: (Text) 분석 근거 (자연어)
*   `created_at`: (DateTime, AutoNow) 분석 시각
*   `accuracy_label`: (String, Nullable) 정확도 레이블 (`SUCCESS`, `FAIL`) [Phase 36]
*   `actual_price_diff_pct`: (Float, Nullable) 실제 가격 변동률 [Phase 36]
*   `accuracy_checked_at`: (DateTime, Nullable) 정확도 검증 시각 [Phase 36]

### 3.8. `ai_chat_messages` (AI 채팅 메시지) [Phase 39 추가]
LangGraph 멀티에이전트 채팅 대화 내역 영구 저장.
*   `id`: (PK) 고유 번호
*   `session_id`: (String, Index) 채팅 세션 식별자
*   `role`: (String) 발화자 (`user`, `assistant`, `tool`)
*   `content`: (Text) 메시지 내용
*   `agent_name`: (String, Nullable) 에이전트 이름 (supervisor, rag_agent 등)
*   `is_tool_call`: (Boolean) 도구 호출 메시지 여부
*   `created_at`: (DateTime, AutoNow)
*   운영 규칙: AI 뱅커에서 세션 삭제를 실행하면 동일 `session_id`를 가진 메시지와 tool-call 로그가 함께 하드 삭제됩니다.

### 3.9. `portfolio_snapshots` (포트폴리오 스냅샷) [Phase 41 추가]
매시 정각 자동 저장되는 자산 상태 시계열 데이터. 수익률 추이 차트에 사용.
*   `id`: (PK) 고유 번호
*   `total_net_worth`: (Float) 총 순자산 (KRW)
*   `total_pnl`: (Float) 총 평가손익 (KRW)
*   `snapshot_data`: (JSON, 배열) 코인별 상세 내역 `[{currency, balance, current_price, total_value, pnl_percentage}, ...]`
*   `created_at`: (DateTime, AutoNow)
## Phase 42 업데이트
- `chat_sessions`
  - `session_id` (PK, String)
  - `surface` (`ai_banker` | `portfolio`)
  - `created_at` (DateTime, AutoNow)
- 기존 `ai_chat_messages.session_id`는 `chat_sessions.session_id`를 부모로 참조하며, 세션 삭제 시 메시지가 함께 cascade delete 됩니다.
- 기존 `ai_chat_messages`에 존재하던 모든 distinct `session_id`는 마이그레이션 시 `surface='ai_banker'`로 백필합니다.
- 기본 AI 뱅커 세션 목록은 `ai_banker` 세션만 조회하고, 포트폴리오 미니챗은 `portfolio` 세션으로 분리 보관합니다.
## Phase 42.1 업데이트
- AI 뱅커 포트폴리오 스냅샷 카드는 기존 `/api/dashboard` 응답과 기존 자산 집계 데이터를 재사용하며, 추가 테이블이나 컬럼 변경은 없습니다.
## Phase 42.2 업데이트
- AI 뱅커 compact 포트폴리오 바는 기존 `/api/dashboard` 응답을 그대로 재사용하며, 추가 테이블/컬럼/API 변경은 없습니다.
## Phase 42.3 업데이트
- AI 뱅커 상단 포트폴리오 bar는 기존 `/api/dashboard` 응답을 그대로 재사용하며, 소개 카드 제거에 따른 추가 테이블/컬럼/API 변경은 없습니다.

## Phase 42.4 업데이트
- PostgreSQL 스키마 변경은 없습니다.
- OpenSearch 3.5.0의 `market_news` 인덱스는 재수집 가능한 RAG 캐시성 벡터 저장소로 운영합니다.
- `market_news.embedding`은 `knn_vector`, `dimension=1536`, `method=hnsw`, `engine=lucene`, `space_type=cosinesimil` 매핑을 사용합니다.
- `system_configs.max_allocation_pct` 기본값은 `30`이며, 기존 기본값 `10`은 시드 실행 시 `30`으로 보정합니다.

## Phase 42.5 업데이트
- PostgreSQL 스키마 변경은 없습니다.
- AI provider fallback은 기존 `system_configs` 테이블의 JSON 문자열 설정으로 관리합니다.
- 신규 키:
  - `ai_provider_priority`: provider 우선순위 배열. 기본값 `["gemini","openai"]`.
  - `ai_provider_settings`: provider별 `enabled`, `model` 설정. 기본 모델은 `gemini-3-flash-preview`, `gpt-5-mini`.
  - `ai_provider_status`: provider별 `blocked_until`, `reason`, `last_error_at`, `last_error`, `last_success_at` 상태.
- `blocked_until`이 미래인 provider는 백엔드 라우터에서 자동 스킵되며, 만료 후 다음 요청부터 다시 우선순위 평가 대상이 됩니다.

## Phase 42.6 업데이트
- 포트폴리오 자동 브리핑은 `/api/portfolio/briefing` 전용 REST API에서 즉시 생성하며, 별도 채팅 세션이나 메시지를 저장하지 않습니다.
- 새 테이블/컬럼은 없고, AI provider fallback 상태는 기존 `system_configs.ai_provider_status`를 그대로 사용합니다.

## Phase 42.7 업데이트
- 스키마 변경은 없습니다.
- `system_configs.live_buy_enabled`는 live 모드 AI 신규 BUY 허용 여부를 관리합니다. 기본값은 `false`이며 SELL/TP/SL 청산은 차단하지 않습니다.
- `system_configs.ai_max_buy_weight_pct`는 AI 신규 매수 1회 실행 비중 상한입니다. 기본값은 `40`입니다.
- `system_configs.ai_min_confidence_trade` 기본값은 과확신 BUY를 줄이기 위해 `85`로 상향합니다.
- `order_history.price`는 체결 단가, `order_history.qty`는 체결 수량을 저장해야 합니다. Upbit 시장가 매수의 `price` 요청값은 주문 KRW 금액이므로 체결가로 저장하지 않습니다.
- live 주문 기록 시 `positions`의 `avg_entry_price`, `quantity`, `status`를 함께 갱신해 성과 집계의 기준 단위를 보정합니다.
- 2026-04-30 07:00 UTC 이전의 `qty≈1`, `price=5,000~100,000 KRW` AI 매수 기록은 레거시 주문금액 기록으로 간주해 AI 성과 집계에서 제외합니다.

## Phase 43 업데이트
- PostgreSQL 스키마 변경은 없습니다. 균형형 월 수익률 최적화 정책은 기존 `system_configs` K/V 테이블의 신규 키로 관리합니다.
- 신규 키: `ai_trade_target_symbols` 기본값 `["KRW-BTC","KRW-ETH","KRW-XRP"]`, `ai_trade_excluded_symbols` 기본값 `["KRW-DOGE"]`, `ai_entry_score_threshold=70`, `ai_entry_shadow_mode=true`, `ai_calibration_min_success_rate=45`, `ai_max_concurrent_positions=2`.
- `ai_max_buy_weight_pct` 기본값은 `30`으로 조정했습니다. 기존 값이 30을 초과하면 시드 보정 시 `30`으로 낮춥니다.
- AI BUY 적중률 보정은 `ai_analysis_logs.accuracy_label`, `actual_price_diff_pct`, `accuracy_checked_at`의 기존 Phase 36 채점 데이터를 사용합니다. 별도 집계 테이블은 만들지 않습니다.
- OpenSearch `market_news`의 dummy/fallback 문서는 DB 스키마 변경 없이 애플리케이션 레이어에서 실제 뉴스가 아닌 항목으로 필터링합니다.

## Phase 44 업데이트
- PostgreSQL 스키마 변경은 없습니다. RAG 실데이터 정상화는 OpenSearch `market_news` 수집/조회 레이어만 변경합니다.
- `market_news`에는 RSS 기반 실제 뉴스도 기존 `title`, `content`, `source`, `link`, `published_at`, `embedding` 필드 구조로 저장합니다.
- `/api/news/rag/status`는 OpenSearch 집계 결과를 이용해 실문서 수, fallback 문서 수, 임베딩 누락 수, 소스별 분포를 반환합니다.
- 실제 RSS/API 문서가 수집되면 dummy/fallback 문서는 새 ingestion 대상에서 제외하며, 기존 fallback 문서는 TTL 정책으로 자연 만료됩니다.

## Phase 45 업데이트
- PostgreSQL 스키마 변경은 없습니다. RAG 2차 변경은 OpenSearch `market_news` 캐시성 인덱스의 매핑과 수집/조회 로직만 변경합니다.
- `market_news` 청크 문서는 기존 `title`, `content`, `source`, `link`, `published_at`, `embedding`에 더해 `parent_id`, `chunk_index`, `chunk_count`, `content_length`, `chunk_text_length`, `is_chunked`를 저장합니다.
- 청크 `_id`는 `{parent_id}:{chunk_index}` 형식으로 고정해 재수집 시 같은 기사 청크가 중복 누적되지 않도록 합니다.
- 기존 인덱스가 청크 매핑을 지원하지 않으면 ingestion 시 자동 재생성됩니다. OpenSearch는 재수집 가능한 RAG 캐시로 취급하므로 Alembic 마이그레이션은 만들지 않습니다.
- `/api/news/rag/status`는 실문서/fallback/임베딩 통계에 더해 parent 문서 수, chunk 문서 수, chunked parent 수, parent당 평균 청크 수를 집계합니다.

## Phase 46 업데이트
- PostgreSQL 스키마 변경은 없습니다. RAG 본문 크롤링과 품질 관측은 OpenSearch `market_news` 캐시 인덱스의 필드와 애플리케이션 집계만 변경합니다.
- `market_news` 청크 문서는 `content_source`, `crawl_status`, `crawl_error`를 추가로 저장해 RSS 요약, 기사 본문, API 문서, fallback 문서를 구분합니다.
- 신규 매핑이 없는 기존 인덱스는 ingestion 경로에서만 자동 재생성됩니다. Alembic 마이그레이션은 만들지 않습니다.
- `/api/news/rag/status`는 크롤 성공/실패/스킵 parent 수, 평균 본문 길이, 평균 청크 길이, content source/crawl status 분포를 집계합니다.

## Phase 46.1 업데이트
- PostgreSQL 스키마 변경은 없습니다. 크롤 실패 원인 집계는 기존 OpenSearch `crawl_error` keyword 필드를 사용합니다.
- Google News RSS 집계 페이지는 `crawl_status=skipped`, `crawl_error=google_news_aggregator`로 저장합니다.
- `/api/news/rag/status`는 `crawl_error_breakdown`과 source별 crawl error 분포를 추가 집계합니다.

## Phase 46.2 업데이트
- PostgreSQL 스키마 변경은 없습니다. RAG 3.2는 OpenSearch 캐시 인덱스와 애플리케이션 집계만 변경합니다.
- `market_news`는 최신 parent 스냅샷 기준 source별 stale 청크 삭제, 실뉴스 수집 시 fallback 즉시 삭제, 28일 TTL 만료 삭제를 함께 적용합니다.
- `market_news_ingestion_runs`는 `run_id`, 시작/종료 시각, run status, 수집/색인/삭제/크롤 통계, `source_health`를 저장하는 14일 TTL 관측용 인덱스입니다.
- `/api/news/rag/status.latest_ingestion`은 최신 run 문서의 source별 fetched/error/parse warning/crawl 통계와 삭제 통계를 반환합니다.

## Phase 46.3 업데이트
- PostgreSQL 스키마 변경은 없습니다. RSS 소스 정리와 수집량 조정은 OpenSearch RAG 수집 레이어만 변경합니다.
- `market_news`는 교체된 4개 RSS source에서 feed당 최대 8건, 전체 최대 32건의 최신 parent/chunk 문서를 저장합니다.
- `market_news_ingestion_runs.source_health`로 CoinDesk, TokenPost, Cointelegraph, Google News source별 수집/크롤 상태를 관측합니다.

## Phase 46.4 업데이트
- PostgreSQL 스키마 변경은 없습니다. RAG 3.4는 OpenSearch `market_news`와 `market_news_ingestion_runs` 관측 필드만 확장합니다.
- `market_news` 청크 문서는 `embedding_status`, `embedding_error`, `embedding_model`, `embedding_generated_at`을 추가로 저장합니다.
- `market_news_ingestion_runs`는 `embedding_requested`, `embedding_succeeded`, `embedding_missing`, `embedding_failed`, `embedding_error`를 저장합니다.
- 기존 `market_news` 매핑에 임베딩 메타데이터 필드가 없으면 ingestion 경로에서 자동 재생성됩니다.

## Phase 46.5 업데이트
- PostgreSQL 스키마 변경은 없습니다. Missing embedding backfill은 OpenSearch 캐시 인덱스만 갱신합니다.
- `market_news` backfill은 기존 청크 문서에 partial update로 임베딩 벡터와 임베딩 메타데이터만 추가합니다.
- `market_news_ingestion_runs`는 `backfill_requested`, `backfill_succeeded`, `backfill_missing`, `backfill_failed`, `backfill_error`, `backfill_skipped_reason`을 저장합니다.
- backfill은 `rate_limited`/`credentials_missing` run에서는 스킵되며, 이 상태는 최신 ingestion health에서 관측합니다.
