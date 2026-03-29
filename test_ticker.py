import asyncio
from app.services.brokers.upbit import UpbitBroker

async def main():
    broker = UpbitBroker()
    try:
        res = await broker.get_ticker(['KRW-SGB', 'KRW-FLR'])
        print(res)
    except Exception as e:
        print(f"Error: {repr(e)}")

asyncio.run(main())
