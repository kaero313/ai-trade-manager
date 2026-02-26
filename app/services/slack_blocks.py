from app.schemas.portfolio import PortfolioSummary


def _fmt_krw(value: float) -> str:
    return f"{value:,.0f}"


def _fmt_signed(value: float, digits: int = 2) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.{digits}f}"


def build_portfolio_blocks(summary: PortfolioSummary) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "포트폴리오 요약",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*총 자산:* ₩{_fmt_krw(summary.total_net_worth)}\n"
                    f"*총 손익:* {_fmt_signed(summary.total_pnl, 0)}"
                ),
            },
        },
        {"type": "divider"},
    ]

    if not summary.items:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "보유 자산이 없습니다.",
                },
            }
        )
        return blocks

    for item in summary.items:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{item.currency}* ({item.broker})\n"
                        f"평가금액: ₩{_fmt_krw(item.total_value)}\n"
                        f"수익률: {_fmt_signed(item.pnl_percentage)}%\n"
                        f"보유수량: {item.balance:,.8f} | 잠금수량: {item.locked:,.8f}"
                    ),
                },
            }
        )

    return blocks


def build_error_blocks(error_msg: str) -> list[dict]:
    message = error_msg.strip() if error_msg and error_msg.strip() else "알 수 없는 오류가 발생했습니다."

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "오류 발생",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "비상 정지 (Stop)",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": "emergency_stop",
                    "value": "stop",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "전량 매도 후 정지 (Liquidate)",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": "emergency_liquidate",
                    "value": "liquidate",
                },
            ],
        },
    ]
