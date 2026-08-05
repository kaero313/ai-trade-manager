# ATM-P1-011 로컬 검증 보고서

> 검증일: 2026-07-14
> 브랜치: `codex/p1-011-provider-deadline`
> 상태: 구현·로컬 backend 검증 완료 / 원격 CI·push 미실행

## 검증 계약

- 중앙 provider router의 목적별 1회·전체 실행 deadline과 제한된 fallback
- OpenAI/Gemini SDK의 30초 timeout과 내부 자동 재시도 억제
- primary provider 전체 실패 시 현재 cycle HOLD 저장
- BUY precheck timeout 시 주문 실행 0회
- timeout의 일반 오류 기록과 rate-limit cooldown 미적용
- 외부 task 취소 전파와 analyzer 정리
- 뉴스 번역 문서 한 건의 Gemini→OpenAI 전체 60초 예산
- 기존 exact analysis ID, BUY risk veto, reduce-only, 중앙 실주문·Kill Switch 경계 유지

## 검증 결과

| 검증 | 결과 |
|---|---:|
| provider router·SDK·BUY fail-closed·채팅·RAG targeted | `93 passed` |
| backend 비-PostgreSQL 전체 | `528 passed, 73 deselected` |
| Ruff | 통과 |
| `git diff --check` | 통과 |

전체 회귀 최초 실행의 SDK 설정 테스트 2건은 앞서 수집된 `test_chat_sessions.py`가 등록한 채팅 모듈
stub을 검사해 실패했습니다. 테스트가 실제 `orchestrator.py`를 격리 로드하도록 수정한 뒤 동일 수집
순서 `12 passed`와 전체 회귀 `528 passed`로 재검증했습니다. 프로덕션 결함이나 외부 API 호출은
없었습니다.

## 범위 확인

- DB 모델과 Alembic head는 변경하지 않았습니다.
- frontend와 공개 REST 계약은 변경하지 않았습니다.
- 실제 Gemini/OpenAI/Upbit API와 운영 DB를 호출하지 않았습니다.
- 원격 저장소 push와 PR을 수행하지 않았습니다.

## 남은 Delta

- deadline은 provider 실행 구간만 제한합니다. 후보 조회·provider 상태 DB 기록까지 포함한 엄밀한
  end-to-end deadline과 bounded cleanup은 후속 hardening 후보입니다.
- 독립 하드 TP/SL scheduler와 다중 worker lease는 `ATM-P2-002`·`ATM-P2-003` 범위입니다.
- provider/model/stage/fallback 감사 계보는 다음 `ATM-P1-008` 범위입니다.
