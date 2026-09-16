"""프로젝트 검증 게이트와 실행 증거 기록.

순서(첫 실패에서 중단):
  1. ruff check .
  2. pytest -q --strict-markers --junitxml   (TEST_DATABASE_URL이 없으면 -m "not postgres")
  3. create_app() 기동 검사                  (pytest가 못 잡는 앱 진입점 오류 방지)
  4. scripts/harness.py render --check       (역할 파일 drift)
  5. frontend lint/test/build                (--frontend 지정 또는 HEAD 대비 frontend/ 변경 시,
                                              vitest는 JUnit도 남긴다)

    python scripts/verify.py             # 전체
    python scripts/verify.py --fast      # 1·3·4만
    python scripts/verify.py --frontend  # 5 강제

결과는 .harness/runs/<id>/의 result.json·junit.xml·vitest-junit.xml에 남기고 마지막 줄에 요약을 출력한다.
테스트 명령이 성공해도 JUnit이 없거나, 0건이거나, 실패·오류가 기록돼 있으면 실패로 처리한다.
실행 전후의 워킹트리 해시가 다르면 증거가 어느 상태를 말하는지 알 수 없으므로
실패(workspace_mutated)로 기록한다. 하위 명령은 이 스크립트를 실행한 인터프리터(sys.executable)로
돌리므로 venv python으로 호출한다. 격리 worktree 안에서 실행하면 그 worktree를 기준으로 검사한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
RUNS_DIR = ROOT / ".harness" / "runs"
TAIL = 2000
SNAPSHOT_EXCLUDE_FILES = {".env", ".env.local"}
SNAPSHOT_EXCLUDE_PREFIXES = (".harness/", "logs/", "tmp_", "frontend/dist/")
PYTEST_SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|deselected|errors?|xfailed|xpassed)")
CHILD_ENV = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTEST_ADDOPTS": ""}
FRONTEND_DEPS_CHECK = (
    "import pathlib, sys; ok = pathlib.Path('node_modules').is_dir(); "
    "ok or print('frontend/node_modules 없음: frontend에서 npm ci를 먼저 실행하세요. "
    "격리 worktree에는 없으므로 프론트 검증은 메인 트리에서 돌립니다.'); "
    "sys.exit(0 if ok else 1)"
)


def run(command: list[str], cwd: Path) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=1800, env={**os.environ, **CHILD_ENV},
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or b""
        out = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
        code, err = 124, "timeout 1800s"
    except FileNotFoundError as exc:
        code, out, err = 127, "", str(exc)
    return {
        "command": command,
        "cwd": cwd.relative_to(ROOT).as_posix() if cwd != ROOT else ".",
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 1),
        "stdout_tail": out[-TAIL:],
        "stderr_tail": err[-TAIL:],
    }


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.stdout if proc.returncode == 0 else ""


def workspace_sha256() -> str:
    """추적+미추적(ignore 제외) 파일 내용 해시. 증거가 어느 트리 상태를 말하는지 고정한다."""
    listing = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    lines = []
    for rel in sorted({p for p in listing.split("\0") if p}):
        if rel in SNAPSHOT_EXCLUDE_FILES or rel.startswith(SNAPSHOT_EXCLUDE_PREFIXES):
            continue
        path = ROOT / rel
        if path.is_file():
            lines.append(f"{rel} {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def frontend_changed() -> bool:
    changed = git("diff", "--name-only", "HEAD", "--", "frontend/")
    untracked = git("ls-files", "--others", "--exclude-standard", "--", "frontend/")
    return bool(changed.strip() or untracked.strip())


def pytest_summary(output: str) -> dict[str, int]:
    """pytest -q 마지막 요약 줄을 {결과: 건수}로 바꾼다."""
    for line in reversed(output.strip().splitlines()):
        found = PYTEST_SUMMARY.findall(line)
        if found and " in " in line:
            return {("error" if key.startswith("error") else key): int(n) for n, key in found}
    return {}


def junit_summary(path: Path) -> dict[str, int]:
    """JUnit XML의 testsuite 속성을 합산한다. 파일이 없거나 깨졌으면 빈 dict."""
    if not path.is_file():
        return {}
    try:
        suites = list(ET.parse(path).iter("testsuite"))
    except ET.ParseError:
        return {}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0))
    return totals


def junit_paths(report_dir: Path) -> dict[str, Path]:
    """JUnit을 남기는 단계와 그 파일 경로."""
    return {"pytest": report_dir / "junit.xml", "frontend_test": report_dir / "vitest-junit.xml"}


def build_steps(fast: bool, frontend: bool, report_dir: Path) -> tuple[list, str]:
    py = sys.executable
    junit = junit_paths(report_dir)
    postgres_scope = "all" if os.environ.get("TEST_DATABASE_URL") else "not postgres"
    steps: list[tuple[str, list[str], Path]] = [("ruff", [py, "-m", "ruff", "check", "."], ROOT)]
    if not fast:
        pytest_cmd = [py, "-m", "pytest", "-q", "--strict-markers", f"--junitxml={junit['pytest']}"]
        if postgres_scope != "all":
            pytest_cmd += ["-m", "not postgres"]
        steps.append(("pytest", pytest_cmd, ROOT))
    steps.append(("create_app", [py, "-c", "from app.main import create_app; create_app()"], ROOT))
    steps.append(("render_check", [py, "scripts/harness.py", "render", "--check"], ROOT))
    if frontend:
        npm = shutil.which("npm") or "npm"
        vitest_junit = junit["frontend_test"].as_posix()
        steps.append(("frontend_deps", [py, "-c", FRONTEND_DEPS_CHECK], FRONTEND))
        steps.append(("frontend_lint", [npm, "run", "lint"], FRONTEND))
        steps.append((
            "frontend_test",
            [npm, "run", "test", "--", "--reporter=default", "--reporter=junit",
             f"--outputFile.junit={vitest_junit}"],
            FRONTEND,
        ))
        steps.append(("frontend_build", [npm, "run", "build"], FRONTEND))
    return steps, postgres_scope


def evidence_error(step: dict) -> str | None:
    """명령은 성공했지만 테스트 증거가 통과로 볼 수 없는 경우의 사유."""
    junit = step.get("junit")
    if junit is None or step["exit_code"] != 0:
        return None
    if not junit:
        return "junit_missing"
    if junit["tests"] == 0:
        return "zero_tests"
    if junit["failures"] or junit["errors"]:
        return "junit_unsuccessful"
    return None


def describe(step: dict) -> str:
    name = step["step"]
    if step["exit_code"] != 0:
        return f"{name} FAIL(exit {step['exit_code']})"
    if step.get("evidence_error"):
        return f"{name} FAIL({step['evidence_error']})"
    if name == "pytest":
        summary = step.get("summary") or {}
        parts = [f"{n} {key}" for key, n in summary.items()] or ["요약 없음"]
        return "pytest " + ", ".join(parts)
    if name == "frontend_test" and step.get("junit"):
        junit = step["junit"]
        return f"frontend_test {junit['tests']} tests, {junit['skipped']} skipped"
    return f"{name} OK"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="프로젝트 검증 게이트")
    parser.add_argument("--fast", action="store_true", help="ruff·기동·render 검사만")
    parser.add_argument("--frontend", action="store_true", help="frontend lint/test/build 강제")
    args = parser.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    report_dir = RUNS_DIR / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    junit = junit_paths(report_dir)
    run_frontend = args.frontend or (not args.fast and frontend_changed())
    steps, postgres_scope = build_steps(args.fast, run_frontend, report_dir)
    before = workspace_sha256()
    results: list[dict] = []
    failed_step: str | None = None
    for name, command, cwd in steps:
        result = run(command, cwd)
        result["step"] = name
        if name == "pytest":
            result["summary"] = pytest_summary(result["stdout_tail"])
        if name in junit:
            result["junit"] = junit_summary(junit[name])
            result["evidence_error"] = evidence_error(result)
        results.append(result)
        if result["exit_code"] != 0 or result.get("evidence_error"):
            failed_step = name
            break
    after = workspace_sha256()
    reason = failed_step or "passed"
    if failed_step is None and before != after:
        reason = "workspace_mutated"

    report = {
        "run_id": run_id,
        "status": "passed" if reason == "passed" else "failed",
        "reason": reason,
        "failed_step": failed_step,
        "exit_code": 0 if reason == "passed" else 1,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_commit": git("rev-parse", "HEAD").strip(),
        "workspace_sha256": before,
        "workspace_sha256_after": after,
        "python": sys.version.split()[0],
        "interpreter": sys.executable,
        "postgres_scope": postgres_scope,
        "frontend": run_frontend,
        "fast": args.fast,
        "junit_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in junit.items()
            if path.is_file()
        },
        "steps": results,
    }
    report_path = report_dir / "result.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if failed_step is not None:
        failed = results[-1]
        sys.stderr.write((failed["stdout_tail"] + failed["stderr_tail"]).rstrip() + "\n")
    summary = " | ".join(describe(step) for step in results)
    if reason == "workspace_mutated":
        summary += " | 실행 중 워킹트리 변경됨"
    print(f"verify: {report['status']} | {summary} | report {report_path.relative_to(ROOT).as_posix()}")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
