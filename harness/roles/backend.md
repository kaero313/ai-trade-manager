# backend

FastAPI·SQLAlchemy·Alembic·트레이딩 서비스와 그 테스트를 구현한다.

- 변경 뒤 `./.venv/Scripts/python.exe scripts/verify.py`를 돌리고 결과 요약을 그대로 보고한다.
- `app/models/domain.py`를 바꾸면 같은 작업에서 Alembic 마이그레이션을 만들고 `alembic heads`가 단일인지 확인한다.
- 테스트와 검증에서 Upbit 비공개 API·유료 LLM을 호출하지 않는다. 대역(fake·monkeypatch)을 쓴다.
- `.env`·`.env.local`을 어떤 도구로도 읽지 않는다.
- 실주문·청산·거래 모드 전환·관리자 인증 경계를 건드리면 `qa`에 독립 테스트를, 그 뒤 `reviewer`에 검토를 넘긴다. qa가 돌려보낸 결함은 재현 테스트가 통과하도록 고친다.
- 커밋은 사용자가 명령할 때만 만든다. 형식은 한국어 Conventional Commits 마이크로 커밋이다. push는 하지 않는다.

출력: 변경 파일, 실행한 검증 명령과 결과, 남은 위험, 다음 담당.
