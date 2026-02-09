import asyncio
import logging
import re
import uuid
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.core.state import state
from app.services.upbit_client import UpbitAPIError, upbit_client

logger = logging.getLogger(__name__)

MAX_BUY_PCT = 0.20
PENDING_TTL = timedelta(minutes=5)
MAX_VOLUME_DECIMALS = 8
MIN_ORDER_BY_BASE = {
    "KRW": 5000.0,
    "BTC": 0.00005,
    "USDT": 0.5,
}


@dataclass
class PendingOrder:
    token: str
    user_id: str
    channel: str
    channel_type: str | None
    market: str
    side: str
    order_type: str
    amount_krw: float | None
    price: float | None
    volume: float | None
    created_at: datetime


@dataclass
class PendingCancel:
    token: str
    user_id: str
    channel: str
    channel_type: str | None
    order_uuid: str
    created_at: datetime


class SlackSocketService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._client = None
        self._web_client = None
        self._bot_user_id: str | None = None
        self._pending_orders: dict[str, PendingOrder] = {}
        self._pending_cancels: dict[str, PendingCancel] = {}
        self._pending_by_user: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(settings.slack_app_token and settings.slack_bot_token)

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Slack Socket Mode disabled; missing tokens")
            return
        if self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="slack-socket")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.socket_mode.response import SocketModeResponse
            from slack_sdk.web.async_client import AsyncWebClient
        except Exception as exc:
            logger.exception("Slack SDK not available: %s", exc)
            return

        self._web_client = AsyncWebClient(token=settings.slack_bot_token)
        self._client = SocketModeClient(
            app_token=settings.slack_app_token,
            web_client=self._web_client,
        )

        async def _process(client: Any, req: Any) -> None:
            if req.type in ("events_api", "slash_commands", "interactive"):
                await client.send_socket_mode_response(
                    SocketModeResponse(envelope_id=req.envelope_id)
                )
            if req.type != "events_api":
                return
            try:
                await self._handle_event(req.payload.get("event") or {})
            except Exception as exc:
                logger.exception("Slack event handling error: %s", exc)

        self._client.socket_mode_request_listeners.append(_process)

        await self._load_bot_user_id()
        try:
            await self._client.connect()
            logger.info("Slack Socket Mode connected")
            await self._stop_event.wait()
        except Exception as exc:
            logger.exception("Slack Socket Mode connection error: %s", exc)
        finally:
            await self._shutdown_client()

    async def _shutdown_client(self) -> None:
        if self._client is not None:
            for method_name in ("close", "disconnect"):
                method = getattr(self._client, method_name, None)
                if method:
                    result = method()
                    if asyncio.iscoroutine(result):
                        await result
                    break
            self._client = None

        if self._web_client is not None:
            close_method = getattr(self._web_client, "close", None)
            if callable(close_method):
                result = close_method()
                if asyncio.iscoroutine(result):
                    await result
            else:
                session = getattr(self._web_client, "session", None)
                if session is not None:
                    await session.close()
            self._web_client = None

    async def _load_bot_user_id(self) -> None:
        if not self._web_client:
            return
        try:
            auth = await self._web_client.auth_test()
            self._bot_user_id = auth.get("user_id")
        except Exception as exc:
            logger.warning("Slack auth_test failed: %s", exc)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        logger.debug(
            "Slack event received: type=%s channel=%s channel_type=%s",
            event_type,
            event.get("channel"),
            event.get("channel_type"),
        )
        if event_type == "app_mention":
            text = self._strip_mention(event.get("text", ""))
            await self._handle_command(text, event)
            return

        if event_type == "message":
            if event.get("bot_id") or event.get("subtype") == "bot_message":
                return
            channel = event.get("channel")
            channel_type = event.get("channel_type")
            if channel_type not in ("im", "mpim"):
                if not (isinstance(channel, str) and channel.startswith(("D", "G"))):
                    return
            text = event.get("text", "")
            await self._handle_command(text, event)
            return

    def _strip_mention(self, text: str) -> str:
        if not self._bot_user_id:
            return text.strip()
        mention = f"<@{self._bot_user_id}>"
        return text.replace(mention, "").strip()

    async def _handle_command(self, text: str, event: dict[str, Any]) -> None:
        channel = event.get("channel")
        if not channel:
            return
        user_id = str(event.get("user") or "")
        channel_type = event.get("channel_type")
        if not self._is_authorized(user_id, channel, channel_type):
            if channel_type == "im":
                await self._post_message(channel, self._err("권한", "허용되지 않은 사용자/채널입니다."))
            return

        raw = (text or "").strip()
        if not raw:
            await self._send_help(channel)
            return

        cmd = raw.lower()
        normalized = re.sub(r"\s+", " ", cmd).strip()
        compact = normalized.replace(" ", "")
        if normalized.startswith("확인") or normalized.startswith("confirm"):
            await self._confirm_order(user_id, channel, raw)
            return

        if normalized.startswith("매수") or normalized.startswith("buy"):
            await self._prepare_buy(user_id, channel, channel_type, raw)
            return

        if normalized.startswith("매도") or normalized.startswith("sell"):
            await self._prepare_sell(user_id, channel, channel_type, raw)
            return

        if normalized in ("help", "/help", "도움말", "도움"):
            await self._send_help(channel)
            return

        if compact.startswith("미체결"):
            await self._send_orders(channel, raw, order_mode="open")
            return

        if compact.startswith("취소내역"):
            await self._send_orders(channel, raw, order_mode="cancel")
            return

        if compact.startswith("체결"):
            await self._send_orders(channel, raw, order_mode="done")
            return

        if normalized.startswith("취소") or normalized.startswith("주문취소") or normalized.startswith("cancel"):
            await self._prepare_cancel(user_id, channel, channel_type, raw)
            return

        if cmd in ("status", "/status", "상태"):
            await self._send_status(channel)
            return

        if "잔고" in cmd or cmd in ("/balance", "balance"):
            await self._send_balance(channel)
            return

        await self._post_message(channel, self._err("형식", "지원하지 않는 명령입니다. 'help'를 입력하세요."))

    async def _send_help(self, channel: str) -> None:
        text = (
            "사용 가능한 명령:\n"
            "- 잔고 / balance\n"
            "- status\n"
            "- 매수 KRW-BTC 100000 (시장가)\n"
            "- 매수 KRW-BTC 10% (시장가)\n"
            "- 매수 KRW-BTC 100000 지정가 50000000\n"
            "- 매도 KRW-BTC 0.01 (시장가, 수량)\n"
            "- 매도 KRW-BTC 10% (시장가, 보유비율)\n"
            "- 매도 KRW-BTC 0.01 지정가 50000000\n"
            "- 미체결 내역 (또는 미체결 내역 KRW-BTC)\n"
            "- 체결 내역 (또는 체결 내역 KRW-BTC)\n"
            "- 취소 내역 (또는 취소 내역 KRW-BTC)\n"
            "- 취소 <주문 UUID>\n"
            "- 확인 <토큰>\n"
            "- 마켓은 BTC처럼 입력하면 기본 KRW로 인식\n"
            "- help\n"
        )
        await self._post_message(channel, text)

    async def _send_status(self, channel: str) -> None:
        status = state.status()
        heartbeat = status.last_heartbeat or "-"
        err = status.last_error or "-"
        text = (
            f"봇 상태: {'실행 중' if status.running else '중지'}\n"
            f"마지막 하트비트: {heartbeat}\n"
            f"최근 오류: {err}"
        )
        await self._post_message(channel, text)

    async def _send_balance(self, channel: str) -> None:
        if not settings.upbit_access_key or not settings.upbit_secret_key:
            await self._post_message(
                channel,
                self._err("설정", "Upbit 키가 설정되지 않았습니다. .env의 UPBIT_ACCESS_KEY/SECRET_KEY를 확인하세요."),
            )
            return

        try:
            accounts = await upbit_client.get_accounts()
        except UpbitAPIError as exc:
            await self._post_message(channel, self._format_upbit_error(exc))
            return

        balances = self._extract_balances(accounts)
        if not balances:
            await self._post_message(channel, "표시할 잔고가 없습니다.")
            return

        price_map, valid_markets = await self._load_prices(balances)
        lines = self._format_balances(balances, price_map, valid_markets)
        await self._post_message(channel, "\n".join(lines))

    async def _send_orders(self, channel: str, raw: str, order_mode: str) -> None:
        if not settings.upbit_access_key or not settings.upbit_secret_key:
            await self._post_message(
                channel,
                self._err("설정", "Upbit 키가 설정되지 않았습니다. .env의 UPBIT_ACCESS_KEY/SECRET_KEY를 확인하세요."),
            )
            return

        market = self._extract_market(raw)
        show_closed = order_mode in ("done", "cancel")
        try:
            if show_closed:
                if order_mode == "done":
                    states = ["done"]
                    title = "[체결 내역]"
                else:
                    states = ["cancel"]
                    title = "[취소 내역]"
                orders = await upbit_client.get_orders_closed(
                    market=market,
                    states=states,
                    limit=10,
                    order_by="desc",
                )
            else:
                states = ["wait", "watch"]
                orders = await upbit_client.get_orders_open(
                    market=market,
                    states=states,
                    limit=10,
                    order_by="desc",
                )
                title = "[미체결 내역]"
        except UpbitAPIError as exc:
            await self._post_message(channel, self._format_upbit_error(exc))
            return

        if states:
            orders = [item for item in orders if item.get("state") in states]

        if not orders:
            await self._post_message(channel, "표시할 주문이 없습니다.")
            return

        buy_count = sum(1 for item in orders if item.get("side") == "bid")
        sell_count = sum(1 for item in orders if item.get("side") == "ask")
        summary = f"요약: 총 {len(orders)}건 (매수 {buy_count} / 매도 {sell_count})"
        if order_mode == "open":
            wait_count = sum(1 for item in orders if item.get("state") == "wait")
            watch_count = sum(1 for item in orders if item.get("state") == "watch")
            summary += f" | 상태 wait {wait_count}, watch {watch_count}"

        lines = [title, summary]
        for item in orders:
            lines.append(self._format_order_line(item))
        await self._post_message(channel, "\n".join(lines))

    def _is_authorized(self, user_id: str, channel: str, channel_type: str | None) -> bool:
        allowed_users = self._split_csv(settings.slack_allowed_user_ids)
        if allowed_users and user_id not in allowed_users:
            logger.info("Slack unauthorized user: %s", user_id)
            return False

        if channel_type == "im" or (isinstance(channel, str) and channel.startswith("D")):
            return True

        allowed_channels = self._split_csv(settings.slack_trade_channel_ids)
        if allowed_channels and channel in allowed_channels:
            return True

        logger.info("Slack unauthorized channel: %s", channel)
        return False

    async def _prepare_buy(
        self,
        user_id: str,
        channel: str,
        channel_type: str | None,
        raw: str,
    ) -> None:
        parsed = self._parse_trade_command(raw)
        if parsed is None:
            await self._post_message(
                channel,
                self._err(
                    "형식",
                    "매수 형식이 올바르지 않습니다. 예) 매수 KRW-BTC 100000, 매수 KRW-BTC 10%, "
                    "매수 KRW-BTC 100000 지정가 50000000",
                ),
            )
            return

        market = parsed["market"]
        base_currency, _ = self._split_market(market)
        order_type = parsed["order_type"]
        amount_value = parsed["amount_value"]
        amount_is_pct = parsed["amount_is_pct"]
        amount_raw = parsed.get("amount_raw")
        limit_price = parsed.get("price")

        if not settings.upbit_access_key or not settings.upbit_secret_key:
            await self._post_message(
                channel,
                self._err("설정", "Upbit 키가 설정되지 않았습니다. .env의 UPBIT_ACCESS_KEY/SECRET_KEY를 확인하세요."),
            )
            return

        try:
            accounts = await upbit_client.get_accounts()
        except UpbitAPIError as exc:
            await self._post_message(channel, self._format_upbit_error(exc))
            return

        available_base = self._available_currency(accounts, base_currency)
        if available_base <= 0:
            await self._post_message(channel, self._err("잔고", f"사용 가능한 {base_currency} 잔고가 없습니다."))
            return

        if amount_is_pct:
            pct = amount_value / 100.0
            if pct <= 0 or pct > 1:
                await self._post_message(channel, self._err("값", "퍼센트 값이 올바르지 않습니다."))
                return
            if pct > MAX_BUY_PCT:
                await self._post_message(
                    channel,
                    self._err(
                        "제한",
                        f"1회 매수 상한은 사용 가능한 {base_currency}의 {int(MAX_BUY_PCT*100)}%입니다.",
                    ),
                )
                return
            amount_krw = available_base * pct
        else:
            amount_krw = amount_value
            if amount_krw <= 0:
                await self._post_message(channel, self._err("값", "매수 금액이 올바르지 않습니다."))
                return
            if amount_krw > available_base * MAX_BUY_PCT:
                await self._post_message(
                    channel,
                    self._err(
                        "제한",
                        f"1회 매수 상한은 사용 가능한 {base_currency}의 {int(MAX_BUY_PCT*100)}%입니다.",
                    ),
                )
                return

        if amount_krw > available_base:
            await self._post_message(channel, self._err("잔고", f"{base_currency} 잔고가 부족합니다."))
            return

        min_amount = self._min_order_amount(base_currency)
        if min_amount and amount_krw < min_amount:
            min_text = self._format_currency_amount(min_amount, base_currency)
            await self._post_message(
                channel,
                self._err("제한", f"최소 주문 금액은 {min_text} {base_currency}입니다."),
            )
            return

        volume = None
        if order_type == "limit":
            if not limit_price or limit_price <= 0:
                await self._post_message(channel, self._err("형식", "지정가 주문은 가격이 필요합니다."))
                return
            tick = self._tick_size(base_currency, limit_price)
            if tick and not self._is_tick_aligned(limit_price, tick):
                tick_text = self._format_currency_amount(tick, base_currency)
                await self._post_message(
                    channel,
                    self._err("제한", f"호가 단위는 {tick_text} {base_currency}입니다."),
                )
                return
            volume = self._floor_decimals(amount_krw / limit_price, MAX_VOLUME_DECIMALS)
            if volume <= 0:
                await self._post_message(channel, self._err("제한", "계산된 수량이 너무 작습니다."))
                return
            if min_amount:
                order_value = volume * limit_price
                if order_value < min_amount:
                    min_text = self._format_currency_amount(min_amount, base_currency)
                    await self._post_message(
                        channel,
                        self._err("제한", f"최소 주문 금액은 {min_text} {base_currency}입니다."),
                    )
                    return

        token = uuid.uuid4().hex[:6]
        pending = PendingOrder(
            token=token,
            user_id=user_id,
            channel=channel,
            channel_type=channel_type,
            market=market,
            side="bid",
            order_type=order_type,
            amount_krw=amount_krw,
            price=limit_price,
            volume=volume,
            created_at=datetime.now(timezone.utc),
        )
        self._register_pending(user_id, pending)

        summary = self._format_pending_summary(pending)
        await self._post_message(
            channel,
            f"{summary}\n확인하려면 `확인 {token}` 을 입력하세요. (유효 {int(PENDING_TTL.total_seconds()/60)}분)",
        )

    async def _prepare_sell(
        self,
        user_id: str,
        channel: str,
        channel_type: str | None,
        raw: str,
    ) -> None:
        parsed = self._parse_trade_command(raw)
        if parsed is None:
            await self._post_message(
                channel,
                self._err(
                    "형식",
                    "매도 형식이 올바르지 않습니다. 예) 매도 KRW-BTC 0.01, 매도 KRW-BTC 10%, "
                    "매도 KRW-BTC 0.01 지정가 50000000",
                ),
            )
            return

        market = parsed["market"]
        order_type = parsed["order_type"]
        amount_value = parsed["amount_value"]
        amount_is_pct = parsed["amount_is_pct"]
        limit_price = parsed.get("price")

        if not settings.upbit_access_key or not settings.upbit_secret_key:
            await self._post_message(
                channel,
                self._err("설정", "Upbit 키가 설정되지 않았습니다. .env의 UPBIT_ACCESS_KEY/SECRET_KEY를 확인하세요."),
            )
            return

        try:
            accounts = await upbit_client.get_accounts()
        except UpbitAPIError as exc:
            await self._post_message(channel, self._format_upbit_error(exc))
            return

        _, currency = self._split_market(market)
        available_volume = self._available_coin(accounts, currency)
        if available_volume <= 0:
            await self._post_message(channel, self._err("잔고", "매도 가능한 코인 잔고가 없습니다."))
            return

        if amount_is_pct:
            pct = amount_value / 100.0
            if pct <= 0 or pct > 1:
                await self._post_message(channel, self._err("값", "퍼센트 값이 올바르지 않습니다."))
                return
            volume = available_volume * pct
        else:
            if amount_raw and self._decimal_places(amount_raw) > MAX_VOLUME_DECIMALS:
                await self._post_message(
                    channel,
                    self._err("제한", f"수량 소수 자릿수는 최대 {MAX_VOLUME_DECIMALS}자리입니다."),
                )
                return
            volume = amount_value
            if volume <= 0:
                await self._post_message(channel, self._err("값", "매도 수량이 올바르지 않습니다."))
                return

        if volume > available_volume:
            await self._post_message(channel, self._err("잔고", "보유 수량이 부족합니다."))
            return

        base_currency, _ = self._split_market(market)
        min_amount = self._min_order_amount(base_currency)
        if min_amount:
            order_value = None
            if order_type == "limit" and limit_price:
                order_value = limit_price * volume
            elif order_type == "market":
                try:
                    tickers = await upbit_client.get_ticker([market])
                except UpbitAPIError as exc:
                    await self._post_message(channel, self._format_upbit_error(exc))
                    return
                if tickers:
                    price = tickers[0].get("trade_price")
                    if price:
                        order_value = float(price) * volume
            if order_value is not None and order_value < min_amount:
                min_text = self._format_currency_amount(min_amount, base_currency)
                await self._post_message(
                    channel,
                    self._err("제한", f"최소 주문 금액은 {min_text} {base_currency}입니다."),
                )
                return

        if order_type == "limit":
            if not limit_price or limit_price <= 0:
                await self._post_message(channel, self._err("형식", "지정가 주문은 가격이 필요합니다."))
                return
            tick = self._tick_size(base_currency, limit_price)
            if tick and not self._is_tick_aligned(limit_price, tick):
                tick_text = self._format_currency_amount(tick, base_currency)
                await self._post_message(
                    channel,
                    self._err("제한", f"호가 단위는 {tick_text} {base_currency}입니다."),
                )
                return

        token = uuid.uuid4().hex[:6]
        pending = PendingOrder(
            token=token,
            user_id=user_id,
            channel=channel,
            channel_type=channel_type,
            market=market,
            side="ask",
            order_type=order_type,
            amount_krw=None,
            price=limit_price,
            volume=volume,
            created_at=datetime.now(timezone.utc),
        )
        self._register_pending(user_id, pending)

        summary = self._format_pending_summary(pending)
        await self._post_message(
            channel,
            f"{summary}\n확인하려면 `확인 {token}` 을 입력하세요. (유효 {int(PENDING_TTL.total_seconds()/60)}분)",
        )

    async def _prepare_cancel(
        self,
        user_id: str,
        channel: str,
        channel_type: str | None,
        raw: str,
    ) -> None:
        parts = raw.split()
        order_uuid = parts[1] if len(parts) > 1 else ""
        if not order_uuid or not self._looks_like_uuid(order_uuid):
            await self._post_message(channel, self._err("형식", "취소는 `취소 <주문 UUID>` 형식입니다."))
            return

        token = uuid.uuid4().hex[:6]
        pending = PendingCancel(
            token=token,
            user_id=user_id,
            channel=channel,
            channel_type=channel_type,
            order_uuid=order_uuid,
            created_at=datetime.now(timezone.utc),
        )
        self._register_pending_cancel(user_id, pending)
        await self._post_message(
            channel,
            f"[주문 취소 확인]\n- uuid: {order_uuid}\n확인하려면 `확인 {token}` 을 입력하세요. "
            f"(유효 {int(PENDING_TTL.total_seconds()/60)}분)",
        )

    async def _confirm_order(self, user_id: str, channel: str, raw: str) -> None:
        self._cleanup_pending()
        parts = raw.split()
        token = parts[1] if len(parts) > 1 else self._pending_by_user.get(user_id)
        if not token:
            await self._post_message(channel, self._err("토큰", "확인할 주문이 없습니다. 토큰을 입력하세요."))
            return

        pending = self._pending_orders.get(token)
        if pending:
            if pending.user_id != user_id:
                await self._post_message(channel, self._err("권한", "다른 사용자 주문은 확인할 수 없습니다."))
                return

            if pending.channel != channel:
                await self._post_message(channel, self._err("권한", "주문을 생성한 채널에서만 확인할 수 있습니다."))
                return

            try:
                result = await self._submit_order(pending)
            except UpbitAPIError as exc:
                await self._post_message(channel, self._format_upbit_error(exc))
                return

            order_uuid = result.get("uuid") if isinstance(result, dict) else None
            action = "매수" if pending.side == "bid" else "매도"
            message = f"{action} 주문이 접수되었습니다."
            if order_uuid:
                message += f" (uuid: {order_uuid})"
            await self._post_message(channel, message)
            self._pending_orders.pop(token, None)
            if self._pending_by_user.get(user_id) == token:
                self._pending_by_user.pop(user_id, None)
            return

        pending_cancel = self._pending_cancels.get(token)
        if not pending_cancel:
            await self._post_message(channel, self._err("토큰", "해당 토큰의 주문이 없습니다."))
            return

        if pending_cancel.user_id != user_id:
            await self._post_message(channel, self._err("권한", "다른 사용자 주문은 확인할 수 없습니다."))
            return

        if pending_cancel.channel != channel:
            await self._post_message(channel, self._err("권한", "주문을 생성한 채널에서만 확인할 수 있습니다."))
            return

        try:
            result = await upbit_client.cancel_order(uuid_=pending_cancel.order_uuid)
        except UpbitAPIError as exc:
            await self._post_message(channel, self._format_upbit_error(exc))
            return

        order_uuid = result.get("uuid") if isinstance(result, dict) else None
        message = "주문이 취소되었습니다."
        if order_uuid:
            message += f" (uuid: {order_uuid})"
        await self._post_message(channel, message)
        self._pending_cancels.pop(token, None)
        if self._pending_by_user.get(user_id) == token:
            self._pending_by_user.pop(user_id, None)

    async def _submit_order(self, pending: PendingOrder) -> dict[str, Any]:
        if pending.side == "bid":
            if pending.order_type == "market":
                return await upbit_client.create_order(
                    market=pending.market,
                    side="bid",
                    ord_type="price",
                    price=self._fmt_number(pending.amount_krw or 0),
                )
            return await upbit_client.create_order(
                market=pending.market,
                side="bid",
                ord_type="limit",
                price=self._fmt_number(pending.price or 0),
                volume=self._fmt_number(pending.volume or 0),
            )

        if pending.order_type == "market":
            return await upbit_client.create_order(
                market=pending.market,
                side="ask",
                ord_type="market",
                volume=self._fmt_number(pending.volume or 0),
            )
        return await upbit_client.create_order(
            market=pending.market,
            side="ask",
            ord_type="limit",
            price=self._fmt_number(pending.price or 0),
            volume=self._fmt_number(pending.volume or 0),
        )

    def _format_pending_summary(self, pending: PendingOrder) -> str:
        action = "매수" if pending.side == "bid" else "매도"
        order_type = "시장가" if pending.order_type == "market" else "지정가"
        base_currency, _ = self._split_market(pending.market)
        amount_text = self._format_currency_amount(pending.amount_krw or 0, base_currency)
        price_text = self._format_currency_amount(pending.price or 0, base_currency)
        lines = [
            f"[{action} 확인]",
            f"- 마켓: {pending.market}",
            f"- 타입: {order_type}",
        ]
        if pending.side == "bid":
            lines.append(f"- 금액: {amount_text} {base_currency}")
        else:
            lines.append(f"- 수량: {self._fmt_amount(pending.volume or 0)}")
        if pending.order_type == "limit":
            lines.append(f"- 가격: {price_text} {base_currency}")
        return "\n".join(lines)

    def _format_order_line(self, item: dict[str, Any]) -> str:
        market = item.get("market", "-")
        base_currency, _ = self._split_market(market)
        side = "매수" if item.get("side") == "bid" else "매도"
        state = item.get("state", "-")
        ord_type = self._format_ord_type(item.get("ord_type"), item.get("side"))
        price = self._format_order_price(item.get("price"), base_currency)
        avg_price = self._format_order_price(item.get("avg_price"), base_currency)
        volume = self._format_amount_field(item.get("volume"))
        executed = self._format_amount_field(item.get("executed_volume"))
        remaining = self._format_amount_field(item.get("remaining_volume"))
        created_at = self._format_time(item.get("created_at"))
        uuid_ = item.get("uuid")

        parts = [f"{side} {market}", f"{ord_type}", f"상태 {state}"]
        if item.get("ord_type") == "price" and price:
            parts.append(f"금액 {price} {base_currency}")
        elif price:
            parts.append(f"주문가 {price} {base_currency}")
        if avg_price:
            parts.append(f"평균가 {avg_price} {base_currency}")
        if volume:
            parts.append(f"주문량 {volume}")
        if executed:
            parts.append(f"체결량 {executed}")
        if remaining:
            parts.append(f"잔량 {remaining}")
        if created_at:
            parts.append(f"시간 {created_at}")
        if uuid_:
            parts.append(f"uuid {uuid_}")
        return " | ".join(parts)

    def _register_pending(self, user_id: str, pending: PendingOrder) -> None:
        previous_token = self._pending_by_user.get(user_id)
        if previous_token:
            self._pending_orders.pop(previous_token, None)
            self._pending_cancels.pop(previous_token, None)
        self._pending_orders[pending.token] = pending
        self._pending_by_user[user_id] = pending.token
        self._cleanup_pending()

    def _register_pending_cancel(self, user_id: str, pending: PendingCancel) -> None:
        previous_token = self._pending_by_user.get(user_id)
        if previous_token:
            self._pending_orders.pop(previous_token, None)
            self._pending_cancels.pop(previous_token, None)
        self._pending_cancels[pending.token] = pending
        self._pending_by_user[user_id] = pending.token
        self._cleanup_pending()

    def _cleanup_pending(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, item in self._pending_orders.items() if now - item.created_at > PENDING_TTL]
        for key in expired:
            pending = self._pending_orders.pop(key, None)
            if pending and self._pending_by_user.get(pending.user_id) == key:
                self._pending_by_user.pop(pending.user_id, None)
        expired_cancels = [key for key, item in self._pending_cancels.items() if now - item.created_at > PENDING_TTL]
        for key in expired_cancels:
            pending = self._pending_cancels.pop(key, None)
            if pending and self._pending_by_user.get(pending.user_id) == key:
                self._pending_by_user.pop(pending.user_id, None)

    def _parse_trade_command(self, raw: str) -> dict[str, Any] | None:
        tokens = raw.split()
        if len(tokens) < 3:
            return None
        market = self._normalize_market_token(tokens[1])
        if not market:
            return None
        rest_tokens = tokens[2:]
        rest_text = " ".join(rest_tokens)

        order_type = "market"
        if any(tok in ("지정가", "limit") for tok in rest_tokens) or "@" in rest_text:
            order_type = "limit"
        if any(tok in ("시장가", "market") for tok in rest_tokens):
            order_type = "market"

        amount_str = None
        price_str = None

        if "@" in rest_text:
            left, right = rest_text.split("@", 1)
            amount_str = self._first_number_in_text(left)
            price_str = self._first_number_in_text(right)
            order_type = "limit"
        else:
            numbers = self._extract_numbers(rest_tokens)
            if not numbers:
                return None
            amount_str = numbers[0]
            if order_type == "limit":
                price_str = self._find_price_after_keyword(rest_tokens, ("지정가", "limit"))
                if not price_str and len(numbers) >= 2:
                    price_str = numbers[1]

        if not amount_str:
            return None

        amount_is_pct = amount_str.endswith("%")
        amount_raw = amount_str.rstrip("%").replace(",", "")
        amount_value = self._to_number(amount_raw)
        if amount_value is None:
            return None

        price = None
        if order_type == "limit":
            if not price_str:
                return None
            price = self._to_number(price_str)
            if price is None:
                return None

        return {
            "market": market,
            "order_type": order_type,
            "amount_value": amount_value,
            "amount_is_pct": amount_is_pct,
            "amount_raw": amount_raw,
            "price": price,
        }

    def _find_price_after_keyword(self, tokens: list[str], keywords: tuple[str, ...]) -> str | None:
        for idx, tok in enumerate(tokens):
            if tok in keywords:
                for candidate in tokens[idx + 1 :]:
                    if self._is_number_like(candidate):
                        return candidate
        return None

    def _first_number_in_text(self, text: str) -> str | None:
        matches = re.findall(r"[0-9][0-9,]*\.?[0-9]*%?", text)
        return matches[0] if matches else None

    def _extract_numbers(self, tokens: list[str]) -> list[str]:
        results = []
        for tok in tokens:
            if self._is_number_like(tok):
                results.append(tok)
        return results

    def _is_number_like(self, value: str) -> bool:
        candidate = value.replace(",", "")
        if candidate.endswith("%"):
            candidate = candidate[:-1]
        return bool(re.fullmatch(r"[0-9]+(\.[0-9]+)?", candidate))

    def _to_number(self, value: str) -> float | None:
        candidate = value.replace(",", "")
        try:
            return float(candidate)
        except ValueError:
            return None

    def _available_krw(self, accounts: list[dict[str, Any]]) -> float:
        return self._available_currency(accounts, "KRW")

    def _available_coin(self, accounts: list[dict[str, Any]], currency: str) -> float:
        return self._available_currency(accounts, currency)

    def _available_currency(self, accounts: list[dict[str, Any]], currency: str) -> float:
        for item in accounts:
            if item.get("currency") == currency:
                balance = self._to_float(item.get("balance"))
                locked = self._to_float(item.get("locked"))
                return max(balance - locked, 0.0)
        return 0.0

    def _split_csv(self, value: str | None) -> set[str]:
        if not value:
            return set()
        return {item.strip() for item in value.split(",") if item.strip()}

    def _fmt_number(self, value: float) -> str:
        return f"{value:.8f}".rstrip("0").rstrip(".") or "0"

    def _normalize_market_token(self, token: str) -> str | None:
        clean = token.strip().upper()
        if not clean:
            return None
        if "-" in clean:
            return clean
        if re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]+", clean):
            return f"KRW-{clean}"
        return None

    def _split_market(self, market: str) -> tuple[str, str]:
        parts = market.split("-", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "KRW", market

    def _extract_market(self, raw: str) -> str | None:
        tokens = raw.split()
        for token in tokens[1:]:
            market = self._normalize_market_token(token)
            if market:
                return market
        return None

    def _extract_balances(self, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for item in accounts:
            currency = item.get("currency")
            balance = self._to_float(item.get("balance"))
            locked = self._to_float(item.get("locked"))
            total = balance + locked
            if not currency or total <= 0:
                continue
            results.append(
                {
                    "currency": currency,
                    "balance": balance,
                    "locked": locked,
                    "total": total,
                    "avg_buy_price": self._to_float(item.get("avg_buy_price")),
                    "unit_currency": item.get("unit_currency") or "KRW",
                }
            )
        return results

    async def _load_prices(
        self, balances: list[dict[str, Any]]
    ) -> tuple[dict[str, float], set[str] | None]:
        markets = []
        for item in balances:
            if item["currency"] == "KRW":
                continue
            if item["unit_currency"] != "KRW":
                continue
            markets.append(f"KRW-{item['currency']}")
        markets = list(dict.fromkeys(markets))
        if not markets:
            return {}, None

        valid_markets: set[str] | None = None
        try:
            market_list = await upbit_client.get_markets()
            valid_markets = {
                item.get("market")
                for item in market_list
                if isinstance(item, dict) and isinstance(item.get("market"), str)
            }
        except UpbitAPIError as exc:
            logger.warning("Upbit market list error: %s", exc)

        if valid_markets is not None:
            markets = [market for market in markets if market in valid_markets]
            if not markets:
                return {}, valid_markets

        try:
            tickers = await upbit_client.get_ticker(markets)
        except UpbitAPIError as exc:
            logger.warning("Upbit ticker error: %s", exc)
            return {}, valid_markets
        price_map: dict[str, float] = {}
        for item in tickers:
            market = item.get("market")
            price = item.get("trade_price")
            if market and price is not None:
                price_map[market] = float(price)
        return price_map, valid_markets

    def _format_balances(
        self,
        balances: list[dict[str, Any]],
        price_map: dict[str, float],
        valid_markets: set[str] | None,
    ) -> list[str]:
        summary_lines = ["[잔고 요약]"]
        detail_lines = ["[보유 코인]"]
        unknown_symbols: list[str] = []

        krw_balance = 0.0
        krw_locked = 0.0
        coin_value = 0.0
        total_pnl = 0.0

        for item in balances:
            currency = item["currency"]
            total = item["total"]
            locked = item["locked"]
            avg_buy = item["avg_buy_price"]
            unit_currency = item["unit_currency"]

            if currency == "KRW":
                krw_balance = item["balance"]
                krw_locked = locked
                continue

            line = f"{currency}: 수량 {self._fmt_amount(total)}"
            if locked > 0:
                line += f" (주문중 {self._fmt_amount(locked)})"
            if avg_buy > 0:
                line += f" | 평균단가 {self._fmt_krw(avg_buy)} {unit_currency}"
            else:
                line += " | 평균단가 -"

            if unit_currency == "KRW":
                market = f"KRW-{currency}"
                if valid_markets is not None and market not in valid_markets:
                    unknown_symbols.append(currency)
                    continue

                price = price_map.get(market)
                if price:
                    value = price * total
                    coin_value += value
                    line += f" | 추정 {self._fmt_krw(value)} KRW"
                    if avg_buy > 0:
                        pnl = (price - avg_buy) * total
                        total_pnl += pnl
                        line += f" | 손익 {self._fmt_signed_krw(pnl)} KRW ({self._fmt_pct(price, avg_buy)})"
                else:
                    unknown_symbols.append(currency)
                    continue
            else:
                unknown_symbols.append(f"{currency}({unit_currency})")
                continue

            detail_lines.append(line)

        krw_total = krw_balance + krw_locked
        summary_line = f"계좌 잔고(KRW): {self._fmt_krw(krw_total)} KRW"
        if krw_locked > 0:
            summary_line += f" (주문중 {self._fmt_krw(krw_locked)} KRW)"
        summary_lines.append(summary_line)
        summary_lines.append(f"보유 코인 평가액: {self._fmt_krw(coin_value)} KRW")
        summary_lines.append(f"추정 총자산: {self._fmt_krw(krw_total + coin_value)} KRW")
        if coin_value > 0:
            summary_lines.append(f"보유 코인 손익 합계: {self._fmt_signed_krw(total_pnl)} KRW")
        if unknown_symbols:
            summary_lines.append(f"미시세 코인: {', '.join(sorted(unknown_symbols))}")

        if len(detail_lines) == 1:
            detail_lines.append("보유 코인이 없습니다.")

        return summary_lines + [""] + detail_lines

    async def _post_message(self, channel: str, text: str) -> None:
        if not self._web_client:
            logger.warning("Slack web client not ready")
            return
        await self._web_client.chat_postMessage(channel=channel, text=text)

    @staticmethod
    def _err(category: str, message: str) -> str:
        return f"오류[{category}] {message}"

    def _format_upbit_error(self, exc: UpbitAPIError) -> str:
        payload = exc.to_dict()
        name = payload.get("error_name") or "unknown"
        message = payload.get("message") or "-"
        return self._err("업비트", f"{name} {message}")

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _fmt_amount(value: float, decimals: int = 8) -> str:
        formatted = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        return formatted or "0"

    @staticmethod
    def _fmt_krw(value: float) -> str:
        return f"{value:,.0f}"

    @staticmethod
    def _fmt_signed_krw(value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.0f}"

    @staticmethod
    def _fmt_pct(current: float, avg: float) -> str:
        if avg <= 0:
            return "-"
        pct = (current / avg - 1.0) * 100.0
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.2f}%"

    def _format_currency_amount(self, value: float, currency: str) -> str:
        if currency == "KRW":
            if value >= 1:
                return self._fmt_krw(value)
            return self._fmt_amount(value, decimals=8)
        return self._fmt_amount(value)

    def _min_order_amount(self, base_currency: str) -> float | None:
        return MIN_ORDER_BY_BASE.get(base_currency)

    @staticmethod
    def _decimal_places(value: str) -> int:
        text = value.strip()
        if "." not in text:
            return 0
        decimals = text.split(".", 1)[1].rstrip("0")
        return len(decimals)

    def _format_order_price(self, value: Any, base_currency: str) -> str | None:
        if value is None:
            return None
        numeric = self._to_float(value)
        if numeric <= 0:
            return None
        return self._format_currency_amount(numeric, base_currency)

    def _format_amount_field(self, value: Any) -> str | None:
        if value is None:
            return None
        numeric = self._to_float(value)
        if numeric <= 0:
            return None
        return self._fmt_amount(numeric)

    @staticmethod
    def _format_time(value: Any) -> str | None:
        if not value:
            return None
        if isinstance(value, str):
            cleaned = value.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(cleaned)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                return value
        return str(value)

    @staticmethod
    def _format_ord_type(value: Any, side: Any) -> str:
        if value == "limit":
            return "지정가"
        if value == "market":
            return "시장가"
        if value == "price":
            return "시장가(금액)"
        return str(value) if value is not None else "-"

    @staticmethod
    def _floor_decimals(value: float, decimals: int) -> float:
        if decimals <= 0:
            return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_DOWN))
        quant = Decimal("1").scaleb(-decimals)
        return float(Decimal(str(value)).quantize(quant, rounding=ROUND_DOWN))

    def _tick_size(self, base_currency: str, price: float) -> float | None:
        if base_currency == "KRW":
            return self._tick_size_krw(price)
        if base_currency == "BTC":
            return 0.00000001
        if base_currency == "USDT":
            return self._tick_size_usdt(price)
        return None

    @staticmethod
    def _tick_size_krw(price: float) -> float:
        if price >= 2_000_000:
            return 1000
        if price >= 1_000_000:
            return 1000
        if price >= 500_000:
            return 500
        if price >= 100_000:
            return 100
        if price >= 50_000:
            return 50
        if price >= 10_000:
            return 10
        if price >= 5_000:
            return 5
        if price >= 1_000:
            return 1
        if price >= 100:
            return 1
        if price >= 10:
            return 0.1
        if price >= 1:
            return 0.01
        if price >= 0.1:
            return 0.001
        if price >= 0.01:
            return 0.0001
        if price >= 0.001:
            return 0.00001
        if price >= 0.0001:
            return 0.000001
        if price >= 0.00001:
            return 0.0000001
        return 0.00000001

    @staticmethod
    def _tick_size_usdt(price: float) -> float:
        if price >= 10:
            return 0.01
        if price >= 1:
            return 0.001
        if price >= 0.1:
            return 0.0001
        if price >= 0.01:
            return 0.00001
        if price >= 0.001:
            return 0.000001
        if price >= 0.0001:
            return 0.0000001
        return 0.00000001

    @staticmethod
    def _is_tick_aligned(price: float, tick: float) -> bool:
        if tick <= 0:
            return True
        quotient = round(price / tick)
        aligned = quotient * tick
        return abs(aligned - price) < max(tick * 1e-6, 1e-9)

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        if re.fullmatch(r"[0-9a-fA-F]{32}", value):
            return True
        return bool(
            re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                value,
            )
        )


slack_socket_service = SlackSocketService()
