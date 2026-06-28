from __future__ import annotations
"""
intel_techno.py — Technographic Scanner (Intelligence Agent 1)

Analyzes a website's HTML to detect technology stack, booking systems,
tracking pixels, chat widgets, compliance signals, and design debt.

Zero extra HTTP requests needed — works on the HTML already fetched by enricher.py.
"""

import re
import json
from typing import Optional
from bs4 import BeautifulSoup


# ─── Detection Patterns ──────────────────────────────────────────────────────

CMS_SIGNATURES = {
    "wordpress": [r"wp-content", r"wp-includes", r"wp-json", r"/wp-admin"],
    "wix": [r"static\.wixstatic\.com", r"wix\.com", r"_wix_browser_sess"],
    "squarespace": [r"squarespace-cdn", r"squarespace\.com", r"static1\.squarespace"],
    "shopify": [r"cdn\.shopify\.com", r"shopify\.com/s/"],
    "joomla": [r"/media/jui/", r"Joomla!", r"/components/com_"],
    "drupal": [r"Drupal", r"drupal\.js", r"/sites/default/files"],
    "webflow": [r"webflow\.com", r"assets-global\.website-files"],
    "jimdo": [r"jimdo", r"jimdosite\.com"],
    "weebly": [r"weebly\.com", r"editmysite\.com"],
    "godaddy": [r"godaddy\.com", r"secureserver\.net"],
    "1and1": [r"1and1", r"ionos\."],
    "strato": [r"strato\.de"],
}

PIXEL_PATTERNS = [
    r"fbq\s*\(", r"facebook\.com/tr", r"connect\.facebook\.net.*fbevents",
    r"_fbp", r"fb-pixel",
]

GTM_PATTERNS = [
    r"gtm\.js", r"googletagmanager\.com/gtm\.js", r"GTM-[A-Z0-9]+",
    r"google_tag_manager",
]

BOOKING_PATTERNS = [
    r"doctolib", r"simplybook", r"calendly", r"treatwell", r"miodentista",
    r"booksy", r"setmore", r"acuity", r"mindbody", r"fresha\.com",
    r"hotdoc", r"zocdoc", r"practo", r"reservar\s+cita", r"pedir\s+cita",
    r"pide\s+tu\s+cita", r"solicitar\s+cita", r"solicitar\s+una\s+cita",
    r"cita\s+online", r"pide\s+cita\s+online", r"agenda\s+tu\s+cita",
    r"primera\s+visita", r"book\s+appointment", r"appointment",
    r"cita\s+previa", r"agendar", r"schedule.*appointment",
]

WHATSAPP_PATTERNS = [
    r"wa\.me", r"api\.whatsapp\.com", r"web\.whatsapp\.com",
    r"whatsapp\.com/send", r"href[^>]*whatsapp", r"class[^>]*whatsapp",
    r">[^<]*whatsapp[^<]*<"  # Visible text containing whatsapp
]

CHAT_PATTERNS = [
    r"intercom", r"drift\.com", r"tidio", r"tawk\.to", r"crisp\.chat",
    r"livechat", r"zendesk", r"hubspot.*conversations", r"olark",
    r"smartsupp", r"chatra", r"freshchat", r"chatwoot",
]

SCHEMA_TYPES = [
    "Dentist", "LocalBusiness", "MedicalBusiness", "HealthAndBeautyBusiness",
    "Physician", "MedicalClinic", "Hospital", "DiagnosticLab",
]

CONSENT_KEYWORDS = [
    r"he\s+le[ií]do\s+y\s+acepto", r"lee\s+y\s+acepta",
    r"acepto\s+la\s+pol[ií]tica\s+de\s+privacidad",
    r"pol[ií]tica\s+de\s+privacidad\s+de\s+datos",
    r"informaci[oó]n\s+b[aá]sica\s+sobre\s+protecci[oó]n\s+de\s+datos",
    r"protecci[oó]n\s+de\s+datos", r"privacidad", r"privacy",
    r"rgpd", r"gdpr", r"acepto", r"consent", r"lopd",
    r"t[eé]rminos\s+y\s+condiciones",
]


# ─── Main Scanner ─────────────────────────────────────────────────────────────

def scan_technographics(html: str, url: str = "") -> dict:
    """
    Analyzes raw HTML to detect technology stack and digital maturity signals.
    
    Args:
        html: Raw HTML string of the homepage.
        url: The URL (used for SSL check).
    
    Returns:
        Dict with all tech_* fields ready for DB insert.
    """
    result = {
        "tech_cms": "unknown",
        "tech_has_pixel": 0,
        "tech_has_gtm": 0,
        "tech_has_booking": 0,
        "tech_has_whatsapp": 0,
        "tech_has_chat": 0,
        "tech_has_schema": 0,
        "tech_has_ssl": 0,
        "tech_has_consent_form": 0,
        "tech_mobile_friendly": 0,
    }

    if not html:
        return result

    html_lower = html.lower()

    # 1. CMS Detection
    for cms_name, patterns in CMS_SIGNATURES.items():
        for pattern in patterns:
            if re.search(pattern, html_lower):
                result["tech_cms"] = cms_name
                break
        if result["tech_cms"] != "unknown":
            break

    # Also check <meta name="generator">
    if result["tech_cms"] == "unknown":
        gen_match = re.search(r'<meta\s+name=["\']generator["\']\s+content=["\']([^"\']+)', html, re.I)
        if gen_match:
            gen_val = gen_match.group(1).lower()
            for cms_name in CMS_SIGNATURES:
                if cms_name in gen_val:
                    result["tech_cms"] = cms_name
                    break
            if result["tech_cms"] == "unknown":
                result["tech_cms"] = f"other:{gen_val[:30]}"

    # 2. Meta Pixel
    for pattern in PIXEL_PATTERNS:
        if re.search(pattern, html_lower):
            result["tech_has_pixel"] = 1
            break

    # 3. Google Tag Manager
    for pattern in GTM_PATTERNS:
        if re.search(pattern, html, re.I):
            result["tech_has_gtm"] = 1
            break

    # 4. Booking System
    for pattern in BOOKING_PATTERNS:
        if re.search(pattern, html_lower):
            result["tech_has_booking"] = 1
            break

    # 5. WhatsApp
    for pattern in WHATSAPP_PATTERNS:
        if re.search(pattern, html_lower):
            result["tech_has_whatsapp"] = 1
            break

    # 6. Chat Widget
    for pattern in CHAT_PATTERNS:
        if re.search(pattern, html_lower):
            result["tech_has_chat"] = 1
            break

    # 7. Schema.org Structured Data
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                ld_data = json.loads(script.string or "")
                # Handle both single objects and arrays
                items = ld_data if isinstance(ld_data, list) else [ld_data]
                for item in items:
                    schema_type = item.get("@type", "")
                    if isinstance(schema_type, list):
                        schema_type = " ".join(schema_type)
                    if any(st.lower() in schema_type.lower() for st in SCHEMA_TYPES):
                        result["tech_has_schema"] = 1
                        break
            except (json.JSONDecodeError, AttributeError):
                continue
            if result["tech_has_schema"]:
                break
    except Exception:
        pass

    # 8. SSL Check
    if url.startswith("https://"):
        result["tech_has_ssl"] = 1

    # 9. Consent/Privacy Form Check
    # Check for strong explicit phrases anywhere in HTML
    strong_consent_phrases = [
        r"he\s+le[ií]do\s+y\s+acepto", r"lee\s+y\s+acepta", 
        r"acepto\s+la\s+pol[ií]tica\s+de\s+privacidad",
        r"informaci[oó]n\s+b[aá]sica\s+sobre\s+protecci[oó]n\s+de\s+datos"
    ]
    has_consent = False
    for phrase in strong_consent_phrases:
        if re.search(phrase, html_lower):
            has_consent = True
            break
            
    if not has_consent:
        # Check inside forms specifically for more generic privacy words
        forms_html = ""
        try:
            soup = soup if 'soup' in dir() else BeautifulSoup(html, 'html.parser')
            for form in soup.find_all('form'):
                forms_html += str(form).lower()
        except Exception:
            forms_html = html_lower

        if forms_html:
            for kw in CONSENT_KEYWORDS:
                if re.search(kw, forms_html):
                    has_consent = True
                    break

    result["tech_has_consent_form"] = 1 if has_consent else 0

    # 10. Mobile Friendly (viewport meta tag)
    if re.search(r'<meta\s+name=["\']viewport["\']', html, re.I):
        result["tech_mobile_friendly"] = 1

    return result


def format_tech_summary(tech: dict) -> str:
    """Creates a human-readable summary of technographic findings for logs."""
    gaps = []
    if not tech.get("tech_has_pixel"):    gaps.append("No Meta Pixel")
    if not tech.get("tech_has_gtm"):      gaps.append("No GTM")
    if not tech.get("tech_has_booking"):   gaps.append("No Booking System")
    if not tech.get("tech_has_whatsapp"):  gaps.append("No WhatsApp")
    if not tech.get("tech_has_chat"):      gaps.append("No Chat Widget")
    if not tech.get("tech_has_schema"):    gaps.append("No Schema.org")
    if not tech.get("tech_has_consent_form"): gaps.append("No GDPR Consent")
    if not tech.get("tech_mobile_friendly"):  gaps.append("Not Mobile-Friendly")

    cms = tech.get("tech_cms", "unknown")
    summary = f"CMS: {cms} | "
    if gaps:
        summary += f"Gaps ({len(gaps)}): {', '.join(gaps)}"
    else:
        summary += "Full stack detected ✅"
    return summary
