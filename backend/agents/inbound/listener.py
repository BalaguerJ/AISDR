from __future__ import annotations
"""
listener.py — Agent 3: The Durable Inbound Listener

This module implements a persistent IMAP poller with durable checkpointing,
layered idempotency (Provider ID -> RFC ID -> Hash), and automatic 
UIDVALIDITY recovery.
"""

import os
import imaplib
import email
import hashlib
import json
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Internal imports
from agents.db import DB_PATH, db_conn

# Configuration
IMAP_SERVER = os.getenv("IMAP_SERVER", "mail.privateemail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("GMAIL_USER")
IMAP_PASS = os.getenv("GMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")

async def poll_inbox_durable(mailbox: str = "INBOX"):
    """
    Performs a durable poll of the specified mailbox.
    Handles UIDVALIDITY changes with a bounded 24-hour rescan.
    """
    if not IMAP_USER or not IMAP_PASS:
        print("⚠️ IMAP credentials not configured. Skipping listener.")
        return 0

    try:
        # 1. Connect and Authenticate
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select(mailbox)

        # 2. Get Mailbox Identity (UIDVALIDITY)
        res, data = mail.status(mailbox, '(UIDVALIDITY UIDNEXT)')
        # Data format: [b'INBOX (UIDVALIDITY 123456789 UIDNEXT 42)']
        status_raw = data[0].decode()
        current_validity = int(status_raw.split('UIDVALIDITY ')[1].split(' ')[0].replace(')', ''))
        
        # 3. Retrieve Sync State
        last_uid = 0
        with db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT uid_validity, last_uid FROM sync_state WHERE mailbox_id = ?", (mailbox,))
            row = cursor.fetchone()
            
            if row:
                stored_validity, last_uid = row['uid_validity'], row['last_uid']
                if stored_validity != current_validity:
                    print(f"⚠️ UIDVALIDITY Change Detected ({stored_validity} -> {current_validity}). Triggering 24h recovery.")
                    # Trigger bounded recovery (last 24h)
                    await run_rescan_recovery(mail, mailbox, current_validity)
                    # We continue from the current UIDNEXT to resume normal polling
            else:
                # First time: Initialize sync state
                cursor.execute("INSERT INTO sync_state (mailbox_id, uid_validity, last_uid) VALUES (?, ?, ?)",
                               (mailbox, current_validity, 0))
                conn.commit()

        # 4. Search for New Messages (UID > last_uid)
        search_criteria = f"UID {last_uid + 1}:*" if last_uid > 0 else "ALL"
        res, data = mail.uid('search', None, search_criteria)
        uids = data[0].split()

        new_checkpoint = last_uid
        for uid_bytes in uids:
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue
            
            # Fetch message
            res, msg_data = mail.uid('fetch', uid_bytes, '(RFC822)')
            raw_email = msg_data[0][1]
            
            # 5. Process with Layered Idempotency
            success = await process_inbound_message(raw_email, provider_id=str(uid), mailbox=mailbox)
            
            if success:
                new_checkpoint = max(new_checkpoint, uid)

        # 6. Final Checkpoint Update
        with db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sync_state SET last_uid = ?, last_sync_at = ? WHERE mailbox_id = ?",
                           (new_checkpoint, datetime.now().isoformat(), mailbox))
            conn.commit()

        mail.logout()
        return len(uids)

    except Exception as e:
        print(f"❌ Listener Error: {str(e)}")
        return 0

async def process_inbound_message(raw_email_bytes: bytes, provider_id: str, mailbox: str) -> bool:
    """
    Ingests an inbound message using the Layered Idempotency Shield.
    1. Provider ID (UID)
    2. RFC Message-ID
    3. Payload Hash Fallback
    """
    from email.header import decode_header
    def decode_mime_header(header_value):
        if not header_value: return ""
        try:
            decoded_parts = decode_header(header_value)
            result = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    result += part.decode(encoding or 'utf-8', errors='replace')
                else:
                    result += part
            return result.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
        except Exception:
            return header_value

    msg = email.message_from_bytes(raw_email_bytes)
    rfc_id = msg.get("Message-ID")
    in_reply_to = msg.get("In-Reply-To")
    references = msg.get("References")
    payload_hash = hashlib.sha256(raw_email_bytes).hexdigest()
    
    clean_sender = decode_mime_header(msg.get("From"))
    clean_subject = decode_mime_header(msg.get("Subject"))
    
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # Layer 1 & 2: ID Check
        cursor.execute("SELECT id FROM inbound_messages WHERE provider_message_id = ? OR rfc_message_id = ?", (provider_id, rfc_id))
        if cursor.fetchone():
            return True # Already processed
            
        # Layer 3: Payload Hash Check
        cursor.execute("SELECT id FROM inbound_messages WHERE payload_hash = ?", (payload_hash,))
        if cursor.fetchone():
            return True # Duplicate content

        # Save to Archive (Durable Ingestion)
        # Note: Normalizer will update the body fields later in the pipeline
        try:
            cursor.execute('''
                INSERT INTO inbound_messages (
                    provider_message_id, rfc_message_id, in_reply_to, references_header,
                    payload_hash, received_at, sender, subject, body_raw, processing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                provider_id, rfc_id, in_reply_to, references,
                payload_hash, datetime.now().isoformat(), clean_sender, clean_subject, 
                raw_email_bytes.decode('utf-8', errors='replace'), 'received'
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return True # Race condition duplicate

async def run_rescan_recovery(mail: imaplib.IMAP4, mailbox: str, new_validity: int):
    """
    Emergency 24-hour fallback rescan when UIDVALIDITY changes.
    Uses strict idempotency to avoid double-processing.
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
    res, data = mail.uid('search', None, f'(SINCE "{yesterday}")')
    uids = data[0].split()
    
    for uid_bytes in uids:
        res, msg_data = mail.uid('fetch', uid_bytes, '(RFC822)')
        await process_inbound_message(msg_data[0][1], provider_id=f"recov_{uid_bytes.decode()}", mailbox=mailbox)
    
    # Update validity in state
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sync_state SET uid_validity = ?, last_uid = 0 WHERE mailbox_id = ?",
                       (new_validity, mailbox))
        conn.commit()
