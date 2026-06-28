import sqlite3
import os
DB_PATH = os.path.join(os.path.dirname(__file__), "state", "contacts.db")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("DROP TABLE IF EXISTS outbox_jobs")
c.execute('''
    CREATE TABLE outbox_jobs (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        campaign_contact_id INTEGER NOT NULL,
        contact_id INTEGER NOT NULL,
        channel TEXT NOT NULL,
        step TEXT NOT NULL DEFAULT 'initial',
        scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER DEFAULT 0,
        last_error TEXT,
        locked_at TEXT,
        locked_by TEXT,
        lock_expires_at TEXT,
        sent_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(campaign_id, campaign_contact_id, channel, step)
    )
''')
c.execute("CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_jobs(status, scheduled_at)")
conn.commit()
print("Table recreated.")
