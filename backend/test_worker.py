import asyncio
from agents.outbox_worker import run_outbox_worker
import sys

async def main():
    task = asyncio.create_task(run_outbox_worker())
    await asyncio.sleep(15)
    task.cancel()

if __name__ == '__main__':
    asyncio.run(main())
