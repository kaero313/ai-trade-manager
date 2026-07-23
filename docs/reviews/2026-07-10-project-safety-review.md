# 프로젝트 안전성 리뷰 기록

> 검토일: 2026-07-10
> 기준 브랜치: `main`
> 기준 커밋: `7895f7ba04c3f76cf74ffdb37a4cff9f430efa0e`
> 상태: 검토 완료 / P0-001~P0-004 코드·로컬 회귀·PostgreSQL 16.12 최종 검증 완료 / ATM-P1-003A~003B 로컬 검증 완료 / ATM-P1-003C 로컬 PostgreSQL 16·전체 회귀 완료 / ATM-P1-007·P1-009·P1-010A·P1-011·P1-008·P1-010B 로컬 검증 완료 / ATM-P1-004·P1-006 로컬 PostgreSQL 16·전체 회귀 완료 / ATM-UI-001 구현·로컬 회귀 완료, viewport 자동화 증거 대기 / 원격 CI 미실행
> 구현 변경: 각 P0 후속 구현과 검증은 연결된 계획 문서에서 추적

이 문서는 기준 커밋 시점의 프로젝트 전체 리뷰 결과를 보존합니다. 현재 구현을 설명하는
`ARCHITECTURE.md`, `DATABASE.md`, `OPERATIONS.md`와 달리, 확인된 위험과 후속 계획을 추적하는
문서입니다.

첫 번째 조치 대상인 `ATM-P0-001`의 상세 실행 계획은
[Upbit 주문 멱등성 강화 계획](../plans/p0-001-upbit-order-idempotency.md)에서 관리합니다.
두 번째 조치 대상인 `ATM-P0-002`의 상세 설계는
[전역 실주문 Kill Switch 설계](../plans/p0-002-live-order-kill-switch.md)에서 관리합니다.
세 번째 조치 대상인 `ATM-P0-003`은
[fail-closed 거래 모드 구현 리뷰](2026-07-11-p0-003-implementation-review.md), 네 번째 조치 대상인
`ATM-P0-004`는 [전량청산 증거 기반 종결 계획·구현 기록](../plans/p0-004-liquidation-proof.md)에서
현재 계약과 검증 상태를 관리합니다.
`ATM-P1-003`의 단계별 보안 계약과 현재 검증 상태는
[API·메신저 보안 경계 계획·구현 기록](../plans/p1-003-api-messenger-security.md)에서 관리합니다.
`ATM-P1-007`의 exact analysis ID와 저장 실패 fail-closed 계약은
[AI cycle 분석 ID 고정 계획·구현 기록](../plans/p1-007-ai-cycle-binding.md)에서 관리합니다.
`ATM-P1-009`의 risk unknown/unhealthy 신규 BUY fail-closed 계약은
[신규 BUY 리스크 fail-closed 계획·구현 기록](../plans/p1-009-risk-buy-fail-closed.md)에서 관리합니다.
`ATM-P1-010A`의 live BUY precheck 증액 금지 계약은
[BUY precheck reduce-only 계획·구현 기록](../plans/p1-010a-buy-precheck-reduce-only.md)에서 관리합니다.
`ATM-P1-011`의 provider deadline과 timeout fail-closed 계약은
[AI provider deadline 계획·구현 기록](../plans/p1-011-provider-deadline.md)에서 관리합니다.
`ATM-P1-008`의 primary/precheck 감사 계보와 통계 분리 계약은
[AI 분석 감사 계보 계획·구현 기록](../plans/p1-008-ai-analysis-lineage.md)에서 관리합니다.
`ATM-P1-010B`의 BUY 직전 실제 최신 뉴스 snapshot과 prompt hash 계약은
[BUY 직전 최신 뉴스 context 계획·구현 기록](../plans/p1-010b-buy-news-context.md)에서 관리합니다.
`ATM-P1-004/006`의 설정 SSOT·lost update 방지·키별 서버 검증 계약은
[설정 SSOT·동시성·서버 검증 계획·구현 기록](../plans/p1-004-006-config-ssot.md)과
[2026-07-15 로컬 검증 보고서](2026-07-15-p1-004-006-verification.md)에서 관리합니다.
`ATM-P1-005`의 프론트엔드 상태 사실성과 Stitch 기반 전체 UI 이식은
[UI-001 계획·구현 기록](../plans/ui-001-stitch-design-overhaul.md)과
[2026-07-15 UI-001 로컬 검증 보고서](2026-07-15-ui-001-verification.md)에서 관리합니다.

## 1. 종합 판단

AI 분석, RAG, 포트폴리오, 백테스트, 메신저, 실시간 설정 화면까지 기능 완성도는 높고,
SQLAlchemy 2.0 비동기 사용, live BUY 잠금, shadow mode, Entry Gate, 2차 검증 같은 방어 계층도
잘 구성되어 있습니다.

다만 실거래 주문 경계에는 중복 주문, 정지 후 주문, fail-live 기본값, 청산 실패 오인 가능성이
함께 존재합니다. `ATM-P0-001`부터 `ATM-P0-004`까지 해결하고 회귀 테스트를 통과하기 전에는
`live` 자동매매를 중단하고 `paper + inactive` 상태를 유지하는 것이 안전합니다. 실키의 주문 권한을
임시 비활성화할지는 운영자가 별도로 결정해야 합니다.

## 2. 검증 기준선

| 검증 | 결과 |
|---|---|
| `python -m pytest -q` | 123 passed |
| `python -m ruff check .` | 통과 |
| `frontend/`에서 `npm run lint` | 통과 |
| `frontend/`에서 `npm run build` | 통과, 단일 JS 청크 약 1.2 MB 경고 |
| Alembic revision graph | 단일 head `d3a9f7c1b2e4` |
| `frontend/`에서 `npm audit --omit=dev` | 10건, high 7건 |
| 프론트엔드 테스트 | 테스트 스크립트와 테스트 파일 없음 |
| 대표 비밀 패턴 검사 | 추적 파일에서 명백한 노출 없음 |
| Git 상태 | `main == origin/main`, clean |

Alembic 검증은 로컬에만 존재하는 ignored `alembic.ini`를 사용했습니다. 해당 파일은 기준 커밋에
포함되어 있지 않으므로 clean clone의 빌드와 마이그레이션 재현성은 별도 문제입니다. 실제 Docker
first boot, 운영 PostgreSQL 마이그레이션, Caddy 인증을 포함한 E2E 검증은 수행하지 않았습니다.

위 표와 P0-002 수치는 기준 시점의 기록입니다. 2026-07-12 P0-004 구현 후 backend 비-PostgreSQL
`359 passed, 64 deselected`, frontend `38 passed`, Ruff, ESLint·production build를 통과했습니다.
PostgreSQL marker는 `64 collected`지만 `TEST_DATABASE_URL`이 없어 실제 PostgreSQL 16
migration 왕복·advisory lock 경합·submit 대 stop·영속 drain·계정 전체 청산 증명 테스트는 실행하지
못했습니다. 원격 CI와 push도 실행하지 않았습니다.

위 문단은 2026-07-12 당시의 기록입니다. 2026-07-13 격리된 로컬 PostgreSQL 16.12에서 marker
`64 passed`를 migration 왕복 전후 두 차례 확인했고, `alembic downgrade d3a9f7c1b2e4` 후
재업그레이드, `alembic check`, 단일 head를 통과했습니다. 최신 비-PostgreSQL backend는
`359 passed, 64 deselected`이며 Ruff도 통과했습니다. 원격 CI와 push는 실행하지 않았습니다.

2026-07-13 ATM-P1-003C는 고정 policy/principal 기반 PostgreSQL fixed-window와 Telegram 실제 sender
검증을 구현하고 로컬 PostgreSQL 16.12·전체 회귀를 완료했습니다. PostgreSQL marker `73 passed`,
backend 비-PostgreSQL `451 passed`, backend 합계 `524 passed`, 보안·migration 대상 `98 passed`,
마지막 보안 hardening 대상 `89 passed`,
frontend `54 passed`, Ruff·ESLint·production build를 통과했습니다. 원격 CI와 실제 Docker Compose
전체 기동은 실행하지 않았습니다.

2026-07-14 ATM-P1-007은 분석 로그 저장 실패 예외를 다시 전파하고, scheduler와 수동 AI Cycle이 해당
호출에서 저장된 정확한 `analysis_id`만 executor에 전달하도록 변경했습니다. executor의 종목별 최신
분석 fallback은 실제 주문 경로에서 제거했습니다. targeted `40 passed`, backend 비-PostgreSQL
`469 passed, 73 deselected`, Ruff와 `git diff --check`를 통과했습니다. schema와 Alembic head는
변경하지 않았고 원격 CI와 push는 실행하지 않았습니다.

2026-07-23 ATM-P1-001은 P0-001 원장·reconciliation 구현이 지적 사항을 이미 흡수했음을 확인했습니다.
모든 실주문은 OrderIntent 원장과 15초 주기 reconciliation worker 경유로만 제출·투영되고, executor의
`_record_order_history`는 paper 경로에서만 호출되고 있었습니다. 남아 있던 미사용 live 체결 반영
경로(`_apply_live_position_fill`)를 제거하고 함수를 `_record_paper_order_history`로 개명해 paper
전용임을 명시했습니다. 같은 날 ATM-P1-002로 `docker-compose.local.yml`과 `docker-compose-dev.yml`에
`migrate` one-shot 서비스를 추가해 backend 시작을 `alembic upgrade head` 성공 완료로 게이트했습니다.
targeted `31 passed`, backend 비-PostgreSQL `626 passed, 79 deselected`(제거된 dead code 단위 테스트
1건 감소), Ruff, `docker compose config` 검증을 통과했습니다. schema와 Alembic head는 변경하지 않았고
원격 CI와 push, 실제 Docker first boot는 실행하지 않았습니다.

2026-07-23 ATM-P2-001은 migration `b7e3f9a4c6d2`(`d5e8a1c4b7f2`의 직접 자식, 새 단일 head)로
positions·order_history·portfolio_snapshots의 금융 컬럼 6개를 `Float`에서 `NUMERIC(38, 18)`로
전환하고 `uq_positions_asset_id_is_paper` 유일 제약을 추가했습니다. upgrade preflight는 중복
포지션을 발견하면 자동 병합 없이 DO 블록 `RAISE EXCEPTION`으로 중단하며(online·offline SQL 동일),
Python 소비 코드는 `asdecimal=False`로 float 인터페이스를 유지해 산술 경로 변경이 없습니다.
offline SQL 검증과 PostgreSQL 왕복 테스트(중복 차단→정리→성공→제약 위반→downgrade)를
`tests/test_financial_numeric_migration.py`에 추가했고 기존 migration 테스트 5개의 head 단언을
갱신했습니다. migration 대상 offline `20 passed`, backend 비-PostgreSQL `629 passed, 80 deselected`,
Ruff를 통과했습니다. 실제 PostgreSQL 16 왕복(신규 postgres marker 1개 포함)과 원격 CI, push는
실행하지 않았습니다. Python 산술의 Decimal 전환은 별도 후속 범위로 남습니다.

## 3. 발견사항 요약

| ID | 우선순위 | 제목 | 상태 | 범위 결정 | 실행 담당 |
|---|---|---|---|---|---|
| `ATM-P0-001` | P0 | 타임아웃 재시도로 동일 주문이 중복 체결될 수 있음 | 코드·로컬 PG16.12 검증 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P0-002` | P0 | 비상 정지가 모든 실주문을 차단하지 않음 | 코드·로컬 PG16.12 검증 완료 / 원격 CI 미실행 | 사용자와 Codex | Codex |
| `ATM-P0-003` | P0 | 거래 모드 누락·오타가 live로 해석됨 | 코드·로컬 PG16.12 검증 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P0-004` | P0 | 전량 청산 실패와 잔여 자산을 성공으로 오인함 | 코드·로컬 PG16.12 검증 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-001` | P1 | 거래소 체결 상태와 내부 주문 원장이 불일치할 수 있음 | P0-001 원장·reconciliation으로 해소 확인, executor 잔여 live 반영 코드 제거 (2026-07-23) / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-002` | P1 | clean clone 빌드와 최초 마이그레이션 경로가 끊겨 있음 | alembic.ini 추적 + Compose migration one-shot 게이트 구현 (2026-07-23) / 원격 CI·실제 first boot 미실행 | 사용자 | Codex |
| `ATM-P1-003` | P1 | Telegram, Slack 테스트, 민감 API 인증 경계가 약함 | 003A~003C 로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-004` | P1 | heartbeat와 설정 저장 사이 lost update가 가능함 | 구현·로컬 PG16.12·전체 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-005` | P1 | 포트폴리오 장애·스냅샷 상태가 정상 실시간 값처럼 보임 | UI 구현·로컬 회귀 완료 / viewport 자동화 증거·원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-006` | P1 | 거래 설정값에 key별 서버 검증이 없음 | 구현·로컬 PG16.12·전체 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-007` | P1 | 분석 저장 실패 후 과거 최신 BUY/SELL 분석이 실행될 수 있음 | 구현·로컬 backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-009` | P1 | 하드 TP/SL·포트폴리오 위험 확인 실패 후에도 같은 cycle의 신규 BUY가 계속될 수 있음 | 구현·로컬 backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-010A` | P1 | live BUY 2차 LLM 검증이 1차 분석보다 주문 비중을 늘릴 수 있음 | 구현·로컬 backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-011` | P1 | AI provider 지연이 분석 cycle과 리스크 점검 주기를 장시간 점유할 수 있음 | 구현·로컬 backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-008` | P1 | primary 분석과 BUY precheck의 provider·stage·parent·prompt 계보가 없어 감사·정확도 통계가 섞임 | 구현·로컬 PostgreSQL 16·backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P1-010B` | P1 | BUY 직전 뉴스 최신화 상태만 2차 prompt에 전달되고 실제 최신 뉴스 내용은 전달되지 않음 | 구현·로컬 backend 회귀 완료 / 원격 CI 미실행 | 사용자 | Codex |
| `ATM-P2-001` | P2 | Float 기반 금융 값과 DB 무결성 제약이 부족함 | NUMERIC(38,18) 전환·포지션 유일 제약 migration 구현 (2026-07-23) / 로컬 PostgreSQL·원격 CI 미실행 | 사용자 | Codex |
| `ATM-P2-002` | P2 | 프로세스 메모리 캐시와 단일 프로세스 스케줄러에 의존함 | 대기 | 사용자 | Codex |
| `ATM-P2-003` | P2 | 비동기 경로 안에 동기 RSS·Slack 네트워크 호출이 있음 | 범위 확정 대기 | 사용자 | Codex |
| `ATM-P2-004` | P2 | CI, 프론트 테스트, fresh DB·복구 검증이 없음 | 프론트 테스트·로컬 PG·복원 리허설 부분 해소 / 원격 CI·E2E 대기 | 사용자 | Codex |
| `ATM-P2-005` | P2 | 의존성 고정과 취약점 관리가 부족함 | 범위 확정 대기 | 사용자 | Codex |

## 4. P0 상세 판단

### ATM-P0-001 — 주문 타임아웃 중복 체결

사실:

- `app.services.brokers.upbit.UpbitBroker.create_order()`는 `httpx.TimeoutException` 발생 시 총
  5회 시도합니다. 즉 최초 요청 이후 최대 4회 재시도합니다.
- 활성 실거래 호출부는 `identifier`를 전달하지 않습니다.
- Upbit의 `identifier` 단건 조회 기능은 구현되어 있지만 공통 브로커 계약과 복구 흐름에서
  사용하지 않습니다.
- `OrderHistory`에는 거래소 UUID, identifier, 주문 상태가 없습니다.

추론:

- 거래소가 주문을 접수한 뒤 응답만 유실되면 다음 POST가 새로운 시장가 주문으로 접수될 수
  있습니다.
- 프로세스 재시작까지 고려하면 인메모리 UUID만으로는 동일 주문 의도를 보호할 수 없습니다.

외부 근거:

- [Upbit 주문 생성](https://docs.upbit.com/kr/reference/new-order): `identifier`는 계정 전체 주문에서
  고유해야 하고 최대 64자이며, 한번 사용하면 주문 생성·체결 여부와 무관하게 재사용할 수
  없습니다. 확인일: 2026-07-10.

권장 방향:

- 주문 의도를 PostgreSQL에 먼저 저장하고 안정적인 identifier를 발급합니다.
- 주문 POST는 한 번만 수행합니다.
- 응답이 불확실하면 재주문하지 않고 identifier로 조회한 뒤 `UNKNOWN` 상태를 조정합니다.
- 활성 실거래 경로를 공통 주문 실행 서비스로 통합합니다.

상세 계획: [P0-001 실행 계획](../plans/p0-001-upbit-order-idempotency.md)

### ATM-P0-002 — 비상 정지 후 실매도 가능

사실:

- `app.services.bot_service.stop_bot()`은 `bot_configs.is_active`만 `false`로 변경합니다.
- `app.core.scheduler.autonomous_ai_analyst_job()`은 봇 상태 확인 전에
  `execute_hard_tp_sl_check()`를 실행합니다.
- 일반 AI 주문은 실행 상태를 확인하지만 하드 TP/SL 경로는 동일한 전역 주문 게이트를 통과하지
  않습니다.

추론:

- UI, Slack, Telegram의 비상 정지 후에도 다음 스케줄에서 실매도가 실행될 수 있습니다.

권장 방향:

- 모든 외부 주문 직전에 PostgreSQL 기반 kill switch를 확인하는 단일 게이트를 도입합니다.
- 정지 시 실행 중 주문, 미체결 주문, 보호성 TP/SL을 어떻게 처리할지 운영 계약을 명시합니다.

현재 조치:

- `ARMED`, `EXIT_ONLY`, `BLOCK_ALL` 제어 원장과 append-only 감사 event를 추가했습니다.
- 모든 Upbit POST를 중앙 주문 서비스와 PostgreSQL session advisory shared/exclusive 배리어로
  직렬화하고, 정지 시 런타임·Gate 차단과 영속 `SUBMITTING` drain을 확인합니다.
- 봇 시작은 분석 런타임만 재개하며 자동 재무장하지 않습니다. Gate 차단 중 Gemini/OpenAI 분석과
  reconciliation은 유지하고 신규 주문만 차단합니다.
- REST·Slack·Telegram 정지, 범위가 고정된 `EXIT_ONLY` 청산, 인증 장애 자동 차단,
  보호된 rollout key, 관리자 REST·React 제어를 통합했습니다.
- 로컬 PostgreSQL 16.12 경합 검증은 완료했으며, 원격 CI와 운영 실주문 활성화는 수행하지 않았습니다.

상세 설계: [P0-002 전역 실주문 Kill Switch 설계](../plans/p0-002-live-order-kill-switch.md)

### ATM-P0-003 — fail-live 거래 모드

기준 커밋 당시 사실:

- `app.services.trading.paper.DEFAULT_TRADING_MODE`는 `live`입니다.
- `_normalize_trading_mode()`는 정확히 `paper`인 값만 paper로 처리하고 나머지를 live로 처리합니다.
- 신규 `BotConfig`는 `is_active=True`로 생성됩니다.
- `docs/OPERATIONS.md`는 모의 거래 모드로 시작한다고 설명합니다.

추론:

- 신규 DB, 설정 누락, 단순 오타가 실거래 상태로 전환될 수 있으며 문서가 제공하는 안전 기대와
  실제 동작이 다릅니다.

권장 방향:

- 기본값은 `paper + inactive`로 변경하고 허용되지 않은 값은 live fallback이 아니라 검증 오류로
  차단합니다.
- live 전환은 별도 승인, 재인증, 감사 로그가 필요한 명시적 절차로 분리합니다.

현재 조치:

- PostgreSQL `trading_mode_controls`와 append-only event를 SSOT로 추가하고 legacy mirror가 정확히
  일치할 때만 상태를 available로 판정합니다.
- 기본값을 `paper + inactive + BLOCK_ALL`로 고정하고 누락·오염·조회 실패를 live로 보정하지 않습니다.
- live 전환, 런타임 시작, Gate 재무장을 재인증·version·멱등 키가 분리된 관리자 작업으로 구현했습니다.
- 상세 구현과 남은 PostgreSQL 검증은
  [P0-003 구현 리뷰](2026-07-11-p0-003-implementation-review.md)에서 추적합니다.

### ATM-P0-004 — 전량 청산 성공 오인

기준 커밋 당시 사실:

- REST와 휴면 Slack 청산 경로는 Upbit `balance`에서 `locked`를 다시 차감합니다.
- 종목별 주문 예외를 로그로만 남기고 성공 응답 또는 성공 메시지를 반환합니다.
- 미체결 주문 취소, 잔고 재조회, 체결 확인, 내부 원장 반영이 없습니다.
- 프론트엔드는 HTTP 성공만으로 전량 롤백 요청 성공을 표시합니다.

외부 근거:

- [Upbit 포켓 잔고 조회](https://docs.upbit.com/kr/reference/get-balance):
  `balance`는 주문 가능 수량이고 `locked`는 주문에 묶인 별도 수량입니다. 확인일: 2026-07-10.

권장 방향:

- `미체결 취소 → 잔고 재조회 → 종목별 주문 → 체결 확인 → 원장 반영` 순서의 공통 청산 서비스를
  사용합니다.
- API는 종목별 `attempted/succeeded/failed/remaining` 결과를 반환하고 UI는 부분 실패를 성공으로
  표시하지 않습니다.

현재 조치:

- `ACCOUNT_ALL` operation이 Upbit `primary` 계정의 봇·수동 `wait/watch` 주문을 모두 먼저 발견·취소하고
  관리 주문 부분체결을 기존 OrderIntent 원장에 exactly-once 투영하도록 구현했습니다.
- strict Decimal 잔고 파서에서 Upbit `balance`를 주문 가능 수량으로 사용하고 `locked`를 다시
  차감하지 않습니다. dust·잠금·미지원 마켓을 명시적인 잔여 결과로 남깁니다.
- 최초·취소 후·최종 계좌 snapshot, 취소 원장, append-only phase event, lease/version worker를
  PostgreSQL SSOT로 추가했습니다.
- 전체 미체결 주문 0, 비-KRW 잔고·잠금 0, intent 투영, Position 일치가 검증된
  `COMPLETED + VERIFIED`만 성공입니다. 외부 체결 또는 Position 차이는 자동 보정하지 않고
  `PARTIAL/LEDGER_MISMATCH`로 남깁니다.
- React는 새 확인 문구를 직접 입력하게 하고 terminal 결과와 UUID를 사용자가 닫을 때까지 보존합니다.
  Slack/Telegram은 실행 기능 없이 status에 phase와 잔여 수만 표시합니다.
- 상세 계약과 2026-07-13 로컬 PostgreSQL 16.12 검증 결과는
  [P0-004 계획·구현 기록](../plans/p0-004-liquidation-proof.md)에서 추적합니다.

## 5. P1/P2 근거 인덱스

아래 표는 기준 커밋에서 확인한 사실과 영향을 보존하고, 후속 구현이 끝난 항목은 날짜와 현재 조치를
함께 기록합니다. 명시적인 현재 조치가 없는 내용은 여전히 제안·대기 상태입니다.

| ID | 관찰 사실과 코드 근거 | 위험 또는 영향 |
|---|---|---|
| `ATM-P1-001` | 기준 시점에는 `app/services/trading/ai_executor.py`의 `_resolve_order_detail()`, `_record_order_history()`가 주문 직후 한 번 조회하고 요청 수량 fallback을 허용했으며 `OrderHistory`에 identifier, exchange UUID, 주문 상태가 없었습니다. 이후 P0-001이 모든 실주문을 OrderIntent 원장(identifier·exchange UUID·제출/거래소 상태 보존)과 reconciliation worker 경유로 교체했고, 종결 시 실체결 VWAP·수량만 `order_intent_id` unique FK로 `OrderHistory`에 정확히 한 번 투영합니다. 2026-07-23 executor에 남아 있던 미사용 live 체결 반영 경로(`_apply_live_position_fill`)를 제거하고 `_record_paper_order_history`로 paper 전용임을 명시했습니다. | live 주문은 즉시 이력을 기록하지 않고 reconciliation projection만 기록하며, 체결 VWAP을 확인할 수 없으면 `FILL_PRICE_UNAVAILABLE` 오류로 남겨 backoff 재시도합니다. 부분체결 이벤트별 실시간 원장은 P0-001 계획에서 후속 범위로 분리되어 있습니다. |
| `ATM-P1-002` | 기준 시점에는 `.gitignore`가 `alembic.ini`를 제외하는데 `Dockerfile.local`이 이를 COPY했고, `ops/scripts/start.sh`는 migration 없이 compose를 시작했으며 `app/main.py`의 lifespan은 즉시 테이블을 조회했습니다. 이후 `alembic.ini`를 추적 대상으로 전환했고, 2026-07-23 `docker-compose.local.yml`과 `docker-compose-dev.yml`에 `migrate` one-shot 서비스(`alembic upgrade head`)를 추가해 backend가 `service_completed_successfully` 조건으로 migration 완료를 기다리도록 게이트했습니다. | clean clone에서도 빈 DB 재시작 루프 없이 스키마가 먼저 준비되고, migration 실패 시 backend는 시작되지 않습니다. 실제 Docker first boot E2E와 원격 CI 검증은 남아 있습니다. |
| `ATM-P1-003` | `app/services/telegram.py`의 `enabled`는 token만 검사하고 `TelegramBotService._handle_update()`는 chat ID 미설정 시 모든 채팅을 허용합니다. `app/api/routes/slack.py`는 요청의 임의 webhook URL을 `SlackClient.send_message()`에 전달합니다. | 무단 봇 제어와 서버 측 임의 URL 요청 위험이 있습니다. |
| `ATM-P1-004` | 기준 시점에는 heartbeat와 프로필 저장이 같은 `BotConfig.config_json`을 갱신했습니다. 2026-07-15 runtime 전용 컬럼, `config_version`, `If-Match` CAS와 migration을 추가했습니다. | heartbeat는 프로필 JSON/version을 변경하지 않고 stale 연구 프로필 저장은 `409`로 거절합니다. PostgreSQL 16.12 marker와 다중 세션 경합을 migration 왕복 전후 통과했습니다. |
| `ATM-P1-005` | 기준 시점에는 portfolio의 `source`, `is_stale`, `error`, `updated_at`을 표시하지 않고 장애·empty를 숫자 0으로 렌더링했습니다. 2026-07-15 UI-001에서 공통 `PortfolioDataState`와 live/snapshot/cached/error/empty/loading 표현, unavailable AI gating을 적용했습니다. | cache 없는 오류·비유한 값은 수치를 숨기고 cached 오류는 마지막 값과 stale 경고를 함께 표시합니다. frontend 우회는 차단했지만 backend chat tool의 기존 오류→0원 context 보정은 별도 Delta입니다. |
| `ATM-P1-006` | 기준 시점에는 key별 범위·형식 검증과 설정 권위 구분이 없었습니다. 2026-07-15 분류 registry, strict canonicalization, 행별 version, 다중 키 원자 저장과 REST·AI Banker·Telegram 공통 서비스를 추가했습니다. | unknown·보호·내부 키와 malformed/범위 이탈 값은 저장 전에 거절되고 UI는 실제 production 소비 키만 표시합니다. PostgreSQL 16.12 marker와 다중 세션 경합을 migration 왕복 전후 통과했습니다. |
| `ATM-P1-007` | 분석 로그 저장 실패가 예외로 전파되지 않았고 scheduler·수동 AI Cycle의 executor가 종목별 최신 분석을 다시 조회했습니다. 2026-07-14 저장된 exact ID 전달과 PK 조회로 교체했습니다. | 새 분석 저장 실패나 동시 분석에서도 과거 BUY/SELL/precheck 로그를 대신 실행하지 않습니다. |
| `ATM-P1-009` | 하드 TP/SL 점검 오류와 portfolio error가 빈 종목 집합으로 축약되었고 scheduler·수동 Cycle이 그 실패 상태를 BUY executor에 전달하지 않았습니다. 2026-07-14 cycle-local `RiskCheckResult`와 BUY-only veto로 교체했습니다. | 누락·`UNKNOWN`·`UNHEALTHY` 상태의 신규 BUY는 포트폴리오·Entry Gate·주문 전에 차단하며 SELL·비상청산·reconciliation은 유지합니다. |
| `ATM-P1-010A` | live BUY가 1차 분석 비중을 버리고 2차 precheck 비중과 시스템 상한만 사용했으며 5,000원 미만 목표를 최소 주문액으로 올렸습니다. 2026-07-14 세 값의 최솟값과 subminimum skip으로 교체했습니다. | 2차 검증은 BUY 차단·축소만 가능하며 1차 비중이나 hard cap보다 주문을 늘리지 않습니다. |
| `ATM-P1-011` | provider SDK 기본 retry와 무기한 application await 때문에 primary·precheck·리포트·RAG 호출 시간이 통제되지 않았습니다. 2026-07-14 목적별 provider 실행 deadline, SDK retry 억제, 번역 전체 fallback 예산을 추가했습니다. | primary timeout은 현재 cycle HOLD, BUY precheck timeout은 주문 0회이며 외부 취소와 P0 Gate는 유지합니다. 독립 리스크 scheduler·분산 lease는 P2 후속입니다. |
| `ATM-P1-008` | primary와 BUY precheck가 같은 로그 형태로 저장되고 provider/model/fallback/parent/prompt context를 잃어 최신 분석·정확도·calibration이 섞였습니다. 2026-07-14 stage와 exact lineage를 추가하고 소비 query를 분리했습니다. | 신규 통계·실행은 primary만 사용하고 precheck 주문은 실제 실행 로그 FK를 보존한 채 parent primary로 성과를 귀속합니다. legacy provider/stage는 추정하지 않습니다. |
| `ATM-P1-010B` | BUY 직전 수집을 수행해도 precheck prompt에는 refresh 상태만 들어가고 실제 최신 기사 내용은 2차 판단에 전달되지 않았습니다. 2026-07-14 최신화 후 별도 뉴스 조회와 제한된 canonical snapshot을 추가했습니다. | 최신화 성공·실패·비활성과 무관하게 최대 3건의 뉴스 근거를 prompt/hash에 고정하며, 뉴스 부재·조회 실패만으로 자동 veto하지 않습니다. |
| `ATM-P2-001` | 기준 시점에는 `app/models/domain.py`가 가격·수량·손익에 `Float`를 사용하고 `Position`에 `(asset_id, is_paper)` unique 제약이 없었습니다. 2026-07-23 migration `b7e3f9a4c6d2`로 positions·order_history·portfolio_snapshots의 금융 컬럼 6개를 `NUMERIC(38, 18)`로 전환하고 `uq_positions_asset_id_is_paper` 유일 제약을 추가했습니다. 중복 포지션이 있으면 자동 병합 없이 migration이 중단됩니다(fail-closed). Python 소비 코드는 `asdecimal=False`로 float 인터페이스를 유지합니다. | DB 저장·비교·집계는 이진 부동소수점 오차 없이 수행되고 동시 생성 중복 포지션은 제약이 차단합니다. Python 산술의 Decimal 전환(paper 엔진·집계 경로)은 별도 후속 범위입니다. P0-001 주문 원장은 이미 `NUMERIC(38, 18)`+Decimal을 사용합니다. |
| `ATM-P2-002` | `app/api/routes/markets.py`, `app/api/routes/news.py`, `app/services/news_scraper.py`에 프로세스 메모리 캐시가 있고, FastAPI lifespan마다 scheduler와 거래 loop를 시작합니다. | worker별 상태 불일치와 다중 프로세스 중복 작업이 가능합니다. |
| `ATM-P2-003` | `news_scraper._parse_feed_entries()`는 동기 `feedparser.parse(URL)`을 async API에서 호출하며, 동기 Slack SDK 호출도 async 스케줄 경로에 존재합니다. | 외부 지연이 이벤트 루프와 주문·스케줄 처리를 막을 수 있습니다. |
| `ATM-P2-004` | 기준 시점에는 frontend test script·테스트 파일과 `.github/workflows`가 없었습니다. 2026-07-15에는 frontend 119개, 로컬 PostgreSQL 16.12 migration 왕복, 외부 snapshot 복원 리허설까지 추가됐지만 원격 workflow·Caddy·운영 restore E2E는 없습니다. | 로컬 회귀 차단 능력은 개선됐지만 원격 CI와 실제 배포 경로의 자동 증거는 여전히 부족합니다. |
| `ATM-P2-005` | `pyproject.toml`은 대부분 하한 버전만 지정하고 Python lock이 없습니다. `requirements.txt`는 중복·상이한 최소 버전을 포함하며 npm production audit에서 high 취약점이 확인됐습니다. | 빌드 재현성과 공급망 보안이 시간에 따라 달라집니다. |

## 6. P1/P2 핵심 개선 방향

### 주문·데이터 무결성

- 외부 주문 성공 후 DB 커밋 실패와 부분체결을 복구할 수 있는 주문 상태 모델과 reconciliation을
  도입합니다.
- 금액, 가격, 수량을 `Float`에서 `Numeric/Decimal`로 전환합니다.
- `(asset_id, is_paper)` unique 제약과 주문·분석·스냅샷 시계열 복합 인덱스를 추가합니다.
- 5초 heartbeat와 사용자 설정은 2026-07-15 runtime 전용 컬럼과 versioned 프로필로 분리했습니다.

### 보안·비동기 경계

- Telegram은 토큰과 허용 chat ID가 모두 설정되어야 활성화되도록 fail-closed로 변경했습니다. polling
  예외는 고정 event와 예외 타입만 기록하고 exception 원문·traceback은 남기지 않습니다.
- Slack 테스트의 임의 webhook URL override 제거, 관리자 인증, 서버 설정 URL 고정은
  2026-07-13 ATM-P1-003A에서 완료했습니다. 알 수 없는 요청 필드는 `422`로 거부하고 외부 오류와
  webhook secret은 응답·로그에 노출하지 않습니다.
- 003B에서 공개 범위를 health·market GET·일반 뉴스 목록 GET으로 제한하고, 계좌·주문·설정·채팅,
  관심종목·LLM 비용·백테스트 등 나머지 API에 관리자 인증을 적용했습니다. React는 전역
  `AdminSessionGate`가 `GET /api/admin/session` 검증을 마친 뒤에만 query를 시작하고 raw chat SSE도
  `X-Admin-Token`을 보냅니다. 현재 token의 인증 거절은 민감 화면을 즉시 잠그되 늦은 이전 응답은
  교체된 token을 지우지 않으며, FastAPI 자동 문서·OpenAPI 경로는 공개하지 않습니다.
- CORS origin은 CSV 운영 allowlist로 제한하고 wildcard와 credential 전송을 거부합니다. 개발
  frontend/backend/DB/OpenSearch/Dashboards 포트와 native backend는 loopback에만 바인딩합니다.
- 003C에서 모든 API route를 고정 policy에 매핑하고 PostgreSQL fixed-window를 원자적으로 공유하도록
  구현했습니다. principal은 `public:global`, `admin:primary`, `auth-failure:global`로 고정하고 서버
  secret으로 HMAC-SHA256한 subject hash만 저장합니다. raw 관리자 토큰·Telegram ID·IP·header·path·query는
  요청 제한 원장에 저장하지 않습니다.
- `GET /api/health`는 요청 제한을 면제하고 봇 정지·paper 전환·Gate 차단은 별도 `SAFETY_STOP`
  bucket을 사용합니다. Telegram은 bot token·허용 chat ID·허용 user ID가 모두 있어야 polling하며
  chat과 실제 `message.from.id`가 모두 일치해야 명령을 실행합니다.
- P1-003B의 자동 OpenAPI 비활성화 뒤에도 로컬 Compose healthcheck가 `/openapi.json`을 조회하던 회귀는
  공개 `/api/health`와 정적 회귀 검사로 수정했습니다. 실제 Compose 기동 검증은 아직 완료로 보지
  않습니다.
- Caddy shared-ingress rate-limit plugin, 장시간 작업의 분산 동시성 lease, Telegram 다중 poller
  lease·durable update receipt는 구현하지 않았으며 명시적인 잔여 위험입니다.
- 동기 RSS 수집과 동기 Slack 호출을 비동기 클라이언트로 교체합니다.

### 배포·운영

- `alembic.ini`의 비밀 없는 표준 설정을 추적하고 clean clone Docker build를 검증합니다.
- one-shot migration 서비스가 성공한 뒤 backend가 시작되도록 구성합니다.
- Caddy Basic Auth와 충돌하지 않는 health endpoint를 만들고 liveness, readiness, operational health를
  분리합니다.
- `backups/`를 Git에서 제외하고 권한, 보존, 암호화, 정기 restore drill을 추가합니다.
- Python lock, dependency audit, GitHub Actions 품질 게이트를 도입합니다.

### 프론트엔드 신뢰성

- 포트폴리오 `live/snapshot/cached/error/empty/loading`, `is_stale`, `updated_at`, 오류를 공통 상태 판정과 화면 본문에 적용했습니다. cache 없는 장애를 정상 0원으로 표시하지 않고 unavailable AI 전송을 차단합니다.
- 설정 key별 범위 검증과 실제 소비 SSOT 표시는 2026-07-15 백엔드 registry와 Settings UI에 적용했습니다.
- AI Banker의 SSE `error`와 exact proposal CAS를 처리하고, 안전 dialog의 focus trap·Escape·inert·focus 복귀를 적용했습니다.
- 미동작 AI 예측선과 runtime font CDN을 제거하고 semantic dark/light token과 상태 텍스트를 적용했습니다.
- Vitest·React Testing Library 기반 119개는 로컬에서 통과했습니다. browser viewport screenshot matrix와 핵심 Playwright/원격 CI E2E는 후속입니다.

## 7. 우선순위와 의존 관계

1. `ATM-P0-001` 주문 멱등성 및 불확실 주문 복구
2. `ATM-P0-002` 모든 실주문 경로의 kill switch
3. `ATM-P0-003` paper/inactive 안전 기본값과 live 전환 계약
4. `ATM-P0-004` 전량 청산 서비스와 결과 계약 — 로컬 구현·회귀·PostgreSQL 16.12 검증 완료
5. 주문 원장 reconciliation, 동시성, Numeric 전환
6. 배포·마이그레이션·보안·프론트 신뢰성 및 CI 강화

`ATM-P0-001`은 사용자가 확정한 계획에 따라 구현하며, 후속 P0도 같은 공통 주문 게이트를
소비하도록 의존 방향을 유지합니다. 별도 AI 설계 승인 단계는 사용하지 않습니다.

## 8. 검토 한계와 재검토 조건

- 실제 Upbit 주문이나 자산 변경 요청은 실행하지 않았습니다.
- 운영 PostgreSQL, OpenSearch, Caddy가 실행 중인 통합 환경은 검증하지 않았습니다. 다만 P0-001~P0-004의
  PostgreSQL 16.12 advisory lock·migration·동시성·청산 worker 통합 테스트 64개는 격리된 로컬 DB에서
  migration 왕복 전후 두 차례 통과했습니다. 원격 CI는 미실행 상태입니다.
- P1-003C PostgreSQL 16 migration·원자 경합과 전체 backend/frontend 회귀는 완료했습니다. 실제 Docker
  Compose 전체 기동과 Caddy 통합 검증은 실행하지 않았습니다. PostgreSQL limiter는 애플리케이션 진입
  뒤의 의미 기반 fixed-window만 제공하며 Caddy 앞단 volumetric 제한을 제공하지 않습니다. 장기 작업
  동시성 lease와 Telegram multiworker exactly-once는 후속 설계 범위입니다.
- dependency audit 결과는 검토일의 레지스트리 상태에 따라 달라질 수 있습니다.
- 구현 또는 외부 API 계약 변경 후에는 기존 결과를 덮어쓰지 않고 새 날짜의 리뷰를 추가합니다.

## 9. 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-07-10 | 전체 프로젝트 안전성 리뷰 결과 최초 기록 |
| 2026-07-10 | 사용자 결정에 따라 별도 AI 승인 절차를 제거하고 P0-001 구현 추적 시작 |
| 2026-07-10 | P0-001 중앙 주문 원장과 복구 경계 구현, 로컬 172 passed 및 PostgreSQL CI 검증 대기 기록 |
| 2026-07-10 | P0-002 전용 제어 원장, 비상청산 범위 예외, PostgreSQL 제출 배리어 설계 기록 |
| 2026-07-10 | P0-002 migration `a91f3e7c5b2d`와 제어 repository·동시성 검증 구현 |
| 2026-07-10 | P0-002 제출 배리어·runtime/stop·청산 lifecycle·REST/메신저/React 통합과 로컬 회귀 완료, 실제 PostgreSQL 16 CI 대기 기록 |
| 2026-07-11 | P0-003 fail-closed 거래 모드 원장·전환 계약 구현과 로컬 회귀 완료, PostgreSQL 16 검증 대기 기록 |
| 2026-07-12 | P0-004 ACCOUNT_ALL 선취소, 잔고·원장 최종 증명, REST·메신저·React 통합과 로컬 회귀 완료, PostgreSQL 16 검증 대기 기록 |
| 2026-07-13 | 로컬 PostgreSQL 16.12 marker 64개를 migration 왕복 전후 2회 통과하고 `alembic check`·단일 head 확인; 원격 CI·push 미실행 |
| 2026-07-13 | ATM-P1-003A Slack 테스트 관리자 인증·서버 webhook 고정·HTTP client 로그 비노출 구현, backend 368 passed·frontend 38 passed; 003B 민감 API 인증 인벤토리는 후속 범위로 유지 |
| 2026-07-13 | ATM-P1-003B 공개 GET allowlist·민감 API 관리자 인증·React session gate·CORS/loopback·Telegram fail-closed 구현, backend 394 passed·frontend 54 passed·Ruff/ESLint/build 통과; 003C rate limit·sender 검증은 후속 유지 |
| 2026-07-13 | ATM-P1-003C PostgreSQL fixed-window·고정 policy/principal·Telegram 허용 user ID 검증 구현 및 Compose healthcheck `/api/health` 회귀 수정; 로컬 PostgreSQL 16.12 `73 passed`, backend 합계 `524 passed`, frontend `54 passed`; 원격 CI·전체 Compose 기동 미실행 |
| 2026-07-14 | ATM-P1-007 분석 저장 실패 fail-closed·exact analysis ID 전달·최신 분석 fallback 제거 구현; targeted `40 passed`, backend 비-PostgreSQL `469 passed, 73 deselected`, Ruff·diff check 통과; schema·Alembic·frontend 변경 없음, 원격 CI·push 미실행 |
| 2026-07-14 | ATM-P1-009 cycle-local 리스크 상태·`UNKNOWN/UNHEALTHY` 신규 BUY fail-closed·수동 BUY read-only 평가 구현; P0 중앙 주문·Kill Switch·SELL·청산·reconciliation 계약 유지; schema·Alembic·frontend 변경 없음, 원격 CI·push 미실행 |
| 2026-07-14 | ATM-P1-010A live BUY 최종 비중을 primary·precheck·hard cap 최솟값으로 제한하고 5,000원 미만 목표 예산 상향 제거; precheck 감사 로그·중앙 주문·P0 Gate 유지; schema·Alembic·frontend 변경 없음, 원격 CI·push 미실행 |
| 2026-07-14 | ATM-P1-011 목적별 AI provider deadline·SDK retry 억제·번역 전체 fallback 60초 예산 구현; primary timeout 현재 cycle HOLD·BUY precheck timeout 주문 0회·외부 취소 전파·P0 Gate 유지; schema·Alembic·frontend 변경 없음, 원격 CI·push 미실행 |
| 2026-07-14 | ATM-P1-008 AI 분석 stage/provider/model/fallback/parent/prompt version/context hash 계보와 legacy unknown migration 구현; latest·accuracy·calibration·performance 조회 분리, PostgreSQL 16.12·backend 회귀 완료; 주문 FK·P0 Gate 유지, 원격 CI·push 미실행 |
| 2026-07-14 | ATM-P1-010B BUY 직전 뉴스 최신화 뒤 실제 최신 또는 캐시/RSS 조회, 최대 3건 whitelist snapshot, `buy_precheck.v2` canonical prompt/hash 구현; schema·paper·SELL·P0 Gate 변경 없음, 로컬 backend 회귀·독립 검토 완료, 원격 CI·push 미실행 |
| 2026-07-15 | ATM-P1-004/006 BotConfig runtime 컬럼 분리, BotConfig/SystemConfig version·CAS, SystemConfig 분류 registry·키별 검증·다중 키 원자 저장, REST·AI Banker·Telegram·Settings 실제 SSOT 통합 구현; migration `d5e8a1c4b7f2` offline SQL, backend 627개·frontend 66개 전체 회귀 통과, 실제 PostgreSQL 16·원격 CI 대기 |
| 2026-07-15 | ATM-UI-001 Stitch 기반 semantic dark/light AppShell과 5개 화면·안전 패널 이식, 공통 PortfolioDataState와 unavailable AI gating으로 ATM-P1-005 해결; PostgreSQL 16.12 marker 79개 왕복 전후, frontend 119개, backend 627개, Ruff·ESLint·production build 통과; browser viewport 증거·원격 CI 대기 |
