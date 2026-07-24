# ATM-P1-011 AI provider deadline 계획·구현 기록

> 기준: P1-010A 완료 커밋 `81841ba`
> 범위: provider 실행 시간 제한, timeout fail-closed, SDK retry 억제

## Delta와 충돌 판정

- OpenAI/Gemini 직접 호출과 중앙 provider fallback에는 application-level deadline이 없었습니다.
- SDK 기본 재시도로 한 번의 분석 지연이 예측보다 길어질 수 있었습니다.
- primary 분석과 BUY precheck의 기존 오류 처리는 각각 현재 cycle HOLD와 BUY veto였으므로, 주문
  경계를 바꾸지 않고 timeout을 그 fail-closed 흐름으로 연결할 수 있었습니다.
- DB schema·공개 API·`LiveOrderExecutionService`·Kill Switch·`BLOCK_ALL/EXIT_ONLY` 변경은 없습니다.

## 구현 계약

| 목적 | provider 1회 | provider 실행 전체 | fallback |
|---|---:|---:|---|
| `trade_analysis` | 20초 | 35초 | 허용 |
| `buy_precheck` | 15초 | 15초 | 금지 |
| portfolio/news/backtest report | 20초 | 35초 | 허용 |
| chat | 30초 | 45초 | 허용 |
| 기타 중앙 router | 20초 | 35초 | 정책에 따름 |

- OpenAI/Gemini SDK는 30초 HTTP/application 제한과 자동 재시도 0회를 사용합니다. Gemini SDK의
  `attempts=1`은 최초 호출 한 번만 뜻합니다.
- timeout은 일반 provider 오류로 기록하고 rate-limit cooldown을 만들지 않습니다.
- 외부 `CancelledError`는 fallback이나 성공으로 변환하지 않습니다.
- primary 전체 실패는 현재 cycle의 HOLD를 새로 저장합니다. BUY precheck 실패는 HOLD 감사 로그를
  남기고 주문을 호출하지 않습니다.
- 뉴스 번역은 문서 한 건의 Gemini→OpenAI 전체 fallback에 60초 예산을 적용합니다.
- analyzer는 성공·오류·timeout에서 정리합니다.

## 제외 범위

- 독립 하드 TP/SL scheduler와 분산 lease는 `ATM-P2-002`·`ATM-P2-003`으로 유지합니다.
- provider 후보 조회와 상태 DB 기록까지 포함한 end-to-end 요청 deadline은 포함하지 않습니다.
- AI 감사 계보 schema는 `ATM-P1-008`, 실제 BUY 최신 뉴스 snapshot은 `ATM-P1-010B` 범위입니다.

## 수용 기준

- 첫 provider timeout 뒤 허용된 다음 provider만 한 번 호출하고 전체 예산을 넘지 않습니다.
- BUY precheck timeout에서 주문 실행은 0회입니다.
- primary timeout은 과거 분석 대신 현재 cycle HOLD를 저장합니다.
- timeout은 rate limit으로 오분류되지 않고 외부 task 취소가 그대로 전파됩니다.
- 번역 fallback 전체 예산과 embedding/translation analyzer 정리를 회귀 테스트로 고정합니다.
- backend 비-PostgreSQL 전체 회귀, Ruff, `git diff --check`를 통과합니다.
