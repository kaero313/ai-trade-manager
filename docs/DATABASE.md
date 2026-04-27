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
*   `config_json`: (JSON) 전략, 리스크, 그리드, 스케줄 등 동적 설정
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
- 기본 AI 뱅커 세션 목록은 `ai_banker` 세션만 조회하고, 포트폴리오 자동 브리핑/미니챗은 `portfolio` 세션으로 분리 보관합니다.
## Phase 42.1 업데이트
- AI 뱅커 포트폴리오 스냅샷 카드는 기존 `/api/dashboard` 응답과 기존 자산 집계 데이터를 재사용하며, 추가 테이블이나 컬럼 변경은 없습니다.
## Phase 42.2 업데이트
- AI 뱅커 compact 포트폴리오 바는 기존 `/api/dashboard` 응답을 그대로 재사용하며, 추가 테이블/컬럼/API 변경은 없습니다.
## Phase 42.3 업데이트
- AI 뱅커 상단 포트폴리오 bar는 기존 `/api/dashboard` 응답을 그대로 재사용하며, 소개 카드 제거에 따른 추가 테이블/컬럼/API 변경은 없습니다.
