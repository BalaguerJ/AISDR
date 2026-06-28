import asyncio
from agents.scheduler import enqueue_pending_campaign_jobs, reset_simulated_outbox_jobs
from agents.outbox_worker import run_outbox_worker
from agents.campaigns import save_campaign
from agents.db import db_conn
import uuid
from datetime import datetime
import json

async def main():
    camp_id = "test-sim-campaign-5"
    
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE outbox_jobs SET scheduled_at = '2026-05-25T00:00:00' WHERE campaign_id = ?", (camp_id,))
        conn.commit()

    print("\nStarting worker in dry-run mode for 15 seconds (backdated jobs)...")
    task = asyncio.create_task(run_outbox_worker())
    await asyncio.sleep(15)
    task.cancel()
    
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, count(*) FROM outbox_jobs WHERE campaign_id = ? GROUP BY status", (camp_id,))
        print("\nFinal Job Statuses:", dict(cursor.fetchall()))
        
    print("\nResetting jobs to pending...")
    print(reset_simulated_outbox_jobs(camp_id))

if __name__ == '__main__':
    asyncio.run(main())
