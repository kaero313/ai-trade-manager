from app.schemas.portfolio import PortfolioSummary


def _fmt_price(value: float) -> str:
    return f"{value:,.2f}"


def _fmt_balance(value: float) -> str:
    return f"{value:,.8f}"


def _fmt_signed(value: float, digits: int = 2) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{digits}f}"


def _extract_bot_status(portfolio: PortfolioSummary) -> str:
    candidates = [
        getattr(portfolio, "bot_status", None),
        getattr(portfolio, "running", None),
        getattr(portfolio, "is_active", None),
        getattr(portfolio, "status", None),
    ]

    for candidate in candidates:
        if candidate is None:
            continue

        if isinstance(candidate, bool):
            return "Running" if candidate else "Paused"

        if isinstance(candidate, dict):
            if isinstance(candidate.get("running"), bool):
                return "Running" if candidate["running"] else "Paused"
            if isinstance(candidate.get("is_active"), bool):
                return "Running" if candidate["is_active"] else "Paused"
            status_value = candidate.get("status")
            if status_value is not None:
                return str(status_value)

        running_attr = getattr(candidate, "running", None)
        if isinstance(running_attr, bool):
            return "Running" if running_attr else "Paused"

        active_attr = getattr(candidate, "is_active", None)
        if isinstance(active_attr, bool):
            return "Running" if active_attr else "Paused"

        return str(candidate)

    return "정보 없음"


def _extract_alert_status(portfolio: PortfolioSummary) -> str:
    candidates = [
        getattr(portfolio, "alert_status", None),
        getattr(portfolio, "notification_status", None),
        getattr(portfolio, "alerts_enabled", None),
    ]

    for candidate in candidates:
        if candidate is None:
            continue

        if isinstance(candidate, bool):
            return "활성" if candidate else "비활성"

        if isinstance(candidate, dict):
            for key in ("enabled", "is_active", "alerts_enabled"):
                if isinstance(candidate.get(key), bool):
                    return "활성" if candidate[key] else "비활성"
            for key in ("status", "state"):
                status_value = candidate.get(key)
                if status_value is not None:
                    return str(status_value)

        enabled_attr = getattr(candidate, "enabled", None)
        if isinstance(enabled_attr, bool):
            return "활성" if enabled_attr else "비활성"

        active_attr = getattr(candidate, "is_active", None)
        if isinstance(active_attr, bool):
            return "활성" if active_attr else "비활성"

        return str(candidate)

    return "정보 없음"


def format_portfolio_for_llm(portfolio: PortfolioSummary) -> str:
    bot_status = _extract_bot_status(portfolio)
    alert_status = _extract_alert_status(portfolio)

    lines: list[str] = [
        "# 포트폴리오 요약",
        f"- 총 자산(total_net_worth): {_fmt_price(portfolio.total_net_worth)}",
        f"- 총 손익(total_pnl): {_fmt_signed(portfolio.total_pnl)}",
        f"- 봇 상태: {bot_status}",
        f"- 알림 상태: {alert_status}",
        "",
        "## 보유 종목 상세",
    ]

    if not portfolio.items:
        lines.append("- 보유 종목 없음")
        return "\n".join(lines).strip()

    for index, item in enumerate(portfolio.items, start=1):
        lines.extend(
            [
                f"{index}. **{item.currency}** ({item.broker})",
                f"   - 수량(balance): {_fmt_balance(item.balance)}",
                f"   - 평균단가(avg_buy_price): {_fmt_price(item.avg_buy_price)}",
                f"   - 현재가(current_price): {_fmt_price(item.current_price)}",
                f"   - 수익률(pnl_percentage): {_fmt_signed(item.pnl_percentage)}%",
            ]
        )

    return "\n".join(lines).strip()
