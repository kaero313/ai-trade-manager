# 🤖 AI-Trade-Manager

> **AI 멀티에이전트 기반 암호화폐 자율 트레이딩 플랫폼**

AI가 실시간으로 시장을 분석하고, 자율적으로 매매를 결정하며, 스스로 정확도를 검증하는 통합 자산 관리 웹 플랫폼입니다.
단순 보조 지표 봇을 넘어 **LangGraph 멀티에이전트 오케스트레이션**, **RAG 기반 문맥 분석**, **자가수정 Reviewer Agent**, **가상 모의투자 시뮬레이터**까지 통합된 풀스택 오토 트레이딩 솔루션입니다.

---

## ✨ 주요 기능

### 🧠 AI 멀티에이전트 시스템
- **LangGraph 오케스트레이터:** Supervisor → RAG/Quant Agent 자동 라우팅
- **RAG Agent:** OpenSearch 3.5.0 `market_news` 벡터 DB 기반 뉴스 문맥 검색
- **Quant Agent:** 실시간 시세, 기술지표(RSI, MACD, BB), 호가 분석
- **Reviewer Agent:** 할루시네이션 검출 + 면책 조항 강제 (Self-Correction Loop, 최대 2회 재작업)
- **SSE 실시간 스트리밍:** 에이전트 작업 과정을 Activity Card로 시각화

### 📊 실시간 대시보드
- 캔들 차트 (lightweight-charts) + 기술지표 오버레이
- 포트폴리오 자산 배분 도넛 차트 (Recharts)
- 시장 공포/탐욕 지수 + 글로벌 뉴스 감성 분석
- AI 인사이트 브리핑 (진입 시 자동 생성)
- 봇 파라미터 실시간 제어 패널

### 🔬 백테스팅 연구소
- 전략 파라미터 시뮬레이션 엔진
- 차트 위 매수/매도 타점 시각화
- 승률, 수익률, 최대낙폭 등 성과 지표

### 🤖 자율 매매 엔진
- AI 분석 기반 자동 매수/매도 실행
- 분 단위 다이내믹 스케줄링 & 위치 사이징
- AI 적중률 메타인지 채점 (정확도 자동 검증)
- 가상 모의투자 (Paper Trading) 시뮬레이터

### 📱 모바일 제어
- Slack Socket Mode 봇 통합
- `/잔고`, `/추천`, `긴급정지` 등 모바일 명령어 지원

---

## 🚀 기술 스택

| 영역 | 스택 |
|---|---|
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (Async), Alembic |
| **Frontend** | React 18, TypeScript, Vite, Recharts, lightweight-charts, TanStack Query |
| **Database** | PostgreSQL 16, OpenSearch 3.5.0 (`market_news` Vector DB) |
| **AI/ML** | LangGraph, LangChain, Google Gemini, OpenAI, Gemini Embeddings |
| **Infrastructure** | Docker & Docker Compose |
| **Scheduler** | APScheduler (AsyncIOScheduler) |
| **Messaging** | Slack (Socket Mode) Bot |

---

## 🛠 Quick Start

```bash
# 1. 환경 변수 설정
cp .env.example .env.local  # API 키 설정 (Upbit, Slack, Gemini/OpenAI)

# 2. Docker DB 실행
docker-compose -f docker-compose-dev.yml up -d db

# 3. 백엔드가 이미 떠 있으면 먼저 종료
#    Windows PowerShell 예시:
#    Get-NetTCPConnection -LocalPort 8000 | Select-Object -ExpandProperty OwningProcess | Get-Unique | ForEach-Object { Stop-Process -Id $_ -Force }

# 4. 백엔드 + 프론트엔드 일괄 실행
.\start_dev.bat

# 또는 백엔드만 단독 실행
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`start_dev.bat`와 백엔드 단독 실행 명령은 동시에 사용하지 않습니다. 둘 중 하나만 사용해 8000 포트 uvicorn 프로세스를 하나로 유지하세요.

---

## 📚 문서
- [시스템 아키텍처 명세](docs/ARCHITECTURE.md)
- [데이터베이스 스키마 명세](docs/DATABASE.md)
- [AI 개발 가이드라인](Agents.md)
- [개발 운영 워크플로우](docs/DEVELOPMENT_WORKFLOW.md)
- [IDE Agent Chat용 Codex 마스터 프롬프트 템플릿](docs/IDE_AGENT_CHAT_PROMPT_TEMPLATE.md)

## 🤖 AI 협업 구조 (2-AI System)
이 프로젝트는 **Gemini(Architect)**와 **Codex(Coder)**의 2-AI 협업 시스템으로 구축되고 있습니다.
- **Gemini / IDE:** 기능 설계, 범위 확정, 아키텍처/DB 변경 승인, 마스터 프롬프트 작성
- **Codex 앱:** 메인 실행 채널. Gemini 프롬프트를 받아 현재 리포지토리와의 Delta 판정, 작업 분해, 멀티 에이전트 실행, 검증, 커밋까지 담당
- **Codex CLI:** 좁은 단일 확인이나 반복 명령이 필요할 때만 쓰는 보조 채널

IDE agent chat에서 Codex용 실행 프롬프트를 만들 때는 [IDE Agent Chat용 Codex 마스터 프롬프트 템플릿](docs/IDE_AGENT_CHAT_PROMPT_TEMPLATE.md)을 기본으로 사용합니다.

Codex 앱 내부는 포트폴리오 지향 **적응형 멀티 에이전트** 구조로 운영됩니다.
- **Main Orchestrator:** 항상 존재하며 Delta 판정, 작업 분해, 통합, 커밋을 담당
- **Explorer:** 중간 이상 작업에서 영향 범위와 충돌 가능성을 조사
- **Backend / Frontend Worker:** API, 서비스, DB, 스케줄러, UI, 시각화 구현을 분담
- **Reviewer:** 중간 이상 작업에서 요구사항 누락, 구조 위반, 회귀 위험을 검토
- **Docs Curator:** 포트폴리오 가치가 큰 작업에서 README/아키텍처/DB/운영 문서를 동기화

상세 운영 규칙과 Codex 앱 실행 계약 템플릿은 [개발 운영 워크플로우](docs/DEVELOPMENT_WORKFLOW.md)에 정리되어 있습니다.

## 운영 안전 설정
- `live_buy_enabled=false`가 기본값입니다. live 모드에서 AI 신규 BUY는 잠기며, 기존 보유분 SELL과 TP/SL 청산은 계속 동작합니다.
- `ai_max_buy_weight_pct=40` 기본값으로 AI가 100% 매수 비중을 제안해도 실행부에서 1회 신규 매수 비중을 제한합니다.
- `ai_min_confidence_trade=85` 기본값으로 낮은 확신도 자동 체결을 차단합니다.
- Upbit 시장가 매수 응답의 `price`는 주문 KRW 금액이므로 체결 단가로 저장하지 않고, 주문 상세 체결 VWAP 또는 현재가 fallback을 사용합니다.
