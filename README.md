# AI-Trade-Manager

AI가 접목된 코인/주식 통합 자산 관리 웹 플랫폼입니다.
기존 단일 환경(In-memory) 트레이딩 봇에서 벗어나, 데이터베이스 완전 격리 및 마이크로서비스 아키텍처를 적용했습니다.

## 📚 문서 (Documentation)
시스템의 자세한 설계와 데이터베이스 구조는 아래 문서를 참고하세요.
- [아키텍처 명세 (Architecture)](docs/ARCHITECTURE.md)
- [데이터베이스 스키마 명세 (Database)](docs/DATABASE.md)

## 🚀 기술 스택 (Tech Stack)
- **Backend:** Python 3.11+, FastAPI
- **Database:** PostgreSQL 16, SQLAlchemy 2.0 (Async), Alembic
- **Infrastructure:** Docker & Docker Compose
- **Control & Alert:** Slack (Socket Mode)
- **Frontend:** React/Vite (예정)

## 🛠 실행 방법 (Getting Started)
1. `.env.example`을 복사하여 `.env.local` 생성 및 비밀번호 설정
2. `docker compose -f docker-compose-dev.yml up -d db` (PostgreSQL 구동)
3. `venv\Scripts\alembic upgrade head` (DB 테이블 생성)
4. `docker compose -f docker-compose-dev.yml up -d api` (또는 로컬에서 uvicorn 실행)

## 🤖 AI 협업 구조 (2-AI System)
이 프로젝트는 Gemini(Architect)와 Codex(Coder)의 협업으로 구축되고 있습니다.
- 새로운 세션을 시작하는 AI 어시스턴트는 반드시 `docs/` 하위의 문서들을 숙지하여 프로젝트 전체 맥락을 파악해야 합니다.
