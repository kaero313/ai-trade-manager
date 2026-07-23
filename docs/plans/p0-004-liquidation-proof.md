# ATM-P0-004 전량청산 증거 기반 종결 계획·구현 기록

> 발견사항: `ATM-P0-004`
> 상태: 구현·로컬 회귀·PostgreSQL 16.12 최종 검증 완료 / 원격 CI 미실행
> 구현 기준일: 2026-07-12
> 원본 리뷰: [2026-07-10 프로젝트 안전성 리뷰](../reviews/2026-07-10-project-safety-review.md)
> 선행 계약: [P0-001 주문 멱등성](p0-001-upbit-order-idempotency.md),
> [P0-002 전역 실주문 Kill Switch](p0-002-live-order-kill-switch.md),
> [P0-003 fail-closed 거래 모드](../reviews/2026-07-11-p0-003-implementation-review.md)

## 1. 목표와 완료 불변식

기준 커밋에서는 Upbit `balance`에서 `locked`를 다시 차감하고, HTTP 성공이나 주문 요청 완료를
전량청산 성공처럼 표시할 수 있었습니다. P0-004는 다음 불변식을 PostgreSQL SSOT와 중앙 주문
서비스에서 강제합니다.

- Upbit `primary` 계정의 봇·수동 `wait/watch` 주문을 모두 확인·취소하기 전에는 청산 매도를
  제출하지 않습니다.
- 매도 가능 수량은 Upbit `balance` 자체이며 `balance - locked`를 사용하지 않습니다.
- 계좌·미체결 주문·청산 intent·Position의 최종 증거가 모두 일치한
  `COMPLETED + VERIFIED`만 성공입니다.
- dust, 잠금, 미지원 자산, 주문 실패, 외부 주문 체결과 원장 차이는 `PARTIAL` 또는 `FAILED`로
  노출합니다.
- 불변 대상 snapshot 이후 새로 나타난 자산에 자동 2차 매도를 만들지 않고, 외부 체결을 가짜
  OrderHistory나 Position 자동 보정으로 숨기지 않습니다.
- terminal 결과와 무관하게 청산 권한을 닫고 Gate를 `BLOCK_ALL`로 복귀시킵니다.
- paper·backtest·Gemini/OpenAI 분석 경로는 변경하지 않습니다.

## 2. 공개 계약

### REST

신규 계정 전체 청산은 다음 요청만 허용합니다.

```http
POST /api/bot/liquidate
Idempotency-Key: <UUID v4>
Content-Type: application/json

{"scope":"ACCOUNT_ALL","confirmation":"CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL"}
```

- `Idempotency-Key`는 UUID v4가 필수입니다.
- 같은 키의 같은 fingerprint는 기존 operation을 재생하고, 다른 fingerprint는
  `409 LIQUIDATION_IDEMPOTENCY_CONFLICT`입니다.
- `(UPBIT, primary)`에 활성 operation이 있으면 `409 ACTIVE_LIQUIDATION_EXISTS`와 기존 operation
  상세를 반환합니다.
- 진행 중이면 `202`, terminal 재요청이면 외부 mutation 없이 `200`입니다.
- P0-002의 `LIQUIDATE_ALL`은 역사적 계약이며 현재 요청에서는 `422`입니다.
- `GET /api/bot/liquidations/{id}`는 DB 결과만 읽습니다. GET이 worker를 깨우거나 Upbit 취소·조회,
  신규 주문 제출을 수행하지 않습니다.

응답에는 `contract_version`, `cancel_scope`, `phase`, `verification_status`, 취소·주문·잔여
`summary`, `cancellations`, 종목별 최초·취소 후·최종 잔고와 주문 결과, 각 계좌 관측 시각을
포함합니다. 결과 코드는 `LIQUIDATED`, `DUST_REMAINING`, `LOCKED_REMAINING`,
`UNSUPPORTED_MARKET`, `ORDER_FAILED`, `VERIFY_FAILED`, `LEDGER_MISMATCH`입니다.

### 브로커

- `BaseBrokerClient.cancel_orders_by_ids(uuids)` capability를 추가하고 Upbit가 UUID 20개 단위 취소를
  구현합니다.
- `cancel_order()`와 `cancel_orders_by_ids()`에는 mutation blind retry를 두지 않습니다.
- 응답 유실·오류는 주문 UUID 조회로 판정하고, 명확히 열린 주문만 다음 worker claim에서 다시
  취소합니다.

## 3. PostgreSQL 증거 원장

마이그레이션 `f6b2c9d4e8a1`은 다음 계약을 추가합니다.

### `liquidation_operations`

- `broker`, `account_scope`, `contract_version`, SHA-256 `request_fingerprint`, `cancel_scope`
- `phase`, `verification_status`, `version`, 120초 operation lease, `next_run_at`, `retry_count`
- 최초·취소 후·최종 계좌 snapshot과 관측 시각
- 불변 대상, 종목별 결과, 취소·주문·잔여 summary
- `(broker, account_scope)` 활성 operation partial unique index

신규 행은 `contract_version=2`, `ACCOUNT_ALL`입니다. 기존 행은 `contract_version=1`,
`LEGACY_NONE`, `TERMINAL`, `LEGACY_UNVERIFIED`로 보존하며 검증 성공으로 승격하지 않습니다.

### `liquidation_order_cancellations`

- operation과 Upbit UUID의 unique 조합, identifier, market, side, 최초 `wait/watch` 상태
- 관리 주문은 `order_intent_id` FK, 수동·외부 주문은 FK가 없는 `EXTERNAL` 소유 구분
- `DISCOVERED`, `CANCELING`, `UNKNOWN`, `CONFIRMED`, `FAILED` 상태
- 최대 3회 DELETE attempt, 별도 취소 결과 조회 attempt와 15초~15분 backoff, version, 90초 lease,
  다음 재시도, 체결·잔여 수량, 오류와 시각

### `liquidation_operation_events`

operation 생성, phase 전환, 주문 발견·취소, 계좌 관측, 대상 확정, 주문 제출·해결, 최종 검증,
오류와 종결을 operation별 sequence로 append-only 저장합니다. event update/delete trigger와
operation·취소 행 hard-delete 차단 trigger가 감사 증거를 보존합니다.

upgrade/downgrade는 공통 advisory transaction lock, rollout OFF, 모든 Gate `BLOCK_ALL`, 활성
청산·활성 긴급 승인·blocking intent 없음이 필수입니다. 기존 활성 청산이나 `ACTIVE` 승인이 있으면
upgrade를 중단합니다. downgrade는 v2 operation과 취소·event 데이터가 한 건도 없을 때만
허용합니다.

## 4. phase와 복구 동작

`BLOCKING → DISCOVERING_ORDERS → CANCELING_ORDERS → RECONCILING_CANCELED_ORDERS → SNAPSHOTTING_TARGETS → SUBMITTING → WAITING_FILLS → VERIFYING → TERMINAL`

1. REST 요청은 exclusive 배리어에서 operation과 `BLOCK_ALL`을 먼저 커밋하고 기존 shared POST와
   영속 `SUBMITTING`을 drain합니다.
2. worker가 계좌 최초 snapshot을 저장하고 Upbit `wait/watch` 주문을 100개씩 끝까지 조회해 취소
   원장에 기록합니다.
3. 취소할 UUID를 최대 20개 claim·commit한 뒤 DB 트랜잭션 없이 DELETE를 한 번 호출합니다. stale
   claim과 응답 유실은 UUID GET으로 복구하며 각 주문은 최대 3회만 취소합니다.
4. 관리 주문의 취소 중 부분체결은 OrderIntent reconciliation으로 먼저 투영합니다. blocking
   intent나 다시 발견된 미체결 주문이 있으면 다음 phase로 가지 않습니다.
5. 취소 후 계좌를 strict Decimal로 파싱합니다. currency 누락·중복·소문자, 누락·빈 값·음수·비유한
   `balance/locked`는 fail-closed 오류입니다.
6. Upbit `balance` 자체를 requested volume으로 사용합니다. 5,000원 미만, 전량 잠금, 미지원 KRW
   마켓은 매도 POST 없이 명시적인 잔여 코드로 저장합니다.
7. 주문 가능한 불변 snapshot만 `EXIT_ONLY` 승인 후 `LiveOrderExecutionService`로 제출합니다. 모든
   intent가 종결·투영될 때까지 identifier reconciliation으로 기다립니다.
8. 최종 phase에서 미체결 주문을 다시 확인하고 계좌 전체와 live Position을 비교합니다. 새 주문은
   최대 3회의 추가 취소 발견 라운드로 처리하지만 신규 매도 target을 만들지 않습니다.
9. phase 오류는 15초, 30초, 1분, 2분, 5분, 10분, 최대 15분 backoff로 due 시각을 저장합니다.
   애플리케이션 시작 시 한 번, POST 직후 즉시, 이후 15초 주기로 worker가 due operation을 claim합니다.

인증·권한·허용 IP·HTTP 418은 rollout 퓨즈 OFF, `BLOCK_ALL`, 치명 로그를 적용하고 청산을 실패
종결합니다. 다중 worker는 lease와 version 검증으로 stale 결과를 쓰지 않습니다.

## 5. 종결 판정과 UI·메신저

최종 검증은 다음을 모두 요구합니다.

- Upbit `wait/watch` 주문 0
- 모든 비-KRW `balance=0`, `locked=0`
- 청산 OrderIntent가 거래소 `done/cancel`이고 투영 `APPLIED/SKIPPED`
- 거래소 보유량과 live Position 차이가 통화별 `1e-12` 이하
- 수동·외부 주문 체결로 조정되지 않은 원장이 남지 않음

모두 만족하면 `COMPLETED + VERIFIED`, 처음부터 증명할 자산이 없으면 `NO_ASSETS + VERIFIED`입니다.
양의 잔고·잠금, dust, 미지원 자산, 주문 실패는 `PARTIAL`이고 수동·외부 주문 체결 또는 Position
차이는 `PARTIAL/LEDGER_MISMATCH`입니다. 최종 계좌 조회가 실패하면 성공 종결하지 않고 worker가
재조회합니다.

React UI는 계정의 수동 주문도 취소된다는 경고와 정확한 확인 문구 직접 입력을 요구합니다. phase,
검증 상태, 취소·주문 집계, 종목별 최초·최종 잔고와 결과를 표시하고 `COMPLETED + VERIFIED`만
성공색으로 렌더링합니다. UUID와 terminal snapshot은 사용자가 결과를 닫거나 새 작업을 준비할 때까지
sessionStorage에 보존합니다.

Slack/Telegram에는 청산 실행 버튼·명령을 추가하지 않습니다. `/status`가 활성 operation ID,
phase와 잔여 수를 보여주며 `/stop`은 기존 fail-closed 정지 경계를 유지합니다.

## 6. 검증과 배포 상태

2026-07-12 로컬 Docker 없이 다음을 확인했습니다.

- frontend `38 passed`, ESLint, TypeScript, production build 통과
- Ruff `app`, `tests` 통과
- backend 비-PostgreSQL `359 passed, 64 deselected`
- PostgreSQL marker `64 collected`; Docker PostgreSQL 16 미실행으로 모두 최종 검증 대기
- 실제 Upbit·Gemini API, 운영 DB, 원격 CI, git push 사용 없음

2026-07-13 후속 검증에서는 로컬 PostgreSQL 16.12 marker 64개를 migration 왕복 전후 두 차례 모두
통과했습니다. 활성 operation partial index, operation/cancellation lease·version CAS, 다중 worker,
수동 주문 선취소, 부분체결 투영과 최종 `COMPLETED + VERIFIED` exactly-once를 포함하며,
`alembic downgrade d3a9f7c1b2e4` 후 재업그레이드, `alembic check`, 단일 head를 확인했습니다. 최신
비-PostgreSQL backend는 `359 passed, 64 deselected`이고 Ruff도 통과했습니다. 원격 CI와 push는
실행하지 않았습니다. 이 로컬 검증 완료는 운영 실주문 기능 활성화를 의미하지 않습니다.

배포는 rollout OFF, 모든 Gate `BLOCK_ALL`, 활성 청산·활성 긴급 승인·blocking intent 없음에서
migration을 먼저 적용합니다. 검증 전에는 퓨즈와 Gate를 활성화하지 않습니다. UNKNOWN intent 또는
v2 청산 증거가 있는 DB는 구버전 코드로 롤백하거나 migration downgrade하지 않습니다.
