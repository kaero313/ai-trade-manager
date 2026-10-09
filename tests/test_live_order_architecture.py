import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
ALLOWED_CREATE_ORDER_SCOPES = {
    (
        "app/services/trading/live_order_execution.py",
        "LiveOrderExecutionService._submit_prepared_once",
    ),
    ("app/services/backtesting/engine.py", "AIPolicyBacktestEngine._try_buy"),
    ("app/services/backtesting/engine.py", "AIPolicyBacktestEngine._try_sell"),
}
ALLOWED_TRADING_MODE_KEY_FILES = {
    "app/db/repository.py",
    "app/db/trading_mode_repository.py",
}
ALLOWED_CANCEL_ORDER_SCOPES = {
    (
        "app/services/trading/liquidation_v2.py",
        "LiquidationV2CoordinatorMixin._phase_canceling_orders",
    ),
}


class _CreateOrderVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.scope_stack: list[str] = []
        self.violations: list[str] = []
        self.allowed_seen: set[tuple[str, str]] = set()

    @property
    def scope(self) -> str:
        return ".".join(self.scope_stack) or "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr == "create_order":
            self._record(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "create_order"
        ):
            self._record(node)
        self.generic_visit(node)

    def _record(self, node: ast.AST) -> None:
        location = (self.relative_path, self.scope)
        if location in ALLOWED_CREATE_ORDER_SCOPES:
            self.allowed_seen.add(location)
            return
        self.violations.append(f"{self.relative_path}:{node.lineno}:{self.scope}")


class _LiveOrderServiceConstructionVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if function_name == "LiveOrderExecutionService":
            has_barrier_keyword = any(
                keyword.arg == "submission_barrier" for keyword in node.keywords
            )
            if len(node.args) < 3 and not has_barrier_keyword:
                self.violations.append(f"{self.relative_path}:{node.lineno}")
        self.generic_visit(node)


class _CancelOrderVisitor(_CreateOrderVisitor):
    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in {"cancel_order", "cancel_orders_by_ids"}:
            location = (self.relative_path, self.scope)
            if location in ALLOWED_CANCEL_ORDER_SCOPES:
                self.allowed_seen.add(location)
            else:
                self.violations.append(
                    f"{self.relative_path}:{node.lineno}:{self.scope}"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"cancel_order", "cancel_orders_by_ids"}
        ):
            self.violations.append(f"{self.relative_path}:{node.lineno}:{self.scope}")
        self.generic_visit(node)


@pytest.mark.architecture
def test_live_order_create_order_calls_use_the_central_gateway() -> None:
    violations: list[str] = []
    allowed_seen: set[tuple[str, str]] = set()

    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        visitor = _CreateOrderVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
        violations.extend(visitor.violations)
        allowed_seen.update(visitor.allowed_seen)

    missing_allowlist = sorted(ALLOWED_CREATE_ORDER_SCOPES - allowed_seen)
    assert not violations, "중앙 실주문 경계를 우회한 create_order 참조:\n" + "\n".join(violations)
    assert not missing_allowlist, f"사용되지 않는 create_order allowlist 항목: {missing_allowlist}"


@pytest.mark.architecture
def test_production_live_order_service_requires_explicit_submission_barrier() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        visitor = _LiveOrderServiceConstructionVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
        violations.extend(visitor.violations)

    assert not violations, "명시적 submission barrier가 없는 실주문 서비스 생성:\n" + "\n".join(
        violations
    )


@pytest.mark.architecture
def test_live_order_cancellation_uses_the_liquidation_gateway() -> None:
    violations: list[str] = []
    allowed_seen: set[tuple[str, str]] = set()
    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        visitor = _CancelOrderVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
        violations.extend(visitor.violations)
        allowed_seen.update(visitor.allowed_seen)

    assert not violations, "중앙 청산 경계를 우회한 cancel_order 참조:\n" + "\n".join(
        violations
    )
    assert ALLOWED_CANCEL_ORDER_SCOPES <= allowed_seen


@pytest.mark.architecture
def test_trading_mode_legacy_mirror_is_only_read_by_central_repository() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path in ALLOWED_TRADING_MODE_KEY_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "TRADING_MODE_KEY":
                violations.append(f"{relative_path}:{node.lineno}")

    assert not violations, "중앙 거래 모드 원장을 우회한 legacy mirror 참조:\n" + "\n".join(
        violations
    )
