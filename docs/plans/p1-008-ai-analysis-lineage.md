# ATM-P1-008 AI 분석 감사 계보 계획·구현 기록

> 기준: P1-011 완료 커밋 `b531a48`
> migration: `c7a1e9d4f2b6` (`b8d4e6f1a2c3` 후속)

## Delta와 범위

primary 분석과 BUY precheck가 같은 `AIAnalysisLog`에서 구분되지 않고 실제 provider/model/fallback,
exact parent, prompt/context version이 사라졌습니다. 그 결과 최신 분석, 정확도 worker, BUY calibration,
자기교정과 주문 성과가 서로 다른 목적의 분석을 섞을 수 있었습니다.

승인된 schema는 다음 7필드로 제한합니다.

- `stage`, `provider`, `model`, `fallback_used`
- `parent_analysis_id`
- `prompt_version`, `context_sha256`

## 저장 계약

- 신규 primary는 `TRADE_ANALYSIS`, BUY 2차 검증은 `BUY_PRECHECK`입니다.
- provider 응답이 있으면 실제 provider/model과 실제 호출 failover 여부를 저장합니다.
- provider 응답 없는 합성 HOLD만 `SYSTEM / DETERMINISTIC_HOLD`, `fallback_used=true`입니다.
- precheck는 exact primary ID를 parent로 저장합니다. 실제 veto 응답을 0/HOLD로 덮지 않습니다.
- context hash는 provider에 전달한 exact user prompt UTF-8 SHA-256입니다.
- legacy는 임의 추정 없이 4개 non-null 문자열만 `LEGACY_UNKNOWN`, 나머지는 NULL로 보존합니다.

## 소비 계약

- executor, 정확도, calibration, 자기교정은 `TRADE_ANALYSIS`만 사용합니다.
- latest/batch/portfolio/scheduler는 primary를 항상 우선하고 없을 때만 legacy를 호환 조회합니다.
- live BUY 주문은 실제 precheck FK를 유지하며 성과 조회에서 parent primary를 사용합니다.
- parent가 없거나 primary가 아니면 PnL은 유지하되 precheck confidence 귀속은 생략합니다.
- 채팅 감사 도구는 모든 stage와 계보를 표시합니다.

## 제외 범위

- 실제 최신 뉴스 snapshot은 `ATM-P1-010B`에서 prompt와 hash에 반영합니다.
- 기존 legacy 행의 provider/stage/parent 추정, 원문 prompt 저장, 추가 schema 필드는 포함하지 않습니다.
- 중앙 주문 서비스, identifier, Kill Switch, `BLOCK_ALL/EXIT_ONLY`는 변경하지 않습니다.

## 수용 기준

- provider 첫 성공/fallback/합성 HOLD와 primary/precheck parent·hash가 정확합니다.
- precheck·legacy ID는 주문 executor 입력으로 사용할 수 없습니다.
- 최신·정확도·calibration·성과 query가 stage 계약을 지킵니다.
- migration legacy backfill, stage/hash CHECK, self FK `RESTRICT`, downgrade/re-upgrade를 PostgreSQL 16에서
  검증합니다.
- backend 비-PostgreSQL 전체, PostgreSQL marker, Ruff, `alembic check`, `git diff --check`를 통과합니다.
