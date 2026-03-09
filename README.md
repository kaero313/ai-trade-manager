# AI-Trade-Manager

AI가 접목된 코인/주식 통합 자산 관리 웹 플랫폼입니다.
기존 단일 환경(In-memory) 트레이딩 봇에서 벗어나, 완벽히 분리된 **마이크로서비스 아키텍처**(백엔드 API, 워커 엔진, 슬랙 봇, 프론트엔드 대시보드)로 구축되었습니다. 최근에는 **백테스트 엔진**과 **기술적 지표 시각화(MA, BB, RSI)** 기능까지 성공적으로 이식되었습니다.

## 📚 문서 (Documentation)
시스템의 자세한 설계와 가이드라인은 아래 문서를 참고하세요.
- [AI-Trade-Manager 아키텍처 명세 (Architecture)](docs/ARCHITECTURE.md)
- [데이터베이스 스키마 명세 (Database)](docs/DATABASE.md)
- [2-AI 시스템 작동 지침 (Agents)](Agents.md)

## 🚀 기술 스택 (Tech Stack)
- **Backend:** Python 3.11+, FastAPI, pandas, pandas-ta-classic
- **Database:** PostgreSQL 16, SQLAlchemy 2.0 (Async), Alembic
- **Infrastructure:** Docker & Docker Compose
- **Control & Alert:** Slack (Socket Mode) Bot 통합
- **Frontend:** React 18, Vite, Tailwind CSS, lightweight-charts
- **AI Integration:** LLM 기반 시장 분석가 및 포트폴리오 매니저 자동 연동

## 🛠 실행 방법 (Getting Started)
1. `.env.example`을 복사하여 `.env.local` 생성 및 API 키 설정 (Upbit, Slack, OpenAI 등)
2. `docker-compose -f docker-compose-dev.yml up -d db` (PostgreSQL 구동)
3. 백엔드 설정: `venv\Scripts\alembic upgrade head` (DB 테이블 생성 후 서버 실행)
4. 프론트엔드 구동: `frontend/` 디렉토리에서 `npm i` 및 `npm run dev` 실행

## 🤖 AI 협업 구조 (2-AI System)
이 프로젝트는 철저히 **Gemini(Architect)**와 **Codex(Coder)**의 쌍방향 협업 시스템으로 구축되고 있습니다.
새로운 세션을 시작하거나 기능을 확장하려는 AI 어시스턴트는 반드시 `docs/` 하위의 마크다운 문서들을 먼저 숙지하여 시스템의 전체 컨텍스트를 파악해야 합니다.
