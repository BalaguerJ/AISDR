from __future__ import annotations
"""
classifier.py — Agent 3: The Neural Intent Classifier

This module uses Gemini Flash to determine the human intent behind a reply,
extracting secondary contacts, follow-up dates, and urgency levels.
"""

from datetime import datetime
import json
from agents.db import db_conn
from agents.ai_brain import call_gemini, parse_json_from_response

async def run_classification_v2(inbound_message_id: int):
    """
    Calls the LLM to classify intent and updates the database with high-resolution metadata.
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sender, subject, body_clean 
            FROM inbound_messages WHERE id = ?
        ''', (inbound_message_id,))
        msg = cursor.fetchone()
        
        if not msg:
            return

        # ━━ NEURAL CLASSIFICATION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        intent_data = await classify_intent_with_ai(msg['sender'], msg['subject'], msg['body_clean'])
        
        # 80% Confidence Safety-Lock
        confidence = intent_data.get('intent_confidence', 0.5)
        requires_review = 1 if (intent_data.get('requires_human_review', False) or confidence < 0.8) else 0

        cursor.execute('''
            INSERT INTO classifications (
                inbound_message_id, intent_class, confidence, 
                suggested_action, processed_at, model_version
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            inbound_message_id, 
            intent_data.get('intent_label', 'unclear'),
            confidence,
            intent_data.get('recommended_action', 'human_review'),
            datetime.now().isoformat(),
            "gemini-1.5-flash"
        ))
        
        # Update high-resolution metadata in inbound_messages
        cursor.execute('''
            UPDATE inbound_messages 
            SET urgency = ?,
                requires_review = ?,
                extracted_entities_json = ?,
                reasoning_summary = ?,
                processing_status = 'classified'
            WHERE id = ?
        ''', (
            intent_data.get('urgency', 'medium'),
            requires_review,
            json.dumps(intent_data.get('extracted_entities_json', {})),
            intent_data.get('reasoning_summary', ''),
            inbound_message_id
        ))
        
        conn.commit()

async def classify_intent_with_ai(sender: str, subject: str, body: str) -> dict:
    """
    Prompts Gemini Flash with the 8-label SDR taxonomy and strict JSON contract.
    """
    prompt = f"""
You are an expert B2B SDR analyzing an inbound reply. Determine intent with surgical precision.

MESSAGE METADATA:
Sender: {sender} | Subject: {subject}

MESSAGE CONTENT:
---
{body}
---

Your task: Classify this reply and separate human intent from the recommended system action.

INTENT TAXONOMY:
1. `interested_now`: High-intent request for a call, demo, or immediate next step.
2. `interested_later`: Future interest (e.g., "Check back in Q3", "Ping me next month").
3. `needs_info`: Not a 'yes' yet; asking for pricing, case studies, or a deck first.
4. `wrong_person`: Lead is the wrong contact but may or may not provide a referral.
5. `referral`: Lead specifically provides a new person's name/email to contact.
6. `not_interested`: Rejection without anger ("Not for us", "Doesn't fit our current stack").
7. `objection`: Specific pushback (e.g., "We already use X", "Too expensive").
8. `unclear`: Ambiguous, administrative, or "Thanks" but no clear signal.

OUTPUT CONTRACT (RAW JSON ONLY):
{{
  "intent_label": "One of the 8 labels above",
  "intent_confidence": 0.xx (float),
  "urgency": "high", "medium", or "low",
  "recommended_action": "Concise next step",
  "requires_human_review": true/false (Set to true if ambiguous or emotional),
  "extracted_entities_json": {{
     "follow_up_date": "ISO-8601 when possible",
     "referral_name": "...",
     "referral_email": "...",
     "competitor_mentioned": "..."
  }},
  "reasoning_summary": "One sentence explaining why you chose this label"
}}
"""
    try:
        raw_response = await call_gemini(prompt)
        return parse_json_from_response(raw_response)
    except Exception as e:
        print(f"⚠️ Neural Classification failed: {e}")
        return {
            "intent_label": "unclear",
            "intent_confidence": 0.0,
            "recommended_action": "human_review",
            "requires_human_review": True
        }
