# P0 로컬 PostgreSQL 16 최종 검증 보고서

> 검증일: 2026-07-13 (Asia/Seoul)
> 대상: ATM-P0-001~ATM-P0-004
> 판정: 로컬 PostgreSQL 16 최종 검증 완료 / 원격 CI 미실행
> 브랜치: `codex/p0-004-liquidation-proof` (upstream 없음)
> 시작 커밋: `b73005ac89bda633682104d6a2796f41ddb9bcec`

## 1. 결론

격리된 PostgreSQL 16.12에서 PostgreSQL marker 테스트 64개를 migration 왕복 전후 두 차례
실행했고 모두 통과했습니다. 빈 DB upgrade, fail-closed downgrade 준비,
`d3a9f7c1b2e4`까지 downgrade, head 재업그레이드, `alembic check`, 단일 head/current도
통과했습니다.

검증 중 애플리케이션 구현 결함은 발견되지 않았습니다. 실제 PostgreSQL에서만 드러난 테스트 fixture,
오류 기대 범위, CI downgrade 준비 계약 및 부하 시간 예산 문제를 최소 수정했고, 수정 후 backend와
frontend 전체 회귀를 다시 통과했습니다.

이 결과는 로컬 검증 완료를 뜻합니다. 원격 GitHub Actions는 실행하지 않았으며 운영 실주문 활성화나
배포 승인을 의미하지 않습니다.

## 2. 격리 환경

| 항목 | 값 |
|---|---|
| Docker Desktop | 4.61.0 |
| Docker Engine | 29.2.1 |
| 이미지 | `postgres:16-alpine` |
| 이미지 digest | `sha256:97ff59a4e30e08d1c11bdcd9455e7832368c0572b576c9092cde2df4ae5552a3` |
| PostgreSQL | 16.12 |
| 컨테이너 | `atm-p0-pg16-test` |
| 컨테이너 ID | `726595a94a50e37d11adba947c5695dfa2823a212227cd9694e6a011e8073f6d` |
| 바인딩 | `127.0.0.1:55432` → `5432` |
| DB | `ai_trade_manager_test` |
| 계정 | 테스트 전용 `postgres` |
| 볼륨 | `atm-p0-pg16-test-data` |
| 격리 라벨 | `com.ai-trade-manager.purpose=p0-pg16-verification` |

환경 변수는 각 검증 프로세스 범위에만 설정했습니다. `.env`는 수정하지 않았고 Upbit, Gemini,
OpenAI 키는 비워 두었으며 Upbit base URL은 연결이 닫힌 localhost 주소로 제한했습니다. 실제 거래소,
운영 PostgreSQL, Gemini API에는 연결하지 않았습니다.

Docker Desktop 시작 전에 존재하던 프로젝트 및 개인 컨테이너 5개는 모두 중지 상태였고 검증 과정에서
시작·중지·수정하지 않았습니다. 검증이 끝난 뒤 전용 컨테이너와 전용 볼륨만 제거했으며 사용자가 직접
시작한 Docker Desktop은 실행 상태로 유지했습니다.

## 3. 실행 결과

### 3.1 최초 migration과 PostgreSQL 테스트

빈 `public` schema에서 `alembic upgrade head`를 적용해 `f6b2c9d4e8a1`까지 성공했습니다.

첫 전체 실행은 로컬 도구의 10분 실행 한도를 넘겨 결과가 확정되지 않아 같은 명령을 충분한 제한으로
다시 실행했습니다. 재실행은 `56 passed, 8 failed, 359 deselected`였고 실패는 다음 테스트·CI 계약
문제로 분류했습니다.

- migration fixture의 데이터 변경 CTE가 의도한 활성 operation을 남기지 못함
- PostgreSQL 제약 위반이 `commit()`이 아니라 `execute()`에서 발생하는데 기대 범위가 너무 좁음
- 테스트 transition helper에 존재하지 않는 `scope` 인자를 전달함
- 청산 권한 request UUID가 operation idempotency key와 일치하지 않음
- 직접 만든 `CLOSED` fixture가 PostgreSQL server default의 `REVOKED` 감사 값을 상속함
- 전체 Docker 부하에서 advisory lock 대기 시간 예산이 지나치게 짧음
- CI downgrade 준비가 P0-004 감사 증거와 fail-closed paper 상태를 명시적으로 정리·검사하지 않음

애플리케이션 서비스, 모델, migration 자체는 수정하지 않았습니다. 테스트 fixture와 기대 범위를 실제
PostgreSQL 동작에 맞추고, CI downgrade 준비를 `paper + inactive + BLOCK_ALL`로 강화했으며, 장시간
부하에서도 의미를 유지하도록 barrier 테스트 시간 예산만 늘렸습니다. 대상 회귀와 반복 barrier 테스트를
먼저 통과한 뒤 전체 suite를 다시 실행했습니다.

최종 1차 결과:

```text
64 passed, 359 deselected in 626.62s (0:10:26)
```

skip은 0건입니다. advisory lock, 8세션 경합, submit/stop 경쟁, CAS, partial unique index,
주문·청산 exactly-once 및 P0-004 계정 전체 청산 증명 테스트가 포함됩니다.

### 3.2 fail-closed migration 왕복

downgrade 전에 다음 조건을 확인하거나 안전 상태로 정리했습니다.

- blocking `OrderIntent`: 0건
- 활성 청산 operation 또는 활성 긴급 승인: 0건
- P0-004 v2/audit 증거: 0건
- rollout flag: OFF
- live order Gate: `BLOCK_ALL`
- PostgreSQL 거래 모드와 legacy mirror: `paper`
- 활성 bot: 0건

그 뒤 다음 순서가 모두 성공했습니다.

```text
alembic downgrade d3a9f7c1b2e4
alembic upgrade head
alembic check
```

최종 `heads`, `current`, `alembic_version`은 모두 단일 revision
`f6b2c9d4e8a1`이었고 `alembic check`는 `No new upgrade operations detected.`를 반환했습니다.

### 3.3 재업그레이드 후 PostgreSQL 테스트

동일한 PostgreSQL marker suite를 재업그레이드된 DB에서 다시 실행했습니다.

```text
64 passed, 359 deselected in 535.50s (0:08:55)
```

skip은 0건입니다. 마지막 확인에서 head/current와 DB revision은 `f6b2c9d4e8a1`이었고
`order_intents`, `liquidation_operations`, `liquidation_order_cancellations`,
`liquidation_operation_events`는 모두 0건이었습니다.

### 3.4 전체 회귀

- backend 비-PostgreSQL: `359 passed, 64 deselected`
- Ruff: 전체 통과
- frontend: 7개 파일, `38 passed`
- frontend ESLint: 통과
- frontend production build: 통과, 2,726개 모듈 변환
- `git diff --check`: 통과

frontend build에는 기존과 같은 500 kB 초과 chunk 경고가 남았습니다. 생성된 JS bundle은
1,242.37 kB였으며 이번 P0 PostgreSQL 검증의 회귀 실패로 판정하지 않았습니다.

## 4. 자원 정리와 외부 영향

검증 전 라벨과 데이터 마운트를 다시 확인한 뒤 `atm-p0-pg16-test`와
`atm-p0-pg16-test-data`만 제거했고 두 자원이 더 이상 존재하지 않음을 확인했습니다. 정리 시점에
다른 작업이 만든 auto-remove PostgreSQL fixture 컨테이너가 새로 관측됐으나 이 프로젝트의 격리
자원이 아니므로 건드리지 않았습니다.

- 실제 Upbit 주문 및 외부 거래소 호출: 0건
- 실제 Gemini/OpenAI 호출: 0건
- 운영 DB 변경: 0건
- 원격 CI 실행: 0건
- 원격 저장소 push/PR 변경: 0건

## 5. 최종 판정

ATM-P0-001~ATM-P0-004에 남아 있던 로컬 PostgreSQL 16 검증 Delta는 완료됐습니다. 주문 의도당
POST 최대 한 번, 전역 Gate와 fail-closed 거래 모드, 계정 전체 청산의 취소·체결·잔여 증명 계약은
실제 PostgreSQL 16.12의 migration, 경합, CAS, lease, partial index, 재시작 및 exactly-once
테스트로 확인했습니다.

남은 검증 상태는 “로컬 PostgreSQL 16 완료 / 원격 CI 미실행”입니다. rollout OFF와
`BLOCK_ALL` 기본값, UNKNOWN 또는 활성 청산이 있을 때 downgrade를 금지하는 운영 제한은 그대로
유효합니다.
