# AI-Trade-Manager 데이터 모델 노트

이 문서는 현재 운영 데이터가 어디에 저장되고, 어떤 기준으로 복구되는지 정리합니다.

## 1. 저장소 역할

| 저장소 | 역할 | 복구 기준 |
|---|---|---|
| PostgreSQL | 주문, 포지션, 설정, AI 판단, 채팅, 포트폴리오 스냅샷의 기준 저장소 | 백업과 마이그레이션 |
| OpenSearch | RAG 뉴스 검색과 수집 상태 관측용 캐시 | 필요 시 재수집 |
| 환경변수 | 거래소, AI 제공자, Slack, 관리자 인증 비밀값 | 운영 환경에서 별도 관리 |

## 2. 주요 데이터

| 데이터 | 용도 |
|---|---|
| 자산 | 거래 가능한 종목과 감시 여부 |
| 포지션 | 현재 보유 상태와 평균 진입가 |
| 주문 이력 | BUY, SELL 체결 기록과 연결된 AI 판단 |
| 봇 설정 | 매매 대상, 전략, 리스크, 스케줄 |
| 시스템 설정 | 거래 모드, 안전락, AI 제공자, RAG, Slack 알림 정책 |
| 관심 종목 | 사용자가 추적하는 종목 |
| AI 분석 로그 | BUY, SELL, HOLD 판단과 근거, 이후 정확도 평가 |
| 채팅 세션과 메시지 | AI 뱅커와 포트폴리오 미니챗 기록 |
| 포트폴리오 스냅샷 | 시간대별 총자산, 손익, 보유 구성 |

## 3. 운영 설정

시스템 설정은 스키마를 자주 바꾸지 않고 운영값을 조정하기 위한 키-값 저장소입니다.

| 범위 | 예시 |
|---|---|
| 매매 안전 정책 | 거래 모드, 실거래 매수 잠금, 관측 모드, 최소 확신도, 진입 게이트 |
| 스케줄 | 뉴스 수집, AI 자율 분석, 시장 심리 갱신 |
| AI 제공자 | 목적별 모델, 제공자 우선순위, 대체 경로 정책 |
| RAG 비용 제어 | 정기 수집과 BUY 직전 최신화의 비용 허용 범위 |
| Slack 알림 | 포트폴리오, 공포지수, 관심종목 AI 신호, 가격 영향 뉴스 알림 규칙 |

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
