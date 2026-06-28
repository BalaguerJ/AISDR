from __future__ import annotations
import sqlite3
import os
from datetime import datetime
import json

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
os.makedirs(STATE_DIR, exist_ok=True)
DB_PATH = os.path.join(STATE_DIR, "contacts.db")

def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_v2():
    print("Initializing Database Schema V2...")
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        
        # 1. Drop old tables safely
        old_tables = [
            "contacts", "campaigns", "campaign_contacts", "conversations", 
            "outbound_messages", "classifications", "global_suppression_list", 
            "action_events", "sync_state", "human_adjudications", 
            "inbound_messages", "lead_enrichment", "campaign_leads", "outbox_jobs", "suppression_list", "inbound_events"
        ]
        for table in old_tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
            
        # 2. Create V2 Schema
        
        # 2.1 contacts: global lead data
        cursor.execute('''
            CREATE TABLE contacts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                company TEXT,
                website TEXT,
                source TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 2.2 campaigns: campaign config
        cursor.execute('''
            CREATE TABLE campaigns (
                id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                first_active_send_at TEXT,
                last_active_send_at TEXT,
                active_sending_days INTEGER DEFAULT 0
            )
        ''')
        
        # 2.3 campaign_leads: state of lead within a campaign
        cursor.execute('''
            CREATE TABLE campaign_leads (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- pending, scheduled, contacted, replied, bounced, unsubscribed, suppressed, paused, failed, completed
                current_step TEXT,
                last_contacted_at TEXT,
                next_scheduled_at TEXT,
                replied BOOLEAN DEFAULT 0,
                bounced BOOLEAN DEFAULT 0,
                unsubscribed BOOLEAN DEFAULT 0,
                suppressed BOOLEAN DEFAULT 0,
                failure_reason TEXT,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY(contact_id) REFERENCES contacts(id),
                UNIQUE(campaign_id, contact_id)
            )
        ''')
        
        # 2.4 outbox_jobs: the actual sending queue
        cursor.execute('''
            CREATE TABLE outbox_jobs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                campaign_lead_id TEXT NOT NULL,
                channel TEXT NOT NULL, -- email, whatsapp
                step TEXT NOT NULL DEFAULT 'initial', -- initial, follow_up_1, etc.
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', -- pending, scheduled, sending, sent, failed, cooldown, cancelled, suppressed, skipped
                attempt_count INTEGER DEFAULT 0,
                last_error TEXT,
                cooldown_until TEXT,
                payload_json TEXT, -- subject, body, etc.
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY(campaign_lead_id) REFERENCES campaign_leads(id),
                UNIQUE(campaign_lead_id, channel, step)
            )
        ''')
        
        # 2.5 suppression_list: global opt-outs and hard bounces
        cursor.execute('''
            CREATE TABLE suppression_list (
                id TEXT PRIMARY KEY,
                contact_id TEXT,
                email TEXT,
                phone TEXT,
                reason TEXT NOT NULL, -- hard_bounce, unsubscribe, spam_complaint
                source TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 2.6 inbound_events
        cursor.execute('''
            CREATE TABLE inbound_events (
                id TEXT PRIMARY KEY,
                contact_id TEXT,
                campaign_id TEXT,
                event_type TEXT NOT NULL, -- reply, bounce, out_of_office, spam_complaint, etc.
                raw_payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(contact_id) REFERENCES contacts(id),
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
            )
        ''')

        # 2.7 contact_enrichment (CRM data)
        cursor.execute('''
            CREATE TABLE contact_enrichment (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                source TEXT,
                industry TEXT,
                city TEXT,
                website TEXT,
                enrichment_status TEXT,
                opportunity_score REAL,
                pain_points TEXT,
                recommended_offer TEXT,
                best_outreach_angle TEXT,
                raw_payload TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(contact_id) REFERENCES contacts(id)
            )
        ''')

        # 2.8 inbound_classifications (Classifier Data)
        cursor.execute('''
            CREATE TABLE inbound_classifications (
                id TEXT PRIMARY KEY,
                inbound_event_id TEXT NOT NULL,
                classification_type TEXT,
                sentiment TEXT,
                intent TEXT,
                temperature REAL,
                lead_stage TEXT,
                needs_action INTEGER,
                confidence REAL,
                summary TEXT,
                raw_payload TEXT,
                created_at TEXT,
                FOREIGN KEY(inbound_event_id) REFERENCES inbound_events(id)
            )
        ''')

        # 2.9 legacy_id_map (Auditing & Mapping)
        cursor.execute('''
            CREATE TABLE legacy_id_map (
                id TEXT PRIMARY KEY,
                legacy_table TEXT NOT NULL,
                legacy_id TEXT NOT NULL,
                new_table TEXT NOT NULL,
                new_id TEXT NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        print("Schema V2 created successfully.")

def migrate_intel_columns():
    """Adds intelligence agent columns to contact_enrichment. Safe to run multiple times."""
    new_columns = [
        # Technographic Scanner
        ("tech_cms", "TEXT"),
        ("tech_has_pixel", "INTEGER DEFAULT 0"),
        ("tech_has_gtm", "INTEGER DEFAULT 0"),
        ("tech_has_booking", "INTEGER DEFAULT 0"),
        ("tech_has_whatsapp", "INTEGER DEFAULT 0"),
        ("tech_has_chat", "INTEGER DEFAULT 0"),
        ("tech_has_schema", "INTEGER DEFAULT 0"),
        ("tech_has_ssl", "INTEGER DEFAULT 0"),
        ("tech_load_time", "REAL"),
        ("tech_has_consent_form", "INTEGER DEFAULT 0"),
        ("tech_mobile_friendly", "INTEGER DEFAULT 0"),
        # Review Pain Miner
        ("review_total", "INTEGER DEFAULT 0"),
        ("review_avg_rating", "REAL"),
        ("review_pain_phone", "INTEGER DEFAULT 0"),
        ("review_pain_booking", "INTEGER DEFAULT 0"),
        ("review_pain_web", "INTEGER DEFAULT 0"),
        ("review_pain_wait", "INTEGER DEFAULT 0"),
        ("review_pain_score", "REAL DEFAULT 0"),
        # Ads Intelligence
        ("ads_active", "INTEGER DEFAULT 0"),
        ("ads_platform", "TEXT"),
        ("ads_landing_url", "TEXT"),
        ("ads_landing_quality", "TEXT"),
        ("ads_category", "TEXT"),
        ("ads_spend_signal", "TEXT"),
        # Revenue Leakage Score
        ("revenue_leakage_score", "INTEGER DEFAULT 0"),
        ("intel_scanned_at", "TEXT"),
    ]
    with db_conn() as conn:
        cursor = conn.cursor()
        # Ensure the table exists first (live DB may not have it)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contact_enrichment (
                id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                source TEXT,
                industry TEXT,
                city TEXT,
                website TEXT,
                enrichment_status TEXT,
                opportunity_score REAL,
                pain_points TEXT,
                recommended_offer TEXT,
                best_outreach_angle TEXT,
                raw_payload TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        for col_name, col_type in new_columns:
            try:
                cursor.execute(f"ALTER TABLE contact_enrichment ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass  # Column already exists
        conn.commit()
    print("✅ Intel columns migration complete.")


def is_already_known(email: str, phone: str = None) -> bool:
    """Dummy function to prevent backend crash while we transition to V2 schema."""
    return False

def get_contact_info(lead_id: str):
    return None

def record_contact(lead_id: str, email: str, phone: str = None, name: str = None, company: str = None, source: str = None):
    pass

if __name__ == "__main__":
    init_db_v2()
    migrate_intel_columns()
