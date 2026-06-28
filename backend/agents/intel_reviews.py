from __future__ import annotations
"""
intel_reviews.py — Review Pain Miner (Intelligence Agent 2)

Analyzes Google Maps reviews to detect operational pain signals:
- Phone/contact problems
- Booking/appointment friction  
- Website issues
- Wait time complaints

Only stores AGGREGATED counts — never individual review text or reviewer data.
"""

import asyncio
import re
from typing import Optional
from playwright.async_api import async_playwright, Page


# ─── Pain Detection Patterns ─────────────────────────────────────────────────

PAIN_PATTERNS = {
    "phone": [
        # Spanish
        r"no cogen el tel[eé]fono", r"no contestan", r"imposible contactar",
        r"no responden al tel[eé]fono", r"llam[eé] y no", r"no cogen",
        r"no atienden el tel[eé]fono", r"no se puede contactar",
        r"no responden las llamadas", r"no descuelgan",
        r"no hay quien conteste", r"no responden nunca",
        # English
        r"don'?t answer the phone", r"no answer", r"unreachable",
        r"can'?t reach", r"never pick up", r"phone goes to voicemail",
        r"impossible to contact", r"no one answers",
    ],
    "booking": [
        # Spanish
        r"no pud[ei] pedir cita", r"tardaron en dar cita",
        r"lista de espera", r"meses para una cita",
        r"no hay disponibilidad", r"semanas para",
        r"imposible conseguir cita", r"no dan cita",
        r"no hay huecos", r"sin cita disponible",
        r"cita para dentro de", r"tardan mucho en dar",
        # English
        r"couldn'?t book", r"long wait.*appointment",
        r"no availability", r"weeks to get",
        r"months? wait", r"can'?t get an appointment",
    ],
    "web": [
        # Spanish
        r"la web no funciona", r"p[aá]gina ca[ií]da", r"web antigua",
        r"no se puede reservar online", r"web muy lenta",
        r"la web est[aá] mal", r"web obsoleta", r"web desactualizada",
        # English
        r"website doesn'?t work", r"no online booking",
        r"website is down", r"outdated website", r"website is slow",
        r"can'?t book online",
    ],
    "wait": [
        # Spanish
        r"mucha espera", r"una hora esperando", r"retraso",
        r"me hicieron esperar", r"siempre con retraso",
        r"esperando m[aá]s de", r"minutos? de espera",
        r"tardaron mucho", r"espera interminable",
        r"puntualidad p[eé]sima", r"nunca puntuales",
        # English
        r"long wait", r"waited forever", r"hour waiting",
        r"always late", r"never on time", r"kept waiting",
        r"waited.*minutes",
    ],
}

# Reviews with these sentiments are more relevant for pain detection
NEGATIVE_RATING_THRESHOLD = 3  # 1-3 stars


# ─── Review Scraping ──────────────────────────────────────────────────────────

async def _scrape_reviews_from_maps(map_url: str, max_reviews: int = 80) -> list[dict]:
    """
    Opens a Google Maps place URL, clicks the Reviews tab,
    scrolls to load reviews, and extracts text + rating.
    
    Returns list of {"text": str, "rating": int} dicts.
    """
    reviews = []
    
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
            
            # Navigate to the place
            await page.goto(map_url, timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            
            # Dismiss cookie banner if present
            try:
                accept_btn = page.locator(
                    'button:has-text("Accept all"), '
                    'button:has-text("Aceptar todo"), '
                    'form[action*="consent"] button'
                )
                if await accept_btn.count() > 0:
                    await accept_btn.first.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            
            # Extract rating and review count from the header
            total_reviews = 0
            avg_rating = 0.0
            try:
                # Try to get the review count from the header
                review_header = await page.locator('[class*="F7nice"] span[aria-hidden="true"]').first.inner_text(timeout=5000)
                if review_header:
                    rating_match = re.search(r'([\d,\.]+)', review_header)
                    if rating_match:
                        avg_rating = float(rating_match.group(1).replace(",", "."))
            except Exception:
                pass
            
            try:
                review_count_el = await page.locator('button[jsaction*="reviewChart"] span, [class*="F7nice"] span:nth-child(2)').first.inner_text(timeout=3000)
                count_match = re.search(r'([\d.,]+)', review_count_el.replace(".", "").replace(",", ""))
                if count_match:
                    total_reviews = int(count_match.group(1))
            except Exception:
                pass
            
            # Click the Reviews tab
            try:
                reviews_tab = page.locator('button[aria-label*="Review"], button[aria-label*="Reseña"], button:has-text("Reviews"), button:has-text("Reseñas")')
                if await reviews_tab.count() > 0:
                    await reviews_tab.first.click()
                    await asyncio.sleep(2)
            except Exception:
                pass
            
            # Sort by "Newest" to get recent reviews
            try:
                sort_btn = page.locator('button[aria-label*="Sort"], button[data-value="sort"]')
                if await sort_btn.count() > 0:
                    await sort_btn.first.click()
                    await asyncio.sleep(1)
                    newest = page.locator('li[data-index="1"], [role="menuitemradio"]:has-text("Newest"), [role="menuitemradio"]:has-text("Más recientes")')
                    if await newest.count() > 0:
                        await newest.first.click()
                        await asyncio.sleep(2)
            except Exception:
                pass
            
            # Scroll to load more reviews
            scrollable = page.locator('div[class*="m6QErb"][class*="DxyBCb"]')
            scroll_attempts = 0
            max_scrolls = min(max_reviews // 10, 8)  # Cap scrolling
            
            while scroll_attempts < max_scrolls:
                try:
                    if await scrollable.count() > 0:
                        await scrollable.first.evaluate("el => el.scrollTop = el.scrollHeight")
                        await asyncio.sleep(1.5)
                        scroll_attempts += 1
                    else:
                        break
                except Exception:
                    break
            
            # Extract review data
            review_elements = page.locator('[data-review-id]')
            count = await review_elements.count()
            
            for i in range(min(count, max_reviews)):
                try:
                    review_el = review_elements.nth(i)
                    
                    # Get rating (number of filled stars)
                    rating = 0
                    try:
                        stars_el = review_el.locator('[role="img"][aria-label]')
                        if await stars_el.count() > 0:
                            stars_label = await stars_el.first.get_attribute("aria-label")
                            star_match = re.search(r'(\d)', stars_label or "")
                            if star_match:
                                rating = int(star_match.group(1))
                    except Exception:
                        pass
                    
                    # Get review text
                    text = ""
                    try:
                        # Try to click "More" button to expand
                        more_btn = review_el.locator('button[aria-label*="More"], button:has-text("Más")')
                        if await more_btn.count() > 0:
                            await more_btn.first.click()
                            await asyncio.sleep(0.3)
                    except Exception:
                        pass
                    
                    try:
                        text_el = review_el.locator('[class*="wiI7pd"], [class*="MyEned"] span')
                        if await text_el.count() > 0:
                            text = await text_el.first.inner_text(timeout=2000)
                    except Exception:
                        pass
                    
                    if text.strip():
                        reviews.append({"text": text.strip(), "rating": rating})
                        
                except Exception:
                    continue
            
            await browser.close()
            
            return reviews, total_reviews, avg_rating
            
    except Exception as e:
        print(f"      ⚠️  Review scraping failed for {map_url}: {e}")
        return [], 0, 0.0


# ─── Pain Analysis ────────────────────────────────────────────────────────────

def _analyze_pain(reviews: list[dict]) -> dict:
    """
    Scans review texts for pain signals. Only processes reviews with 3 stars or less
    for pain detection (positive reviews are irrelevant for pain scoring).
    
    Returns aggregated pain counts per category.
    """
    pain_counts = {
        "review_pain_phone": 0,
        "review_pain_booking": 0,
        "review_pain_web": 0,
        "review_pain_wait": 0,
    }
    
    for review in reviews:
        text = review.get("text", "").lower()
        rating = review.get("rating", 5)
        
        # Only analyze negative/neutral reviews for pain signals
        if rating > NEGATIVE_RATING_THRESHOLD:
            continue
        
        for pain_type, patterns in PAIN_PATTERNS.items():
            col_name = f"review_pain_{pain_type}"
            for pattern in patterns:
                if re.search(pattern, text, re.I):
                    pain_counts[col_name] += 1
                    break  # One match per category per review
    
    return pain_counts


def _calculate_pain_score(pain_counts: dict, total_reviews: int) -> float:
    """
    Calculates a normalized pain score (0-100) based on:
    - Total pain mentions relative to review count
    - Weighted by pain category severity
    """
    if total_reviews == 0:
        return 0.0
    
    weights = {
        "review_pain_phone": 3.0,    # Phone issues = highest friction
        "review_pain_booking": 2.5,  # Booking issues = direct revenue loss
        "review_pain_web": 2.0,      # Web issues = your exact product
        "review_pain_wait": 1.5,     # Wait time = operational signal
    }
    
    weighted_sum = sum(
        pain_counts.get(k, 0) * weights.get(k, 1.0) 
        for k in pain_counts
    )
    
    # Normalize: cap the denominator so small clinics with few reviews
    # but many complaints still get a high score
    effective_reviews = max(total_reviews, 20)  # Floor at 20
    raw_score = (weighted_sum / effective_reviews) * 100
    
    return min(round(raw_score, 1), 100.0)


# ─── Main Entry Point ────────────────────────────────────────────────────────

async def mine_review_pain(map_url: str) -> dict:
    """
    Full pipeline: scrape reviews → detect pain → calculate score.
    
    Args:
        map_url: Google Maps place URL.
    
    Returns:
        Dict with all review_* fields ready for DB insert.
    """
    result = {
        "review_total": 0,
        "review_avg_rating": 0.0,
        "review_pain_phone": 0,
        "review_pain_booking": 0,
        "review_pain_web": 0,
        "review_pain_wait": 0,
        "review_pain_score": 0.0,
    }
    
    if not map_url:
        return result
    
    reviews, total, avg_rating = await _scrape_reviews_from_maps(map_url)
    
    result["review_total"] = total or len(reviews)
    result["review_avg_rating"] = avg_rating
    
    if reviews:
        pain_counts = _analyze_pain(reviews)
        result.update(pain_counts)
        result["review_pain_score"] = _calculate_pain_score(
            pain_counts, result["review_total"]
        )
    
    return result


def format_review_summary(data: dict) -> str:
    """Human-readable summary for logs."""
    total = data.get("review_total", 0)
    rating = data.get("review_avg_rating", 0)
    score = data.get("review_pain_score", 0)
    pains = []
    if data.get("review_pain_phone"): pains.append(f"Phone:{data['review_pain_phone']}")
    if data.get("review_pain_booking"): pains.append(f"Booking:{data['review_pain_booking']}")
    if data.get("review_pain_web"): pains.append(f"Web:{data['review_pain_web']}")
    if data.get("review_pain_wait"): pains.append(f"Wait:{data['review_pain_wait']}")
    
    pain_str = ", ".join(pains) if pains else "None detected"
    return f"Reviews: {total} ({rating}★) | Pain Score: {score}/100 | Signals: {pain_str}"
