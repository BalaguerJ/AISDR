from __future__ import annotations
"""
intel_ads.py — Ads Intelligence Agent (hardened v3)

Detecta anuncios activos en Meta Ad Library con validación real:
- Extrae el texto de la página completa para detectar nombre del anunciante
- Usa fuzzy matching con stopwords (nombre de clínica vs. nombre del anunciante)
- Cuenta ads por el texto "~N resultados" o por "Identificador de la biblioteca"
- Blacklist de dominios internos de Meta para landing URLs
- ads_active = 1 SOLO si hay coincidencia de nombre + ads encontrados
- ads_scan_status = "needs_review" si hay ads pero sin coincidencia de nombre

Principio: menos positivos fiables >> muchos falsos positivos.
"""

import asyncio
import re
from typing import Optional
from playwright.async_api import async_playwright
from urllib.parse import quote_plus, unquote, urlparse


# ─── Blacklist de dominios no válidos como landing ───────────────────────────
INVALID_LANDING_DOMAINS = {
    "metastatus.com",
    "facebook.com",
    "fb.com",
    "fb.me",           # Facebook short URL redirector
    "meta.com",
    "about.facebook.com",
    "transparency.meta.com",
    "business.facebook.com",
    "instagram.com",
    "l.facebook.com",
    "google.com",
    "adstransparency.google.com",
    "support.google.com",
    "policies.google.com",
}

# ─── Meta UI strings that must never be treated as advertiser names ───────────
# These are page chrome/labels that the text scanner can accidentally pick up
REJECTED_ADVERTISER_PATTERNS = [
    r'^filtros$',
    r'^ordenar',
    r'^estado activo',
    r'^suprimir',
    r'^publicidad$',
    r'^activo$',
    r'^transparencia',
    r'en circulaci[oó]n desde',
    r'resultados incluyen anuncios',
    r'identificador de la biblioteca',
    r'plataformas',
    r'^ver detalles',
    r'\d{1,2}\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)',  # dates
    r'^\d+$',          # pure numbers
    r'^[\W\s]+$',      # only symbols/spaces
    r'biblioteca de anuncios',
    r'informe de la biblioteca',
    r'api de la biblioteca',
    r'contenido de marca',
    r'iniciar sesi[oó]n',
    r'^calle\s',       # address lines
    r'metro\s',        # metro station references
    r'📍',             # location pin emoji (addresses)
    r'\d{4,}',         # long number sequences (IDs)
]

DENTAL_CATEGORIES = {
    "implantes": ["implante", "implant", "dental implant"],
    "invisalign": ["invisalign", "ortodoncia invisible", "clear aligners", "alineador"],
    "estetica": ["estética dental", "carillas", "blanqueamiento", "whitening", "veneer"],
    "general": ["clínica dental", "dentista", "dental clinic", "odontología"],
    "ortodoncia": ["ortodoncia", "brackets", "orthodontics", "braces"],
}

META_AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
GOOGLE_ADS_TRANSPARENCY_URL = "https://adstransparency.google.com/"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_valid_landing(url: str) -> bool:
    """Returns True if URL is a real external landing (not Meta/Google internal)."""
    if not url or len(url) < 10:
        return False
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        if parsed.scheme not in ("http", "https"):
            return False
        for bad in INVALID_LANDING_DOMAINS:
            if domain == bad or domain.endswith("." + bad):
                return False
        if "." not in domain:
            return False
        return True
    except Exception:
        return False


def _is_rejected_advertiser(text: str) -> bool:
    """Returns True if a text line is a Meta UI element, not a real advertiser name."""
    t = text.strip()
    # Too short or too long to be a business name
    if len(t) < 4 or len(t) > 80:
        return True
    # High emoji density
    emoji_count = sum(1 for c in t if ord(c) > 127462)
    if emoji_count > 2:
        return True
    # Matches any rejected pattern
    t_lower = t.lower()
    for pattern in REJECTED_ADVERTISER_PATTERNS:
        if re.search(pattern, t_lower):
            return True
    return False


def _fuzzy_name_match(business_name: str, candidate: str) -> tuple[bool, float]:
    """
    Checks if a business name reasonably matches a candidate string.
    Returns (matched: bool, confidence: float 0-1).
    Rejects Meta UI strings before matching. Ignores dental sector stopwords.
    """
    if not business_name or not candidate:
        return False, 0.0

    # Hard reject obvious UI strings
    if _is_rejected_advertiser(candidate):
        return False, 0.0

    biz = business_name.lower().strip()
    cand = candidate.lower().strip()

    # Exact substring match
    if biz in cand or cand in biz:
        return True, 1.0

    STOPWORDS = {"la", "el", "de", "del", "en", "y", "e", "clínica", "clinica",
                 "dental", "dentista", "dr", "dra", "doctor", "doctora",
                 "the", "and", "madrid", "barcelona", "spain"}
    biz_words = [w for w in re.split(r'\W+', biz) if w and w not in STOPWORDS and len(w) > 2]
    cand_words = [w for w in re.split(r'\W+', cand) if w and w not in STOPWORDS and len(w) > 2]

    if not biz_words:
        return False, 0.0

    matches = sum(1 for w in biz_words if any(w in cw or cw in w for cw in cand_words))
    confidence = matches / len(biz_words)
    return confidence >= 0.5, round(confidence, 2)


# ─── Meta Ad Library Scraper ─────────────────────────────────────────────────

async def _scan_meta_ads(business_name: str, country: str = "ES") -> dict:
    """
    Searches the Meta Ad Library for active ads by the business.

    Strategy:
    - Search by business name
    - Get full page text to detect "N resultados" count and advertiser names
    - Scan [role="heading"] and text lines for fuzzy name match
    - Only mark found=True if name matches AND ads > 0
    - If ads found but no name match → needs_review (not found)
    """
    result = {
        "found": False,
        "ad_count": 0,
        "landing_url": "",
        "landing_domain": "",
        "category": "",
        "platform": "meta",
        "advertiser_name": "",
        "match_confidence": 0.0,
        "detection_reason": "no_ads_found",
    }

    search_query = quote_plus(business_name)
    url = (
        f"{META_AD_LIBRARY_URL}?active_status=active"
        f"&ad_type=all&country={country}&q={search_query}"
    )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="es-ES",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(6)

            # Dismiss cookie/login overlays
            for selector in ['[aria-label="Close"]', '[aria-label="Cerrar"]',
                              'button:has-text("Allow all")', 'button:has-text("Aceptar todo")']:
                try:
                    btn = page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await asyncio.sleep(1)
                        break
                except Exception:
                    pass

            # ─── Step 1: Get full page text ──────────────────────────────
            page_text = ""
            try:
                page_text = await page.locator("body").inner_text(timeout=8000)
            except Exception:
                pass
            page_lower = page_text.lower()

            # ─── Step 2: No-results check ────────────────────────────────
            no_result_phrases = [
                "no se encontraron resultados",
                "no results found",
                "no ads match",
                "no hay anuncios",
                "0 resultados",
            ]
            if any(phrase in page_lower for phrase in no_result_phrases):
                result["detection_reason"] = "no_ads_found"
                await browser.close()
                return result

            # ─── Step 3: Count ads ───────────────────────────────────────
            # Meta shows "~N resultados" or "N results" in the page text
            ad_count = 0
            count_match = re.search(r'~?(\d+)\s+resultado', page_lower)
            if count_match:
                ad_count = int(count_match.group(1))
            else:
                # Fallback: count "Identificador de la biblioteca" / "Ad library ID" occurrences
                ad_count = len(re.findall(r'identificador de la biblioteca', page_lower))
                if ad_count == 0:
                    ad_count = len(re.findall(r'ad library id', page_lower))

            # ─── Step 4: Find advertiser name ────────────────────────────
            # Meta renders advertiser names as text in the feed
            # Strategy: scan [role="heading"] first, then all text lines
            best_match = False
            best_confidence = 0.0
            best_advertiser = ""

            # Approach A: headings
            try:
                headings = page.locator('[role="heading"]')
                h_count = await headings.count()
                for i in range(min(h_count, 30)):
                    text = (await headings.nth(i).inner_text(timeout=1500)).strip()
                    if 2 < len(text) < 120:
                        ok, conf = _fuzzy_name_match(business_name, text)
                        if ok and conf > best_confidence:
                            best_match = True
                            best_confidence = conf
                            best_advertiser = text
            except Exception:
                pass

            # Approach B: all text lines
            if not best_match:
                lines = [l.strip() for l in page_text.split('\n')
                         if 3 < len(l.strip()) < 100]
                for line in lines:
                    ok, conf = _fuzzy_name_match(business_name, line)
                    if ok and conf > best_confidence:
                        best_match = True
                        best_confidence = conf
                        best_advertiser = line.strip()

            # ─── Step 5: Extract landing URLs ────────────────────────────
            landing_url = ""
            landing_domain = ""
            if best_match and ad_count > 0:
                try:
                    all_links = await page.evaluate("""
                        () => Array.from(document.querySelectorAll('a[href]'))
                              .map(a => a.href)
                              .filter(h => h.includes('l.facebook.com/l.php') ||
                                          (!h.includes('facebook.com') &&
                                           !h.includes('meta.com') &&
                                           !h.includes('metastatus.com') &&
                                           h.startsWith('http')))
                              .slice(0, 20)
                    """)
                    for href in all_links:
                        if "l.facebook.com/l.php" in href:
                            m = re.search(r'u=([^&]+)', href)
                            if m:
                                href = unquote(m.group(1))
                        if _is_valid_landing(href):
                            landing_url = href
                            landing_domain = urlparse(href).netloc.lower().replace("www.", "")
                            break
                except Exception:
                    pass

            # ─── Step 6: Final decision ──────────────────────────────────
            if best_match and ad_count > 0:
                result["found"] = True
                result["ad_count"] = ad_count
                result["advertiser_name"] = best_advertiser
                result["match_confidence"] = best_confidence
                result["landing_url"] = landing_url
                result["landing_domain"] = landing_domain
                result["detection_reason"] = f"name_match({best_confidence:.0%})+{ad_count}_ads"
            elif ad_count > 0:
                # Ads found but no name match → likely competitor/keyword results
                result["found"] = False
                result["ad_count"] = ad_count
                result["detection_reason"] = f"ads_found_no_name_match({ad_count}_results)"
            else:
                result["detection_reason"] = "no_ads_found"

            # Category
            if result["found"]:
                for cat_name, keywords in DENTAL_CATEGORIES.items():
                    if any(kw in page_lower for kw in keywords):
                        result["category"] = cat_name
                        break

            await browser.close()

    except Exception as e:
        result["detection_reason"] = f"error:{type(e).__name__}:{str(e)[:100]}"
        print(f"      ⚠️  Meta scan failed for '{business_name}': {e}")

    return result


# ─── Google Ads Transparency Scraper ─────────────────────────────────────────

async def _scan_google_ads(business_name: str, region: str = "ES") -> dict:
    """Google Ads Transparency — requires name match to mark as found."""
    result = {
        "found": False,
        "platform": "google",
        "advertiser_name": "",
        "match_confidence": 0.0,
        "detection_reason": "no_ads_found",
    }

    search_query = quote_plus(business_name)
    url = f"{GOOGLE_ADS_TRANSPARENCY_URL}?region={region}&query={search_query}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="es-ES",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(4)

            for sel in ['[class*="advertiser-name"]', '[class*="result-card"]',
                        'a[href*="advertiser"]', '[role="listitem"]']:
                try:
                    els = page.locator(sel)
                    count = await els.count()
                    if count == 0:
                        continue
                    for i in range(min(count, 5)):
                        text = await els.nth(i).inner_text(timeout=3000)
                        ok, conf = _fuzzy_name_match(business_name, text.strip())
                        if ok:
                            result["found"] = True
                            result["advertiser_name"] = text.strip()
                            result["match_confidence"] = conf
                            result["detection_reason"] = f"name_match({conf:.0%})"
                            break
                    if result["found"]:
                        break
                except Exception:
                    continue

            await browser.close()

    except Exception as e:
        result["detection_reason"] = f"error:{type(e).__name__}:{str(e)[:100]}"
        print(f"      ⚠️  Google Ads scan failed for '{business_name}': {e}")

    return result


# ─── Landing Page Quality ─────────────────────────────────────────────────────

async def _assess_landing_quality(landing_url: str) -> str:
    """Returns 'good', 'weak', or 'broken'. Only called for valid external URLs."""
    if not landing_url or not _is_valid_landing(landing_url):
        return "unknown"
    try:
        import time
        from agents.enricher import _fetch_html
        start = time.time()
        html = await _fetch_html(landing_url, timeout=10)
        load_time = time.time() - start
        if not html or len(html) < 200:
            return "broken"
        html_lower = html.lower()
        score = 0
        if re.search(r"wa\.me|whatsapp", html_lower): score += 2
        if re.search(r"calendly|simplybook|reservar|book|cita", html_lower): score += 2
        if re.search(r"<form", html_lower): score += 1
        if re.search(r'<meta\s+name=["\']viewport', html_lower): score += 1
        if load_time < 3: score += 1
        if load_time > 5: score -= 2
        if not re.search(r"<form", html_lower): score -= 1
        return "good" if score >= 4 else "weak"
    except Exception:
        return "broken"


# ─── Spend Signal ─────────────────────────────────────────────────────────────

def _infer_spend_signal(meta_ads: dict, google_ads: dict) -> str:
    ad_count = meta_ads.get("ad_count", 0)
    has_google = google_ads.get("found", False)
    if ad_count > 10 or (ad_count > 3 and has_google):
        return "high"
    elif ad_count > 0 or has_google:
        return "medium"
    return "low"


# ─── Main Entry Point ─────────────────────────────────────────────────────────

async def scan_ads_intelligence(business_name: str, website_domain: str = "") -> dict:
    """
    Full pipeline: scan Meta + Google → validate with strict confidence rules → assess landing quality.

    Confidence rules (ChatGPT v3):
    - ads_active = 1 ONLY if:
        a) match_confidence >= 75%, OR
        b) match_confidence >= 50% AND landing_domain matches website_domain, OR
        c) landing_domain matches website_domain directly (no name needed)
    - Everything else → ads_scan_status = needs_review, ads_active = 0
    """
    result = {
        "ads_active": 0,
        "ads_platform": "none",
        "ads_landing_url": "",
        "ads_landing_domain": "",
        "ads_landing_quality": "unknown",
        "ads_category": "",
        "ads_spend_signal": "low",
        "ads_advertiser_name": "",
        "ads_match_confidence": 0.0,
        "ads_detection_reason": "not_scanned",
        "ads_scan_status": "ok",
        "ads_scan_error": "",
    }

    if not business_name:
        result["ads_scan_status"] = "skipped"
        result["ads_detection_reason"] = "no_business_name"
        return result

    # Normalize website_domain for comparison
    website_domain_clean = (website_domain or "").lower().replace("www.", "").split("/")[0].strip()

    meta_result, google_result = await asyncio.gather(
        _scan_meta_ads(business_name),
        _scan_google_ads(business_name),
        return_exceptions=True,
    )

    if isinstance(meta_result, Exception):
        result["ads_scan_error"] = f"meta:{str(meta_result)[:100]}"
        result["ads_scan_status"] = "partial"
        meta_result = {"found": False, "detection_reason": "exception"}
    if isinstance(google_result, Exception):
        err = f"google:{str(google_result)[:100]}"
        result["ads_scan_error"] = (result["ads_scan_error"] + " | " + err).strip(" | ")
        result["ads_scan_status"] = "partial"
        google_result = {"found": False}

    has_meta = meta_result.get("found", False)
    has_google = google_result.get("found", False)
    meta_reason = meta_result.get("detection_reason", "")

    if has_meta or has_google:
        src = meta_result if has_meta else google_result
        confidence = src.get("match_confidence", 0.0)
        landing_domain = meta_result.get("landing_domain", "") if has_meta else ""
        landing_domain_clean = landing_domain.lower().replace("www.", "")

        # ─── Confidence rules ──────────────────────────────────────────
        # Rule A: high confidence match (>= 75%)
        rule_a = confidence >= 0.75
        # Rule B: medium confidence + landing domain matches website
        rule_b = (confidence >= 0.50 and website_domain_clean and
                  landing_domain_clean and website_domain_clean in landing_domain_clean)
        # Rule C: landing domain directly matches the website domain
        rule_c = (website_domain_clean and landing_domain_clean and
                  website_domain_clean in landing_domain_clean)

        is_confirmed = rule_a or rule_b or rule_c

        result["ads_advertiser_name"] = src.get("advertiser_name", "")
        result["ads_match_confidence"] = confidence
        result["ads_detection_reason"] = src.get("detection_reason", "")
        result["ads_category"] = meta_result.get("category", "") if has_meta else ""

        # Only compute landing quality if it's a valid external URL
        landing_url = meta_result.get("landing_url", "") if has_meta else ""
        if landing_url and _is_valid_landing(landing_url):
            result["ads_landing_url"] = landing_url
            result["ads_landing_domain"] = landing_domain
            result["ads_landing_quality"] = await _assess_landing_quality(landing_url)

        if is_confirmed:
            result["ads_active"] = 1
            result["ads_platform"] = "both" if (has_meta and has_google) else ("meta" if has_meta else "google")
            result["ads_spend_signal"] = _infer_spend_signal(
                meta_result if has_meta else {},
                google_result if has_google else {}
            )
            rule_used = "A" if rule_a else ("B" if rule_b else "C")
            result["ads_detection_reason"] += f" [rule_{rule_used}_confirmed]"
        else:
            # Found ads but confidence too low to confirm → needs human review
            result["ads_active"] = 0
            result["ads_scan_status"] = "needs_review"
            result["ads_detection_reason"] += f" [weak_match_{confidence:.0%}_not_confirmed]"
    else:
        result["ads_detection_reason"] = meta_reason
        if "no_name_match" in meta_reason:
            result["ads_scan_status"] = "needs_review"

    return result



def format_ads_summary(data: dict) -> str:
    """Human-readable summary for logs."""
    if not data.get("ads_active"):
        reason = data.get("ads_detection_reason", "")
        status = data.get("ads_scan_status", "")
        return f"Ads: None detected | reason={reason[:50]} | status={status}"

    platform = data.get("ads_platform", "?")
    quality = data.get("ads_landing_quality", "?")
    conf = data.get("ads_match_confidence", 0)
    advertiser = data.get("ads_advertiser_name", "?")[:30]
    domain = data.get("ads_landing_domain", "") or "no landing"

    return (f"Ads: ACTIVE on {platform} | '{advertiser}' conf={conf:.0%} "
            f"| landing={domain} ({quality})")
