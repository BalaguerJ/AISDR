from __future__ import annotations
"""
web_extractor.py — Web Search Scraper (Scraper Mode: Web)

Searches DuckDuckGo HTML (primary) and falls back to Google stealth (Playwright)
to discover digital targets: music blogs, record labels, curators, radios, etc.

Returns leads in the same dict format as extractor.py so the enricher can
process them without any changes.
"""

import asyncio
import re
from typing import Optional
from urllib.parse import unquote, urlparse, parse_qs
import requests
import urllib3
from bs4 import BeautifulSoup
from agents.db import is_already_known

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
}

# Domains to skip — directories, social platforms, video sites (not what we want)
_SKIP_DOMAINS = {
    'youtube.com', 'youtu.be', 'facebook.com', 'instagram.com',
    'twitter.com', 'x.com', 'tiktok.com', 'linkedin.com',
    'wikipedia.org', 'yelp.com', 'tripadvisor.com', 'google.com',
    'duckduckgo.com', 'bing.com', 'spotify.com', 'soundcloud.com',
    'apple.com', 'amazon.com', 'reddit.com', 'pinterest.com',
}


def _decode_ddg_url(href: str) -> str:
    """Decode a DuckDuckGo redirect URL to the actual destination URL."""
    if href.startswith('//duckduckgo.com/l/') or 'duckduckgo.com/l/' in href:
        parsed = urlparse('https:' + href if href.startswith('//') else href)
        params = parse_qs(parsed.query)
        uddg = params.get('uddg', [''])[0]
        if uddg:
            return unquote(uddg)
    return href


def _is_valid_target(url: str) -> bool:
    """Returns True if URL is a real target website we should enrich."""
    if not url or not url.startswith('http'):
        return False
    try:
        domain = urlparse(url).netloc.replace('www.', '').lower()
        return not any(skip in domain for skip in _SKIP_DOMAINS)
    except Exception:
        return False


async def _search_duckduckgo(query: str, max_results: int = 15) -> list[dict]:
    """
    Search DuckDuckGo HTML and return a list of {title, url} results.
    DuckDuckGo HTML is scraping-friendly and returns clean results.
    """
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    try:
        loop = asyncio.get_event_loop()
        def do_fetch():
            r = requests.get(search_url, headers=_HEADERS, timeout=12, verify=False)
            r.raise_for_status()
            return r.text
        html = await loop.run_in_executor(None, do_fetch)
    except Exception as e:
        print(f"      ⚠️  DDG fetch failed for '{query}': {e}")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results = []

    for result in soup.select('.result'):
        title_tag = result.select_one('.result__a')
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        href = title_tag.get('href', '')
        url = _decode_ddg_url(href)

        if not _is_valid_target(url):
            continue

        snippet_tag = result.select_one('.result__snippet')
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ''

        results.append({'title': title, 'url': url, 'snippet': snippet})
        if len(results) >= max_results:
            break

    return results


async def _search_google_stealth(query: str, max_results: int = 10) -> list[dict]:
    """
    Google Search fallback using Playwright stealth.
    Only used when DuckDuckGo returns insufficient results.
    """
    results = []
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=_HEADERS['User-Agent'],
                viewport={'width': 1280, 'height': 800}
            )
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            page = await context.new_page()

            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={max_results}"
            await page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(1.5)

            # Extract organic results
            links = await page.query_selector_all('a[href^="http"]:not([href*="google"])')
            for link in links[:max_results * 3]:
                href = await link.get_attribute('href')
                if not href or not _is_valid_target(href):
                    continue
                text = await link.inner_text()
                results.append({'title': text.strip()[:80], 'url': href, 'snippet': ''})
                if len(results) >= max_results:
                    break
    except Exception as e:
        print(f"      ⚠️  Google stealth failed for '{query}': {e}")
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

    return results


async def extract_web_leads(mission_data: dict, limit: int = 10, skip_existing: bool = True):
    """
    Main entry point for Web Search mode.
    Searches DuckDuckGo (+ Google stealth fallback) for each query and
    yields status messages and finally yields the list of lead dicts.
    """
    queries = mission_data.get('queries', [])
    if not queries:
        yield []
        return

    all_leads: list[dict] = []
    seen_urls: set[str] = set()

    for q_num, query in enumerate(queries):
        if len(all_leads) >= limit:
            break

        yield f"🔎 Web Search {q_num + 1}/{len(queries)} — '{query}'"

        # Layer 1: DuckDuckGo
        yield f"   🦆 Querying DuckDuckGo..."
        results = await _search_duckduckgo(query, max_results=20)

        # Layer 2: Google stealth if DDG returned too few
        if len(results) < 5:
            yield f"   🌐 DDG sparse — engaging Google stealth fallback..."
            google_results = await _search_google_stealth(query, max_results=10)
            results.extend(google_results)

        yield f"   📍 {len(results)} targets found. Processing..."

        for item in results:
            if len(all_leads) >= limit:
                break

            url = item['url']
            title = item['title'] or urlparse(url).netloc

            # Deduplicate by domain
            domain = urlparse(url).netloc.replace('www.', '')
            if domain in seen_urls:
                continue
            if skip_existing and is_already_known(url):
                continue

            seen_urls.add(domain)
            all_leads.append({
                'name': title,
                'category': 'Web Target',
                'website': url,
                'phone': '',
                'address': '',
                'map_url': url,
                'ai_notes': item.get('snippet', ''),
            })
            yield f"      ✅ Target found: {title[:60]}"

        await asyncio.sleep(1.5)  # Polite delay between queries

    yield all_leads[:limit]
