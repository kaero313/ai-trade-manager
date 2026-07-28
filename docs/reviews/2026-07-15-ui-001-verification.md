# ATM-UI-001 로컬 검증 보고서

> 검증일: 2026-07-15
> 후속 검증: 2026-07-16 desktop sidebar 접힘 동작과 sticky ModeBanner 계약
> 기준 브랜치: 로컬 `main`
> 기준 HEAD: `d2cc0b1abd1d5ecf38bd28608d378cbd92b73f91`
> 상태: 구현·로컬 회귀·production build·주요 viewport 측정 완료 / 전체 screenshot matrix·원격 CI 미실행
> Git 작업: 기존 index 보존, stage·commit·push·PR 수행 안 함

## 1. 검증 범위

ATM-UI-001은 Google Stitch 산출물의 색상·정보 계층·레이아웃을 기존 React/Vite 기능 위에
재구현한 작업입니다. 정적 HTML을 복사하거나 iframe으로 포함하지 않았고, 다음 제품 계약을 검증
대상으로 삼았습니다.

- semantic dark/light token과 공통 AppShell
- 펼침형/아이콘 레일 전환을 지원하는 fixed desktop sidebar, top status bar, 확장형 mobile drawer,
  sticky ModeBanner
- 접힘 시 AppShell·Navbar·ModeBanner의 `1440px → 1600px` 동시 확장
- compact 안전 배너, `AI ACTIVITY` 상태 띠와 중복 ENGINE 제거
- 1024~1535px 차트 우선 2단 구성, 1536px 이상 3열 구성과 하단 운영 제어 2열
- Dashboard, Portfolio, AI Banker, Strategy Laboratory, Settings 전면 이식
- 봇·전량청산·수동 AI controller의 상시 mount와 기존 멱등성 identity 보존
- 공통 `PortfolioDataState`의 live/snapshot/cached/error/empty/loading 판정
- cache 없는 오류·비유한 값을 정상 0원으로 표시하지 않는 fail-closed 표현
- AI Banker SSE error 처리와 exact `current_value + expected_version` 승인
- Settings의 키별 CAS, `409`, `503 + saved=true`, 전용 provider reset 계약
- Headless UI dialog의 focus trap, Escape, inert, focus 복귀
- Laboratory가 운영 LLM 재현이 아닌 규칙 기반 참고 전략임을 명시

가짜 USD/Binance/주식·채권·입금·Pro·프로필·API key 관리·음성·파일 첨부·원클릭 주문 기능은
추가하지 않았습니다.

## 2. 안전 경계 확인

UI 구조가 바뀌어도 다음 P0/P1 경계는 변경하지 않았습니다.

- `AdminAuthProvider → AdminSessionGate → ThemeProvider → Router → Layout`
- PostgreSQL 거래 모드 SSOT와 `PAPER/LIVE/UNAVAILABLE` fail-closed 표시
- `ARMED/EXIT_ONLY/BLOCK_ALL` Kill Switch와 중앙 `LiveOrderExecutionService`
- OrderIntent identifier, CAS, reconciliation, exactly-once 체결 투영
- 전량청산 operation UUID·snapshot·`COMPLETED + VERIFIED` 종결 증명
- Settings와 AI Banker의 versioned CAS

HTTP 성공이나 주문 접수는 체결 성공으로 표시하지 않으며 `PREPARED`, `SUBMITTING`, `UNKNOWN`,
`ACCEPTED`, `PARTIAL`, `LEGACY_UNVERIFIED`, `NO_ASSETS + VERIFIED`를 각 상태의 실제 의미로 유지합니다.
DB model·schema·Alembic, backend 공개 API, broker 계약은 변경하지 않았습니다. 따라서
`docs/DATABASE.md`는 검토만 수행하고 수정하지 않았습니다.

## 3. 로컬 검증 결과

| 검증 | 결과 |
|---|---|
| PostgreSQL 16.12 marker | migration 왕복 전후 각 `79 passed`, skip 0 |
| migration | 빈 DB upgrade, fail-closed downgrade/re-upgrade, `alembic check`, 단일 head/current 통과 |
| Phase 0 복원 리허설 | 외부 snapshot을 기준 HEAD 임시 clone에 복원, staged·unstaged·untracked count와 184개 경로 hash 일치 |
| frontend | `26 files / 125 tests` 통과 |
| ESLint | 통과 |
| backend 비-PostgreSQL | `627 passed` |
| Ruff | 통과 |
| production build | 통과, 2,734 modules transformed; 단일 JS 청크 약 1.30MB 경고 |
| 원격 CI | 미실행 |

검증 중 실제 Upbit 주문, Gemini/OpenAI 호출, 운영 PostgreSQL, 원격 Git 작업은 수행하지 않았습니다.

## 4. 알려진 Delta

### 브라우저 viewport 증거

2026-07-16 후속 headless browser QA는 실제 API 대신 인증 성공과 장애 응답을 mock해
390/1024/1279/1280/1535/1536/1920px을 측정했습니다. 모든 구간에서 가로 overflow가 없었고,
ModeBanner는 scrollTop 0과 600 모두 Navbar 아래 `y=64px`를 유지했습니다. 1920px에서 본문은 접힘 전
1440px, 접힘 후 1600px였고 전체 scroll height는 초기 구조 측정 2703px에서 최종 2019px로 줄었습니다.
본문 건너뛰기 링크는 `main-content`로 포커스를 옮기며 scroll margin 적용 후 main과 배너가 모두
Navbar 아래 `y=64px`를 유지했습니다.
다만 320/768/1440px, dark/light screenshot matrix, 200% reflow, 실제 API 데이터 기반 시각 증거는 아직
남기지 않았으므로 focus·contrast·터치 영역을 포함한 완전한 browser QA로 해석하지 않습니다.

### backend 채팅 portfolio context

frontend는 portfolio unavailable이면 briefing과 AI Banker 전송을 차단합니다. 그러나 backend
`app/services/chat/tools.py`가 별도 경로로 직접 호출될 때 portfolio 조회 오류를 0원 context로 서술할
수 있는 기존 동작은 남아 있습니다. 이는 UI-001의 frontend 범위를 벗어난 별도 승인 Delta이며,
해결되기 전에는 unavailable 상태의 frontend 우회 전송을 허용하지 않습니다.

### 배포 증거

production build는 통과했지만 원격 CI와 실제 Compose/Caddy 통합 검증은 수행하지 않았습니다. 로컬
검증 결과를 운영 배포 승인으로 해석하지 않습니다.

## 5. 판정

Stitch 디자인을 현재 기능과 안전 계약 위에 이식한 구현과 로컬 회귀는 완료했습니다. ATM-P1-005의
프론트엔드 오인 위험은 공통 상태 판정과 fail-closed gating으로 해소했습니다. 다만 browser viewport
screenshot matrix는 증거가 남아 있지 않으므로 최종 시각 QA·배포 승인과 분리해 추적합니다.

2026-07-24 후속 code-splitting Delta를 해소했습니다. `App.tsx`의 5개 페이지를 `React.lazy()`+
`Suspense`(`RouteFallback`)로 라우트 단위 지연 로딩하고, `vite.config.ts`의 `manualChunks`로
`recharts`(+d3)와 `lightweight-charts`를 각각 `charts-recharts`·`charts-lightweight` leaf 청크로
격리했습니다. 그 결과 단일 1,312 kB 청크가 최대 480 kB(`index`)로 분할돼 500 kB 경고가 사라졌고,
recharts 청크(389 kB / gzip 113 kB)는 초기 대시보드 경로에서 완전히 지연 로딩됩니다. ESLint,
Vitest `125 passed`(26 파일), production build를 통과했습니다. browser viewport screenshot matrix
증거와 원격 CI는 여전히 대기입니다.
