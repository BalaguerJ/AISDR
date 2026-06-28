from __future__ import annotations
"""
sync_json_to_db.py — Agent 2 & 3: Persistence Bridge

This surgical utility synchronizes historical campaign JSON data into the 
SQLite database (contacts.db). This ensures Agent 3 can correctly match 
inbound replies to previous outbound campaign history.
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# Fix path to db
DB_PATH = Path(__file__).parent.parent / "state" / "contacts.db"
CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"

def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sync_all_campaigns():
    print("🧠 Starting Neural Ledger Restoration (JSON -> DB)...")
    
    conn = get_db_conn()
    cursor = conn.cursor()
    
    # 1. Ensure versioning
    cursor.execute("PRAGMA user_version = 5")
    
    campaign_files = list(CAMPAIGNS_DIR.glob("*.json"))
    print(f"📂 Found {len(campaign_files)} campaign persistence files.")
    
    restored_outbound = 0
    restored_contacts = 0
    
    for f_path in campaign_files:
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                camp = json.load(f)
            
            # 1. Sync Campaign Entry
            cursor.execute('''
                INSERT OR IGNORE INTO campaigns (id, csv_source, pitch, created_at, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (camp["id"], camp.get("csv_source", "unknown"), camp.get("pitch", ""), camp.get("created_at"), camp["status"]))
            
            # 2. Sync Leads (Contacts & Outbound)
            for lead in camp.get("leads", []):
                # Ensure Contact exists
                cursor.execute("SELECT id FROM contacts WHERE email = ?", (lead["email"],))
                row = cursor.fetchone()
                if row:
                    contact_id = row["id"]
                else:
                    cursor.execute("INSERT INTO contacts (email, name, phone) VALUES (?, ?, ?)",
                                   (lead["email"], lead["name"], lead.get("phone", "")))
                    contact_id = cursor.lastrowid
                    restored_contacts += 1
                
                # 3. Sync Campaign Contact (Durable Tier 2 context)
                cursor.execute('''
                    INSERT OR IGNORE INTO campaign_contacts (campaign_id, lead_id, current_lead_status, last_touch_at)
                    VALUES (?, ?, ?, ?)
                ''', (camp["id"], contact_id, lead["status"], lead.get("sent_at")))
                
                # 4. Handle Conversation & Outbound Entry
                if lead.get("status") == "sent":
                    # Create stable conversation ID or regenerate
                    conv_id = f"conv_{hash(camp['id'] + lead['email'] + 'legacy') % 10**12}"
                    cursor.execute('''
                        INSERT OR IGNORE INTO conversations (id, lead_id, campaign_id, channel, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (conv_id, contact_id, camp["id"], 'email', lead.get("sent_at"), lead.get("sent_at")))
                    
                    # Store Outbound Record
                    # We use a stable ID for re-runs
                    outbound_id = f"out_{hash(camp['id'] + lead['email']) % 10**12}"
                    
                    # Matcher expects rfc_message_id for Tier 1
                    # Matcher expects subject for Tier 3
                    cursor.execute('''
                        INSERT OR IGNORE INTO outbound_messages (id, conversation_id, contact_id, campaign_id, channel, subject, rfc_message_id, status, sent_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        outbound_id, conv_id, contact_id, camp["id"], 'email', 
                        lead.get("draft_subject", "No Subject"), 
                        lead.get("rfc_message_id"), 
                        'sent', lead.get("sent_at")
                    ))
                    if cursor.rowcount > 0:
                        restored_outbound += 1
            
            conn.commit()
        except Exception as e:
            print(f"💥 Failed to sync campaign {f_path.name}: {str(e)}")

    conn.close()
    print(f"🎬 Neural Restoration Complete.")
    print(f"✅ Restored {restored_contacts} Contacts.")
    print(f"✅ Restored {restored_outbound} Outbound Persistence Records.")

if __name__ == "__main__":
    sync_all_campaigns()
