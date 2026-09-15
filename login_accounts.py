from telethon import TelegramClient
import asyncio
from config import ACCOUNTS

async def login_all():
    for acc in ACCOUNTS:
        print(f"\n{'='*40}")
        print(f"  Logging in: {acc['name']}")
        print(f"{'='*40}")
        client = TelegramClient(acc["session"], acc["api_id"], acc["api_hash"])
        await client.start()
        me = await client.get_me()
        print(f"  Logged in as: {me.first_name} (ID: {me.id})")
        await client.disconnect()

    print(f"\nAll {len(ACCOUNTS)} accounts logged in and sessions saved!")

if __name__ == "__main__":
    asyncio.run(login_all())
