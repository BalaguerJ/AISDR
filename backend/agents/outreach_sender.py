from __future__ import annotations
"""
outreach_sender.py — Agent 2: The Outreach Executioner

This module handles the low-level delivery of messages to Gmail (and eventually WhatsApp).
It implements the three layers of protection:
1. Daily Caps (Safety Floors)
2. Intelligent Delay (Mimicking Human behavior)
3. Drip Scheduling (Distributed delivery)
"""

import os
import random
import asyncio
import logging
import ssl
from datetime import datetime
from email.message import EmailMessage
import aiosmtplib
import httpx
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=env_path)

# HARD CEILING — Emergency cap only. The user's panel setting is the real daily limit.
# This only kicks in to prevent accidental runaway sends (e.g. a bug sending 10,000 emails).
MAX_DAILY_EMAIL = 500
MAX_DAILY_WHATSAPP = 100

# SMTP Settings
SMTP_SERVER = os.getenv("SMTP_SERVER", "mail.privateemail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

def get_smtp_credentials():
    """Dynamically fetch credentials to ensure .env changes are picked up."""
    user = os.getenv("GMAIL_USER")
    # Support both GMAIL_PASSWORD and GMAIL_APP_PASSWORD for flexibility
    pw = os.getenv("GMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    return user, pw

# WhatsApp Business API Settings
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WA_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

# DELAY STYLE PRESETS (Seconds) — Maps to UI Mode selector
DELAY_PRESETS = {
    "conservative": (600, 1200),  # 10–20 min gaps (Cauteloso — maximum reputation safety)
    "standard":     (240, 720),   # 4–12 min gaps  (Estándar  — recommended for cold email)
    "aggressive":   (60, 180),    # 1–3 min gaps   (Agresivo  — faster, slightly riskier)
}

async def send_gmail_human_like(
    to_email: str, 
    subject: str, 
    body: str, 
    delay_style: str = "standard",
    time_jitter: bool = False,
    signature_jitter: bool = False,
    sender_name: str = "",
    log_callback=None
):
    """
    Sends a single email with a human-like delay injection BEFORE sending.
    Returns: dict with {'success': bool, 'message_id': str, 'error': str}
    """
    user, pw = get_smtp_credentials()
    if not user or not pw:
        raise ValueError("GMAIL_USER or GMAIL_PASSWORD not configured correctly in .env")

    # The delay has been moved to the main campaign loop to avoid redundancy.

    # Layer 2.5: Signature Jitter
    if signature_jitter:
        body_lower = body.lower()
        es_score = sum(body_lower.count(w) for w in [" el ", " la ", " de ", " que ", " y ", " en ", " un ", " hola "])
        en_score = sum(body_lower.count(w) for w in [" the ", " and ", " of ", " to ", " a ", " in ", " hi ", " hello "])
        
        if es_score >= en_score:
            sign_offs = ["Un saludo,", "Saludos,", "Abrazos,", "Quedo a la espera,", "Gracias,", "Un abrazo,", "Cualquier cosa me dices,"]
        else:
            sign_offs = ["Best,", "Regards,", "Best regards,", "Warmly,", "Thanks again,", "Talk soon,"]
            
        sign_off = random.choice(sign_offs)
        signature = f"\n\n{sign_off}"
        if sender_name:
            signature += f"\n{sender_name}"
            
        if "\n\n" in body:
            parts = body.rsplit("\n\n", 1)
            body = parts[0] + signature + "\n" + (parts[1] if len(parts) > 1 else "")
        else:
            body += signature

    # Prepare Message
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    
    # Generate an explicit Message-ID if not present (best for traceability)
    from email.utils import make_msgid
    rfc_id = make_msgid(domain=SMTP_SERVER)
    msg["Message-ID"] = rfc_id
    
    msg.set_content(body)

    # Layer 3: The actual send
    try:
        if log_callback:
            await log_callback(f"📧 Connecting to SMTP Layer: {SMTP_SERVER}:{SMTP_PORT}...")
            
        # Create a relaxed SSL context for macOS compatibility with Namecheap certs
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        await aiosmtplib.send(
            msg,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            use_tls=(SMTP_PORT == 465),
            username=user,
            password=pw,
            tls_context=context if (SMTP_PORT == 465) else None
        )
        
        if log_callback:
            await log_callback(f"✅ Email successfully delivered to {to_email}")
        return {"success": True, "message_id": rfc_id, "error": None}
        
    except Exception as e:
        error_msg = str(e)
        if log_callback:
            await log_callback(f"❌ SMTP Error while sending to {to_email}: {error_msg}")
        return {"success": False, "message_id": None, "error": error_msg}


async def send_gmail_reply(
    to_email: str,
    subject: str,
    body: str,
    in_reply_to: str = None,
    references: str = None,
    sender_name: str = "",
) -> dict:
    """
    Sends a reply email with proper threading headers (In-Reply-To + References).
    Ensures the reply appears as a thread in Gmail, not a new conversation.
    """
    user, pw = get_smtp_credentials()
    if not user or not pw:
        return {"success": False, "message_id": None, "error": "SMTP credentials not configured"}

    from email.utils import make_msgid
    msg = EmailMessage()
    display_name = sender_name if sender_name else user
    msg["From"] = f"{display_name} <{user}>"
    msg["To"] = to_email
    
    # Ensure subject has Re: prefix for threading and sanitize newlines
    safe_subject = subject.replace('\n', ' ').replace('\r', '').strip()
    msg["Subject"] = safe_subject if safe_subject.lower().startswith("re:") else f"Re: {safe_subject}"

    rfc_id = make_msgid(domain=SMTP_SERVER)
    msg["Message-ID"] = rfc_id

    # Threading headers — critical for Gmail to group as a thread
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        # References should include all previous message IDs in the chain
        existing_refs = references or ""
        msg["References"] = f"{existing_refs} {in_reply_to}".strip()

    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        await aiosmtplib.send(
            msg,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            use_tls=(SMTP_PORT == 465),
            username=user,
            password=pw,
            tls_context=context if (SMTP_PORT == 465) else None
        )
        return {"success": True, "message_id": rfc_id, "error": None}
    except Exception as e:
        return {"success": False, "message_id": None, "error": str(e)}

async def send_whatsapp_human_like(
    to_phone: str, 
    body: str, 
    delay_style: str = "standard",
    time_jitter: bool = False,
    signature_jitter: bool = False,
    sender_name: str = "",
    log_callback=None
):
    """
    Sends a single WhatsApp message via Meta Graph API with a human-like delay injection BEFORE sending.
    """
    # No longer using Meta API, routing to local Node.js gateway.
    # Clean the phone number (must be international format without +)
    clean_phone = "".join(filter(str.isdigit, to_phone))
    if not clean_phone:
         if log_callback:
            await log_callback(f"⚠️ Invalid phone number format: {to_phone}")
         return False

    # Delay logic moved to main campaign loop

    # Layer 3: The actual send via local OpenWA Gateway (whatsapp-web.js)
    url = "http://localhost:3001/send"
    payload = {
        "phone": clean_phone,
        "message": body
    }

    try:
        if log_callback:
            await log_callback(f"💬 Sending WhatsApp message to +{clean_phone} via Local Gateway...")
            
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30.0)
            
        if resp.status_code in [200, 201]:
            if log_callback:
                await log_callback(f"✅ WhatsApp successfully delivered to +{clean_phone}")
            return True
        else:
            if log_callback:
                await log_callback(f"❌ Failed to reach +{clean_phone} via gateway: {resp.text}")
            return False
            
    except Exception as e:
        if log_callback:
            await log_callback(f"❌ WhatsApp API Error: {str(e)}")
        return False
