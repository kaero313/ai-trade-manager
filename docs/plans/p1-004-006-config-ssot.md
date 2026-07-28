# ATM-P1-004/006 설정 SSOT·동시성·서버 검증 계획·구현 기록

> 작성일: 2026-07-15  
> 상태: 구현·로컬 PostgreSQL 16·backend/frontend 전체 회귀 완료 / 원격 CI 미실행  
> Alembic: `c7a1e9d4f2b6 → d5e8a1c4b7f2`  
> 원격 push·PR: 수행하지 않음

## 1. 문제와 목표

기존 구현은 5초 heartbeat와 사용자 프로필 저장이 모두 `BotConfig.config_json` 전체를 갱신해 서로의
변경을 잃을 수 있었습니다. 동시에 실제 운영 매매는 `SystemConfig`를 소비하지만 Settings와 Telegram
일부 경로는 `BotConfig`를 저장해, 성공 안내와 실제 runtime 동작이 달라질 수 있었습니다.

이번 작업의 목표는 다음과 같습니다.

- heartbeat·최근 오류·동작을 사용자 프로필과 다른 저장 단위로 분리합니다.
- 운영 설정의 실제 SSOT와 소비자를 명시합니다.
- stale UI·AI Banker 승인과 다중 writer의 lost update를 version으로 차단합니다.
- 모든 외부 설정 변경이 동일한 키별 서버 검증과 원자 저장 경계를 사용하게 합니다.
- 운영에서 소비되지 않는 설정을 적용된 값처럼 표시하지 않습니다.
- P0 거래 모드, Kill Switch, 배포 퓨즈와 중앙 주문 경계를 일반 설정으로 약화하지 않습니다.

## 2. 확정 SSOT

| 데이터 | 권위 저장소 | 소비·변경 경계 |
|---|---|---|
| 운영 매매 대상·Entry Gate·주문 한도·스케줄 | 분류된 `SystemConfig` | 중앙 설정 서비스 |
| 봇 실행 여부 | `BotConfig.is_active` | 시작·정지 서비스 |
| heartbeat·최근 오류·최근 동작 | `BotConfig.runtime_*` | 런타임 writer |
| legacy/연구 전략 프로필 | `BotConfig.config_json` | `/api/config` ETag/CAS |
| 거래 모드 | `trading_mode_controls` | P0 전용 서비스 |
| 실주문 허용 범위 | `live_order_controls` | P0 전용 서비스 |
| 실주문 배포·인증 퓨즈 | 보호된 `live_order_v2_enabled` | P0 내부 경계 |

`BotConfig.config_json`의 `symbols`, `allocation_pct_per_symbol`, strategy, risk, schedule은 연구소·구버전
호환 프로필입니다. production scheduler, Entry Gate와 live BUY sizing의 권위값으로 사용하지 않습니다.

## 3. 데이터 모델과 migration

### `bot_configs`

- `config_version INTEGER NOT NULL DEFAULT 1`
- `runtime_last_heartbeat TIMESTAMPTZ NULL`
- `runtime_last_error TEXT NULL`
- `runtime_latest_action TEXT NULL`
- `runtime_updated_at TIMESTAMPTZ NULL`
- `config_version >= 1` check

### `system_configs`

- `version INTEGER NOT NULL DEFAULT 1`
- `version >= 1` check

마이그레이션 `d5e8a1c4b7f2`는 `c7a1e9d4f2b6`의 직접 자식입니다. 기존
`config_json.metadata.runtime_status`가 객체인 행만 runtime 컬럼으로 옮깁니다. PostgreSQL 16의
입력 검증을 통과하지 못하는 timestamp는 `NULL`로 격리하며 `owner`, `note` 같은 다른 metadata는
보존합니다. runtime_status 제거 뒤 metadata가 비면 metadata 키도 제거합니다. downgrade는 객체형
metadata를 보존한 채 runtime 컬럼을 `metadata.runtime_status`로 재구성합니다.

## 4. SystemConfig 분류

| 분류 | 외부 변경 | 예시 |
|---|---|---|
| `PUBLIC_MUTABLE` | REST·AI Banker 승인·Telegram 공통 서비스에서 허용 | 대상 종목, 한도, 스케줄, provider 설정, RAG, Slack |
| `INTERNAL_STATE` | 내부 writer 또는 제한된 전용 API만 허용 | paper 잔액, 시장 심리 snapshot, provider 상태 |
| `DEDICATED_PROTECTED` | 일반 설정 변경 금지 | `trading_mode`, `live_order_v2_enabled` |
| `LEGACY_READ_ONLY` | 호환 조회만 허용 | `autonomous_ai_interval_hours` |

unknown key는 외부 요청으로 생성할 수 없습니다. startup seed는 누락 행만 version 1로 추가하고 기존
운영값을 자동 변경하지 않습니다.

## 5. 동시성 계약

### BotConfig 연구 프로필

- `GET /api/config`는 `ETag: "<config_version>"`과 `X-Config-Version`을 반환합니다.
- `POST /api/config`는 현재 ETag의 `If-Match`가 필수입니다.
- 누락은 `428`, 잘못된 헤더는 `400`, stale version이나 CAS 경쟁 패배는 `409`입니다.
- heartbeat/start/stop은 runtime 컬럼과 `is_active`만 갱신하고 `config_json/config_version`을 건드리지
  않습니다.

### SystemConfig

외부 mutation은 키마다 `expected_version >= 1`을 요구합니다.

1. 요청 전체의 key·value를 검증하고 canonicalize합니다.
2. 관련 키를 정렬해 `SELECT ... FOR UPDATE`로 잠급니다.
3. 모든 필수 행과 expected version을 확인합니다.
4. 병합된 최종 설정의 교차 제약을 확인합니다.
5. 모든 행을 한 트랜잭션으로 갱신하고 각 version을 증가시킵니다.
6. 하나라도 실패하면 전체 rollback합니다.

`live_buy_enabled` 또는 `ai_entry_shadow_mode` 변경은 두 행을 모두 잠그며 두 값이 동시에 true인 최종
상태를 거절합니다. DB 커밋 뒤 scheduler reload가 실패한 경우 저장 성공으로 위장하지 않고
`503 SCHEDULER_RELOAD_FAILED`, `saved=true`를 반환합니다.

## 6. 서버 검증

| 설정 | 계약 |
|---|---|
| 뉴스 주기 | 정수 1~23시간 |
| 시장 심리 주기 | 정수 1~59분 |
| 자율 AI 주기 | 정수 1~1440분 |
| 브리핑 시각 | 유효한 `HH:MM` |
| 최대 배분 | 유한 Decimal 0~100 |
| BUY 1회 상한 | 유한 Decimal 0~30 |
| TP / SL | TP 0~1000, SL -1000~0 |
| 점수·확신도 | 정수 0~100 |
| calibration 적중률 | 유한 Decimal 0~100 |
| 분석·뉴스 유효시간 | 정수 1~1440분 |
| 동시 포지션 | 정수 1~10 |
| 종목 목록 | uppercase `KRW-*`, 중복 금지, 최대 50개; target은 비어 있을 수 없음 |
| boolean | `true` 또는 `false`만 허용 |
| persona | 최대 8,000자 |
| provider priority | Gemini와 OpenAI를 각각 한 번 포함 |
| provider settings | 지원 provider·purpose와 1~128자 model만 허용 |
| Slack 규칙 | 필드·요일·시각·section·decision·confidence 구조 검증 |

지수 표기, `NaN`, `Infinity`, malformed JSON, 중복 종목·규칙·시각과 알 수 없는 필드는 저장 전에
거절합니다. canonical JSON은 정렬된 compact 형식으로 저장합니다.

## 7. REST·AI Banker·Telegram·UI

- `PUT /api/system/configs`는 모든 항목의 `expected_version`을 요구합니다.
- AI Banker 제안은 생성 시점의 version을 포함하고 승인 시 같은 중앙 서비스를 사용합니다.
- Telegram `/setrisk`는 `max_allocation`, `max_buy_weight`, `max_positions`, `entry_score`,
  `min_confidence`만 지원합니다. 미지원·중복·혼합 오류는 전체 변경을 거절합니다.
- provider runtime 상태는 일반 설정 payload로 변경할 수 없습니다.
  `POST /api/system/ai/providers/status/reset`이 현재 version을 요구하고 빈 상태로 초기화합니다.
- Settings는 실제 runtime이 소비하는 target/excluded symbols, 전체 배분, BUY hard cap, 동시 포지션,
  calibration과 기존 운영 설정을 `SystemConfig`에서 읽고 저장합니다.
- Settings는 각 키를 처음 편집한 시점의 version을 저장 기준으로 고정합니다. 편집 중 query가 더 최신
  version으로 갱신되면 stale draft를 새 version으로 자동 재기반하지 않고 API 호출 전에 저장을 차단한 뒤
  draft와 기준 version을 폐기하고 최신 설정을 다시 조회합니다.
- 기존 `BotConfigForm`과 적용되지 않는 `allocation_pct_per_symbol` 운영 입력은 제거했습니다.
- Laboratory는 legacy BotConfig 전략 프로필을 참고하되 운영 market·리스크 기본값은 SystemConfig가
  있으면 그 값을 우선합니다.

## 8. 보존 경계와 제외 범위

- `trading_mode_controls`, `live_order_controls`, `live_order_v2_enabled`의 P0 전용 경계를 유지합니다.
- `LiveOrderExecutionService`, 주문 intent, reconciliation, 청산 계약을 변경하지 않습니다.
- paper·backtest 계산 엔진과 AI 분석·주문 의사결정 계약을 변경하지 않습니다.
- 설정을 비밀 저장소로 확장하지 않습니다. API 키와 관리자 secret은 계속 환경변수에서만 읽습니다.
- 포트폴리오 stale/error UI와 결정론적 백테스트 표시 개선은 후속 작업입니다.

## 9. 수용 기준

- heartbeat와 프로필 저장이 경합해도 양쪽 값과 version 의미가 보존됩니다.
- 같은 version의 동시 저장은 정확히 하나만 성공합니다.
- 다중 키 중 하나가 stale·누락·무효이면 변경 0건입니다.
- 오래된 AI Banker 승인은 `409`이며 Telegram 미지원·혼합 요청은 변경 0건입니다.
- server validation이 숫자·JSON·종목·provider·Slack 경계를 강제합니다.
- UI는 production이 실제 소비하는 SystemConfig만 운영값으로 표시합니다.
- provider status reset은 전용 version 계약만 사용합니다.
- P0 거래 모드·Kill Switch·중앙 주문 경계 회귀가 없습니다.
- migration upgrade/downgrade/re-upgrade, PostgreSQL 다중 세션 경합, backend/frontend 전체 회귀를
  통과해야 최종 완료로 판정합니다.

상세 검증 상태는 [2026-07-15 검증 보고서](../reviews/2026-07-15-p1-004-006-verification.md)에
기록합니다.
