from __future__ import annotations
from typing import Any
import json
import email.utils
from datetime import datetime, timedelta
from agents.db import db_conn

CONFIDENCE_THRESHOLD = 0.85

def run_matching_v2(inbound_message_id: int):
    """
    Executes the 3-tier matching pipeline for an inbound message.
    Updates DB with match metadata and processing status.
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sender, subject, rfc_message_id, in_reply_to, references_header 
            FROM inbound_messages WHERE id = ?
        ''', (inbound_message_id,))
        msg = cursor.fetchone()
        if not msg:
            return

        # ━━ MATCHING STACK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1. Clean the sender email address for lookup
        _, clean_email = email.utils.parseaddr(msg['sender'])
        
        result = perform_tiered_match(msg, clean_email)
        
        # ━━ QUARANTINE LOGIC ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        status = 'matched'
        quarantine_reason = None
        
        if not result['conversation_id']:
            status = 'quarantined'
            quarantine_reason = 'no_match'
        elif result['match_confidence'] < CONFIDENCE_THRESHOLD:
            status = 'quarantined'
            quarantine_reason = 'weak_match'
        # Conflicting match logic could be added here if multiple candidates are found
        
        cursor.execute('''
            UPDATE inbound_messages 
            SET conversation_id = ?, contact_id = ?, 
                match_confidence = ?, match_reasons = ?, matched_by_rule = ?,
                quarantine_reason = ?, processing_status = ?
            WHERE id = ?
        ''', (
            result['conversation_id'], result['contact_id'],
            result['match_confidence'], json.dumps(result['match_reasons']), 
            result['matched_by_rule'], quarantine_reason, status, inbound_message_id
        ))
        conn.commit()

def perform_tiered_match(msg: Any, clean_email: str) -> dict:
    """Primary 3-tier matching engine."""
    res = {
        "conversation_id": None,
        "contact_id": None,
        "match_confidence": 0.0,
        "match_reasons": [],
        "matched_by_rule": None
    }
    
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # TIER 1: RFC/Provider Header Match (High Confidence)
        if msg['in_reply_to']:
            cursor.execute("SELECT conversation_id, contact_id FROM outbound_messages WHERE rfc_message_id = ?", (msg['in_reply_to'],))
            row = cursor.fetchone()
            if row:
                res.update({
                    "conversation_id": row['conversation_id'],
                    "contact_id": row['contact_id'],
                    "match_confidence": 0.98,
                    "match_reasons": ["Tier 1: Direct RFC In-Reply-To match"],
                    "matched_by_rule": "rfc_direct"
                })
                return res

        # TIER 2: Contextual Continuity (Medium-High Confidence)
        # Search for active campaign contacts from this sender in the last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        cursor.execute('''
            SELECT cc.campaign_id, cc.lead_id, c.id as conv_id
            FROM campaign_contacts cc
            JOIN contacts con ON cc.lead_id = con.id
            JOIN conversations c ON c.lead_id = con.id AND c.campaign_id = cc.campaign_id
            WHERE con.email = ? AND cc.last_touch_at > ?
            ORDER BY cc.last_touch_at DESC LIMIT 1
        ''', (clean_email, thirty_days_ago))
        
        row = cursor.fetchone()
        if row:
            res.update({
                "conversation_id": row['conv_id'],
                "contact_id": row['lead_id'],
                "match_confidence": 0.88,
                "match_reasons": ["Tier 2: Strong participant + active campaign window continuity"],
                "matched_by_rule": "contextual_continuity"
            })
            return res

        # TIER 3: Subject Fallback (Weak Confidence)
        sub_raw = msg['subject'] or ""
        sub_clean = sub_raw.lower().replace("re:", "").strip()
        cursor.execute('''
            SELECT m.conversation_id, m.contact_id 
            FROM outbound_messages m
            JOIN contacts c ON m.contact_id = c.id
            WHERE c.email = ? AND LOWER(m.subject) LIKE ?
            ORDER BY m.sent_at DESC LIMIT 1
        ''', (clean_email, f"%{sub_clean}%"))
        
        row = cursor.fetchone()
        if row:
            res.update({
                "conversation_id": row['conversation_id'],
                "contact_id": row['contact_id'],
                "match_confidence": 0.65,
                "match_reasons": ["Tier 3: Weak subject keyword similarity fallback"],
                "matched_by_rule": "heuristic_subject"
            })
            return res
            
    return res
