from __future__ import annotations
"""
ai_brain.py — The Intelligence Layer of Agent 1: The Prospector

This module wraps the Google Gemini Flash API and provides two core AI capabilities:
  1. generate_queries()       → Turns a plain-English goal into smart Google Maps queries
  2. extract_contact_info()   → Reads raw webpage text and extracts phone, email & lead quality
"""

import json
import time
import re
import asyncio
import google.generativeai as genai
import os
from agents.config import GEMINI_API_KEYS, GEMINI_MODEL, AI_REQUEST_DELAY_SECONDS, MAX_PAGE_TEXT_CHARS

class AllAIKeysExhaustedError(Exception):
    """Raised when all configured Gemini API keys have hit their daily/quota limits."""
    pass

# ── Dynamic Model Rotation ───────────────────────────────────────────────────
_active_key_index: int = 0
_model = None

def _get_active_model(key_index: int = None):
    """Configures and returns the Gemini model using the current active key."""
    global _active_key_index, _model
    if key_index is not None:
        _active_key_index = key_index
    
    if not GEMINI_API_KEYS:
        raise ValueError("No GEMINI_API_KEYS found in configuration.")
    
    # Wrap index to start over if we hit the end (circular)
    idx = _active_key_index % len(GEMINI_API_KEYS)
    current_key = GEMINI_API_KEYS[idx]
    
    genai.configure(api_key=current_key)
    _model = genai.GenerativeModel(GEMINI_MODEL)
    return _model, idx

# Initial configuration
_get_active_model(0)

# ── Internal rate-limiter state ────────────────────────────────────────────────
_last_request_time: float = 0.0
_api_lock = asyncio.Lock()
_ai_is_offline: bool = False  # True FailFast flag

async def call_gemini(prompt: str, files: list = None, log_callback=None) -> str:
    """
    Public wrapper for calling Gemini with automatic rate-limit throttling
    and smart ASYNC RETRY logic for 429 (Rate Limit) errors.
    """
    global _last_request_time, _active_key_index, _ai_is_offline
    
    if _ai_is_offline:
        raise AllAIKeysExhaustedError("❌ AI is offline due to previous quota exhaustion. Fast-failing.")
    
    # Resilient Mode: Wait for quota resets instead of failing fast.
    max_retries = 1
    retry_count = 0
    keys_tried_this_round = 0

    while retry_count < max_retries:
        async with _api_lock:
            # Serial throttling (polite delay)
            elapsed = time.time() - _last_request_time
            if elapsed < AI_REQUEST_DELAY_SECONDS:
                wait = AI_REQUEST_DELAY_SECONDS - elapsed
                await asyncio.sleep(wait)
            
            # Proactive rotation to distribute load evenly across all keys
            _active_key_index = (_active_key_index + 1) % len(GEMINI_API_KEYS)
            current_model, key_idx = _get_active_model(_active_key_index)
            
            # Update request time inside the lock before yielding
            _last_request_time = time.time()

        try:
            loop = asyncio.get_event_loop()

            content_parts = [prompt]
            if files:
                for file_path in files:
                    if os.path.exists(file_path):
                        ext = os.path.splitext(file_path)[1].lower()
                        mime_type = "application/pdf" if ext == ".pdf" else "image/jpeg"
                        with open(file_path, "rb") as f:
                            content_parts.append({
                                "mime_type": mime_type,
                                "data": f.read()
                            })

            # The SDK often hangs for 40-60 seconds on 429 Quota errors due to internal retries.
            # We enforce a strict timeout to fail fast, but 30 seconds allows large responses to finish.
            response = await asyncio.wait_for(
                loop.run_in_executor(None, current_model.generate_content, content_parts),
                timeout=30.0
            )
            keys_tried_this_round = 0  # Reset on success
            return response.text.strip()

        except Exception as e:
            error_msg = str(e).lower()
            is_quota_error = "429" in error_msg or "quota" in error_msg or "rate" in error_msg
            is_permission_error = "403" in error_msg or "permission" in error_msg
            is_timeout = isinstance(e, asyncio.TimeoutError) or "timeout" in error_msg
            
            if is_quota_error or is_permission_error or is_timeout:
                keys_tried_this_round += 1
                error_type = "Timeout/Hang" if is_timeout else ("Permission Denied" if is_permission_error else "Quota/RPM")

                # ── Try next key if we haven't cycled through all of them ──
                if keys_tried_this_round < len(GEMINI_API_KEYS):
                    next_key = (_active_key_index + 1) % len(GEMINI_API_KEYS)
                    status_rot = f"🔄 {error_type} on Key {key_idx+1}. Rotating to AI Key {next_key + 1}/{len(GEMINI_API_KEYS)}..."
                    if log_callback:
                        await log_callback(status_rot)
                    print(status_rot)
                    _last_request_time = 0.0
                    continue

                # ── All keys exhausted — instantly fail fast ──
                _ai_is_offline = True
                status_msg = f"❌ All {len(GEMINI_API_KEYS)} AI Keys exhausted. Falling back immediately..."
                print(status_msg)
                if log_callback:
                    await log_callback(status_msg)
                raise AllAIKeysExhaustedError(status_msg)
            else:
                raise e

    raise AllAIKeysExhaustedError(f"❌ AI Mission aborted after exhausting all {len(GEMINI_API_KEYS)} keys.")


from typing import Union, List, Dict

def parse_json_from_response(text: str) -> Union[dict, list]:
    """
    Robustly extract a JSON object or array from an LLM response,
    even if the model wraps it in markdown code fences.
    """
    # Strip ```json ... ``` or ``` ... ``` wrappers if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


# ── PUBLIC API ─────────────────────────────────────────────────────────────────

async def analyze_mission(goal: str, count: int = 5, log_callback=None) -> dict:
    """
    Given a plain-English prospecting goal, ask Gemini to act as a Geographic Intelligence Unit.
    Produces highly specific Google Maps queries, physical location/locale, 
    AND semantic constraints (e.g., must/must-not have a website).
    """
    prompt = f"""
You are an expert B2B lead generation specialist and a Geographic Intelligence Unit.
I have a prospecting goal: "{goal}"

Your task is to analyze this goal and return a raw JSON object containing the exact browser configuration 
needed to scrape Google Maps as if we were physically standing in the target location, {count} 
highly diverse search queries, AND any semantic constraints implied by the goal.

Constraints Logic:
- "website": 
    - "forbidden": Only if the goal explicitly asks for NO website/no presence.
    - "required": Only if the goal explicitly mentions "must have a website" or "with a website". Otherwise, treat it as "optional" so we don't lose potential leads.
    - "optional": Default.
- "email":
    - "gmail_only": If the goal mentions "gmail".
    - "required": If the goal mentions "with email", "contact info", or "message them".
    - "optional": Default.
- "phone": 
    - "required": If the goal mentions "with phone" or "contactable".
    - "whatsapp_only": If the goal mentions "whatsapp", "textable", or "mobile number".
    - "optional": Default.

Rules for the JSON:
1. "queries": Array of {count} highly specific Google Maps search queries in the local language.
2. "latitude": Float representing the geographical center of the target region.
3. "longitude": Float representing the geographical center.
4. "locale": The correct BCP-47 locale code (e.g., 'de-DE', 'es-ES').
5. "timezoneId": The IANA timezone ID (e.g., 'Europe/Berlin').
6. "constraints": Object with "website", "phone", "email" keys (phone values: "required", "whatsapp_only", "optional").
7. "audit_requirements": Array of strings if the goal implies checking website quality.
8. "target_location": String. The exact name of the city, region, or neighborhood extracted from the goal (e.g., "ibiza", "madrid", "brooklyn"). If no location is specified, return "".

Output ONLY the raw JSON object. No markdown, no explanation.

Example output:
{{
  "queries": ["vinyasa studio berlin", "ashtanga yoga mitte"],
  "latitude": 52.5200,
  "longitude": 13.4050,
  "locale": "de-DE",
  "timezoneId": "Europe/Berlin",
  "target_location": "berlin",
  "constraints": {{
    "website": "optional",
    "phone": "optional"
  }}
}}
"""
    print(f"🧠 AI: Deriving geographic intent and brainstorming {count} localized queries...")
    try:
        raw = await call_gemini(prompt, log_callback=log_callback)
        mission_data = parse_json_from_response(raw)
        if not isinstance(mission_data, dict) or "queries" not in mission_data:
            raise ValueError("Unexpected AI format")
        return mission_data
    except Exception as e:
        print(f"      ⚠️ AI Mission Brainstorming failed: {e}. Switching to direct search fallback.")
        if log_callback:
            await log_callback("⚠️ AI Offline. Switching to Raw Search Fallback...")
        # Hard fallback: return exactly what we need to keep the mission alive
        return {
            "queries": [goal],
            "latitude": None,
            "longitude": None,
            "locale": "en-US",
            "timezoneId": "UTC",
            "target_location": ""
        }


async def extract_contact_info(raw_text: str, business_name: str, audit_context: str = "", log_callback=None) -> dict:
    """
    Given the raw text content of a company website, ask Gemini to
    intelligently extract contact details and assess lead quality.
    Supports technical audit context for combined reporting.
    """
    truncated_text = raw_text[:MAX_PAGE_TEXT_CHARS]

    prompt = f"""
You are an expert data extraction agent specializing in lead generation.

Analyze the following raw text scraped from the website of a business called "{business_name}".
The text may include a section labeled [EMAILS FOUND IN PAGE] — those are real emails extracted directly
from the page's HTML. They are reliable. Prioritize them for the email field.

SCRAPED TEXT:
---
{truncated_text}
---

Your task — extract these exact fields:

1. "email": Find the primary contact email. 
   - FIRST check the [EMAILS FOUND IN PAGE] section if present — use the best one from there.
   - Then look for email patterns (anything with @) anywhere in the text.
   - Prefer: info@, contact@, hello@, hola@, studio@ over noreply@ or admin@.
   - Return "" ONLY if absolutely no email exists anywhere.

2. "phone": Find the best phone number. Prefer mobile (+34 6xx) for WhatsApp outreach.
   - Return ONLY the phone number digits/symbols. NOT dates, prices, or times.
   - Return "" if none found.

3. "is_good_lead": true if this is a real local business with at least some contact info,
   false if it's a directory, aggregator, or empty/dead page.

4. "notes": Write a single specific sentence (max 25 words) describing what this business does.
   - If I provided AUDIT CONTEXT below, incorporate those findings into the notes.
   - Example: "Family dental clinic in London specializing in Invisalign. [AUDIT]: Site loads in 12s and is not mobile-friendly."

AUDIT CONTEXT (IF ANY):
---
{audit_context}
---

Output ONLY a raw JSON object. No markdown, no explanation.

Example: {{"phone": "+34 612 345 678", "email": "info@example.com", "is_good_lead": true, "notes": "Premium yoga studio specializing in hot yoga and mindfulness retreats."}}
"""
    raw = await call_gemini(prompt, log_callback=log_callback)
    result = parse_json_from_response(raw)

    return {
        "phone":        str(result.get("phone", "") or ""),
        "email":        str(result.get("email", "") or ""),
        "is_good_lead": bool(result.get("is_good_lead", False)),
        "notes":        str(result.get("notes") or result.get("description") or "").replace('None', '').strip(),
    }


async def identify_best_website(serp_text: str, business_name: str, log_callback=None) -> str:
    """
    Given raw search engine results (titles/snippets), ask Gemini to
    pick the single most likely official website or contact page.
    """
    prompt = f"""
You are an expert lead researcher. I am looking for the official website of "{business_name}".
Below is the text from a search result page.

SEARCH RESULTS:
---
{serp_text[:4000]}
---

Your task:
1. Identify the single URL that is most likely the official home page, contact page, or 
   primary social media profile (Facebook/Instagram/LinkedIn) for "{business_name}".
2. Prioritize official domains (.com, .es, etc.) over directory sites (Yelp, Páginas Amarillas).
3. If multiple valid social profiles exist, pick the most active one (usually Facebook/Instagram for small trades).
4. If no clear match exists, return "".

Output ONLY the raw URL as a string. No markdown, no explanation.

Example output:
https://www.example.com
"""
    raw = await call_gemini(prompt, log_callback=log_callback)
    
    # Extract URL using simple regex or direct return
    url_match = re.search(r'(https?://\S+)', raw)
    if url_match:
        return url_match.group(1).split('"')[0].split("'")[0].strip()
    return ""
async def identify_contact_link(links: list[dict], business_name: str, log_callback=None) -> str:
    """
    Given a list of links (text and href) from a homepage, ask Gemini to
    pick the single one most likely to contain contact information (Email/Phone).
    This replaces hardcoded keywords and works in any language.

    Args:
        links: List of {"text": "...", "href": "..."} dicts
        business_name: Name of the business for context
    """
    if not links:
        return ""
        
    # Format links for the prompt
    links_str = "\n".join([f"- {l['text']} ({l['href']})" for l in links[:50]])

    prompt = f"""
You are an expert web navigation agent. I am looking for the contact information (Email/Phone) for "{business_name}".
Below is a list of links found on their homepage.

LINKS:
{links_str}

Your task:
1. Identify the single URL that is most likely to contain an email address, contact form, or phone number.
2. Look for patterns in ANY language (e.g., Contact, Impressum, Legal, About, Contacto, Kontakt, etc.).
3. Return ONLY the raw URL. If no link looks relevant, return "".

Example output:
https://www.example.com/contact
"""
    raw = await call_gemini(prompt, log_callback=log_callback)
    
    # Extract URL
    url_match = re.search(r'(https?://\S+)', raw)
    if url_match:
        return url_match.group(1).split('"')[0].split("'")[0].strip()
    
    # Fallback: if the AI returned a relative path, we'll try to find it in our original list
    raw_cleaned = raw.strip().lower()
    for l in links:
        if raw_cleaned in l['href'].lower() or raw_cleaned in l['text'].lower():
            return l['href']
            
    return ""
