# 아키텍처 상세 문서 (Trading Bot v1)

이 문서는 현재 구현된 구조와 앞으로 확장될 구조를 **쉽게 이해할 수 있도록** 설명합니다.

---

## 1) 전체 구조 요약 (큰 그림)

```
[사용자]
  | UI/브라우저            | 텔레그램(예정)
  v                        v
[FastAPI 서버]  <-->  [텔레그램 Bot 서비스]
  |
  | (Upbit 테스트 API)
  v
[Upbit REST API]
```

- 현재는 FastAPI 서버가 핵심이며, UI와 API를 동시에 제공합니다.
- 텔레그램 제어/알림은 다음 단계에서 붙일 예정입니다.
- 텔레그램 폴링 기반 명령 처리(기본 명령)는 구현됨.
- Upbit 개인 API는 인증(JWT)까지 연결되어 있고, **조회 테스트**가 가능합니다.

---

## 2) 실행 흐름 (현재 동작 기준)

### 2.1 서버 기동
1. `uvicorn app.main:app` 실행
2. `app/main.py`에서 FastAPI 앱 생성
3. 라우터 연결:
   - API: `app/api/router.py`
   - UI: `app/ui/routes.py`
4. 로그 설정: `app/core/logging.py`
5. 텔레그램 폴링 시작: `app/services/telegram_bot.py`

### 2.2 상태/설정
- 런타임 상태: `app/core/state.py`
  - 봇 실행 여부, 마지막 heartbeat 저장
- 설정 관리: `app/models/schemas.py`
  - BotConfig(전략/리스크/스케줄)

### 2.3 API 호출
- `/api/config`, `/api/status`, `/api/bot/start` 등은
  **in-memory 상태를 읽고/수정**하는 구조입니다.
- `/api/upbit/*` 는 UpbitClient를 통해 **실제 Upbit REST API**로 요청합니다.

---

## 3) 코드 구조 (폴더별 역할)

```
app/
  main.py                # FastAPI 앱 진입점
  api/
    router.py            # API 라우터 집합
    routes/              # 엔드포인트 구현
  core/
    config.py            # .env 기반 설정
    state.py             # 런타임 상태 저장
    logging.py           # 로깅 설정
  models/
    schemas.py           # Pydantic 모델
  services/
    upbit_client.py      # Upbit REST 클라이언트 (JWT 인증 포함)
    telegram.py          # Telegram 클라이언트(송/수신)
    telegram_bot.py      # Telegram 폴링/명령 처리
  ui/
    routes.py            # UI 라우터
    templates/           # HTML 템플릿
    static/              # CSS 등 정적 자원

docs/                    # 문서
```

---

## 4) 핵심 모듈 설명

### 4.1 FastAPI 앱 (`app/main.py`)
- API + UI를 단일 서버에서 제공
- `/api/*`는 JSON API, `/`와 `/settings`는 HTML

### 4.2 설정/상태 (`app/core/config.py`, `app/core/state.py`)
- `.env`에서 키/환경변수 로딩
- 상태는 현재 **메모리 기반**
- 재시작 시 상태가 초기화됨 (추후 DB 저장 필요)

### 4.3 Upbit 클라이언트 (`app/services/upbit_client.py`)
- JWT 인증 생성
  - access_key + nonce
  - 요청 파라미터 해시(query_hash)
- GET/POST/DELETE 래핑
- Upbit 에러 발생 시 명확한 메시지로 변환

### 4.4 Telegram (`app/services/telegram_bot.py`)
- getUpdates 롱폴링으로 명령 수신
- /start, /stop, /status, /balance, /pnl, /positions, /setrisk, /help 처리

### 4.5 UI (`app/ui`)
- 대시보드: 현재는 정적 화면
- 설정 화면: 향후 `/api/config`와 연동 예정

---

## 5) 데이터 흐름 (상세)

### A. 설정 변경 흐름
```
사용자(UI) -> POST /api/config -> state.config 업데이트 -> UI 표시 반영(예정)
```

### B. 봇 시작/중지 흐름
```
POST /api/bot/start -> state.running = true
POST /api/bot/stop  -> state.running = false
```

### C. Upbit 조회 흐름
```
GET /api/upbit/accounts -> UpbitClient -> Upbit REST API
   -> 응답/에러 반환 -> 클라이언트(JSON)
```

---

## 6) 보안/운영 관련
- `.env`에 실키 저장 (깃 제외)
- 현재 인증/권한 없음 → 로컬 전용으로만 사용
- 운영 전 반드시 인증/접근 통제 추가 필요

---

## 7) 앞으로 확장될 구조 (로드맵)

### 7.1 텔레그램 제어/알림
- `app/services/telegram.py` 확장
- 메시지 수신(getUpdates) + 명령 파서 추가

### 7.2 전략/리스크 엔진
- 새로운 서비스 모듈 추가 예정
  - `strategy/` (EMA/RSI 계산)
  - `risk/` (포지션 사이징, 손실 한도)
  - `executor/` (주문 실행/취소)
- 메인 루프 또는 백그라운드 작업으로 실행

### 7.3 데이터 저장
- SQLite 연동
- 포지션/체결/로그/설정 영속화

---

## 8) 재시작 체크리스트
1. `.env` 존재 및 키 설정 확인
2. `uvicorn app.main:app --reload` 실행
3. `/docs`에서 API 테스트

## 8.1) 실행 환경 전제
- OS: Windows (PowerShell)
- Python: 3.11+
- 실행 환경: 로컬 머신

## 8.2) Upbit 키/IP 주의사항
- Upbit Open API는 IP 화이트리스트 설정 시, 등록된 공인 IP에서만 호출 가능
- IP가 변경되면 401 `no_authorization_ip` 오류 발생

---

## 9) 현재 아키텍처의 한계
- 실제 매매 루프/전략 엔진 미구현
- UI는 정적 (설정 저장 연결 필요)
- 인증/보안 미구현
- 데이터 영속화 없음

---

## 10) 문서 위치
- API 레퍼런스: `docs/API_REFERENCE.ko.md`
- 상태 요약: `docs/PROJECT_STATE.ko.md`
- v1 명세서: `docs/v1-spec.md`, `docs/v1-spec.ko.md`
