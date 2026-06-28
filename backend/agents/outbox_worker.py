import asyncio
import os
from datetime import datetime, timedelta
import sqlite3
from agents.db import db_conn
from agents.campaigns import get_campaign, save_campaign
from agents.outreach_sender import send_gmail_human_like, send_whatsapp_human_like
from agents.outreach_ai import generate_cold_email

OUTREACH_WORKER_MODE = os.getenv("OUTREACH_WORKER_MODE", "outbox_dry_run") 

async def run_outbox_worker():
    if OUTREACH_WORKER_MODE == "legacy":
        return

    print(f"🚀 Outbox Worker Started in {OUTREACH_WORKER_MODE} mode.")
    
    while True:
        try:
            await asyncio.sleep(10)
            
            with db_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # 1. Rescue expired locks
                cursor.execute("""
                    UPDATE outbox_jobs 
                    SET status = 'pending', locked_at = NULL, locked_by = NULL, lock_expires_at = NULL
                    WHERE status = 'locked' AND lock_expires_at <= ?
                """, (now,))
                conn.commit()

                # 2. Find jobs to process
                cursor.execute("""
                    SELECT * FROM outbox_jobs 
                    WHERE status = 'pending' AND scheduled_at <= ?
                    ORDER BY scheduled_at ASC LIMIT 5
                """, (now,))
                jobs = [dict(row) for row in cursor.fetchall()]
                
                if not jobs:
                    continue
                    
                for job in jobs:
                    lock_id = "worker_1"
                    expires = (datetime.now() + timedelta(minutes=10)).isoformat()
                    
                    cursor.execute("""
                        UPDATE outbox_jobs 
                        SET status = 'locked', locked_at = ?, locked_by = ?, lock_expires_at = ?
                        WHERE id = ? AND status = 'pending'
                    """, (now, lock_id, expires, job['id']))
                    
                    if cursor.rowcount == 0:
                        continue
                        
                    conn.commit()
                    
                    await process_job(job, cursor, conn)
                    
        except Exception as e:
            import traceback
            print(f"💥 Outbox Worker Error: {e}\n{traceback.format_exc()}")
            
async def process_job(job, cursor, conn):
    print(f"[{OUTREACH_WORKER_MODE}] Processing job {job['id']} for campaign {job['campaign_id']}")
    
    # 1. Stop Conditions Check (Pre-flight validation)
    cursor.execute("SELECT global_status, email FROM contacts WHERE id = ?", (job['contact_id'],))
    contact = dict(cursor.fetchone())
    
    cursor.execute("SELECT current_lead_status FROM campaign_contacts WHERE id = ?", (job['campaign_contact_id'],))
    camp_contact_status = cursor.fetchone()[0]
    
    # Check global suppression list explicitly
    cursor.execute("SELECT email FROM global_suppression_list WHERE email = ?", (contact['email'],))
    is_suppressed = cursor.fetchone() is not None
    
    stop_statuses = ['suppressed', 'bounced', 'unsubscribed', 'replied']
    
    if contact['global_status'] in stop_statuses or camp_contact_status in stop_statuses or is_suppressed:
        print(f"[{OUTREACH_WORKER_MODE}] Skipping job {job['id']} - Contact is globally suppressed or has invalid status")
        cursor.execute("UPDATE outbox_jobs SET status = 'suppressed' WHERE id = ?", (job['id'],))
        conn.commit()
        return
        
    if not contact['email'] or '@' not in contact['email']:
        print(f"[{OUTREACH_WORKER_MODE}] Skipping job {job['id']} - Invalid email")
        cursor.execute("UPDATE outbox_jobs SET status = 'cancelled' WHERE id = ?", (job['id'],))
        conn.commit()
        return

    camp = get_campaign(job['campaign_id'])
    if not camp or camp.get('status') not in ['active', 'drafted']:
        print(f"[{OUTREACH_WORKER_MODE}] Skipping job {job['id']} - Campaign is not active")
        cursor.execute("UPDATE outbox_jobs SET status = 'cancelled' WHERE id = ?", (job['id'],))
        conn.commit()
        return


    # In dry-run, we simulate it
    if OUTREACH_WORKER_MODE == "outbox_dry_run":
        msg = f"[{datetime.now().strftime('%H:%M:%S')}] [DRY-RUN] Simulated JIT email generation and send to {contact['email']}"
        print(msg)
        if 'logs' not in camp: camp['logs'] = []
        camp['logs'].insert(0, msg)
        camp['logs'] = camp['logs'][:50] # Keep last 50
        save_campaign(camp)
        
        cursor.execute("UPDATE outbox_jobs SET status = 'simulated_sent', sent_at = ? WHERE id = ?", (datetime.now().isoformat(), job['id']))
        conn.commit()
        return

        
    # Real outbox live logic goes here later...

if __name__ == '__main__':
    import asyncio
    asyncio.run(run_outbox_worker())
