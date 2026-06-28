from __future__ import annotations
"""
router.py — Agent 3: The Deterministic Router

This module acts as the pre-LLM gatekeeper, handling clear-cut signals 
like Unsubscribes, Bounces, and OOO with hard-coded safety rules.
"""

import re
import sqlite3
import email.utils
from datetime import datetime
import json
from agents.db import db_conn

# HIGH-CONFIDENCE OPT-OUT PATTERNS
UNSUBSCRIBE_PATTERNS = [
    r"(?i)^unsubscribe$",
    r"(?i)^stop$",
    r"(?i)^remove me$",
    r"(?i)^do not contact$",
    r"(?i)^please remove$",
    r"(?i)^opt out$"
]

# BOUNCE PATTERNS — matched against body_clean OR subject
BOUNCE_PATTERNS = [
    r"(?i)delivery status notification",
    r"(?i)undeliverable",
    r"(?i)address not found",
    r"(?i)mailbox unavailable",
    r"(?i)mail system",           # Postfix/jellyfish: "This is the mail system at host"
    r"(?i)returned to sender",    # "Undelivered Mail Returned to Sender"
    r"(?i)delivery failure",
    r"(?i)failed to deliver",
    r"(?i)permanent fatal errors",
]

# BOUNCE SUBJECT PATTERNS — matched against subject line only
BOUNCE_SUBJECT_PATTERNS = [
    r"(?i)undelivered mail",
    r"(?i)returned to sender",
    r"(?i)delivery status",
    r"(?i)mail delivery failed",
    r"(?i)undeliverable",
    r"(?i)failure notice",
]

# NDR SENDER PATTERNS — automatic bounce signal from the envelope sender
NDR_SENDER_PATTERNS = [
    r"(?i)MAILER-DAEMON",
    r"(?i)postmaster@",
    r"(?i)Mail Delivery System",
]

def run_triage_v2(inbound_message_id: int):
    """
    Executes the deterministic triage rules first, then the intent-specific 
    workflow actions based on the neural classification.
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT i.id, i.sender, i.subject, i.body_clean, i.conversation_id, i.contact_id, 
                   i.processing_status, i.requires_review,
                   c.intent_class, c.confidence as intent_confidence
            FROM inbound_messages i
            LEFT JOIN classifications c ON c.id = (
                SELECT id FROM classifications WHERE inbound_message_id = i.id ORDER BY id DESC LIMIT 1
            )
            WHERE i.id = ?
        ''', (inbound_message_id,))
        msg = cursor.fetchone()
        
        if not msg:
            return

        # 1. CHECK FOR DETERMINISTIC SIGNALS (Highest Priority)
        # ─────────────────────────────────────────────────────────────────
        body = (msg['body_clean'] or '').strip()
        subject = (msg['subject'] or '')
        sender = (msg['sender'] or '')

        for pattern in UNSUBSCRIBE_PATTERNS:
            if re.match(pattern, body):
                handle_opt_out(msg, pattern, "explicit_unsubscribe_regex")
                return

        # Check NDR sender (MAILER-DAEMON, postmaster) — strongest bounce signal
        for pattern in NDR_SENDER_PATTERNS:
            if re.search(pattern, sender):
                handle_bounce(msg, pattern, "ndr_sender_detected")
                return

        # Check bounce subject patterns (NDR emails often have canonical subjects)
        for pattern in BOUNCE_SUBJECT_PATTERNS:
            if re.search(pattern, subject):
                handle_bounce(msg, pattern, "bounce_subject_detected")
                return

        # Check bounce body patterns
        for pattern in BOUNCE_PATTERNS:
            if re.search(pattern, body):
                handle_bounce(msg, pattern, "bounce_body_detected")
                return

        # 2. NEURAL ACTION MATRIX (Intent-Specific)
        # ─────────────────────────────────────────────────────────────────
        intent = msg['intent_class']
        confidence = msg['intent_confidence'] or 0.0
        
        # Matrix Logic:
        # - interested_now -> Pause + High Priority
        # - interested_later -> Pause + Follow-up
        # - needs_info -> Pause + Suggest Response
        # - referral/wrong_person -> Pause current + Review
        # - not_interested -> Global Suppression
        # - objection/unclear -> No Action unless Extreme Confidence
        
        if intent == 'interested_now':
            handle_positive_interest(msg, "immediate_pause")
        elif intent == 'interested_later':
            handle_deferred_interest(msg)
        elif intent == 'needs_info':
            handle_needs_info(msg)
        elif intent in ['wrong_person', 'referral']:
            handle_reassignment(msg)
        elif intent == 'not_interested':
            handle_opt_out(msg, "ai_detected_negative", "neural_rejection")
            return # handle_opt_out marks as resolved
        elif intent == 'objection':
            # Only pause if we are 95%+ sure, otherwise keep it running
            if confidence > 0.95:
                handle_positive_interest(msg, "objection_safety_pause")
        
        # 3. TRANSITION TO ACTIONED
        cursor.execute("UPDATE inbound_messages SET processing_status = 'actioned' WHERE id = ?", (inbound_message_id,))
        conn.commit()

def handle_positive_interest(msg: sqlite3.Row, rule_reason: str):
    """Pauses active outreach for this lead to prevent automated double-touches."""
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            UPDATE campaign_contacts 
            SET current_lead_status = 'paused', last_touch_at = ?
            WHERE lead_id = ?
        ''', (now, msg['contact_id']))
        
        metadata = {"intent": msg['intent_class'], "action": rule_reason, "confidence": msg['intent_confidence']}
        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, metadata_json, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (msg['conversation_id'], 'lead_interested', f'Targeted Pause: {rule_reason}', 
              json.dumps(metadata), now))
        conn.commit()
    print(f"🔥 Hot Lead Detected: {msg['sender']}. Status: {rule_reason}")

def handle_deferred_interest(msg: sqlite3.Row):
    """Pauses outreach and flags for future follow-up."""
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("UPDATE campaign_contacts SET current_lead_status = 'paused' WHERE lead_id = ?", (msg['contact_id'],))
        
        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (msg['conversation_id'], 'interest_deferred', 'Outreach paused: Lead requested follow-up later', now))
        conn.commit()

def handle_needs_info(msg: sqlite3.Row):
    """Slowing down automation to provide a specific information response."""
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        # We pause the automation so the human can provide the info manually
        cursor.execute("UPDATE campaign_contacts SET current_lead_status = 'paused' WHERE lead_id = ?", (msg['contact_id'],))
        
        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (msg['conversation_id'], 'info_requested', 'Automation paused: Lead requested more information', now))
        conn.commit()

def handle_reassignment(msg: sqlite3.Row):
    """Stopping current thread to handle referral or wrong person logic."""
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        # Global suppression of THIS email, but not the company
        cursor.execute("UPDATE contacts SET global_status = 'suppressed' WHERE email = ?", (msg['sender'],))
        cursor.execute("UPDATE campaign_contacts SET current_lead_status = 'stopped' WHERE lead_id = ?", (msg['contact_id'],))
        
        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (msg['conversation_id'], 'contact_reassigned', 'Outreach stopped: Lead provided referral or is wrong person', now))
        conn.commit()

def handle_opt_out(msg: sqlite3.Row, pattern: str, rule_name: str):
    """Executes the global suppression workflow."""
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT OR IGNORE INTO global_suppression_list (email, reason, added_at)
            VALUES (?, ?, ?)
        ''', (msg['sender'], f"Auto-suppressed via {rule_name}", now))
        
        cursor.execute("UPDATE contacts SET global_status = 'suppressed', suppression_reason = ? WHERE email = ?",
                       (f"Matched {rule_name}", msg['sender']))
        
        metadata = {"inbound_id": msg['id'], "pattern_matched": pattern, "rule": rule_name}
        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, metadata_json, rule_name, matched_pattern, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (msg['conversation_id'], 'auto_suppressed', 'Lead requested removal via clear opt-out signal', 
              json.dumps(metadata), rule_name, pattern, now))
        
        cursor.execute("UPDATE inbound_messages SET processing_status = 'resolved' WHERE id = ?", (msg['id'],))
        conn.commit()
    print(f"🛡️ Auto-Suppressed lead: {msg['sender']} (Rule: {rule_name})")

def _extract_bounced_email(body_raw: str, body_clean: str) -> str | None:
    """
    Parses the actual failed recipient email from an NDR/bounce body.
    Handles Postfix (jellyfish.systems), Google, and generic MTA formats.
    """
    # Strategy 1: Postfix style — <email>: host ... said:
    # e.g. <academiafernandatorrresi@gmail.com>: host gmail-smtp-in...
    m = re.search(r'<([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})>:\s*(?:host|user|The\s)', body_clean or '')
    if m:
        return m.group(1)

    # Strategy 2: Multiline <email> at start of line in body_clean
    m = re.search(r'^<([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})>', body_clean or '', re.MULTILINE)
    if m:
        return m.group(1)

    # Strategy 3: Search raw body for Final-Recipient header (RFC 3464)
    m = re.search(r'Final-Recipient:.*?rfc822;\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', body_raw or '', re.IGNORECASE)
    if m:
        return m.group(1)

    # Strategy 4: Any email in body that isn't our sending domain
    candidates = re.findall(r'<([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})>', body_clean or '')
    for email_addr in candidates:
        if 'utomis.com' not in email_addr and 'jellyfish' not in email_addr and 'privateemail' not in email_addr:
            return email_addr

    return None


def handle_bounce(msg: sqlite3.Row, pattern: str, rule_name: str):
    """Executes the bounce handling workflow.
    
    Critically: marks the actual BOUNCED recipient (parsed from the NDR body),
    NOT the MAILER-DAEMON sender address.
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # Extract the actual failed email from the NDR body
        body_raw = msg['body_raw'] if 'body_raw' in msg.keys() else ''
        body_clean = msg['body_clean'] or ''
        bounced_email = _extract_bounced_email(body_raw, body_clean)

        if bounced_email:
            print(f"📭 Bounce detected for: {bounced_email} (Rule: {rule_name})")
            cursor.execute(
                "UPDATE contacts SET global_status = 'bounced', suppression_reason = ? WHERE LOWER(email) = LOWER(?)",
                (f"Hard bounce: {rule_name}", bounced_email)
            )
            cursor.execute(
                "INSERT OR IGNORE INTO global_suppression_list (email, reason, added_at) VALUES (?, ?, ?)",
                (bounced_email, f"Hard bounce via {rule_name}", now)
            )
        else:
            print(f"⚠️  Bounce detected but could not extract recipient email. Rule: {rule_name}")

        cursor.execute('''
            INSERT INTO action_events (conversation_id, event_type, description, rule_name, matched_pattern, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (msg['conversation_id'], 'bounce_detected', 
              f'Hard bounce for {bounced_email or "unknown"} — {rule_name}', 
              rule_name, pattern, now))
        cursor.execute("UPDATE inbound_messages SET processing_status = 'resolved' WHERE id = ?", (msg['id'],))
        conn.commit()
