import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    from app.services.brokers.upbit import UpbitBroker

    broker = UpbitBroker(
        base_url="https://api.upbit.com",
        access_key=os.environ.get("UPBIT_ACCESS_KEY"),
        secret_key=os.environ.get("UPBIT_SECRET_KEY"),
    )
    try:
        accounts = await broker.get_accounts()
        print(f"Upbit 계좌 조회 성공: {accounts}")
    except Exception as exc:
        print(f"Upbit 계좌 조회 실패: {exc}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env.local")
    asyncio.run(main())
