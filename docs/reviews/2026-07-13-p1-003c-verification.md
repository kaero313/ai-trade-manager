# ATM-P1-003C 로컬 PostgreSQL 16·전체 회귀 검증 보고서

> 검증일: 2026-07-13 (Asia/Seoul)
> 대상: ATM-P1-003C PostgreSQL 공유 요청 제한·Telegram sender 검증
> 판정: 로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행

## 1. 결론

격리된 PostgreSQL 16.12에서 P1-003C fixed-window migration, 원자 요청 집계, route별 policy,
fail-closed 응답과 Telegram sender 검증을 확인했습니다. 빈 DB migration, 신규 head에서 이전 head로의
downgrade, head 재업그레이드, `alembic check`, 단일 head/current가 모두 통과했습니다.

PostgreSQL marker 73개와 backend 비-PostgreSQL 451개를 합친 backend 524개, frontend 54개 및
Ruff·ESLint·production build가 통과했습니다. 신규 limiter PostgreSQL 테스트 9개는 migration 왕복
전후에 각각 통과했고, 보안·migration 대상 테스트 98개와 마지막 보안 hardening 대상 89개도 별도로
통과했습니다. 대상 실행은 전체
suite와 중복되므로 테스트 총계에 다시 더하지 않습니다.

이 판정은 로컬 PostgreSQL 16·전체 코드 회귀 완료를 의미합니다. 원격 CI, 실제 Docker Compose 전체
기동, 운영 배포 또는 외부 API 검증 완료를 의미하지 않습니다.

## 2. 검증 환경

| 항목 | 값 |
|---|---|
| 이미지 | `postgres:16-alpine` |
| 이미지 digest | `sha256:97ff59a4e30e08d1c11bdcd9455e7832368c0572b576c9092cde2df4ae5552a3` |
| PostgreSQL | 16.12 |
| 데이터베이스 | 격리된 로컬 테스트 DB |
| 외부 API | Slack·Telegram·Upbit·Gemini/OpenAI 호출 없음 |
| 운영 DB | 연결·변경 없음 |
| 원격 저장소 | CI·push·PR 변경 없음 |

실제 API key와 운영 데이터는 사용하지 않았습니다. P1-003B healthcheck 회귀는
`docker-compose.local.yml`이 공개 `/api/health`를 조회하도록 수정하고 정적 보안 회귀에서 확인했지만,
Docker Compose 전체 서비스의 backend healthy·web 기동은 실행하지 않았습니다.

## 3. 실행 결과

### 3.1 보안·migration 대상 회귀

P1-003C와 직접 연결된 route 분류, fixed-window 서비스·repository, 인증 실패, 공개 market·뉴스,
Telegram transport·sender, migration 계약과 Compose healthcheck 정적 검사를 먼저 실행했습니다.

```text
98 passed
```

이 대상 실행으로 다음 계약을 확인했습니다.

- 모든 API route는 하나의 고정 policy에 매핑되고 미분류 route는 fail-closed
- `/api/health`는 요청 제한 면제
- 봇 정지·paper 전환·Gate 차단은 일반 mutation과 다른 `SAFETY_STOP` bucket 사용
- 초과 요청은 `429 RATE_LIMIT_EXCEEDED`와 `Retry-After` 반환
- 유효한 요청의 limiter DB 장애는 `503 RATE_LIMIT_UNAVAILABLE`
- 잘못되거나 누락된 관리자 credential은 limiter DB 장애 중에도 `401/403` 유지
- raw 관리자 token·Telegram ID·IP·header·path·query를 요청 제한 원장에 저장하지 않음
- Telegram token·chat ID·allowed user ID 3요소와 실제 sender 조합 검증

독립 secret 재사용 차단과 CORS 노출 header를 추가 점검한 마지막 보안 hardening 대상 실행도
`89 passed`로 통과했습니다.

### 3.2 fresh migration과 왕복

빈 테스트 DB에 `alembic upgrade head`를 적용해 신규 `api_rate_limit_windows`를 포함한 단일 head를
구성했습니다. 그 뒤 다음 순서를 검증했습니다.

```text
b8d4e6f1a2c3 -> f6b2c9d4e8a1 downgrade
alembic upgrade head
alembic check
```

fresh upgrade, downgrade, head 재업그레이드, `alembic check`, 단일 Alembic head와 현재 DB revision이
모두 통과했습니다. migration 왕복 뒤에도 새 limiter table의 기본 키·제약·index가 다시 생성되고
모델 metadata와 migration 사이에 새 upgrade 작업이 남지 않음을 확인했습니다.

### 3.3 PostgreSQL 16 원자성

신규 limiter PostgreSQL 테스트 9개를 재업그레이드 전후 각각 실행했고 두 번 모두 통과했습니다.
독립 session 경합에서도 fixed-window 요청 수가 PostgreSQL의 원자 `INSERT ... ON CONFLICT DO UPDATE`로
집계되고, 고정 policy/principal별 bucket과 24시간 정리 기준이 유지됨을 확인했습니다.

최종 PostgreSQL marker 전체 결과는 다음과 같습니다.

```text
73 passed
```

### 3.4 backend·frontend 전체 회귀

- backend 비-PostgreSQL: `451 passed`
- backend 합계: `524 passed` (`451` non-PG + `73` PostgreSQL)
- Ruff: 통과
- frontend: `54 passed`
- frontend ESLint: 통과
- frontend production build: 통과
- `git diff --check`: 통과

frontend production build에는 기존 500KB 초과 chunk 경고가 남았습니다. 이번 P1-003C 변경으로 새로
발생한 회귀로 판정하지 않았습니다.

## 4. 검증 안정화 변경

Windows Docker의 fsync 지연에서는 기존 PostgreSQL 테스트가 의미 있는 상태 전이를 기다리기 전에
2~5초 제한으로 종료될 수 있었습니다. 다음과 같이 테스트만 보강했습니다.

- 기존 PostgreSQL 비동기 처리 대기 상한을 2~5초에서 30초로 확대
- 청산 취소 phase 테스트를 한 번의 고정 대기 대신 최대 3회 상태를 다시 읽는 bounded refresh로 변경

대기 상한과 refresh 횟수는 실패를 숨기는 무제한 retry가 아니며 최종 조건 검증은 그대로 유지합니다. 이
안정화 과정에서 애플리케이션 서비스·API·worker·migration 등 운영 코드는 변경하지 않았습니다.

## 5. 외부 영향과 미실행 범위

- 실제 Slack·Telegram 메시지 또는 polling: 0건
- 실제 Upbit 조회·주문·취소: 0건
- 실제 Gemini/OpenAI 호출: 0건
- 운영 PostgreSQL 연결·변경: 0건
- 원격 CI 실행: 0건
- git push·PR·원격 저장소 변경: 0건
- Docker Compose 전체 기동: 미실행

따라서 `/api/health` 정적 healthcheck 회귀는 고정됐지만 Caddy, web, backend, PostgreSQL,
OpenSearch를 함께 기동한 Compose E2E 결과로 확대 해석하지 않습니다.

## 6. 잔여 위험

- **Caddy volumetric limiter:** shared-ingress rate-limit plugin을 설치·버전 고정·검증하지 않았습니다.
  PostgreSQL limiter는 애플리케이션 진입 뒤의 의미 기반 방어입니다.
- **hot-path 정리 지연:** 현재 만료 window 정리는 제한 판정 SQL 안에서 수행됩니다. 대량 backlog나
  장시간 lock 보유 상황의 bounded DB timeout은 후속으로 보강해야 합니다.
- **장시간 작업 lease:** fixed-window는 AI·backtest 같은 장시간 작업의 분산 동시 실행 수를 제한하는
  lease/semaphore가 아닙니다.
- **Telegram multi-poller receipt:** bot별 poller lease와 durable update receipt가 없어 단일 backend
  poller 운영 전제를 유지합니다. 다중 worker exactly-once와 crash replay 방지는 후속 범위입니다.

## 7. 최종 판정

ATM-P1-003C의 로컬 검증 Delta는 완료됐습니다. PostgreSQL 16.12에서 fixed-window schema·migration
왕복·원자 집계와 보안 route·Telegram sender 계약을 확인했고 backend·frontend 전체 회귀도
통과했습니다.

현재 상태는 **로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행**입니다. 실제 Compose 전체 기동과
네 가지 잔여 위험은 별도 후속 검증·설계 없이는 완료로 간주하지 않습니다.
