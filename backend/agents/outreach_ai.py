from __future__ import annotations
"""
outreach_ai.py — The Generative Outreach Layer (Agent 2)

This module is responsible for reading the scraped data of a single lead (name, category, 
ai_notes, website) and crafting a hyper-personalized, non-spammy cold email using a 
provided base pitch. 
"""

import json
import re
import asyncio
from agents.ai_brain import call_gemini, parse_json_from_response

async def generate_cold_email(lead: dict, pitch: str, context_files: list = None, log_callback=None) -> dict:
    """
    Takes a single lead and a general pitch, and outputs a highly personalized 
    Subject Line and Email Body. 

    Args:
        lead: Dictionary containing 'name', 'category', 'ai_notes', 'website'.
        pitch: The core offer/pitch the user wants to communicate.
    
    Returns:
        dict: {"subject": "...", "body": "..."}
    """
    
    # Determine if this is a cold intro or a follow-up based on database touch_count
    touch_count = lead.get('touch_count', 0)
    
    if touch_count > 0:
        goal_text = "Your goal is to write a casual follow-up/remarketing email to a local business that we contacted recently. Gently circle back on the pitch, provide a tiny bit of additional value, and keep it very brief."
    else:
        goal_text = "Your goal is to write a highly personalized, deeply authentic cold email to a local business."

    # We want to force the AI to be extremely conversational and brief, 
    # as long, robotic emails get sent to spam immediately.
    prompt = f"""
You are an elite, human-like SDR (Sales Development Representative).
{goal_text}

LEAD INFORMATION:
- Business Name: {lead.get('name', 'The Business')}
- Category: {lead.get('category', 'Local Business')}
- Notes about them: {lead.get('ai_notes', 'No specific notes')}
- Website: {lead.get('website', 'No website')}

THE SENDER'S PITCH / OFFER:
"{pitch}"

CORE PHILOSOPHY (STRICTLY ADHERE):
- GOAL: Generate genuine interest and start a conversation based on the provided pitch.
- TONE: Do NOT sound like a typical salesperson. Do NOT sound desperate. Show respect for their work, provide a sincere observation, and invite them to engage.
- LINKS: DO NOT include any links in this first email.
- CALL TO ACTION: Use a soft, low-friction call to action derived naturally from the pitch. Do not ask for a meeting or a 15-minute call directly unless the pitch explicitly says so.
- OVERALL: Do not sound like another automated cold email. We want a natural reply to start a conversation.

CRITICAL: The pitch above is the ONLY source of truth for what we are offering. Do NOT invent, assume, or add any services, products, or value propositions beyond what the pitch describes. Stay 100% faithful to the pitch.

RULES FOR THE EMAIL:
1. It MUST feel like a human wrote it. No robotic language, no "I hope this email finds you well."
2. Keep it under 5 sentences. Short and punchy.
3. STRICT VOCABULARY BANS:
   - NEVER use the phrase "prueba gratuita" or "free trial". Use "prototipo privado sin compromiso" instead.
   - NEVER say "instalar IA" or "instalar inteligencia artificial". We are preparing a "prototipo visual y funcional" or "prototipo de mejora digital".
   - NEVER use "caso práctico" if it sounds public. Use "preparar un prototipo privado aplicado a vuestra clínica".
   - NEVER mention prices, costs, or money in this first email.
   - NEVER use the word "conversión" or "leads" (unless the recipient is explicitly a marketing agency). Use "flujo de contacto", "reservas", or "resolver dudas".
3. MENTION OBSERVABLE FACTS ONLY (RISK CLASSIFICATION):
You must classify the 'Notes about them' into one of three risk levels before writing the email:
- SAFE TO MENTION (e.g. hidden buttons, no clear CTA, confusing menu, no WhatsApp): Mention these clearly but politely.
- MENTION SOFTLY (e.g. slow load times, generic text, old structure): Soften the observation. e.g. "He visto que la web parece apoyarse bastante en contenido visual, y quizá habría margen para hacer la experiencia más ágil."
- DO NOT MENTION (e.g. "you lose patients", "bad SEO", "bad conversion", or if notes are empty/vague): Do not invent anything. Use a neutral phrase. CRITICAL: NEVER use the word "conversión". Substitute it with "claridad", "experiencia de usuario", or "flujo de contacto" (e.g. "creo que podría haber margen para mejorar la claridad y el flujo de contacto de la web").
4. MISSING WEBSITE RULE: If website is missing, empty, invalid, or unavailable, do not say the business has no website, no active website, or weak online presence. Simply avoid website-specific observations and use a neutral opening based on the business category.
5. LOW-FRICTION ENGAGEMENT: Do not ask for a meeting or a call. Just end with the soft CTA to search for it, or ask if they are open to giving their opinion.
6. Never hallucinate fake links, fake facts, or fake case studies. No links allowed in the first email.
7. ABSOLUTELY NO PLACEHOLDERS: Do NOT output literal brackets like [Business Name], [Name], or [Insert Name]. You MUST inject the name into the text organically.
7. NEURAL CONTEXT: If additional files (PDFs/Images) are attached, analyze them to understand the sender's portfolio or brand voice.
8. PRESERVE SIGNATURE: If the pitch already contains a sign-off and name at the end (e.g. "Un saludo,\\nAire"), keep it EXACTLY as written. Do not add another signature on top.
9. DIVERSITY: Every email must feel genuinely unique in structure, word choice and flow. Vary sentence length, opening hook, and how the personalization is woven in. No two emails should read the same.
10. NATURAL NAMING (CRITICAL): Extract the natural, conversational name of the business or person from the 'Business Name'. Discard any SEO keywords, locations, or extra descriptors (e.g., if the name is "Michael Seen - DJ en Mallorca - Baleares", you MUST refer to them simply as "Michael Seen" or "Michael"). NEVER copy-paste the literal raw Business Name if it sounds like a Google Maps search result.

Respond ONLY with a valid JSON document containing two keys: "subject" and "body".
DO NOT wrap the response in markdown blocks like ```json.
DO NOT include any text outside the JSON.
"""

    raw_response = await call_gemini(prompt, files=context_files, log_callback=log_callback)
    
    return parse_json_from_response(raw_response)

async def score_leads(leads: list, pitch: str, context_files: list = None, log_callback=None) -> dict:
    """
    Takes a batch of leads and asks Gemini to score them 1-100 based on their fit
    for the given pitch. Returns a dictionary mapping email -> score.
    """
    if not leads:
        return {}

    # Create a simplified version of leads to send to Gemini
    leads_summary = []
    for l in leads:
        leads_summary.append({
            "email": l.get("email", ""),
            "category": l.get("category", ""),
            "ai_notes": l.get("ai_notes", "")
        })

    # Process leads in chunks of 50 to avoid massive payload timeouts / 429s
    chunk_size = 50
    scores = {}
    
    for i in range(0, len(leads_summary), chunk_size):
        chunk = leads_summary[i:i+chunk_size]
        if log_callback:
            await log_callback(f"🧠 AI is scoring batch {i//chunk_size + 1} (leads {i} to {i+len(chunk)})...")
        
        prompt = f"""
You are an expert sales analyst. We are trying to find the WARMEST leads for this pitch:
"{pitch}"

Please score these leads from 1 to 100 on how likely they are to be a good fit, based on their category and notes.
100 = Perfect fit, extremely relevant.
1 = Terrible fit, completely irrelevant.

LEADS DATA (JSON):
{json.dumps(chunk, indent=2)}

Respond ONLY with a valid JSON document mapping the "email" -> integer score.
Example Response:
{{
    "johndoe@example.com": 95,
    "badfit@example.com": 10
}}
"""
        raw_response = await call_gemini(prompt, files=context_files, log_callback=log_callback)
        chunk_scores = parse_json_from_response(raw_response)
        if isinstance(chunk_scores, dict):
            scores.update(chunk_scores)
        
        # Give a short breather to the API to avoid TPM rate limits
        await asyncio.sleep(2)

    
    # Ensure all are ints and fallback to 50 if missing
    final_scores = {}
    for l in leads:
        email = l.get("email")
        if email:
            score = scores.get(email, 50)
            try:
                final_scores[email] = int(score)
            except:
                final_scores[email] = 50
                
    return final_scores

def _parse_json_from_response(text: str) -> dict:
    """Safely extracts JSON from the AI response."""
    text = text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    # Fallback if AI hallucinates formatting
    return {"subject": "Quick question", "body": text}
