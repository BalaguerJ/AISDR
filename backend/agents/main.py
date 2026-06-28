from __future__ import annotations
"""
main.py — Orchestrator for Agent 1: The Prospector

Usage:
    python main.py --goal "carpentry shops in Barcelona" --limit 10 --headless

Flow:
    1. AI Brain generates smart Google Maps queries from the plain-English goal
    2. Playwright scrapes Google Maps for each query (with deduplication)
    3. AI Brain enriches each lead by crawling its website for phone, email & quality
    4. Results exported to a timestamped CSV file
"""

import asyncio
import argparse
import pandas as pd
from datetime import datetime

# Config must be first — it validates the API key on import
try:
    from agents.config import DEFAULT_LEAD_LIMIT, DEFAULT_QUERY_COUNT
    from agents.ai_brain import analyze_mission, AllAIKeysExhaustedError
    from agents.extractor import extract_leads
    from agents.web_extractor import extract_web_leads
    from agents.youtube_extractor import extract_youtube_leads
    from agents.enricher import enrich_lead, generate_fallback_notes
except ImportError:
    from config import DEFAULT_LEAD_LIMIT, DEFAULT_QUERY_COUNT
    from ai_brain import analyze_mission
    from extractor import extract_leads
    from web_extractor import extract_web_leads
    from youtube_extractor import extract_youtube_leads
    from enricher import enrich_lead


def print_banner():
    print("\n" + "═" * 60)
    print("  🤖  AGENT 1: THE PROSPECTOR  |  Powered by Gemini Flash")
    print("═" * 60)


def print_summary(leads: list[dict], filename: str):
    total        = len(leads)
    with_phone   = sum(1 for l in leads if l.get('phone'))
    with_email   = sum(1 for l in leads if l.get('email'))
    good_leads   = sum(1 for l in leads if l.get('is_good_lead'))

    print("\n" + "═" * 60)
    print("  ✅  PROSPECTING COMPLETE")
    print("═" * 60)
    print(f"  📊  Total leads collected : {total}")
    print(f"  📞  Leads with phone      : {with_phone} / {total}")
    print(f"  📧  Leads with email      : {with_email} / {total}")
    print(f"  ⭐  High-quality leads    : {good_leads} / {total}")
    print(f"  💾  Saved to              : {filename}")
    print("═" * 60 + "\n")


async def run_prospecting_agent(goal: str, limit: int = 10, use_hunt: bool = True, skip_existing: bool = True, headless: bool = True, scraper_mode: str = "maps"):
    """
    The Mission Orchestrator. Streams logs and leads to the frontend via WebSocket.
    """
    
    # ── Logging System ──────────────────────────────────
    log_queue = asyncio.Queue()
    
    async def log_fn(msg: str):
        await log_queue.put(msg)

    async def stream_logs():
        """Generator-friendly log streamer"""
        while True:
            msg = await log_queue.get()
            if msg is None: break # Sentinel
            yield msg
            log_queue.task_done()
    
    yield f"🎯 Starting mission for goal: {goal}"
    
    # ── Step 1: Query Projection & Localization ──────────────────────────────────
    if "\n" in goal:
        yield "📋 Batch Mode detected: Bypassing AI query generation and using manual queries directly..."
        raw_queries = [q.strip() for q in goal.split("\n") if q.strip()]
        if not raw_queries:
            raw_queries = [goal.strip()]
        mission_data = {
            "queries": raw_queries,
            "constraints": {},
            "audit_requirements": [],
            "locale": "es-ES"  # Assume default locale since no AI is used to guess it.
        }
    else:
        yield "🧠 AI brain is generating specialized search queries and computing geographic locale..."
        mission_data = await analyze_mission(goal, count=DEFAULT_QUERY_COUNT, log_callback=log_fn)
    
    # Check for immediate logs from analyze_mission
    while not log_queue.empty():
        yield await log_queue.get()
    
    queries = mission_data.get('queries', [])
    constraints = mission_data.get('constraints', {})
    audit_reqs = mission_data.get('audit_requirements', [])
    lat = mission_data.get('latitude')
    lon = mission_data.get('longitude')
    locale = mission_data.get('locale', 'en-US')
    
    # Inject safe_goal for namespacing intermediate files
    safe_goal = goal.replace(' ', '_').replace(',', '').replace('/', '_')[:30]
    mission_data['safe_goal'] = safe_goal
    
    if lat and lon:
        yield f"🛰️ Calibrating orbital sensors: Spoofing browser location to {lat}°N, {lon}°E ({locale})..."
        
    yield f"✅ AI generated {len(queries)} localized queries."

    # ── Step 2: Scraping (mode-aware) ──────────────────────────────────────────
    mode_labels = {
        "maps": "🗺️  Opening Google Maps for deep exploration...",
        "web":  "🌐 Launching Web Search engine...",
        "youtube": "🎬 Connecting to YouTube Data API...",
    }
    yield mode_labels.get(scraper_mode, "🔎 Starting scraper...")

    leads = []
    if scraper_mode == "youtube":
        async for update in extract_youtube_leads(mission_data, limit=limit, skip_existing=skip_existing):
            if isinstance(update, str):
                yield update
            else:
                leads = update
    elif scraper_mode == "web":
        async for update in extract_web_leads(mission_data, limit=limit, skip_existing=skip_existing):
            if isinstance(update, str):
                yield update
            else:
                leads = update
    else:  # maps (default)
        async for update in extract_leads(mission_data, limit=limit, skip_existing=skip_existing, headless=headless):
            if isinstance(update, str):
                yield update
            else:
                leads = update

    if not leads:
        yield "❌ No leads found for this goal. Try being more specific."
        return

    yield f"📦 Found {len(leads)} leads. {'Skipping enrichment (data already complete).' if scraper_mode == 'youtube' else 'Starting AI enrichment...'}"

    # Extract AI enrichment toggle
    use_ai_enrichment = mission_data.get('use_ai_enrichment', False)

    # ── Step 3: Enrichment — skip for YouTube (already fully populated) ─────────
    if scraper_mode == "youtube":
        enriched_leads = leads
        # Ensure all have required fields
        for lead in enriched_leads:
            lead.pop('_skip_enrichment', None)  # Remove internal flag
            if not lead.get('ai_notes'):
                lead['ai_notes'] = generate_fallback_notes(lead)
    else:
        yield f"🧠 Data decoding complete. Starting enrichment engine for {len(leads)} leads..."
        if use_ai_enrichment:
            from agents.config import GEMINI_API_KEYS
            concurrency = max(2, min(4, len(GEMINI_API_KEYS)))
        else:
            concurrency = 40
        semaphore = asyncio.Semaphore(concurrency)
        
        # --- INCREMENTAL SAVE & RESUME LOGIC ---
        import os, csv
        results_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
        os.makedirs(results_dir, exist_ok=True)
        partial_csv_path = os.path.join(results_dir, f"enriched_leads_partial_{safe_goal}.csv")
        column_order = ['name', 'category', 'phone', 'email', 'website', 'address', 'is_good_lead', 'ai_notes', 'map_url', 'asunto_email']
        csv_lock = asyncio.Lock()

        enriched_leads_recovered = []
        if os.path.exists(partial_csv_path):
            try:
                with open(partial_csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row['is_good_lead'] = str(row.get('is_good_lead', '')).lower() == 'true'
                        enriched_leads_recovered.append(row)
                
                recovered_keys = { (r.get('name', ''), r.get('map_url', '')) for r in enriched_leads_recovered }
                original_len = len(leads)
                leads = [l for l in leads if (l.get('name', ''), l.get('map_url', '')) not in recovered_keys]
                if len(leads) < original_len:
                    yield f"✅ Resumed {original_len - len(leads)} leads already enriched locally."
            except Exception as e:
                yield f"⚠️ Could not read existing enriched leads: {e}"

        async def save_lead_incrementally(lead_data):
            async with csv_lock:
                try:
                    file_exists = os.path.exists(partial_csv_path)
                    with open(partial_csv_path, 'a', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=column_order, extrasaction='ignore')
                        if not file_exists:
                            writer.writeheader()
                        writer.writerow(lead_data)
                except Exception as e:
                    print(f"⚠️ Could not incremental save: {e}")
        # ----------------------------------------

        enriched_leads = []
        leads_processed = 0
        total_leads = len(leads)

        async def enrich_task(idx, lead):
            nonlocal leads_processed
            name = lead.get('name', 'Unknown')
            async with semaphore:
                try:
                    await log_fn(f"🧪 [{idx+1}/{total_leads}] Started: {name}")
                    res = await asyncio.wait_for(
                        enrich_lead(lead, use_hunter=use_hunt, log_callback=log_fn,
                                    constraints=constraints, audit_requirements=audit_reqs, locale=locale, use_ai_enrichment=use_ai_enrichment),
                        timeout=20.0
                    )
                    leads_processed += 1
                    await save_lead_incrementally(res)
                    await log_fn(f"✅ [{leads_processed}/{total_leads}] Finished: {name}")
                    return res
                except asyncio.TimeoutError:
                    await log_fn(f"⚠️ [{idx+1}/{total_leads}] Failed: {name} (Hard Timeout - Playwright Froze)")
                    leads_processed += 1
                    lead['ai_notes'] = generate_fallback_notes(lead)
                    await save_lead_incrementally(lead)
                    return lead
                except AllAIKeysExhaustedError:
                    await log_fn(f"⚠️ [{idx+1}/{total_leads}] AI Tokens Empty: {name} (Bypassing AI - Regex Only)")
                    leads_processed += 1
                    lead['ai_notes'] = generate_fallback_notes(lead)
                    await save_lead_incrementally(lead)
                    return lead
                except Exception as e:
                    import traceback
                    trace_msg = traceback.format_exc()
                    await log_fn(f"⚠️ [{idx+1}/{total_leads}] Failed: {name} (Processing Error: {str(e)})")
                    print(f"DEBUG EXCEPTION for {name}: {trace_msg}")
                    leads_processed += 1
                    lead['ai_notes'] = generate_fallback_notes(lead)
                    await save_lead_incrementally(lead)
                    return lead

        tasks = [asyncio.create_task(enrich_task(i, lead)) for i, lead in enumerate(leads)]
        pending_tasks = asyncio.gather(*tasks)

        while not pending_tasks.done():
            try:
                msg = await asyncio.wait_for(log_queue.get(), timeout=0.1)
                yield msg
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                continue
            except AllAIKeysExhaustedError:
                yield "❌ ALL AI Quota Keys Exhausted. Forcing results to dashboard..."
                break
            except Exception:
                break

        while not log_queue.empty():
            yield await log_queue.get()

        try:
            enriched_leads = list(await pending_tasks) + enriched_leads_recovered
        except AllAIKeysExhaustedError:
            enriched_leads = [t.result() for t in tasks if t.done()]
            done_indices = {i for i, t in enumerate(tasks) if t.done()}
            for i, lead in enumerate(leads):
                if i not in done_indices:
                    enriched_leads.append(lead)
            enriched_leads += enriched_leads_recovered

    # ── Step 4: Export ────────────────────────────────────────────────────────
    yield "💾 Finalizing results and saving to CSV..."

    # Filter out ghost leads — only drop leads with NO name or NO address at all
    # We keep leads even if they have no email/phone/website, because:
    # 1. The user may be searching for businesses WITHOUT a website (e.g. no ticketing platform)
    # 2. A phone from Google Maps is enough to be a valid lead
    # 3. Address + name alone is useful for outreach research
    valid_leads = []
    for lead in enriched_leads:
        has_name = bool(lead.get('name', '').strip())
        has_address = bool(lead.get('address', '').strip())
        has_email = bool(lead.get('email'))
        has_phone = bool(lead.get('phone'))
        has_website = bool(lead.get('website'))
        
        # Keep if it's a real, identified business (name + any locating info)
        if has_name and (has_address or has_phone or has_email or has_website):
            valid_leads.append(lead)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_goal = goal.replace(' ', '_').replace(',', '')[:30]
    filename = f"leads_{safe_goal}_{timestamp}.csv"

    import os
    results_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)
    filepath = os.path.join(results_dir, filename)

    column_order = ['name', 'category', 'phone', 'email', 'website', 'address', 'is_good_lead', 'ai_notes', 'map_url', 'asunto_email']
    df = pd.DataFrame(valid_leads if valid_leads else enriched_leads) # Fallback if empty just in case
    
    # --- SPINTAX GENERATOR ---
    # Generates a randomized, natural subject per lead — used by campaign runner when AI is offline.
    import random
    import os as _os
    spintax = []
    spintax_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "spintax_asuntos.txt")
    if _os.path.exists(spintax_path):
        with open(spintax_path, 'r', encoding='utf-8') as f:
            spintax = [line.strip() for line in f if line.strip()]
    if not spintax:
        spintax = ["Pregunta rápida", "Duda", "Información", "Consulta"]
    if not df.empty:
        df['asunto_email'] = [random.choice(spintax) for _ in range(len(df))]

    ordered_cols = [c for c in column_order if c in df.columns]
    df = df[ordered_cols]
    df.to_csv(filepath, index=False, encoding='utf-8-sig')

    # --- AUTO-CLEANUP OF CHECKPOINT FILES ---
    # Only delete temporary files if the campaign processed everything without being artificially cut off by 'limit'
    # Wait, main.py doesn't know the exact number of raw links. A simple proxy is:
    # If the number of valid_leads (or enriched_leads) is EXACTLY the limit, there's a high chance 
    # it stopped prematurely. If it's less than the limit, it means it exhausted all available targets.
    # To be perfectly safe, we shouldn't delete checkpoints unless the system naturally exhausts targets.
    if len(enriched_leads) < limit:
        try:
            for tmp_file in [
                f"raw_targets_{safe_goal}.csv",
                f"failed_targets_{safe_goal}.csv",
                f"clean_leads_pre_ia_{safe_goal}.csv",
                f"deduped_out_{safe_goal}.csv",
                f"dedupe_summary_{safe_goal}.json"
            ]:
                tmp_path = os.path.join(results_dir, tmp_file)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as e:
            print(f"⚠️ Cleanup warning: {e}")

    yield {"status": "complete", "leads": valid_leads, "filename": filename}


async def main():
    # Keep the CLI working for backward compatibility
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", type=str, required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    
    async for update in run_prospecting_agent(args.goal, limit=args.limit):
        if isinstance(update, str):
            print(update)
        else:
            print(f"✅ Mission complete. Saved to {update['filename']}")


if __name__ == "__main__":
    asyncio.run(main())
