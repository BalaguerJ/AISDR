from __future__ import annotations
"""
youtube_extractor.py — YouTube Data API v3 Scraper (Scraper Mode: YouTube)

Uses the free YouTube Data API to search for channels matching the goal,
then extracts contact emails from channel descriptions using regex + AI.

Quota usage: ~100 units/search query + ~2 units/channel detail = very cheap.
Free tier: 10,000 units/day → ~50 searches + thousands of channel details.

Returns leads in the same dict format as extractor.py.
No enricher pass needed — email is extracted directly from the API response.
"""

import asyncio
import os
import re
import requests
from urllib.parse import urlparse
import urllib3
from agents.config import MAX_PAGE_TEXT_CHARS
from agents.db import is_already_known

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

_EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)
_BAD_EMAIL_FRAGMENTS = ['sentry', 'example.com', 'schema.org', '.png', '.jpg', '.gif']


def _extract_emails(text: str) -> list[str]:
    """Extract clean emails from raw text."""
    found = []
    for match in _EMAIL_RE.findall(text or ''):
        if not any(b in match.lower() for b in _BAD_EMAIL_FRAGMENTS):
            found.append(match.lower())
    return list(set(found))


def _pick_best_email(emails: list[str]) -> str:
    """Prefer business-sounding emails over personal ones."""
    if not emails:
        return ''
    priority = ['info@', 'contact@', 'hello@', 'hola@', 'booking@', 'management@', 'music@', 'demo@']
    for prefix in priority:
        for e in emails:
            if e.startswith(prefix):
                return e
    return emails[0]


def _format_subs(count: str) -> str:
    """Format subscriber count for display."""
    try:
        n = int(count)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M subscribers"
        elif n >= 1_000:
            return f"{n/1_000:.0f}K subscribers"
        return f"{n} subscribers"
    except Exception:
        return "subscribers unknown"


async def _search_channels(query: str, max_results: int = 20) -> list[str]:
    """Search YouTube for channels matching the query. Returns list of channel IDs."""
    if not YOUTUBE_API_KEY:
        print("      ⚠️  YOUTUBE_API_KEY not set in .env")
        return []

    params = {
        'part': 'snippet',
        'type': 'channel',
        'q': query,
        'maxResults': max_results,
        'key': YOUTUBE_API_KEY,
    }
    try:
        loop = asyncio.get_event_loop()
        def do_fetch():
            r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        data = await loop.run_in_executor(None, do_fetch)
        items = data.get('items', [])
        return [item['id']['channelId'] for item in items if item.get('id', {}).get('channelId')]
    except Exception as e:
        print(f"      ⚠️  YouTube search failed for '{query}': {e}")
        return []


async def _get_channel_details(channel_ids: list[str]) -> list[dict]:
    """Fetch full channel details (description, stats, etc.) for a batch of IDs."""
    if not channel_ids or not YOUTUBE_API_KEY:
        return []

    params = {
        'part': 'snippet,statistics,brandingSettings',
        'id': ','.join(channel_ids),
        'key': YOUTUBE_API_KEY,
    }
    try:
        loop = asyncio.get_event_loop()
        def do_fetch():
            r = requests.get(YOUTUBE_CHANNELS_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        data = await loop.run_in_executor(None, do_fetch)
        return data.get('items', [])
    except Exception as e:
        print(f"      ⚠️  YouTube channel details failed: {e}")
        return []


async def extract_youtube_leads(mission_data: dict, limit: int = 10, skip_existing: bool = True):
    """
    Main entry point for YouTube mode.
    Searches YouTube for channels matching each query, extracts emails from
    descriptions, and yields status messages then the final list of leads.

    NOTE: These leads skip the enricher — they are already fully populated
    from the YouTube API response.
    """
    if not YOUTUBE_API_KEY:
        yield "❌ YOUTUBE_API_KEY not found in .env. Please add it."
        yield []
        return

    queries = mission_data.get('queries', [])
    if not queries:
        yield []
        return

    all_leads: list[dict] = []
    seen_channel_ids: set[str] = set()

    for q_num, query in enumerate(queries):
        if len(all_leads) >= limit:
            break

        yield f"🎬 YouTube Search {q_num + 1}/{len(queries)} — '{query}'"
        yield f"   📡 Querying YouTube Data API..."

        channel_ids = await _search_channels(query, max_results=25)
        if not channel_ids:
            yield f"   ⚠️  No channels found for this query."
            continue

        # Deduplicate channel IDs across queries
        new_ids = [cid for cid in channel_ids if cid not in seen_channel_ids]
        seen_channel_ids.update(new_ids)

        yield f"   📺 {len(new_ids)} channels found. Extracting contact info..."

        # Batch fetch channel details (max 50 per API call)
        for batch_start in range(0, len(new_ids), 50):
            if len(all_leads) >= limit:
                break

            batch = new_ids[batch_start:batch_start + 50]
            channels = await _get_channel_details(batch)

            for ch in channels:
                if len(all_leads) >= limit:
                    break

                snippet = ch.get('snippet', {})
                stats = ch.get('statistics', {})
                branding = ch.get('brandingSettings', {}).get('channel', {})

                channel_id = ch.get('id', '')
                title = snippet.get('title', 'Unknown Channel')
                description = snippet.get('description', '')
                custom_url = snippet.get('customUrl', '')
                sub_count = stats.get('subscriberCount', '0')
                country = snippet.get('country', '')

                # Build channel URL
                if custom_url:
                    channel_url = f"https://www.youtube.com/{custom_url}"
                else:
                    channel_url = f"https://www.youtube.com/channel/{channel_id}"

                # Check Neural Memory (skip if seen in a previous campaign)
                if skip_existing and is_already_known(channel_url):
                    yield f"      ⏭️  Skipping known channel: {title[:30]}..."
                    continue

                # Extract emails from description
                emails = _extract_emails(description)
                # Also check branding keywords field
                emails += _extract_emails(branding.get('keywords', ''))
                best_email = _pick_best_email(emails)

                sub_display = _format_subs(sub_count)
                is_good = bool(best_email)

                # Build AI notes from description snippet
                desc_short = description[:200].replace('\n', ' ').strip()
                notes = f"YouTube channel — {sub_display}"
                if country:
                    notes += f" — {country}"
                if desc_short:
                    notes += f". {desc_short}"

                lead = {
                    'name': title,
                    'category': 'YouTube Channel',
                    'website': channel_url,
                    'phone': '',
                    'address': sub_display,
                    'map_url': channel_url,
                    'email': best_email,
                    'ai_notes': notes,
                    'is_good_lead': is_good,
                    '_skip_enrichment': True,  # Already fully enriched from API
                }

                all_leads.append(lead)

                status = f"✅ {title[:50]} — {sub_display}"
                if best_email:
                    status += f" — 📧 {best_email}"
                else:
                    status += " — No email found"
                yield f"      {status}"

        await asyncio.sleep(0.5)  # Polite delay between queries

    yield all_leads[:limit]
