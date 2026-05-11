import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    from app.services.brokers.upbit import UpbitBroker

    broker = UpbitBroker()
    try:
        tickers = await broker.get_ticker(["KRW-SGB", "KRW-FLR"])
        print(tickers)
    except Exception as exc:
        print(f"Upbit 티커 조회 실패: {exc!r}")


if __name__ == "__main__":
    asyncio.run(main())
