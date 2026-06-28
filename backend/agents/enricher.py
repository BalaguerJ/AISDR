from __future__ import annotations
"""
enricher.py — Website Crawler & AI Contact Extractor (Agent 1: The Prospector)

Visits a lead's website, extracts ALL possible contact data using a layered strategy:
  1. Extracts mailto: links directly from raw HTML (before any stripping)
  2. Extracts visible page text (fast requests)
  3. Scans footer HTML specifically (highest density of contact info)
  4. Tries contact / legal / about pages
  5. Falls back to Playwright deep scrape if page renders with JS
  6. Sends ALL collected text to AI for intelligent extraction
  7. Regex fallback if AI quota fails
"""

import requests
from bs4 import BeautifulSoup
import re
import asyncio
import time
import json
from typing import Optional
from urllib.parse import urljoin, urlparse
import urllib3
from playwright.async_api import async_playwright
from agents.config import WEB_REQUEST_TIMEOUT, MAX_PAGE_TEXT_CHARS
from agents.ai_brain import extract_contact_info, identify_best_website, identify_contact_link

from agents.utils import is_whatsapp_ready
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
}

# Pages commonly containing contact info — tried in order
_CONTACT_PATH_HINTS = [
    '/contact', '/contacto', '/kontakt', '/contact-us', '/contactus',
    '/about', '/sobre-nosotros', '/uber-uns', '/chi-siamo',
    '/legal', '/aviso-legal', '/impressum', '/mentions-legales',
    '/info', '/team', '/equipo',
]


# ─── Email Extraction Utilities ────────────────────────────────────────────────

def _extract_emails_from_html(html: str) -> list[str]:
    """
    Extracts emails from both visible text AND href='mailto:...' attributes.
    This is critical — many sites only expose email in mailto links, not visible text.
    """
    emails = set()
    bad = ['.png', '.jpg', '.jpeg', '.gif', '.css', '.js', 'sentry', 'example.com', 'schema.org']

    # 1. mailto: links in raw HTML (most reliable — always present if email exists)
    for match in re.findall(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html):
        if not any(b in match.lower() for b in bad):
            emails.add(match.lower())

    # 2. Email pattern anywhere in the raw HTML (catches obfuscated text)
    for match in re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html):
        if not any(b in match.lower() for b in bad):
            emails.add(match.lower())

    return list(emails)


def _extract_footer_text(html: str) -> str:
    """
    Parse footer elements specifically — footers have the highest density of
    contact info (email, phone, address) and are often missed in full-page text.
    """
    soup = BeautifulSoup(html, 'html.parser')
    footer_text_parts = []

    # Look for semantic footer and common footer class names
    for selector in ['footer', '[class*="footer"]', '[id*="footer"]', '[class*="contact"]', '[id*="contact"]']:
        for el in soup.select(selector):
            footer_text_parts.append(el.get_text(separator=' ', strip=True))

    return ' '.join(footer_text_parts)


def _html_to_text(html: str) -> str:
    """Strip scripts/styles and return visible text."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(["script", "style", "noscript", "meta", "head"]):
        tag.decompose()
    return soup.get_text(separator=' ', strip=True)


# ─── Page Fetching ─────────────────────────────────────────────────────────────

async def _fetch_html(url: str, timeout: int = None) -> Optional[str]:
    """Async wrapper for fast fetching using OS-level curl to prevent Python socket/GIL hangs."""
    t = timeout or WEB_REQUEST_TIMEOUT
    try:
        proc = await asyncio.create_subprocess_exec(
            'curl', '-sSL', '--max-time', str(t),
            '-A', _HEADERS['User-Agent'],
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=t + 2.0)
            if proc.returncode == 0:
                # Truncate to 150KB to prevent regex/BeautifulSoup from hanging the executor on massive files
                return stdout.decode('utf-8', errors='ignore')[:150000]
            return None
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            print(f"      ⚠️  Strict Timeout enforced on {url} (curl killed)")
            return None
    except Exception:
        return None


def _fetch_html_playwright_sync(url: str) -> Optional[str]:
    """Synchronous Playwright fetch — runs in a thread so it can be hard-killed."""
    import subprocess, sys
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(_HEADERS)
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            content = page.content()
            browser.close()
            return content
    except Exception as e:
        print(f"      ⚠️  Deep Scrape failed for {url}: {e}")
        return None


async def _fetch_html_playwright(url: str) -> Optional[str]:
    """Deep fetch using a real browser in a thread — CANNOT freeze the event loop.
    
    Running playwright in a ThreadPoolExecutor means asyncio.wait_for CAN actually
    kill it with a real OS-level thread timeout, unlike async playwright which
    blocks the event loop when the browser subprocess hangs.
    """
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_html_playwright_sync, url),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        print(f"      ⚠️  Deep Scrape hard-killed (10s OS timeout): {url}")
        return None
    except Exception as e:
        print(f"      ⚠️  Deep Scrape failed for {url}: {e}")
        return None


async def _perform_surgical_audit(url: str, requirements: list) -> dict:
    """
    Performs a diagnostic audit of a website's health (Speed, Mobile, Features).
    Only runs if the mission goal implies a 'Tier 1' quality check.
    """
    results = {
        "load_time_seconds": 0,
        "is_mobile_friendly": True,
        "has_booking_system": False,
        "aesthetic_critique": "",
        "issues_found": []
    }
    
    start_time = time.time()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_extra_http_headers(_HEADERS)
            
            # 1. Benchmark Speed
            try:
                await page.goto(url, wait_until="load", timeout=20000)
                results["load_time_seconds"] = round(time.time() - start_time, 2)
            except:
                results["load_time_seconds"] = 20.0 # Timeout fallback
                
            content = await page.content()
            text = await page.evaluate("document.body.innerText")
            html = await page.content()

            # 2. Mobile Check
            viewport = await page.locator('meta[name="viewport"]').count()
            results["is_mobile_friendly"] = viewport > 0
            
            # 3. Feature Detection (Booking Systems)
            booking_vectors = ['book', 'reservation', 'appointment', 'calendly', 'opentable', 'thefork', 'booking.com']
            results["has_booking_system"] = any(v in text.lower() or v in html.lower() for v in booking_vectors)
            
            # 4. Identify Issues Based on Requirements
            if results["load_time_seconds"] > 5:
                results["issues_found"].append("slow_loading")
            if not results["is_mobile_friendly"]:
                results["issues_found"].append("not_mobile_friendly")
            if not results["has_booking_system"]:
                results["issues_found"].append("no_booking_system")
                
            # 5. Semantic Critique (Will be handled by the main AI extraction to save requests)
            results["aesthetic_critique"] = ""
            
            await browser.close()
            return results
    except Exception as e:
        print(f"      ⚠️  Audit failed for {url}: {e}")
        return results


async def _analyze_website_aesthetics(page_text: str, url: str) -> str:
    """Uses Gemini to judge if a website looks outdated or 'ugly' based on its content/structure."""
    prompt = f"""
Analyze this website content and structure (URL: {url}). 
Judge if this website likely has "Design Debt" (looks old, 1990s-2010s style, unpolished, or amateur).
Website Text Fragment:
{page_text}

Return a single short sentence characterizing the design quality. 
Example: "Site appears to be an outdated template from the early 2010s with poor mobile formatting."
If it looks modern and professional, say "Site looks modern and professional."
"""
    try:
        from agents.ai_brain import call_gemini
        critique = await call_gemini(prompt)
        return critique.strip()
    except:
        return "Could not perform aesthetic analysis."


# ─── Contact Page Discovery ────────────────────────────────────────────────────

async def _find_contact_pages(base_url: str, homepage_html: str, business_name: str, log_callback=None) -> list[str]:
    """
    Returns a list of URLs likely to contain contact info.
    Strategy 1: Check known path patterns directly (fast, no AI needed).
    Strategy 2: Use AI to pick from all homepage links (covers non-English sites).
    """
    found_urls = []
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"

    # Strategy 1: Try common paths directly (fast, async)
    loop = asyncio.get_event_loop()
    async def check_path(candidate):
        try:
            def do_head():
                return requests.head(candidate, headers=_HEADERS, timeout=5, verify=False, allow_redirects=True)
            r = await loop.run_in_executor(None, do_head)
            if r.status_code < 400:
                return candidate
        except:
            return None

    # Parallelize path checks
    candidates = [base + path for path in _CONTACT_PATH_HINTS]
    results = await asyncio.gather(*[check_path(c) for c in candidates])
    found_urls = [r for r in results if r]

    # Strategy 2: AI-powered link discovery from homepage (multilingual)
    if not found_urls:
        soup = BeautifulSoup(homepage_html, 'html.parser')
        links = []
        seen = set()
        for a in soup.find_all('a', href=True):
            full_url = urljoin(base_url, a['href'])
            text = a.get_text(strip=True)
            if full_url not in seen and len(text) > 2 and base in full_url:
                links.append({"text": text, "href": full_url})
                seen.add(full_url)

        if links:
            ai_url = await identify_contact_link(links, business_name, log_callback=log_callback)
            if ai_url and ai_url != base_url:
                found_urls.append(ai_url)

    return found_urls


# ─── Website Hunter ────────────────────────────────────────────────────────────

async def _hunt_for_website(name: str, address: str, locale: str = 'en-US', log_callback=None, use_ai: bool = True) -> str:
    """
    Multi-strategy website discovery for businesses with no Google Maps website:
    1. Try common domain patterns directly (fast & reliable)
    2. DuckDuckGo HTML search (fallback)
    3. Google search + AI (last resort)
    """
    print(f"      🔎 Hunting for website of '{name}' (Locale: {locale})...")

    # Strategy 1: Direct domain guessing
    clean_name = re.sub(r'[^a-z0-9]', '', name.lower().replace(' ', ''))
    candidates = [
        f"https://{clean_name}.com",
        f"https://{clean_name}.es",
        f"https://www.{clean_name}.com",
        f"https://www.{clean_name}.es",
    ]
    async def check_domain(url):
        try:
            def do_head():
                return requests.head(url, headers=_HEADERS, timeout=5, verify=False, allow_redirects=True)
            r = await loop.run_in_executor(None, do_head)
            if r.status_code < 400:
                return r.url
        except:
            return None

    results = await asyncio.gather(*[check_domain(u) for u in candidates])
    for r in results:
        if r:
            print(f"      ✨ Direct domain hit: {r}")
            return r

    # Strategy 2: DuckDuckGo HTML (more scraping-friendly than Google)
    search_terms = {
        'es': 'sitio web oficial',
        'de': 'offizielle website',
        'fr': 'site web officiel',
        'it': 'sito web ufficiale',
        'pt': 'site oficial',
        'en': 'official website'
    }
    lang = locale.split('-')[0].lower()
    term = search_terms.get(lang, 'official website')
    
    search_query = f"{name} {address} {term}".replace(" ", "+")
    try:
        ddg_url = f"https://html.duckduckgo.com/html/?q={search_query}"
        html = await _fetch_html(ddg_url)  # ← FIX: was missing await
        if html and len(html) > 200:
            if use_ai:
                found = await identify_best_website(html[:5000], name, log_callback=log_callback)
                if found:
                    print(f"      ✨ DDG found (AI): {found}")
                    return found
            else:
                # Fast fallback: Extract the first search result link
                soup = BeautifulSoup(html, 'html.parser')
                first_link = soup.select_one('a.result__url')
                if first_link and first_link.get('href'):
                    url = first_link.get('href')
                    if 'duckduckgo.com' not in url and 'google.com' not in url:
                        print(f"      ✨ DDG found (Fast): {url}")
                        return url
    except Exception:
        pass

    # Strategy 3: Google fallback (Async)
    try:
        google_url = f"https://www.google.com/search?q={name}+{address}+website"
        html = await _fetch_html(google_url)
        if html:
            if use_ai:
                found = await identify_best_website(html[:5000], name, log_callback=log_callback)
                if found:
                    print(f"      ✨ Google found (AI): {found}")
                    return found
            else:
                soup = BeautifulSoup(html, 'html.parser')
                # Usually Google search results have an 'a' tag with href starting with /url?q=
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '/url?q=' in href and 'google' not in href:
                        url = href.split('/url?q=')[1].split('&')[0]
                        print(f"      ✨ Google found (Fast): {url}")
                        return url
    except Exception:
        pass

    return ""


# ─── Phone & Email Cleanup ────────────────────────────────────────────────────

def _clean_phone(phone: str) -> str:
    if not phone:
        return ""
    date_patterns = [
        r'\d{1,2}\.\d{1,2}\.\d{4}', r'\d{4}\.\d{1,2}\.\d{1,2}',
        r'\d{1,2}\.\d{1,2}\.\d{2}',
    ]
    for p in date_patterns:
        if re.search(p, phone):
            return ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) > 15:
        halfway = len(digits) // 2
        if digits[:halfway] == digits[halfway:]:
            return phone[:len(phone)//2].strip()
    return phone.strip()


def _regex_phone_fallback(text: str) -> str:
    pattern = r'(?:\+?[\d]{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}'
    for m in re.findall(pattern, text):
        cleaned = _clean_phone(m)
        if cleaned and len(re.sub(r'\D', '', cleaned)) >= 9:
            return cleaned
    return ""


def _pick_best_email(emails: list[str]) -> str:
    """Pick the most likely primary contact email from a list."""
    if not emails:
        return ""
    # Prefer info@, contact@, hello@, hola@ over noreply@ or system emails
    priority = ['info@', 'contact@', 'hello@', 'hola@', 'contacto@', 'mail@', 'studio@', 'studio']
    for prefix in priority:
        for e in emails:
            if e.startswith(prefix):
                return e
    return emails[0]


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def generate_fallback_notes(lead: dict) -> str:
    """Creates a professional description even if AI enrichment is skipped."""
    category = lead.get('category', '')
    # Clean the address one more time just in case, and remove the weird pin emoji
    address = lead.get('address', '').replace('\ue0c8', '').replace('\n', ' ').strip()
    
    if category:
        return f"{category} business located in {address}." if address else f"{category} business."
    return f"Local business located in {address}." if address else "Local business."


async def enrich_lead(lead: dict, use_hunter: bool = True, log_callback=None, constraints: dict = None, audit_requirements: list = None, locale: str = 'en-US', use_ai_enrichment: bool = False) -> dict:
    """
    Main entry point. Enriches a lead with email, phone, AI notes, and quality score.
    Now supports technical auditing for 'Tier 1' targeting.
    """
    url = lead.get('website', '')
    name = lead.get('name', 'Unknown Business')
    already_has_phone = bool(lead.get('phone', '').strip())
    already_has_address = bool(lead.get('address', '').strip())
    
    constraints = constraints or {}
    audit_requirements = audit_requirements or []
    website_forbidden = constraints.get("website") == "forbidden"
    # Detect if this is a "no ticketing platform" / "no online presence" type of goal
    website_optional = constraints.get("website", "optional") == "optional"

    lead.setdefault('email', '')
    lead.setdefault('is_good_lead', False)
    lead.setdefault('ai_notes', '')

    # ── TIER 1 AUDIT: Check website health if requested ───────────────────────
    audit_data = None
    audit_context = ""
    if url and audit_requirements:
        print(f"      🩺  Mission Parameter: Tier 1 Audit required for '{name}'...")
        if log_callback: await log_callback(f"🩺 Checking Technical Health of {url}...")
        audit_data = await _perform_surgical_audit(url, audit_requirements)
        
        # Build context for the AI to incorporate into notes
        if audit_data:
            audit_context = f"[TECHNICAL DATA]: Speed: {audit_data['load_time_seconds']}s. "
            if not audit_data['is_mobile_friendly']:
                audit_context += "Mobile check: FAILED. "
            if not audit_data['has_booking_system']:
                audit_context += "Booking system: MISSING. "

    # ── HUNTER: Find website if missing ───────────────────────────────────────
    # If the goal is "No Website" or "No Ticketing Platform", we MUST NOT hunt for one —
    # because finding a website would contradict the goal.
    if (not url or 'google.com' in url) and use_hunter and not website_forbidden:
        # Only use AI for hunting if AI enrichment is enabled
        found_url = await _hunt_for_website(name, lead.get('address', ''), locale=locale, log_callback=log_callback)
        if found_url:
            lead['website'] = found_url
            url = found_url

    if not url or 'google.com' in url:
        # ── NO WEBSITE FOUND ─────────────────────────────────────────────────
        # A business with NO website is a PERFECT lead for goals like:
        #   - "no ticketing platform" (no website = definitely no Eventbrite/Ticketmaster)
        #   - "no online presence" goals
        # Mark as good lead if we have at least a phone OR a verified address.
        has_any_contact = already_has_phone or already_has_address
        lead['is_good_lead'] = has_any_contact
        
        # Build a note that explains the absence of web presence (valuable signal)
        category = lead.get('category', 'Business')
        address = lead.get('address', '').replace('\ue0c8', '').replace('\n', ' ').strip()
        if address:
            lead['ai_notes'] = f"{category} in {address}. No website or online ticketing platform detected — operates offline only."
        else:
            lead['ai_notes'] = f"{category}. No website or online ticketing platform detected — operates offline only."
        return lead

    if not url.startswith('http'):
        url = 'https://' + url

    # ── COLLECTION: Build a rich combined text corpus ─────────────────────────
    all_emails_found: list[str] = []
    combined_text_parts: list[str] = []
    homepage_html: str = ""

    # Step 1: Fetch homepage (fast, non-blocking)
    msg_fetch = f"      🌐 Fetching homepage: {url}"
    print(msg_fetch)
    if log_callback: await log_callback(msg_fetch)
    homepage_html = await _fetch_html(url)

    if not homepage_html or len(homepage_html) < 300:
        msg_deep = f"      🕵️  Fast fetch insufficient. Engaging Deep Scrape for '{name}'..."
        print(msg_deep)
        if log_callback: await log_callback(msg_deep)
        homepage_html = await _fetch_html_playwright(url) or ""

    if homepage_html:
        all_emails_found.extend(_extract_emails_from_html(homepage_html))
        footer_text = _extract_footer_text(homepage_html)
        if footer_text:
            combined_text_parts.append(f"[FOOTER]: {footer_text}")
        page_text = _html_to_text(homepage_html)
        combined_text_parts.append(page_text)

        # ── INTELLIGENCE: Technographic scan (free — reuses same HTML) ────
        try:
            from agents.intel_techno import scan_technographics, format_tech_summary
            tech_signals = scan_technographics(homepage_html, url)
            lead['tech_signals'] = tech_signals
            tech_summary = format_tech_summary(tech_signals)
            print(f"      🔬 Tech Scan: {tech_summary}")
            if log_callback:
                await log_callback(f"🔬 Tech: {tech_summary}")
        except Exception as e:
            print(f"      ⚠️  Tech scan skipped: {e}")

    # Step 2: Scan contact/legal/about subpages in PARALLEL for maximum speed
    # Skip only if we already have an email (no need to scan further)
    if not all_emails_found:
        contact_pages = await _find_contact_pages(url, homepage_html or "", name, log_callback=log_callback)
        valid_contact_pages = [cp for cp in contact_pages[:2] if cp != url]  # up to 2 subpages
        if valid_contact_pages:
            msg_scan = f"      📋 Parallel-scanning {len(valid_contact_pages)} subpage(s): {valid_contact_pages}"
            print(msg_scan)
            if log_callback: await log_callback(msg_scan)
            sub_htmls = await asyncio.gather(*[_fetch_html(cp) for cp in valid_contact_pages])
            for sub_html in sub_htmls:
                if sub_html:
                    all_emails_found.extend(_extract_emails_from_html(sub_html))
                    combined_text_parts.append(_html_to_text(sub_html))

    # Inject discovered emails directly into text so AI sees them
    if all_emails_found:
        unique_emails = list(set(all_emails_found))
        combined_text_parts.insert(0, f"[EMAILS FOUND IN PAGE]: {', '.join(unique_emails)}")

    combined_text = ' '.join(combined_text_parts)

    # If still very sparse, try Playwright deep scrape
    if len(combined_text) < 300:
        msg_deep2 = f"      🕵️  Sparse content. Engaging Deep Scrape for '{name}'..."
        print(msg_deep2)
        if log_callback: await log_callback(msg_deep2)
        deep_html = await _fetch_html_playwright(url)
        if deep_html:
            all_emails_found.extend(_extract_emails_from_html(deep_html))
            combined_text = _html_to_text(deep_html) + ' '.join(combined_text_parts)

    if not combined_text.strip():
        lead['is_good_lead'] = bool(already_has_phone or all_emails_found)
        if all_emails_found:
            lead['email'] = _pick_best_email(all_emails_found)
        return lead

    if use_ai_enrichment:
        # ── AI EXTRACTION (Consolidated) ──────────────────────────────────────────
        try:
            from agents.ai_brain import extract_contact_info
            ai_result = await extract_contact_info(combined_text, name, audit_context=audit_context, log_callback=log_callback)

            # AI email — but prefer our directly-extracted emails if AI missed it
            ai_email = ai_result.get('email', '')
            if ai_email:
                lead['email'] = ai_email
            elif all_emails_found:
                lead['email'] = _pick_best_email(all_emails_found)

            lead['is_good_lead'] = ai_result.get('is_good_lead', False)
            lead['ai_notes'] = ai_result.get('notes', '')

            if not already_has_phone and ai_result.get('phone'):
                lead['phone'] = _clean_phone(ai_result['phone'])

        except Exception as e:
            msg_err = f"      ⚠️  AI extraction failed for '{name}', using fallbacks: {e}"
            print(msg_err)
            if log_callback: await log_callback(msg_err)

            # Direct email fallback — if we already extracted emails, use them
            if all_emails_found:
                lead['email'] = _pick_best_email(all_emails_found)
            else:
                lead['email'] = _pick_best_email(_extract_emails_from_html(homepage_html or "")) or \
                                _regex_email_fallback(combined_text)

            if not already_has_phone:
                lead['phone'] = _regex_phone_fallback(combined_text)

            lead['is_good_lead'] = bool(lead['phone'] or lead['email'])

            # Template description fallback (so notes field is never empty)
            if not lead.get('ai_notes') or lead.get('ai_notes') == 'None':
                lead['ai_notes'] = generate_fallback_notes(lead)
    else:
        # ── FAST REGEX EXTRACTION (AI Bypassed to save keys & speed up) ────────────
        # Direct email fallback — if we already extracted emails, use them
        if all_emails_found:
            lead['email'] = _pick_best_email(all_emails_found)
        else:
            lead['email'] = _pick_best_email(_extract_emails_from_html(homepage_html or "")) or \
                            _regex_email_fallback(combined_text)

        if not already_has_phone:
            lead['phone'] = _regex_phone_fallback(combined_text)

        lead['is_good_lead'] = bool(lead['phone'] or lead['email'])
        lead['ai_notes'] = generate_fallback_notes(lead)

    # ── SEMANTIC CONSTRAINT ENFORCEMENT ───────────────────────────────────────
    # If the user requested an email specifically, we check if we found one.
    email_status = constraints.get("email", "optional")
    found_email = lead.get("email", "").lower()
    
    if email_status == "required" and not found_email:
        lead['is_good_lead'] = False
    elif email_status == "gmail_only" and "@gmail.com" not in found_email:
        lead['is_good_lead'] = False

    # Phone / WhatsApp Enforcement
    phone_status = constraints.get("phone", "optional")
    raw_phone = lead.get("phone", "")
    is_whatsapp = is_whatsapp_ready(raw_phone)
    
    # Store phone type as clean metadata — NOT in the description
    if raw_phone:
        lead['phone_type'] = "mobile" if is_whatsapp else "landline"
    else:
        lead['phone_type'] = "none"
    
    if phone_status == "whatsapp_only" and not is_whatsapp:
        lead['is_good_lead'] = False

    # ── FINAL FALLBACK CHECK ──────────────────────────────────────────────────
    # Ensure ai_notes is NEVER empty if we can help it
    if not lead.get('ai_notes') or str(lead.get('ai_notes', '')).strip() == '' or lead.get('ai_notes') == 'None':
        lead['ai_notes'] = generate_fallback_notes(lead)

    return lead


def _regex_email_fallback(text: str) -> str:
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    bad = ['.png', '.jpg', '.jpeg', '.gif', '.css', '.js', 'sentry.io', 'example.com']
    for match in re.findall(pattern, text):
        if not any(b in match.lower() for b in bad):
            return match.lower()
    return ""
