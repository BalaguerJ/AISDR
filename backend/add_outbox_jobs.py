import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "state", "contacts.db")

def add_outbox_jobs():
    print(f"Connecting to {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outbox_jobs (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            campaign_lead_id TEXT NOT NULL,
            contact_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            step TEXT NOT NULL DEFAULT 'initial',
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- pending, scheduled, locked, sending, sent, failed, cancelled, suppressed, cooldown, failed_retryable
            attempt_count INTEGER DEFAULT 0,
            last_error TEXT,
            locked_at TEXT,
            locked_by TEXT,
            lock_expires_at TEXT,
            sent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(campaign_id, campaign_lead_id, channel, step)
        )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_jobs(status, scheduled_at)")
    
    conn.commit()
    conn.close()
    print("Table outbox_jobs created successfully.")

if __name__ == "__main__":
    add_outbox_jobs()
