from __future__ import annotations
import re
from typing import Dict, Any, Optional
import email
from email import policy
import sqlite3
from agents.db import db_conn

def run_normalization_v2(inbound_message_id: int):
    """
    Executes the 4-stage normalization pipeline for a specific inbound message.
    Stages: Raw -> Parsed -> Stripped -> Clean.
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT body_raw FROM inbound_messages WHERE id = ?", (inbound_message_id,))
        row = cursor.fetchone()
        if not row or not row['body_raw']:
            return

        raw_body = row['body_raw']
        
        # STAGE 2: Parsed (MIME Extraction)
        parsed_body = parse_mime_text(raw_body)
        
        # STAGE 3: Stripped (History/Quote Removal)
        stripped_body = strip_quote_history(parsed_body)
        
        # STAGE 4: Clean (Signatures/Boilerplate Removal)
        clean_body = clean_boilerplate(stripped_body)
        
        cursor.execute('''
            UPDATE inbound_messages 
            SET body_parsed = ?, body_stripped = ?, body_clean = ?, processing_status = 'normalized'
            WHERE id = ?
        ''', (parsed_body, stripped_body, clean_body, inbound_message_id))
        conn.commit()

def parse_mime_text(raw_email_str: str) -> str:
    """Stage 2: Extracts the most relevant text/plain content from a raw MIME string."""
    try:
        msg = email.message_from_string(raw_email_str, policy=policy.default)
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    body = part.get_payload(decode=True).decode(errors='replace')
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors='replace')
            
        return body.strip()
    except Exception:
        return raw_email_str # Fallback

def strip_quote_history(text: str) -> str:
    """Stage 3: Removes common email quote patterns (On... wrote, > lines)."""
    # 1. Split on common horizontal "Original Message" delimiters
    delimiters = [
        r"(?i)^-----Original Message-----",
        r"(?i)^From: ",
        r"(?i)^On .* wrote:$",
        r"(?i)^_+$", # Long underscores
    ]
    
    lines = text.splitlines()
    stripped_lines = []
    
    for line in lines:
        # Stop processing if we hit an common outbound history marker
        if any(re.match(d, line.strip()) for d in delimiters):
            break
        # Skip lines starting with quote markers
        if line.strip().startswith(">"):
            continue
        stripped_lines.append(line)
        
    return "\n".join(stripped_lines).strip()

def clean_boilerplate(text: str) -> str:
    """Stage 4: Removes common signatures and SDR-specific boilerplate."""
    # 1. Look for signature delimiter "-- "
    if "-- \n" in text:
        text = text.split("-- \n")[0]
    elif "--\n" in text:
        text = text.split("--\n")[0]
        
    # 2. Heuristic: Remove anything after common sign-offs if they appear near the end
    sign_offs = [r"Best regards,", r"Kind regards,", r"Best,", r"Thanks,", r"Sincerely,"]
    lines = text.splitlines()
    if len(lines) > 2:
        for i in range(len(lines)-1, max(-1, len(lines)-5), -1):
            if any(re.match(s, lines[i].strip(), re.I) for s in sign_offs):
                return "\n".join(lines[:i]).strip()

    return text.strip()
