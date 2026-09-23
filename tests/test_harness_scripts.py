"""하네스 스크립트(scripts/harness.py, scripts/verify.py) 자체 회귀."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROLES = {"scout", "backend", "frontend", "qa", "reviewer"}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


harness = _load("harness")
verify = _load("verify")


def test_generated_role_files_have_frontmatter_and_tool_policy() -> None:
    outputs = harness.generated()
    claude = {f".claude/agents/{role}.md" for role in ROLES}
    codex = {f".codex/agents/{role}.toml" for role in ROLES}
    assert set(outputs) == claude | codex | {".codex/config.toml"}
    for rel in sorted(claude):
        text = outputs[rel]
        role = rel.rsplit("/", 1)[1].removesuffix(".md")
        head = text.split("---", 2)[1]
        assert f"\nname: {role}\n" in head
        assert "\nmodel: claude-" in head and "\neffort: " in head
        assert harness.MARKER in text
        tools = next(line for line in head.splitlines() if line.startswith("tools: "))
        if role in {"scout", "reviewer"}:
            assert tools == "tools: Read, Glob, Grep"
        else:
            assert tools.endswith("Edit, Write, Bash")


def test_committed_role_files_match_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.render(check=True) == 0
    assert "OK" in capsys.readouterr().out


@pytest.fixture
def harness_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel in ("AGENTS.md", "harness/agents.toml", ".mcp.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    shutil.copytree(ROOT / "harness" / "roles", tmp_path / "harness" / "roles")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "CONFIG", tmp_path / "harness" / "agents.toml")
    monkeypatch.setattr(harness, "COMMON", tmp_path / "AGENTS.md")
    monkeypatch.setattr(harness, "ROLES_DIR", tmp_path / "harness" / "roles")
    monkeypatch.setattr(harness, "OUTPUT_DIR", tmp_path / ".claude" / "agents")
    monkeypatch.setattr(harness, "CODEX_DIR", tmp_path / ".codex")
    monkeypatch.setattr(harness, "MCP_CONFIG", tmp_path / ".mcp.json")
    return tmp_path


def test_render_detects_missing_changed_and_stale_files(harness_copy: Path) -> None:
    agents = harness_copy / ".claude" / "agents"
    assert harness.render(check=True) == 1  # 생성물 없음
    assert harness.render(check=False) == 0
    assert harness.render(check=True) == 0
    role = harness_copy / "harness" / "roles" / "backend.md"
    role.write_text(role.read_text(encoding="utf-8") + "- 임시 규칙\n", encoding="utf-8")
    assert harness.render(check=True) == 1  # 원본 변경
    assert harness.render(check=False) == 0 and harness.render(check=True) == 0
    stale = agents / "ghost.md"
    stale.write_text(f"---\nname: ghost\n---\n<!-- {harness.MARKER} -->\n", encoding="utf-8")
    codex_stale = harness_copy / ".codex" / "agents" / "ghost.toml"
    codex_stale.write_text(f"# {harness.MARKER}\nname = \"ghost\"\n", encoding="utf-8")
    assert harness.render(check=True) == 1  # 원본 없는 생성물
    assert harness.render(check=False) == 0
    assert not stale.exists() and not codex_stale.exists()
    mcp = harness_copy / ".mcp.json"
    mcp.write_text(mcp.read_text(encoding="utf-8").replace('"mcp"]', '"mcp", "--x"]'), encoding="utf-8")
    assert harness.render(check=True) == 1  # MCP 설정 변경도 Codex 설정 drift


def test_render_refuses_to_overwrite_unowned_file(harness_copy: Path) -> None:
    agents = harness_copy / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "scout.md").write_text("손으로 쓴 파일\n", encoding="utf-8")
    with pytest.raises(harness.HarnessError):
        harness.render(check=True)


def test_pytest_summary_parses_last_summary_line() -> None:
    output = "....\n1 failed, 183 passed, 8 deselected, 2 errors in 30.81s\n"
    assert verify.pytest_summary(output) == {
        "failed": 1, "passed": 183, "deselected": 8, "error": 2,
    }
    assert verify.pytest_summary("no summary here") == {}


def test_junit_summary_sums_suites(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1"/>'
        '<testsuite tests="2" failures="0" errors="1" skipped="0"/></testsuites>',
        encoding="utf-8",
    )
    assert verify.junit_summary(junit) == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}
    assert verify.junit_summary(tmp_path / "missing.xml") == {}


def test_build_steps_respects_flags_and_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    junit = verify.junit_paths(tmp_path)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    steps, scope = verify.build_steps(fast=False, frontend=False, report_dir=tmp_path)
    names = [name for name, _, _ in steps]
    assert names == ["ruff", "pytest", "create_app", "render_check"]
    assert scope == "not postgres"
    pytest_cmd = steps[1][1]
    assert "not postgres" in pytest_cmd and f"--junitxml={junit['pytest']}" in pytest_cmd

    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    steps, scope = verify.build_steps(fast=True, frontend=True, report_dir=tmp_path)
    names = [name for name, _, _ in steps]
    assert scope == "all"
    assert "pytest" not in names
    assert names[-4:] == ["frontend_deps", "frontend_lint", "frontend_test", "frontend_build"]
    vitest_cmd = dict((name, cmd) for name, cmd, _ in steps)["frontend_test"]
    assert "--reporter=junit" in vitest_cmd
    assert f"--outputFile.junit={junit['frontend_test'].as_posix()}" in vitest_cmd


def test_evidence_error_rejects_missing_empty_and_failed_junit() -> None:
    ok = {"tests": 3, "failures": 0, "errors": 0, "skipped": 1}
    assert verify.evidence_error({"exit_code": 0, "junit": ok}) is None
    assert verify.evidence_error({"exit_code": 0, "junit": {}}) == "junit_missing"
    assert verify.evidence_error({"exit_code": 0, "junit": {**ok, "tests": 0}}) == "zero_tests"
    assert verify.evidence_error({"exit_code": 0, "junit": {**ok, "errors": 1}}) == (
        "junit_unsuccessful"
    )
    # 명령 자체가 실패했으면 exit code가 사유이므로 따로 적지 않는다
    assert verify.evidence_error({"exit_code": 1, "junit": {}}) is None
    # JUnit을 남기지 않는 단계는 검사하지 않는다
    assert verify.evidence_error({"exit_code": 0}) is None


def test_describe_marks_failures_and_counts() -> None:
    assert verify.describe({"step": "ruff", "exit_code": 0}) == "ruff OK"
    assert verify.describe({"step": "ruff", "exit_code": 2}) == "ruff FAIL(exit 2)"
    assert verify.describe({"step": "pytest", "exit_code": 0, "summary": {"passed": 3}}) == (
        "pytest 3 passed"
    )
    assert verify.describe(
        {"step": "frontend_test", "exit_code": 0, "evidence_error": "zero_tests"}
    ) == "frontend_test FAIL(zero_tests)"
    assert verify.describe({
        "step": "frontend_test", "exit_code": 0,
        "junit": {"tests": 125, "failures": 0, "errors": 0, "skipped": 0},
    }) == "frontend_test 125 tests, 0 skipped"


def test_role_files_point_to_agents_md_instead_of_copying_it(harness_copy: Path) -> None:
    import tomllib

    outputs = harness.generated()
    agents_md = (harness_copy / "AGENTS.md").read_text(encoding="utf-8")
    first_rule_line = next(
        line for line in agents_md.splitlines() if line.startswith("- ") and len(line) > 40
    )
    for rel, text in outputs.items():
        assert first_rule_line not in text
        if rel.startswith(".claude/agents/"):
            assert harness.COMMON_POINTER in text
        elif rel.startswith(".codex/agents/"):
            instructions = tomllib.loads(text)["developer_instructions"]
            assert instructions.startswith(harness.CODEX_POINTER)
    # AGENTS.md를 고쳐도 역할 파일은 바뀌지 않는다
    assert harness.render(check=False) == 0
    (harness_copy / "AGENTS.md").write_text(agents_md + "- 임시 규칙\n", encoding="utf-8")
    assert harness.render(check=True) == 0
    # 원본이 없으면 안내가 가리킬 곳이 없으므로 실패한다
    (harness_copy / "AGENTS.md").unlink()
    with pytest.raises(harness.HarnessError):
        harness.generated()


@pytest.mark.parametrize("line", ['"claude-opus-5-5" = "Opus 5.5"\n', '"gpt-5.6-terra" = "GPT-5.6 Terra"\n'])
def test_missing_display_name_is_rejected(harness_copy: Path, line: str) -> None:
    config = harness_copy / "harness" / "agents.toml"
    text = config.read_text(encoding="utf-8")
    assert line in text
    config.write_text(text.replace(line, ""), encoding="utf-8")
    with pytest.raises(harness.HarnessError, match=line.split('"')[1]):
        harness.generated()


def test_codex_files_match_agents_toml_and_mcp_json() -> None:
    import tomllib

    config = _config()
    outputs = harness.generated()
    for name, role in config["roles"].items():
        text = outputs[f".codex/agents/{name}.toml"]
        assert text.startswith(f"# {harness.MARKER}")
        agent = tomllib.loads(text)
        assert agent["name"] == name and agent["description"] == role["description"]
        assert (agent["model"], agent["model_reasoning_effort"]) == (role["codex_model"], role["effort"])
        assert agent["sandbox_mode"] == ("read-only" if role["read_only"] else "workspace-write")
    codex = tomllib.loads(outputs[".codex/config.toml"])
    lead = config["lead"]
    assert (codex["model"], codex["model_reasoning_effort"]) == (lead["codex_model"], lead["effort"])
    assert codex["approval_policy"] == "on-request"
    assert codex["sandbox_workspace_write"]["network_access"] is False
    servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(codex["mcp_servers"]) == set(servers)
    for name, server in servers.items():
        converted = codex["mcp_servers"][name]
        assert (converted["command"], converted["args"]) == (server["command"], server["args"])
        assert converted.get("env", {}) == server.get("env", {})


def test_claude_lead_settings_match_agents_toml() -> None:
    lead = _config()["lead"]
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert (settings["model"], settings["effortLevel"]) == (lead["claude_model"], lead["effort"])


def test_codex_skill_directory_links_to_claude_skills() -> None:
    link = ROOT / ".agents" / "skills"
    assert link.is_symlink(), ".agents/skills는 .claude/skills를 가리키는 심볼릭 링크여야 한다"
    assert link.resolve() == (ROOT / ".claude" / "skills").resolve()


def _table_rows(path: Path, first_header: str) -> dict[str, list[str]]:
    """첫 머리칸이 first_header인 마크다운 표를 {역할: 나머지 칸}으로 읽는다.

    머리줄은 표의 첫 줄만 인정한다. 다른 표의 본문 행이 우연히 같은 단어로 시작해도 잡지 않는다.
    """
    rows: dict[str, list[str]] = {}
    in_table = False
    previous_was_table_line = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            if in_table:
                break
            previous_was_table_line = False
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        is_first_line = not previous_was_table_line
        previous_was_table_line = True
        if not in_table and is_first_line and cells[0] == first_header:
            in_table = True
            continue
        if in_table and not set(cells[0]) <= {"-", ":"}:
            rows[cells[0]] = cells[1:]
    return rows


def _config() -> dict:
    import tomllib

    return tomllib.loads((ROOT / "harness" / "agents.toml").read_text(encoding="utf-8"))


def _expected_roles() -> tuple[dict, dict]:
    config = _config()
    return config["roles"], config["display"]["models"]


def _paths_cell(role: dict) -> str:
    return " ".join(f"`{p}`" for p in role["allowed_paths"]) or "없음"


def _model_pair(role: dict, names: dict) -> str:
    return f"{names[role['claude_model']]} / {names[role['codex_model']]}"


def test_agents_md_role_table_matches_agents_toml() -> None:
    roles, names = _expected_roles()
    rows = _table_rows(ROOT / "AGENTS.md", "역할")
    assert set(rows) == set(roles), "AGENTS.md 역할 표와 agents.toml 역할이 다르다"
    for name, role in roles.items():
        models, effort, paths = rows[name][0], rows[name][1], rows[name][2]
        assert models == _model_pair(role, names), name
        assert effort == role["effort"], name
        assert paths == _paths_cell(role), name


def test_readme_role_table_matches_agents_toml() -> None:
    roles, names = _expected_roles()
    rows = _table_rows(ROOT / "README.md", "역할")
    lead = rows.pop("lead")
    assert lead[:2] == [_model_pair(_config()["lead"], names), _config()["lead"]["effort"]], "lead 행"
    assert set(rows) == set(roles), "README 역할 표와 agents.toml 역할이 다르다"
    for name, role in roles.items():
        models, effort, permission = rows[name][0], rows[name][1], rows[name][2]
        assert models == _model_pair(role, names), name
        assert effort == role["effort"], name
        assert permission == ("읽기 전용" if role["read_only"] else "쓰기"), name


def test_workflow_doc_role_table_matches_agents_toml() -> None:
    roles, _ = _expected_roles()
    rows = _table_rows(ROOT / "docs" / "DEVELOPMENT_WORKFLOW.md", "역할")
    assert set(rows) == set(roles), "DEVELOPMENT_WORKFLOW.md 역할 표와 agents.toml 역할이 다르다"
    for name, role in roles.items():
        claude, codex, effort, paths, tools = rows[name][:5]
        assert (claude, codex, effort) == (role["claude_model"], role["codex_model"], role["effort"])
        assert paths == _paths_cell(role), name
        expected_tools = "Read, Glob, Grep" if role["read_only"] else "+ Edit, Write, Bash"
        assert tools == expected_tools, name
