# AI-Trade-Manager 개발 워크플로우

Claude Code와 Codex로 개발할 때 쓰는 하네스의 사용법이다. 공통 규칙은 [AGENTS.md](../AGENTS.md)에 있고, 이 문서는 파일 구성·역할·검증·커밋 절차만 다룬다.

## 1. 파일 구성

| 경로 | 역할 | 추적 |
|---|---|---|
| `AGENTS.md` | 공통 규칙 원본. `CLAUDE.md`가 `@AGENTS.md`로 불러오고 Codex는 직접 읽는다 | O |
| `CLAUDE.md` | Claude Code 진입점 | O |
| `.claude/settings.json` | 권한. `.env`·`.env.local` Read 차단, `git push`·`git reset --hard`는 확인, 검증 명령은 allow | O |
| `.claude/settings.local.json` | 개인 allowlist. 전역 ignore로 제외 | X |
| `harness/agents.toml`, `harness/roles/*.md` | 역할·모델·effort·허용 경로와 역할 본문의 원본. lead 모델은 `[lead]` | O |
| `.claude/agents/*.md` | `scripts/harness.py render` 생성물(Claude Code 역할). 직접 편집 금지 | O |
| `.codex/agents/*.toml`, `.codex/config.toml` | `scripts/harness.py render` 생성물(Codex 역할, lead 모델·승인·샌드박스·MCP). 직접 편집 금지 | O |
| `.claude/skills/*/SKILL.md` | 절차 스킬 5종과 GitNexus 스킬 6종. 제3자 출처는 `.claude/skills/NOTICE.md` | O |
| `.agents/skills` | `.claude/skills`를 가리키는 심볼릭 링크. Codex가 같은 스킬을 읽는다 | O |
| `.gitnexusrc`, `.mcp.json` | GitNexus 인덱싱 기본값, MCP 서버 설정 | O |
| `.gitnexus/` | GitNexus 인덱스와 `run.cjs`. 약 150MB | X |
| `scripts/verify.py` | 검증 게이트와 증거 기록 | O |
| `tests/conftest.py`, `tests/test_harness_scripts.py` | 테스트 격리, 하네스 자체 테스트 | O |
| `.github/workflows/ci.yml` | CI 세 잡 | O |
| `.harness/runs/<id>/result.json` | 검증 증거 | X |

## 2. 역할과 모델

| 역할 | Claude 모델 | Codex 모델 | effort | 쓰기 허용 | Claude 도구 |
|---|---|---|---|---|---|
| scout | claude-sonnet-5 | gpt-6-luna | low | 없음 | Read, Glob, Grep |
| backend | claude-opus-5-5 | gpt-5.6-terra | high | `app/` `migrations/` `tests/` `docs/` | + Edit, Write, Bash |
| frontend | claude-opus-5-5 | gpt-5.6-terra | high | `frontend/` `docs/` | + Edit, Write, Bash |
| qa | claude-opus-5-5 | gpt-6-sol | high | `tests/` | + Edit, Write, Bash |
| reviewer | claude-opus-5-5 | gpt-6-sol | xhigh | 없음 | Read, Glob, Grep |

lead는 대화형 세션 자신이고, 모델은 `agents.toml`의 `[lead]`(claude-opus-5-5 / gpt-6-sol, xhigh)다. Codex는 render가 이 값으로 `.codex/config.toml`을 만들고, Claude Code는 권한 설정과 한 파일인 `.claude/settings.json`의 `model`·`effortLevel`을 손으로 맞춘다. 두 값이 `[lead]`와 어긋나면 테스트가 실패한다. 역할을 바꾸려면 `harness/agents.toml`이나 `harness/roles/<role>.md`를 고치고 render를 돌린다. 이 표와 `AGENTS.md` §3, `README.md` "하네스 엔지니어링" 표는 `tests/test_harness_scripts.py`가 `agents.toml`과 대조하므로, 모델·effort·쓰기 경로를 바꾸면 네 곳을 함께 고쳐야 테스트가 통과한다. 새 모델을 쓰면 `agents.toml`의 `[display.models]`에 표기명도 추가한다.

역할 파일에는 `AGENTS.md` 전문을 복사하지 않고 "먼저 읽는다"는 안내만 넣는다. Claude Code는 `CLAUDE.md`로, Codex는 저장소 루트 지시 파일로 `AGENTS.md`를 이미 불러오기 때문이다. 역할 해시도 역할 원본만으로 계산하므로 `AGENTS.md`만 고쳤을 때는 render가 필요 없다. `.codex/config.toml`의 MCP 서버는 `.mcp.json`에서 옮겨 오므로 `.mcp.json`을 고쳤을 때는 render가 필요하다.

2026-09-23 실측: scout에게 도구 사용을 금지하고 `AGENTS.md`에만 있는 문장 세 개를 인용하게 했더니 세 개 모두 원문대로 인용했다. 도구 호출은 없었고 모델은 `claude-sonnet-5`였다. 서브에이전트에도 `AGENTS.md`가 프로젝트 지시로 주입된다는 뜻이다. 다만 주입되는 것은 **세션 시작 시점의 사본**이다. 같은 세션에서 직전에 고친 문장은 고치기 전 문장으로 인용했다. `AGENTS.md`를 고친 뒤 서브에이전트에 반영하려면 새 세션을 연다.

```sh
./.venv/Scripts/python.exe scripts/harness.py render          # 생성·갱신
./.venv/Scripts/python.exe scripts/harness.py render --check  # drift 검사. verify.py가 매번 실행한다
```

**모델을 바꾸면 실제 실행으로 확인한다.** 설정 파일 검사로는 잘못된 모델 ID를 잡지 못한다. 존재하지 않는 ID는 실행 시점에야 `unrecognized_model`로 실패한다. 바꾼 역할마다 도구 없이 한 번 실행해, 실행 기록의 모델명이 설정과 같은지 본다. lead는 `--agent` 없이 실행한다.

```sh
claude -p --agent <역할> --output-format stream-json --verbose --no-session-persistence \
  --max-turns 1 --tools "" --strict-mcp-config "Reply with exactly: MODEL_OK"
# system/init의 model과 result의 modelUsage 키가 설정한 모델 ID와 같아야 한다
```

2026-09-23 모델 재배정 뒤 다섯 역할 모두 확인했다. lead·backend·frontend·reviewer는 `claude-opus-5-5`, scout는 `claude-sonnet-5`로 실행됐다. effort는 실행 기록에 나오지 않아 관측하지 못했다(unknown). lead는 사용자 기본 모델도 Opus 5.5라서, 이 확인만으로 프로젝트 설정이 적용됐는지까지 구분되지는 않는다.
같은 날 추가한 qa도 `claude-opus-5-5`로 실행됐다. Codex 쪽 확인 방법과 결과는 §9에 있다.

## 3. 스킬

| 스킬 | 언제 | 출처 |
|---|---|---|
| verification-before-completion | 완료·통과를 말하기 전 | obra/superpowers (MIT) |
| systematic-debugging | 버그·테스트 실패·예상 밖 동작, 수정 제안 전 | obra/superpowers (MIT) |
| surgical-patch | 원인을 안 뒤 가장 좁은 계층만 고칠 때 | 자체 |
| safe-refactor | 동작을 보존하는 구조 변경 | 자체 |
| verify-and-stop | 검증 전용 요청, 마지막 증명 | 자체 |
| gitnexus-exploring · impact-analysis · debugging · refactoring · guide · cli | 코드 그래프로 구조·영향·버그·리팩터링 분석 | GitNexus 1.6.12 (PolyForm Noncommercial) |

작업에 해당하는 스킬만 읽는다. 스킬은 권한을 넓히지 않는다.

## 4. 검증

```sh
./.venv/Scripts/python.exe scripts/verify.py              # ruff → pytest → create_app 기동 → render --check
./.venv/Scripts/python.exe scripts/verify.py --fast       # ruff·기동·render 검사만
./.venv/Scripts/python.exe scripts/verify.py --frontend   # + frontend lint/test/build (frontend/ 변경 시 자동)
```

- pytest는 `TEST_DATABASE_URL`이 없으면 `-m "not postgres"`로 돈다. 있으면 CI `backend-postgres` 잡과 같은 조건으로 전체를 돈다.
- 기동 검사는 `from app.main import create_app; create_app()`이다. pytest를 전부 통과하고도 앱이 못 뜨는 커밋을 걸러낸다.
- 결과는 `.harness/runs/<YYYYmmdd-HHMMSS>-<8hex>/`의 `result.json`, `junit.xml`(pytest), `vitest-junit.xml`(프론트)에 남는다. `result.json`은 `status`, `reason`, `failed_step`, `base_commit`, 실행 전후 `workspace_sha256`(추적+미추적 파일 내용 해시), 단계별 `junit_sha256`, `steps[]`의 명령·exit code·출력 꼬리·JUnit 합계·`evidence_error`, pytest `summary`를 담는다. 보고와 커밋 메시지의 수치는 이 파일의 값을 쓴다.
- 테스트 명령이 exit 0이어도 JUnit이 없으면 `junit_missing`, 0건이면 `zero_tests`, 실패·오류가 기록돼 있으면 `junit_unsuccessful`로 실패 처리한다. 테스트가 하나도 수집되지 않았는데 통과로 보고되는 경우를 막는다.
- 실행 중 워킹트리가 바뀌면 `reason: workspace_mutated`로 실패 처리한다. 증거가 어느 트리를 말하는지 알 수 없기 때문이다.
- `tests/conftest.py`가 테스트를 격리한다. `Settings`를 `.env`·`.env.local` 없이 다시 만들고 비밀값 환경변수를 지우며, 루프백과 `TEST_DATABASE_URL`의 host:port 외 소켓 연결을 차단한다. Upbit·LLM 실호출이 섞이면 여기서 즉시 실패한다. PostgreSQL이 필요한 테스트는 `test_database_url` 픽스처를 쓰면 DSN이 없을 때 자동으로 건너뛴다.
- 하네스 스크립트 자체는 `tests/test_harness_scripts.py`가 검증한다. render drift 감지, 생성물 형식, 역할 파일이 규칙 전문을 복사하지 않는지, 역할 표 세 곳과 `agents.toml`의 일치, verify의 요약 파싱과 증거 판정을 본다.
- 테스트 통과와 스크린샷은 화면 품질의 증거가 아니다. 프론트 변경은 사람이 앱을 열어 확인할 화면과 상태를 보고에 적는다.
- `--frontend`는 `frontend/node_modules`가 있어야 한다. 없으면 `frontend_deps` 단계에서 멈춘다. 격리 worktree에는 node_modules가 없으므로 프론트 검증은 메인 트리에서 돌리거나 worktree에서 `npm ci`를 먼저 한다.
- 실거래소 수동 진단은 `test_*.py` 이름을 쓰지 않고 `scripts/manual/`에서 사람이 직접 실행한다.

## 5. 코드 그래프 (GitNexus)

```sh
SCARF_ANALYTICS=false DO_NOT_TRACK=1 npm i -g gitnexus@1.6.12   # 최초 1회. 설치 통계 전송을 끈다
gitnexus analyze                                  # 인덱싱. .gitnexusrc 기본값이 적용된다
gitnexus status                                   # 인덱싱 시점 커밋·파일과 비교 (커밋만 바뀌어도 stale)
gitnexus impact <심볼> --repo . --file <경로>      # 편집 전 호출자·위험도
gitnexus detect-changes --scope staged --repo .   # 커밋 전 영향받는 실행 흐름
```

- 인덱스는 워킹트리 파일 내용 기준이고, 이 머신에서 한 번에 약 4분 걸린다. 실제 분석은 30초 남짓이고 나머지는 실행기 준비 시간이다.
- 다시 인덱싱할 때는 파일을 수정했을 때다. `gitnexus status`는 인덱싱 당시 커밋과 현재 커밋이 다르면 내용 비교 없이 stale로 표시하므로, 기존 변경을 커밋만 한 경우에는 경고가 떠도 그래프는 정확하다. 수정 여부는 `.gitnexus/meta.json`의 `indexedAt` 이후에 바뀐 파일이 있는지로 본다.
- `.gitnexusrc`가 `skipAgentsMd`·`skipSkills`·`noStats`를 켜 둔다. 이게 없으면 analyze가 `AGENTS.md`와 `CLAUDE.md` 양쪽에 같은 안내 블록을 넣고(`CLAUDE.md`가 `AGENTS.md`를 import하므로 이중 적재), `.agents/skills/`를 새로 만든다.
- `.mcp.json`이 `cmd /c gitnexus mcp`로 MCP 서버를 띄우고, `.claude/settings.json`의 `enabledMcpjsonServers`가 승인 없이 켠다. 새 세션부터 `impact`·`context`·`query`·`detect_changes`·`rename`·`trace` 도구가 생긴다. 읽기 전용 도구만 allow에 넣었다.
- 그래프에는 빠지는 간선이 있다. 첫 실측에서 `BaseBrokerClient.create_order`의 호출자로 `live_order_execution`은 잡혔지만 `backtesting/engine.py`의 두 호출은 빠졌다. 호출자 0건과 `UNKNOWN`은 텍스트 검색으로 교차 확인한다.
- 변경 묶음을 나눠 올릴 때는 HEAD 기준 판단이 필요하므로 아래 절차의 격리 worktree 텍스트 검색을 유지하고, 그래프는 영향 범위를 좁히는 데 쓴다.
- 라이선스는 PolyForm Noncommercial 1.0.0이다. 비상업적 개인 사용 범위에서만 쓴다.

## 6. 변경 묶음 나눠 올리기

여러 주제가 섞인 변경을 의미 단위로 나눠 커밋하는 절차다. 각 커밋 시점에도 저장소가 검증을 통과해야 한다.

1. `git worktree add --detach <임시경로> HEAD`로 격리 worktree를 만든다.
2. 후보 파일만 복사하고 그 안에서 `<repo>/.venv/Scripts/python.exe scripts/verify.py`를 돌린다. cwd가 우선되므로 venv의 editable 설치와 충돌하지 않는다. 프론트 변경이 섞였으면 `--frontend`는 메인 트리에서 따로 돌린다.
3. 단독으로 성립하지 않는 파일은 순서를 잡아 하나씩 얹으며 매 단계 검증한다. 예: 유틸을 먼저, 소비자를 뒤에. 호출자에서 인자 제거를 먼저, 함수에서 파라미터 제거를 뒤에.
4. 통과한 파일만 `git commit -m "..." -- <paths>`로 커밋한다. 미추적 파일은 먼저 `git add`한다.
5. `git worktree remove --force <경로>; git worktree prune`으로 지운다.

## 7. Git 규칙

- 한국어 Conventional Commits, 의미 단위 마이크로 커밋. 트레일러는 붙이지 않는다.
- 커밋은 사용자가 명령할 때만 만든다. 작업을 끝냈다고 스스로 커밋하지 않는다. push·`reset --hard`·강제 push는 사용자 확인이 필요하다.

## 8. CI

`.github/workflows/ci.yml`이 push와 PR마다 세 잡을 돌린다. 저장소가 공개라 GitHub Actions 기본 러너로 무료로 돈다.

| 잡 | 내용 |
|---|---|
| backend-quality | ruff, postgres 제외 pytest. 하네스 자체 테스트도 여기서 돌아 역할 파일 drift를 잡는다 |
| backend-postgres | PostgreSQL 16 서비스 컨테이너에 마이그레이션 적용, postgres 테스트, 롤백 준비 데이터 투입 후 downgrade·재upgrade, `alembic check` |
| frontend-quality | `npm ci`, lint, Vitest, build |

- `alembic check`에는 `continue-on-error: true`가 붙어 있다. 마이그레이션이 모델 코드보다 먼저 반영된 구간이라 이 단계는 모델과 스키마의 차이를 보고하며 실패한다. 실패 표시는 남고 잡은 통과한다. 모델 코드가 반영돼 이 단계가 통과하기 시작하면 `continue-on-error` 줄을 지운다.
- 처음 켜기 전에 backend-postgres 잡을 같은 PostgreSQL 16 조건으로 로컬에서 재현했다. 마이그레이션, postgres 테스트, 롤백 왕복은 통과했고 `alembic check`만 예상대로 실패했다. 모델 코드까지 얹은 상태에서는 `alembic check`도 통과했다.
- CI는 설치 시점의 최신 라이브러리를 받는다. 로컬 venv와 버전이 달라 생기는 실패는 CI가 먼저 알려 준다. lock 파일 도입은 별도 과제다.

## 9. Codex

Codex도 같은 `AGENTS.md`·역할 본문·스킬을 쓴다. 아래는 Claude Code와 다른 점만 적는다.

- **설정이 적용되는 조건.** Codex는 신뢰한 프로젝트에서만 `.codex/config.toml`과 `.codex/agents/`를 읽는다. 신뢰 목록은 사용자 Codex 설정(`$CODEX_HOME/config.toml`, 기본 `~/.codex`)의 `[projects.'<경로>'] trust_level = "trusted"`다. 2026-09-23 실측: 예전 버전이 기록한 `\\?\C:\...` 형식 키를 0.156.0이 인식하지 못해 프로젝트 설정 전체가 조용히 무시됐고(lead가 사용자 기본 모델로 실행), 상위 폴더 신뢰도 적용되지 않았다. `C:\...` 형식(대소문자 무관) 키를 두거나 이 폴더에서 Codex를 열어 신뢰를 다시 승인한다.
- **lead 설정.** `.codex/config.toml`은 `[lead]` 모델·effort, `approval_policy = "on-request"`, `sandbox_mode = "workspace-write"`, 샌드박스 네트워크 차단(`git push`·패키지 설치는 승인 요청으로 올라온다), 동시 하위 에이전트 2개, `.mcp.json`에서 옮긴 GitNexus MCP로 구성된다.
- **읽기 전용 역할.** 역할 파일에 `sandbox_mode = "read-only"`를 넣지만, 실측에서 하위 에이전트는 lead의 샌드박스를 그대로 물려받았다. 권한 프로필(`default_permissions = ":read-only"`)로 바꿔도 같았다. Codex에서 scout·reviewer의 읽기 전용은 역할 지시로 지킨다.
- **`.env` 차단.** 권한 프로필의 읽기 거부(`deny`)는 Windows에서 elevated 샌드박스 백엔드가 있어야 동작한다. 일반 백엔드에서는 `Restricted read-only access requires the elevated Windows sandbox backend`로 모든 명령이 거부됐고 elevated 백엔드에서는 확인하지 못해 넣지 않았다. `AGENTS.md` §4 규칙으로 막는다.
- **스킬.** `.agents/skills`는 `.claude/skills`를 가리키는 심볼릭 링크다(`core.symlinks=true`). Codex는 링크 대상을 따라가 같은 스킬 11종을 읽는다.

모델 호출 없이 Codex가 무엇을 보는지 확인할 때는 `codex debug prompt-input "hi"`를 쓴다. `AGENTS.md` 적재, 스킬 목록과 경로, 적용된 샌드박스가 나온다.

실행 모델은 실제 실행 기록으로 확인한다. `codex exec`로 lead를 한 번 실행하고, lead에게 각 역할을 스폰해 한 줄만 답하게 한 뒤, `$CODEX_HOME/state_5.sqlite`의 `threads` 표에서 `model`·`reasoning_effort`·`agent_role`을 읽는다(`thread_spawn_edges`로 부모·자식 연결). 신뢰 키를 고치기 전에 확인하려면 `-c 'projects={"<저장소 절대 경로>"={trust_level="trusted"}}'`로 한 번만 신뢰를 준다. 점(.)이 든 경로는 `projects.<경로>.trust_level` 형식으로 넘기면 경로가 점에서 잘려 적용되지 않는다.

2026-09-23 결과: lead `gpt-6-sol`/xhigh, scout `gpt-6-luna`/low, backend·frontend `gpt-5.6-terra`/high, qa `gpt-6-sol`/high, reviewer `gpt-6-sol`/xhigh로 설정과 모두 일치했다. Codex는 effort도 기록에 남는다. 도구 호출 없이 scout에게 `AGENTS.md` §4 첫 항목을 인용하게 했더니 원문 그대로 인용해, Codex 하위 에이전트에도 `AGENTS.md`가 적재됨을 확인했다.

## 10. 변경 이력

`harness/agents.toml`의 `harness_version`이 버전 원본이다.

| 버전 | 날짜 | 내용 |
|---|---|---|
| 1.0 | 2026-09-14 | 하네스 도입: `AGENTS.md` 규칙 재작성, `CLAUDE.md`, 권한 설정, 역할 4종과 생성기, 절차 스킬 5종, `verify.py` |
| 1.0 | 2026-09-15 | 검증 보강: `.gitattributes`(LF 고정), `tests/conftest.py` 격리, `verify.py` JUnit 기록·워킹트리 변경 감지, pytest 기본 옵션, 하네스 자체 테스트 |
| 1.0 | 2026-09-16 | 역할 파일에서 `AGENTS.md` 전문 복사 제거(안내로 대체, 해시는 역할 원본 기준), `[display.models]`와 역할 표 drift 테스트, 프론트 테스트 0건·실패 기록을 실패로 처리, 화면 품질은 사람이 판정한다는 규칙 |
| 1.0 | 2026-09-16 | GitNexus 1.6.12 도입: `.gitnexusrc`로 규칙 파일 자동 주입 차단, `.mcp.json` MCP 서버, 스킬 6종과 라이선스 표기, `AGENTS.md` §6 사용 규칙(편집 전 impact, 커밋 전 detect-changes, 그래프와 텍스트 검색 교차 확인) |
| 1.0 | 2026-09-23 | CI 도입(세 잡, `alembic check` 실패 허용), GitNexus 재인덱싱 기준을 파일 수정 여부로 정정, 서브에이전트의 `AGENTS.md` 적재 실측 |
| 1.0 | 2026-09-23 | 모델 재배정: lead·backend·frontend·reviewer를 Opus 5.5로(lead·reviewer xhigh, backend·frontend high), scout는 Sonnet 5 / low 유지. lead 모델을 `.claude/settings.json`에 고정. 역할별 실제 실행으로 모델 ID 확인 절차 추가 |
| 1.0 | 2026-09-23 | 위임 기준(lead 직접 처리와 backend·frontend·scout 위임의 경계)과 qa 역할 추가: 실주문·청산·거래 모드·인증 변경은 qa가 계약 기준 독립 테스트를 쓰고 reviewer가 그 테스트와 diff를 함께 검토 |
| 1.0 | 2026-09-23 | Codex 병행: `agents.toml`에 `codex_model`과 `[lead]`, render가 `.codex/agents/*.toml`·`.codex/config.toml`(MCP는 `.mcp.json`에서) 생성, `.agents/skills` 링크, 실제 실행으로 여섯 역할의 모델·effort 확인, 하위 에이전트 샌드박스 상속과 신뢰 키 형식 문제 기록 |
