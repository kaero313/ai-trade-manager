@AGENTS.md

Claude Code는 위 공통 규칙과 `harness/agents.toml`의 역할·모델 배정을 사용한다.
역할은 `.claude/agents/`, 스킬은 `.claude/skills/`에서 읽는다. 생성된 역할 파일은 직접 편집하지 않는다.
사용자·조직 설정이나 실행 인자가 역할의 모델·effort를 덮어쓰면 보고하고 진행 여부를 묻는다.
실주문·청산·거래 모드·관리자 인증 경계를 건드리는 변경은 reviewer 역할로 검토한다.
