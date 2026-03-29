import asyncio
import os
from app.services.brokers.upbit import UpbitBroker

async def main():
    broker = UpbitBroker(
        base_url="https://api.upbit.com",
        access_key=os.environ.get("UPBIT_ACCESS_KEY"),
        secret_key=os.environ.get("UPBIT_SECRET_KEY"),
    )
    try:
        accounts = await broker.get_accounts()
        print(f"Accounts fetched successfully: {accounts}")
    except Exception as e:
        print(f"Error fetching accounts: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env.local")
    asyncio.run(main())
