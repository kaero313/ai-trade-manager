# AI-Trade-Manager 개발 규칙

Upbit KRW 현물 자동매매 봇(FastAPI + React/Vite + PostgreSQL)이다. 응답과 코드 주석은 한국어로 짧고 직접적으로 쓴다. 요청 범위 안에서 구현하고 묻지 않은 리팩터링·추상화·의존성을 추가하지 않는다. 기존 사용자 변경은 보존한다.

## 1. 기준과 구조

- 로드맵과 우선순위의 원본은 `docs/reviews/2026-07-10-project-safety-review.md` §3·§7이다. 구조는 `docs/ARCHITECTURE.md`, 스키마는 `docs/DATABASE.md`, 운영은 `docs/OPERATIONS.md`를 따른다.
- 역할·모델·effort·허용 경로의 원본은 `harness/agents.toml`과 `harness/roles/*.md`다. 생성물 `.claude/agents/*.md`, `.codex/agents/*.toml`, `.codex/config.toml`은 직접 편집하지 않고 `scripts/harness.py render`로 갱신한다.
- 하네스 사용법은 `docs/DEVELOPMENT_WORKFLOW.md`에 있다. Claude Code와 Codex가 이 규칙과 역할을 함께 쓴다. 스킬 원본은 `.claude/skills/`이고, Codex는 `.agents/skills` 링크로 같은 스킬을 읽는다.

## 2. 도메인 규칙

- **Async-First:** DB 접근과 외부 API 호출(Upbit 등)은 모두 `async/await`로 작성한다.
- **SQLAlchemy 2.0 강제:** `session.query()` 같은 1.x 스타일은 금지. `select()`·`execute()`와 `AsyncSession`만 쓴다.
- **Alembic 필수:** `app/models/domain.py`가 바뀌면 같은 작업에서 마이그레이션을 만들고 `alembic heads`가 하나인지 확인한다. 기존 행이 있는 테이블에 NOT NULL 컬럼을 추가할 때는 server_default를 두거나 HEAD의 insert 경로를 함께 고친다.
- **인메모리 상태 금지:** 전역 변수·싱글턴으로 상태를 들지 않는다. PostgreSQL이 유일한 신뢰 출처다.
- **프론트엔드 분리:** FastAPI는 REST 데이터만 서빙하고 UI는 `frontend/`(React/Vite)가 렌더링한다.
- **추상화:** 새 거래소는 `BaseBrokerClient`를 상속한다.
- **지표 무결성:** pandas-ta 계산의 `NaN`은 프론트 전송 전에 JSON 호환 `null`/`None`으로 바꾼다.

## 3. 작업과 모델

- 대화를 시작한 세션이 lead다. 기본 모델은 Claude Code가 Opus 5.5, Codex가 GPT-6 Sol이고 effort는 xhigh다(`agents.toml`의 `[lead]`). 다른 에이전트를 부를 수 있는 것은 lead뿐이다.

| 역할 | 모델 (Claude / Codex) | effort | 쓰기 | 용도 |
|---|---|---|---|---|
| scout | Sonnet 5 / GPT-6 Luna | low | 없음 | 코드 경로·영향 범위·HEAD 호출자 조사 |
| backend | Opus 5.5 / GPT-5.6 Terra | high | `app/` `migrations/` `tests/` `docs/` | FastAPI·DB·트레이딩 로직·테스트 |
| frontend | Opus 5.5 / GPT-5.6 Terra | high | `frontend/` `docs/` | 대시보드·브라우저 회귀 |
| qa | Opus 5.5 / GPT-6 Sol | high | `tests/` | 위험 경로 변경의 계약 기준 독립 테스트 |
| reviewer | Opus 5.5 / GPT-6 Sol | xhigh | 없음 | 독립 검토, 소스 수정 금지 |

- Codex의 하위 에이전트는 역할 파일의 `sandbox_mode`와 관계없이 lead의 샌드박스를 물려받는다(실측). Codex에서 scout·reviewer의 읽기 전용은 역할 지시로 지킨다.

- **위임 기준.** 몇 개 파일의 수정과 대화하며 방향을 잡는 작업은 lead가 직접 한다. 서브에이전트는 빈 맥락에서 시작해 파일을 다시 읽고 결과를 요약으로만 돌려주므로, 작은 작업은 맡기는 비용이 더 크다. 여러 파일에 걸쳐 lead의 맥락을 크게 차지할 구현은 backend·frontend에 맡기고, 서로 독립인 서버·화면 작업은 둘에 나눠 병렬로 맡긴다. 영향 범위가 넓은 조사는 scout에 맡긴다.
- **실주문 제출·취소, 청산, 거래 모드 전환, 관리자 인증·재인증 경계를 건드리는 변경은 누가 구현했든 qa의 독립 테스트와 reviewer 검토를 거친다.** qa는 구현이 아니라 계약을 기준으로 실패 경로 테스트를 쓰고, reviewer는 그 테스트와 diff를 함께 본다. 작성자의 자체 점검을 독립 검토로 표시하지 않는다.
- 지정 모델을 쓸 수 없거나 대체됐으면 중단하고 보고한다. 자동으로 낮추지 않는다. 요청한 모델과 실제 관측된 모델을 구분해 적고, 확인할 수 없으면 unknown이라고 쓴다.

## 4. 권한과 안전

- `.env`·`.env.local`은 어떤 도구로도 읽지 않는다. Claude Code의 Read 차단(`.claude/settings.json`)은 Bash `cat`까지 막지 못하고, Codex에는 파일 단위 읽기 차단을 두지 않았으므로 이 규칙으로 보완한다. 비밀값·실계좌 값은 커밋하지 않는다.
- 테스트와 검증에서 Upbit 비공개 API·유료 LLM을 호출하지 않는다. 대역(fake·monkeypatch)을 쓴다. 기본 거래 모드는 PAPER다. 실거래소 수동 진단은 `scripts/manual/`에서 사람이 직접 실행한다.
- 커밋은 사용자가 명령할 때만 만든다. 작업을 끝냈다고 스스로 커밋하지 않고 변경은 워킹트리에 둔 채 보고한다. `git push`·`git reset --hard`는 사용자 확인이 필요하다. 강제 push와 이력 재작성은 하지 않는다.
- 커밋 메시지는 한국어 Conventional Commits(`feat(db): ...`, `refactor(slack): ...`)를 쓰고, 모델·마이그레이션·리포지토리·API·UI·테스트·문서 단위로 잘게 나눈다. 빈 커밋이나 설명할 수 없는 커밋은 만들지 않는다. 트레일러(Co-Authored-By 등)는 붙이지 않는다.
- 섞인 변경을 나눠 커밋할 때는 격리 worktree에 후보만 복사해 검증한다. 단독으로 성립하지 않는 파일은 순서를 잡아 각 중간 상태가 성립하도록 연쇄 커밋한다.

## 5. 검증과 완료

```sh
./.venv/Scripts/python.exe scripts/verify.py              # ruff → pytest → create_app 기동 → render --check (+ frontend 변경 시 lint/test/build)
./.venv/Scripts/python.exe scripts/verify.py --fast       # ruff·기동·render 검사만
./.venv/Scripts/python.exe scripts/verify.py --frontend   # frontend lint/test/build 강제
```

- 백엔드 변경은 위 게이트를, 프론트 변경은 `--frontend`를, 크로스스택은 둘 다 통과해야 한다. pytest 통과만으로 앱이 뜬다고 말하지 않는다(기동 검사가 따로 있는 이유).
- 완료·통과를 말하기 전에 같은 메시지 안에서 검증을 실제로 돌리고 출력을 읽는다(`verification-before-completion`). skip·not_run·모델 대체를 통과로 표현하지 않는다.
- 도달할 수 없는 검증을 완료 조건으로 두지 않는다. 이 환경에서 실행할 수 없는 검증(예: `TEST_DATABASE_URL` 없는 postgres 테스트)은 미실행으로 적고 남은 확인 항목으로 따로 넘긴다. 반대로 실행할 수 있는 검증을 미실행으로 남겨 두지 않는다.
- 테스트 통과와 스크린샷은 화면 품질의 증거가 아니다. 프론트 변경은 사람이 앱을 열어 확인할 화면과 상태를 보고에 적는다.
- 증거는 `.harness/runs/<id>/result.json`에 남는다. 커밋 메시지나 보고에 적는 수치는 이 파일의 값이어야 한다.
- 버그는 `systematic-debugging` → `surgical-patch`, 구조 변경은 `safe-refactor`, 검증 전용 요청은 `verify-and-stop`을 적용한다. 작업에 맞는 스킬만 읽는다.

## 6. 코드 그래프 (GitNexus)

이 저장소는 GitNexus 1.6.12(전역 설치)로 인덱싱한다. 인덱스는 `.gitnexus/`에 있고 커밋하지 않는다. `.gitnexusrc`가 `AGENTS.md`·`CLAUDE.md` 자동 주입과 스킬 설치를 꺼 두었으므로 `node .gitnexus/run.cjs analyze`나 `gitnexus analyze`를 그대로 써도 된다. MCP 서버 설정은 `.mcp.json`에 있다.

- 인덱스는 HEAD가 아니라 **워킹트리** 파일 내용 기준이다. **파일을 수정했으면** 그래프를 쓰기 전에 다시 인덱싱한다. 이 머신에서 한 번에 약 4분 걸린다.
- `gitnexus status`의 stale 표시는 인덱싱 당시 커밋과 현재 커밋이 다르기만 해도 뜬다. 이미 있던 변경을 커밋한 것만으로는 그래프가 틀어지지 않으므로 그 경우에는 다시 인덱싱하지 않는다. 마지막 인덱싱 뒤 바뀐 파일이 있는지는 `.gitnexus/meta.json`의 `indexedAt`보다 새로운 파일이 있는지로 판단한다.
- **함수·클래스·메서드를 고치기 전에** `gitnexus impact <이름> --repo . --file <경로>`(MCP `impact`)로 호출자와 위험도를 확인해 보고한다. HIGH·CRITICAL이면 편집 전에 사용자에게 알린다.
- **그래프만 믿지 않는다.** 호출자 0건이나 `risk: UNKNOWN`은 "쓰이지 않는다"는 뜻이 아니다. 팩토리나 지역 변수로 받은 객체의 메서드 호출, Python과 TypeScript 경계는 간선이 빠질 수 있으므로 텍스트 검색으로 교차 확인한다. 실측으로 `create_order` 호출 중 `live_order_execution`은 잡혔고 `backtesting/engine.py`의 두 곳은 빠졌다.
- **커밋을 만들기 전에** `gitnexus detect-changes --scope staged --repo .`(MCP `detect_changes`)로 바뀐 심볼과 영향받는 실행 흐름을 확인해 보고한다. push 전 누적 변경은 `--scope compare --base-ref origin/main`으로 본다.
- 섞인 변경을 나눠 커밋할 때는 HEAD 기준 판단이 필요한데 인덱스는 워킹트리 기준이다. HEAD 호출자는 격리 worktree에서 텍스트 검색으로 확인하는 절차를 유지하고, 그래프는 후보와 영향 범위를 좁히는 데 쓴다.
- 이름 변경은 찾아 바꾸기 대신 MCP `rename`을 먼저 dry run으로 돌리고, 적용 뒤 diff를 직접 확인한다.
- 스킬: 구조 파악 `gitnexus-exploring`, 영향 분석 `gitnexus-impact-analysis`, 버그 추적 `gitnexus-debugging`, 리팩터링 `gitnexus-refactoring`, 도구 안내 `gitnexus-guide`, CLI `gitnexus-cli`.
- GitNexus는 PolyForm Noncommercial 1.0.0 라이선스다. 비상업적 개인 사용 범위에서만 쓴다.
