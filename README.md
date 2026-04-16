# 🤖 AI-Trade-Manager

> **AI 멀티에이전트 기반 암호화폐 자율 트레이딩 플랫폼**

AI가 실시간으로 시장을 분석하고, 자율적으로 매매를 결정하며, 스스로 정확도를 검증하는 통합 자산 관리 웹 플랫폼입니다.
단순 보조 지표 봇을 넘어 **LangGraph 멀티에이전트 오케스트레이션**, **RAG 기반 문맥 분석**, **자가수정 Reviewer Agent**, **가상 모의투자 시뮬레이터**까지 통합된 풀스택 오토 트레이딩 솔루션입니다.

---

## ✨ 주요 기능

### 🧠 AI 멀티에이전트 시스템
- **LangGraph 오케스트레이터:** Supervisor → RAG/Quant Agent 자동 라우팅
- **RAG Agent:** ChromaDB 벡터 DB 기반 과거 뉴스/분석 문맥 검색
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
| **Database** | PostgreSQL 16, ChromaDB (Vector DB) |
| **AI/ML** | LangGraph, LangChain, Google Gemini, OpenAI GPT |
| **Infrastructure** | Docker & Docker Compose |
| **Scheduler** | APScheduler (AsyncIOScheduler) |
| **Messaging** | Slack (Socket Mode) Bot |

---

## 🛠 Quick Start

```bash
# 1. 환경 변수 설정
cp .env.example .env.local  # API 키 설정 (Upbit, Slack, OpenAI, Gemini)

# 2. Docker DB 실행
docker-compose -f docker-compose-dev.yml up -d db

# 3. 백엔드 + 프론트엔드 일괄 실행
.\start_dev.bat
```

---

## 📚 문서
- [시스템 아키텍처 명세](docs/ARCHITECTURE.md)
- [데이터베이스 스키마 명세](docs/DATABASE.md)
- [AI 개발 가이드라인](Agents.md)

## 🤖 AI 협업 구조 (2-AI System)
이 프로젝트는 **Gemini(Architect)**와 **Codex(Coder)**의 2-AI 협업 시스템으로 구축되고 있습니다.
- **Gemini:** 시스템 설계, 기술 스택 결정, 단계별 마스터 프롬프트 작성
- **Codex:** 마스터 프롬프트의 요구사항을 코드로 구현
