from __future__ import annotations
import os
import re
import glob
import shutil
import sqlite3
import json
import asyncio
from datetime import datetime
import pandas as pd

# Define absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
STATE_DIR = os.path.join(BASE_DIR, "state")
DB_PATH = os.path.join(STATE_DIR, "contacts.db")

# Basic Email validation regex
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')

# Blacklist of invalid placeholder emails
EMAIL_BLACKLIST = {
    "info@website.com", "email@example.com", "test@test.com", "noreply@example.com",
    "noemail@example.com", "none@example.com", "noemail", "none", "null", "undefined",
    "example.com", "website.com", "test@example.com"
}

def is_blacklisted_email(email: str | None) -> bool:
    """Checks if an email is a generic placeholder or part of the blacklist."""
    if not email:
        return True
    e = email.strip().lower()
    if e in EMAIL_BLACKLIST:
        return True
    if e.endswith("@example.com") or e.endswith("@website.com") or e.endswith("@yourdomain.com"):
        return True
    # If the domain is just a placeholder
    parts = e.split("@")
    if len(parts) == 2:
        domain = parts[1]
        if domain in ["example.com", "website.com", "domain.com", "placeholder.com"]:
            return True
    return False

def clean_phone(phone: str | None) -> str | None:
    """Sanitizes phone number leaving it in a standard tel: or + format."""
    if pd.isna(phone) or not phone:
        return None
    p = str(phone).strip()
    if p.lower().startswith("tel:"):
        p = p[4:]
    # Remove whitespace, parentheses, dashes
    p = re.sub(r'[\s\-\(\)]', '', p)
    if not p:
        return None
    return f"tel:{p}" if not p.startswith("+") else p

def clean_email(email: str | None) -> str | None:
    """Sanitizes and normalizes email address."""
    if pd.isna(email) or not email:
        return None
    e = str(email).strip().lower()
    if not EMAIL_REGEX.match(e):
        # Fallback loose validation
        if "@" in e and "." in e:
            return e
        return None
    return e

def clean_text(text: str | None) -> str | None:
    """Trim and clean general string fields."""
    if pd.isna(text) or not text:
        return None
    val = str(text).strip()
    return val if val else None

def normalize_name(name: str | None) -> str | None:
    """Normalizes names by capitalizing words."""
    cleaned = clean_text(name)
    if not cleaned:
        return None
    # Title-case but keep abbreviations
    return " ".join(word.capitalize() for word in cleaned.split())

# ── AI-powered metadata classifier ─────────────────────────────────────────
_INDUSTRY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Music Promotion / Directory", ["blog", "blogs", "blogger", "database", "directory", "submit your music", "playlist submission", "curator list", "envía tu música"]),
    ("Restaurant / Hospitality", ["restaurant", "restaurante", "food", "grill", "asador", "café", "comida", "gastrono", "bistró", "taberna", "tapería", "heladería", "gelateria", "helados", "ice cream", "gelato", "cafetería", "bakery", "panadería", "pastelería", "pizzería", "sushi", "ramen", "cocina", "catering"]),
    ("Music / Playlist Curator", ["playlist", "curator", "music curator"]),
    ("Music Studio", ["music", "studio", "grabación", "salsa", "mambo", "radio", "channel", "sound", "audio", "beat", "producer", "cantante", "artista"]),
    ("Dance Academy", ["dance", "baile", "academia", "danz", "salsa academy", "dance school"]),
    ("Healthcare / Physiotherapy", ["fisioter", "physio", "dental", "dentis", "clinic", "clínica", "salud", "osteopat", "médic", "rehabilit", "doctor", "health", "hospital"]),
    ("Nightlife / Club", ["nightclub", "discoteca", "club nocturno", "nightlife"]),
    ("Marketing Agency", ["marketing", "seo", "agencia de marketing", "agencia de publicidad", "advertising", "digital agency", "consultora de marketing", "servicio de marketing"]),
    ("Real Estate", ["inmobiliaria", "real estate", "property", "bienes raíces", "agencia inmobiliaria"]),
    ("Fitness / Gym", ["gym", "gimnasio", "fitness", "crossfit", "pilates", "yoga", "personal trainer"]),
    ("Beauty / Wellness", ["peluquería", "salón de belleza", "beauty salon", "barbería", "barbershop", "spa", "estética", "nail"]),
    ("Retail / E-commerce", ["tienda", "store", "shop", "boutique", "retail", "ecommerce", "e-commerce"]),
    ("Technology", ["software", "tech", "tecnología", "app", "startup", "it services", "consultora tecnológica"]),
    ("Education", ["academia", "escuela", "colegio", "instituto", "universidad", "school", "tutoring", "formación"]),
    ("Legal / Financial", ["abogad", "lawyer", "notaría", "gestoría", "asesoría", "contabilidad", "accounting", "financial"]),
    ("Hotel / Tourism", ["hotel", "hostal", "alojamiento", "tourism", "turismo", "airbnb", "b&b", "resort"]),
    ("Construction / Architecture", ["construcción", "arquitectura", "reformas", "interiorismo", "contractor"]),
    ("Automotive", ["taller", "garage", "automoción", "car wash", "concesionario", "automotive"]),
    ("Photography / Video", ["fotografía", "photography", "videographer", "filmmaker", "fotógrafo"]),
]

_CITY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Palma de Mallorca", ["palma", "mallorca", "baleares", "calvià", "manacor", "illes balears"]),
    ("Ibiza", ["ibiza", "eivissa", "sant josep", "santa eulalia", "formentera"]),
    ("London", ["london", "londres", "hackney", "shoreditch", "camden", "brixton"]),
    ("Barcelona", ["barcelona", "bcn", "catalunya", "cataluña", "badalona", "hospitalet", "terrassa"]),
    ("Madrid", ["madrid", "comunidad de madrid", "alcalá", "móstoles", "alcobendas", "getafe"]),
    ("Valencia", ["valencia", "valenciana", "alicante", "castellón"]),
    ("Seville", ["sevilla", "seville", "andalucía"]),
    ("Bilbao", ["bilbao", "bilbo", "país vasco", "euskadi", "donostia", "san sebastián"]),
    ("Cologne", ["köln", "cologne", "nordrhein", "westfalen", "düsseldorf"]),
    ("Berlin", ["berlin", "berlín"]),
    ("Paris", ["paris", "île-de-france"]),
    ("New York", ["new york", "nyc", "brooklyn", "manhattan", "queens"]),
    ("Miami", ["miami", "florida"]),
]

def _infer_metadata_heuristic(row: dict, filename: str) -> dict:
    """
    Fast keyword-based heuristic classifier (rules_v2).
    Checks category, address, filename and name against known keywords.
    Returns industry, city, country and acquisition_source.
    """
    category = clean_text(row.get('category')) or ""
    address = clean_text(row.get('address')) or ""
    map_url = clean_text(row.get('map_url')) or ""
    name = clean_text(row.get('name')) or ""

    cat_lower = category.lower()
    addr_lower = address.lower()
    file_lower = filename.lower()
    name_lower = name.lower()
    combined = f"{cat_lower} {name_lower} {addr_lower} {file_lower}"

    # Industry
    industry = "Unclassified"
    subcat = category if category else "General Prospect"
    for ind_name, keywords in _INDUSTRY_KEYWORDS:
        if any(k in combined for k in keywords):
            industry = ind_name
            subcat = category if category else ind_name
            break
    # Special: bar standalone word
    if industry == "Unclassified" and re.search(r'\bbar\b', combined):
        industry = "Restaurant / Hospitality"
        subcat = "Bar / Grill"

    # City
    city = "Unknown"
    country = "Unknown"
    for city_name, keywords in _CITY_KEYWORDS:
        if any(k in addr_lower or k in file_lower or k in name_lower for k in keywords):
            city = city_name
            break

    # Country fallback
    if city in ("Madrid", "Barcelona", "Valencia", "Seville", "Bilbao", "Ibiza", "Palma de Mallorca"):
        country = "Spain"
    elif city in ("London",):
        country = "United Kingdom"
    elif city in ("Cologne", "Berlin"):
        country = "Germany"
    elif city in ("Paris",):
        country = "France"
    elif city in ("New York", "Miami"):
        country = "United States"
    elif "spain" in addr_lower or "españa" in addr_lower:
        country = "Spain"
    elif "uk" in addr_lower or "united kingdom" in addr_lower or "england" in addr_lower:
        country = "United Kingdom"

    # Source
    source = "Unknown"
    if "youtube.com" in map_url or "youtu.be" in map_url or "youtube" in cat_lower:
        source = "YouTube API"
    elif "google.com/maps" in map_url or "maps" in file_lower or "españa" in addr_lower:
        source = "Google Maps"
    elif map_url and map_url.startswith("http") and not ("google.com" in map_url or "youtube.com" in map_url):
        source = "Web Search"
    elif row.get('website') and str(row.get('website')).startswith("http"):
        source = "Web Search"

    return {
        "industry": industry,
        "subcategory": subcat,
        "city": city,
        "country": country,
        "acquisition_source": source
    }


def infer_metadata(row: dict, filename: str) -> dict:
    """
    Smart classifier (rules_v2 + AI fallback).
    First tries the fast keyword heuristic. If industry or city remain
    Unclassified / Unknown, calls Gemini once to fill in the gaps.
    Fully synchronous wrapper — runs the async AI call in a fresh thread to avoid event loop conflicts.
    """  
    result = _infer_metadata_heuristic(row, filename)

    # If both are already classified, return immediately (no AI cost)
    if result["industry"] != "Unclassified" and result["city"] != "Unknown":
        return result

    # AI fallback for unclassified leads
    try:
        category = clean_text(row.get('category')) or ""
        address = clean_text(row.get('address')) or ""
        name = clean_text(row.get('name')) or ""
        
        # Run the async coroutine in a separate thread pool to prevent event loop collision
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _classify_with_ai(name, category, address))
            ai_result = future.result()
            
        if ai_result:
            if result["industry"] == "Unclassified" and ai_result.get("industry"):
                result["industry"] = ai_result["industry"]
                result["subcategory"] = ai_result.get("subcategory", result["subcategory"])
            if result["city"] == "Unknown" and ai_result.get("city"):
                result["city"] = ai_result["city"]
                if ai_result.get("country"):
                    result["country"] = ai_result["country"]
    except Exception as e:
        print(f"      ⚠️ AI classification failed for '{row.get('name')}': {e}")

    return result


async def _classify_with_ai(name: str, category: str, address: str) -> dict | None:
    """
    Asks Gemini to classify a single business into an industry and city.
    Returns a dict with 'industry', 'subcategory', 'city', 'country' or None on failure.
    """
    from agents.ai_brain import call_gemini
    from agents.ai_brain import parse_json_from_response

    prompt = f"""You are a business classifier. Given a business name, category and address, return ONLY a raw JSON object (no markdown) with these fields:
- "industry": the high-level industry (e.g. "Restaurant / Hospitality", "Marketing Agency", "Healthcare", "Fitness / Gym", "Retail", "Beauty / Wellness", "Hotel / Tourism", "Real Estate", "Technology", "Education", "Legal / Financial", "Automotive", etc.)
- "subcategory": more specific type within that industry
- "city": the city where the business is located. If unknown, return ""
- "country": the country of the business. If unknown, return ""

Business:
- Name: {name}
- Category: {category}
- Address: {address}

Output ONLY the raw JSON object."""

    raw = await call_gemini(prompt)
    return parse_json_from_response(raw)


def _infer_metadata_heuristic_legacy(row: dict, filename: str) -> dict:
    """
    Original heuristic classifier (rules_v1) — kept as reference, not used.
    """
    category = clean_text(row.get('category')) or ""
    address = clean_text(row.get('address')) or ""
    map_url = clean_text(row.get('map_url')) or ""
    name = clean_text(row.get('name')) or ""
    
    cat_lower = category.lower()
    addr_lower = address.lower()
    file_lower = filename.lower()
    name_lower = name.lower()
    
    # 1. INDUSTRY & SUBCATEGORY INFERENCE
    industry = "Unclassified"
    subcat = category if category else "General Prospect"
    category = clean_text(row.get('category')) or ""
    address = clean_text(row.get('address')) or ""
    map_url = clean_text(row.get('map_url')) or ""
    name = clean_text(row.get('name')) or ""
    
    cat_lower = category.lower()
    addr_lower = address.lower()
    file_lower = filename.lower()
    name_lower = name.lower()
    
    # 1. INDUSTRY & SUBCATEGORY INFERENCE
    industry = "Unclassified"
    subcat = category if category else "General Prospect"
    
    # Music Promotion / Directory keywords
    if any(k in cat_lower or k in file_lower or k in name_lower for k in [
        "blog", "blogs", "blogger", "bloggers", "database", "directory", 
        "submit your music", "music blogs", "playlist submission", "curator list", "envía tu música"
    ]):
        industry = "Music Promotion / Directory"
        subcat = "Music Blog Directory"

    # Restaurant / Hospitality keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower or k in addr_lower for k in [
        "restaurant", "restaurants", "restaurante", "restaurantes", "mexican_restaurants",
        "food", "grill", "asador", "café", "comida", "gastronom", "bistró", "taberna", "tapería"
    ]) or any(re.search(r'\bbar\b', t) for t in [cat_lower, file_lower, name_lower, addr_lower]):
        industry = "Restaurant / Hospitality"
        if "mexican" in file_lower or "mexicano" in name_lower or "mexican" in cat_lower:
            subcat = "Mexican Restaurant"
        elif "bar" in cat_lower or "grill" in cat_lower or "bar" in name_lower:
            subcat = "Bar / Grill"
        elif "llevar" in name_lower or "takeaway" in cat_lower:
            subcat = "Takeaway"
        else:
            subcat = "Restaurant"


    # YouTube Curator / Creator
    elif "youtube.com" in map_url or "youtu.be" in map_url or "youtube" in cat_lower or "youtube" in file_lower:
        if any(k in cat_lower or k in file_lower or k in name_lower for k in [
            "music", "playlist", "curator", "salsa", "mambo", "sound", "beat", "producer", "artista"
        ]):
            industry = "Music / Playlist Curator"
            subcat = "YouTube Music Curator"
        else:
            industry = "Creator / YouTube Channel"
            subcat = "YouTube Creator"
            
    # Music Studio keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower for k in [
        "music", "studio", "grabación", "curator", "playlist", "salsa", "mambo",
        "radio", "channel", "sound", "audio", "beat", "producer", "cantante", "artista"
    ]):
        industry = "Music Studio"
        subcat = "Recording Studio"
    
    # Dance Academy keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower for k in [
        "dance", "baile", "academia", "danz", "salsa", "mambo"
    ]) and any(k in cat_lower or k in file_lower for k in ["baile", "dance", "academia", "academy"]):
        industry = "Dance Academy"
        subcat = "Dance School"
        
    # Healthcare / Physiotherapy keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower or k in addr_lower for k in [
        "fisioter", "physio", "dental", "dentis", "clinic", "salud", "osteopat", "médic", 
        "rehabilit", "doctor", "health", "hospital"
    ]):
        industry = "Healthcare / Physiotherapy"
        subcat = "Physiotherapy Clinic"
        
    # Nightlife / Club keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower for k in [
        "club", "nightlife", "pub", "bar", "discoteca", "party", "event", "night"
    ]):
        industry = "Nightlife / Club"
        subcat = "Nightclub"

    # Marketing Agency keywords
    elif any(k in cat_lower or k in file_lower or k in name_lower for k in [
        "marketing", "seo", "agency", "agencia", "publicidad", "advertising", "digital"
    ]):
        industry = "Marketing Agency"
        subcat = "Digital Marketing"

    # 2. CITY & COUNTRY INFERENCE
    city = "Unknown"
    country = "Unknown"
    
    if any(k in addr_lower or k in file_lower or k in name_lower for k in ["palma", "mallorca", "baleares", "calvià", "manacor"]):
        city = "Palma de Mallorca"
        country = "Spain"
    elif any(k in addr_lower or k in file_lower or k in name_lower for k in ["london", "londres", "uk", "united kingdom", "hackney", "london"]):
        city = "London"
        country = "United Kingdom"
    elif any(k in addr_lower or k in file_lower or k in name_lower for k in ["barcelona", "bcn", "catalunya", "cataluña", "badalona", "hospitalet"]):
        city = "Barcelona"
        country = "Spain"
    elif any(k in addr_lower or k in file_lower or k in name_lower for k in ["madrid", "comunidad de madrid", "alcalá", "móstoles"]):
        city = "Madrid"
        country = "Spain"
    elif "spain" in addr_lower or "españa" in addr_lower:
        country = "Spain"
    elif "uk" in addr_lower or "united kingdom" in addr_lower or "england" in addr_lower:
        country = "United Kingdom"

    # 3. ACQUISITION SOURCE INFERENCE
    source = "Unknown"
    if "youtube.com" in map_url or "youtu.be" in map_url or "youtube" in cat_lower:
        source = "YouTube API"
    elif "google.com/maps" in map_url or "maps" in file_lower or "reino unido" in addr_lower or "españa" in addr_lower:
        source = "Google Maps"
    elif map_url and map_url.startswith("http") and not ("google.com" in map_url or "youtube.com" in map_url):
        source = "Web Search"
    elif row.get('website') and str(row.get('website')).startswith("http"):
        source = "Web Search"

    return {
        "industry": industry,
        "subcategory": subcat,
        "city": city,
        "country": country,
        "acquisition_source": source
    }

def analyze_csv_for_preview(csv_path: str, existing_emails: set, existing_maps: set, existing_names_phones: set) -> dict:
    """
    Reads a CSV and computes high-quality ingestion statistics (Read-Only).
    """
    filename = os.path.basename(csv_path)
    report = {
        "filename": filename,
        "total_rows": 0,
        "columns": [],
        "valid_real_emails": 0,
        "placeholder_emails": 0,
        "no_direct_contact_leads": 0,
        "website_only_leads": 0,
        "contactable_leads": 0,
        "email_contactable": 0,
        "phone_contactable": 0,
        "low_contactability": 0,
        "estimated_new": 0,
        "estimated_duplicates": 0,
        "inferred_industry": "Unclassified",
        "inferred_city": "Unknown",
        "inferred_source": "Unknown",
        "warnings": [],
        "sample_leads": []
    }

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        report["warnings"].append(f"Could not parse CSV file: {str(e)}")
        return report

    report["total_rows"] = len(df)
    report["columns"] = [str(c).strip() for c in df.columns]
    
    # Check for basic required columns
    cols_lower = [c.lower() for c in report["columns"]]
    missing_cols = []
    for c in ["name", "email", "phone"]:
        if c not in cols_lower:
            missing_cols.append(c)
    if missing_cols:
        report["warnings"].append(f"Missing recommended column(s): {', '.join(missing_cols)}")

    if report["total_rows"] == 0:
        report["warnings"].append("The CSV file is completely empty.")
        return report

    # Fill NaN to avoid parsing issues
    df = df.fillna("")
    rows = df.to_dict("records")
    
    # Keep track of local duplicates inside this file to avoid double-counting
    local_emails = set()
    local_maps = set()
    local_names_phones = set()

    industries_list = []
    cities_list = []
    sources_list = []
    
    sample_leads = []

    for i, row in enumerate(rows):
        raw_name = clean_text(row.get("name"))
        raw_email = clean_email(row.get("email"))
        raw_phone = clean_phone(row.get("phone"))
        raw_map_url = clean_text(row.get("map_url"))
        raw_website = clean_text(row.get("website"))
        
        # Inferred Metadata
        meta = infer_metadata(row, filename)
        industries_list.append(meta["industry"])
        cities_list.append(meta["city"])
        sources_list.append(meta["acquisition_source"])
        
        # Detect if email is a placeholder
        is_placeholder = False
        if raw_email:
            if is_blacklisted_email(raw_email):
                is_placeholder = True
                report["placeholder_emails"] += 1
                raw_email = None # Nullify placeholder email
            else:
                report["valid_real_emails"] += 1
                
        has_email = raw_email is not None
        has_phone = raw_phone is not None
        has_map = raw_map_url is not None and ("google.com" in raw_map_url or "youtube.com" in raw_map_url)
        has_web = raw_website is not None and raw_website.startswith("http")
        is_contactable = has_email or has_phone

        # Classification of Contactability
        if has_email:
            report["email_contactable"] += 1
            report["contactable_leads"] += 1
        elif has_phone:
            report["phone_contactable"] += 1
            report["contactable_leads"] += 1
        elif has_web:
            report["website_only_leads"] += 1
            report["no_direct_contact_leads"] += 1
        else:
            report["no_direct_contact_leads"] += 1

        if ("youtube.com" in (raw_website or "") or "youtube.com" in (raw_map_url or "")) and not (has_email or has_phone):
            report["low_contactability"] += 1

        # Strict safety check: No email, no phone, no map_url -> invalid lead unless clean website exists
        if not has_email and not has_phone and not has_map and not has_web:
            # Skip deduplication check since we reject it outright
            continue
            
        # Deduplication cascading logic
        is_duplicate = False
        
        # Tier 1: Email check
        if has_email:
            if raw_email in existing_emails or raw_email in local_emails:
                is_duplicate = True
            else:
                local_emails.add(raw_email)
                
        # Tier 2: Map URL check
        elif has_map:
            if raw_map_url in existing_maps or raw_map_url in local_maps:
                is_duplicate = True
            else:
                local_maps.add(raw_map_url)
                
        # Tier 3: Name + Phone check
        elif raw_name and has_phone:
            norm_name = re.sub(r'[^a-z0-9]', '', raw_name.lower())
            norm_phone = re.sub(r'[^0-9]', '', raw_phone)
            pair = (norm_name, norm_phone)
            if pair in existing_names_phones or pair in local_names_phones:
                is_duplicate = True
            else:
                local_names_phones.add(pair)
                
        if is_duplicate:
            report["estimated_duplicates"] += 1
        else:
            report["estimated_new"] += 1

        # Build tags
        tags = []
        if not has_email:
            tags.append("no_direct_email")
        if "youtube.com" in (raw_website or "") or "youtube.com" in (raw_map_url or ""):
            tags.append("youtube_channel")
            if not is_contactable:
                tags.append("low_contactability")

        # Capture sample leads (up to 5)
        if len(sample_leads) < 5:
            sample_leads.append({
                "name": normalize_name(row.get("name")) or "Unknown",
                "email": raw_email or ("Placeholder" if is_placeholder else "None"),
                "phone": raw_phone or "None",
                "website": raw_website or "None",
                "inferred_industry": meta["industry"],
                "inferred_city": meta["city"],
                "inferred_source": meta["acquisition_source"],
                "is_duplicate_estimate": is_duplicate,
                "is_contactable": is_contactable,
                "inferred_tags": tags
            })

    report["sample_leads"] = sample_leads

    # Compute majorities
    if industries_list:
        report["inferred_industry"] = pd.Series(industries_list).value_counts().index[0]
    if cities_list:
        report["inferred_city"] = pd.Series(cities_list).value_counts().index[0]
    if sources_list:
        report["inferred_source"] = pd.Series(sources_list).value_counts().index[0]

    # Percentage warnings
    unusable_leads = report["total_rows"] - report["contactable_leads"] - report["website_only_leads"] - report["estimated_duplicates"]
    if report["total_rows"] > 0:
        pct_unusable = (unusable_leads / report["total_rows"]) * 100
        if pct_unusable > 30:
            report["warnings"].append(f"High ratio of unusable leads: {round(pct_unusable, 1)}% lack actionable direct contact or website.")

    return report

def get_db_existings() -> tuple[set, set, set]:
    """Retrieves existing contact keys from DB for in-memory deduplication."""
    emails = set()
    maps = set()
    names_phones = set()
    
    if not os.path.exists(DB_PATH):
        return emails, maps, names_phones
        
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("SELECT email FROM contacts WHERE email IS NOT NULL")
        for row in cursor.fetchall():
            emails.add(row[0].lower().strip())
            
        cursor.execute("SELECT map_url FROM contacts WHERE map_url IS NOT NULL")
        for row in cursor.fetchall():
            maps.add(row[0].strip())
            
        cursor.execute("SELECT name, phone FROM contacts WHERE name IS NOT NULL AND phone IS NOT NULL")
        for row in cursor.fetchall():
            norm_name = re.sub(r'[^a-z0-9]', '', row[0].lower())
            norm_phone = re.sub(r'[^0-9]', '', row[1])
            names_phones.add((norm_name, norm_phone))
            
        conn.close()
    except Exception as e:
        print(f"⚠️ Error loading existing database identifiers: {str(e)}")
        
    return emails, maps, names_phones

def run_dry_run_report(filename: str = "all", limit: int | None = None) -> dict:
    """Runs a complete dry-run scan without writing anything to DB."""
    emails, maps, names_phones = get_db_existings()
    
    # Locate files
    if filename == "all":
        files = glob.glob(os.path.join(RESULTS_DIR, "*.csv"))
    else:
        target = os.path.join(RESULTS_DIR, filename)
        files = [target] if os.path.exists(target) else []
        
    reports = []
    total_new = 0
    total_dups = 0
    total_scanned = 0
    total_valid_real_emails = 0
    total_placeholder_emails = 0
    total_no_direct_contact = 0
    total_website_only = 0
    total_contactable = 0
    total_email_contactable = 0
    total_phone_contactable = 0
    total_low_contactability = 0
    
    for f in files:
        rep = analyze_csv_for_preview(f, emails, maps, names_phones)
        reports.append(rep)
        
        # Accumulate
        total_scanned += rep["total_rows"]
        total_new += rep["estimated_new"]
        total_dups += rep["estimated_duplicates"]
        total_valid_real_emails += rep["valid_real_emails"]
        total_placeholder_emails += rep["placeholder_emails"]
        total_no_direct_contact += rep["no_direct_contact_leads"]
        total_website_only += rep["website_only_leads"]
        total_contactable += rep["contactable_leads"]
        total_email_contactable += rep["email_contactable"]
        total_phone_contactable += rep["phone_contactable"]
        total_low_contactability += rep["low_contactability"]
        
    return {
        "dry_run": True,
        "total_csv_files": len(files),
        "total_leads_scanned": total_scanned,
        "estimated_new_contacts": total_new,
        "estimated_duplicates": total_dups,
        "valid_real_emails": total_valid_real_emails,
        "placeholder_emails": total_placeholder_emails,
        "no_direct_contact_leads": total_no_direct_contact,
        "website_only_leads": total_website_only,
        "contactable_leads": total_contactable,
        "email_contactable": total_email_contactable,
        "phone_contactable": total_phone_contactable,
        "low_contactability": total_low_contactability,
        "files": reports
    }

def execute_ingest_pipeline(filename: str = "all", dry_run: bool = True, limit: int | None = None) -> dict:
    """
    Executes the secure ingestion pipeline:
    1. If dry_run is True: fully simulates and counts without writing.
    2. If dry_run is False: backs up contacts.db, opens a transaction, normalizes,
       deduplicates and upserts data, then commits. Rolls back completely on failure.
    """
    # Load existing to prevent duplicate insertions
    existing_emails, existing_maps, existing_names_phones = get_db_existings()
    
    # 1. Locate files
    if filename == "all":
        files = glob.glob(os.path.join(RESULTS_DIR, "*.csv"))
        # Sort files to ensure deterministic scans
        files.sort()
    else:
        target = os.path.join(RESULTS_DIR, filename)
        files = [target] if os.path.exists(target) else []
        
    if not files:
        return {
            "status": "error",
            "message": f"No CSV files found for target '{filename}'",
            "files_processed": 0
        }

    # Simulation metrics
    metrics = {
        "files_processed": 0,
        "rows_scanned": 0,
        "estimated_new_contacts": 0,
        "estimated_existing_contacts": 0,
        "estimated_duplicates_skipped": 0,
        "estimated_invalid_rows_skipped": 0,
        "estimated_enrichments_created": 0,
        "estimated_enrichments_updated": 0,
        "valid_real_emails": 0,
        "placeholder_emails": 0,
        "email_contactable": 0,
        "phone_contactable": 0,
        "website_only": 0,
        "low_contactability": 0,
        "no_direct_contact": 0,
        "contactable_leads": 0
    }
    
    breakdown = {
        "industry": {},
        "city": {},
        "acquisition_source": {}
    }
    
    warnings = []
    
    # Samples for reporting
    sample_inserts = []
    sample_duplicates = []
    sample_rejected = []
    
    # In-memory session registries for duplicate tracking during multi-file scan
    session_emails = set()
    session_maps = set()
    session_names_phones = set()
    
    leads_to_write = []
    total_leads_scanned_counter = 0

    # Phase 2 & 3 Scanning Loop
    for file_path in files:
        metrics["files_processed"] += 1
        fn = os.path.basename(file_path)
        
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            warnings.append(f"Could not parse '{fn}': {str(e)}")
            continue
            
        df = df.fillna("")
        rows = df.to_dict("records")
        
        # Structure columns warn
        cols_lower = [str(c).strip().lower() for c in df.columns]
        missing = [c for c in ["name", "email", "phone"] if c not in cols_lower]
        if missing:
            warnings.append(f"File '{fn}' has missing recommended column(s): {', '.join(missing)}")
            
        for row in rows:
            # Check global limit cap
            if limit is not None and total_leads_scanned_counter >= limit:
                break
                
            total_leads_scanned_counter += 1
            metrics["rows_scanned"] += 1
            
            # Normalization
            raw_name = clean_text(row.get("name"))
            raw_email = clean_email(row.get("email"))
            raw_phone = clean_phone(row.get("phone"))
            raw_map_url = clean_text(row.get("map_url"))
            raw_website = clean_text(row.get("website"))
            
            meta = infer_metadata(row, fn)
            
            # Check placeholder email
            is_placeholder = False
            if raw_email:
                if is_blacklisted_email(raw_email):
                    is_placeholder = True
                    metrics["placeholder_emails"] += 1
                    raw_email = None # Nullify placeholder
                else:
                    metrics["valid_real_emails"] += 1
                    
            # Normalize fields
            clean_name = normalize_name(raw_name) or "Unknown"
            clean_phone_val = raw_phone
            clean_email_val = raw_email
            clean_map = raw_map_url
            clean_web = raw_website
            
            has_email = clean_email_val is not None
            has_phone = clean_phone_val is not None
            has_map = clean_map is not None and ("google.com" in clean_map or "youtube.com" in clean_map)
            has_web = clean_web is not None and clean_web.startswith("http")
            
            # Strict safety check: No email, no phone, no map_url -> invalid lead unless clean website exists
            if not has_email and not has_phone and not has_map and not has_web:
                metrics["estimated_invalid_rows_skipped"] += 1
                if len(sample_rejected) < 5:
                    sample_rejected.append({
                        "file": fn,
                        "name": clean_name,
                        "raw_row": row
                    })
                continue
                
            # Classify contactability subsets
            if has_email:
                metrics["email_contactable"] += 1
                metrics["contactable_leads"] += 1
            elif has_phone:
                metrics["phone_contactable"] += 1
                metrics["contactable_leads"] += 1
            elif has_web:
                metrics["website_only"] += 1
                metrics["no_direct_contact"] += 1
            else:
                metrics["no_direct_contact"] += 1
                
            # Check YouTube low contactability tags
            is_youtube_low = False
            if ("youtube.com" in (clean_web or "") or "youtube.com" in (clean_map or "")) and not (has_email or has_phone):
                is_youtube_low = True
                metrics["low_contactability"] += 1
                
            # Deduplication Cascade
            is_duplicate = False
            dup_type = ""
            dup_matched_key = ""
            
            if has_email:
                if clean_email_val in existing_emails or clean_email_val in session_emails:
                    is_duplicate = True
                    dup_type = "Email"
                    dup_matched_key = clean_email_val
                else:
                    session_emails.add(clean_email_val)
                    
            elif has_map:
                if clean_map in existing_maps or clean_map in session_maps:
                    is_duplicate = True
                    dup_type = "Map URL"
                    dup_matched_key = clean_map
                else:
                    session_maps.add(clean_map)
                    
            elif clean_name and has_phone:
                norm_name = re.sub(r'[^a-z0-9]', '', clean_name.lower())
                norm_phone = re.sub(r'[^0-9]', '', clean_phone_val)
                pair = (norm_name, norm_phone)
                if pair in existing_names_phones or pair in session_names_phones:
                    is_duplicate = True
                    dup_type = "Name + Phone"
                    dup_matched_key = f"{clean_name} | {clean_phone_val}"
                else:
                    session_names_phones.add(pair)
                    
            # Accumulate breakdown
            ind = meta["industry"]
            cit = meta["city"]
            src = meta["acquisition_source"]
            
            breakdown["industry"][ind] = breakdown["industry"].get(ind, 0) + 1
            breakdown["city"][cit] = breakdown["city"].get(cit, 0) + 1
            breakdown["acquisition_source"][src] = breakdown["acquisition_source"].get(src, 0) + 1
            
            tags = []
            if not has_email:
                tags.append("no_direct_email")
            if is_youtube_low:
                tags.append("youtube_channel")
                tags.append("low_contactability")
                
            lead_details = {
                "name": clean_name,
                "email": clean_email_val,
                "phone": clean_phone_val,
                "map_url": clean_map,
                "website": clean_web,
                "inferred_industry": ind,
                "inferred_subcategory": meta["subcategory"],
                "inferred_city": cit,
                "inferred_country": meta["country"],
                "inferred_source": src,
                "campaign_origin": fn,
                "tags": tags,
                "is_youtube_low": is_youtube_low
            }
            
            if is_duplicate:
                metrics["estimated_duplicates_skipped"] += 1
                metrics["estimated_existing_contacts"] += 1
                metrics["estimated_enrichments_updated"] += 1
                if len(sample_duplicates) < 5:
                    sample_duplicates.append({
                        "name": clean_name,
                        "matched_by": dup_type,
                        "matched_key": dup_matched_key
                    })
            else:
                metrics["estimated_new_contacts"] += 1
                metrics["estimated_enrichments_created"] += 1
                leads_to_write.append(lead_details)
                if len(sample_inserts) < 5:
                    sample_inserts.append(lead_details)
                    
        # Break outer loop if global limit reached
        if limit is not None and total_leads_scanned_counter >= limit:
            break

    # If dry_run is True, return simulation directly
    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "backup_created": False,
            "backup_path": None,
            "metrics": metrics,
            "breakdown": breakdown,
            "warnings": warnings,
            "sample_insert_payloads": sample_inserts,
            "sample_duplicate_matches": sample_duplicates,
            "sample_rejected_rows": sample_rejected
        }

    # ==============================================================================
    # ━━ REAL WRITE PIPELINE (FASE 3 - ONLY EXECUTED WHEN dry_run=False) ━━━━━━━━━━━
    # ==============================================================================
    
    # 1. Create prevent backup of contacts.db
    backup_file = None
    if not dry_run:
        if os.path.exists(DB_PATH):
            os.makedirs(STATE_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"contacts_backup_before_ingest_{timestamp}.db"
            backup_file = os.path.join(STATE_DIR, backup_name)
            try:
                shutil.copy2(DB_PATH, backup_file)
                print(f"✅ Auto-Backup preventive successfully saved at {backup_file}")
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Auto-Backup failed, aborting write: {str(e)}",
                    "files_processed": 0
                }
                
    # 2. SQL transaction write pipeline
    conn = None
    real_inserted = 0
    real_updated = 0
    real_enrichments_created = 0
    real_enrichments_updated = 0
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        cursor = conn.cursor()
        
        # Force WAL mode and foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("BEGIN TRANSACTION")
        
        for lead in leads_to_write:
            # Upsert contact
            # Check duplicate one last time inside transaction
            clean_email_val = lead["email"]
            clean_map = lead["map_url"]
            clean_phone_val = lead["phone"]
            clean_name = lead["name"]
            
            contact_id = None
            
            # Cascading search in DB
            if clean_email_val:
                cursor.execute("SELECT id FROM contacts WHERE email = ?", (clean_email_val,))
                row = cursor.fetchone()
                if row:
                    contact_id = row[0]
            elif clean_map:
                cursor.execute("SELECT id FROM contacts WHERE map_url = ?", (clean_map,))
                row = cursor.fetchone()
                if row:
                    contact_id = row[0]
            elif clean_name and clean_phone_val:
                # Approximate search in DB
                cursor.execute("SELECT id, name, phone FROM contacts WHERE phone = ?", (clean_phone_val,))
                for row in cursor.fetchall():
                    ex_name = row[1]
                    norm_ex = re.sub(r'[^a-z0-9]', '', ex_name.lower())
                    norm_new = re.sub(r'[^a-z0-9]', '', clean_name.lower())
                    if norm_ex == norm_new:
                        contact_id = row[0]
                        break
                        
            if contact_id:
                # Existing contact. DO NOT alter touch_count or last_contacted_at
                # Update general profile columns if they were missing
                cursor.execute("""
                    UPDATE contacts
                    SET name = COALESCE(NULLIF(name, ''), ?),
                        phone = COALESCE(NULLIF(phone, ''), ?),
                        map_url = COALESCE(NULLIF(map_url, ''), ?),
                        website = COALESCE(NULLIF(website, ''), ?)
                    WHERE id = ?
                """, (clean_name, clean_phone_val, clean_map, lead["website"], contact_id))
                real_updated += 1
            else:
                # Insert contact
                cursor.execute("""
                    INSERT INTO contacts (email, phone, name, map_url, website, touch_count, global_status)
                    VALUES (?, ?, ?, ?, ?, 0, 'active')
                """, (clean_email_val, clean_phone_val, clean_name, clean_map, lead["website"]))
                contact_id = cursor.lastrowid
                real_inserted += 1
                
            # Upsert enrichment record
            cursor.execute("SELECT id FROM lead_enrichment WHERE contact_id = ?", (contact_id,))
            enr_row = cursor.fetchone()
            
            tags_json_str = json.dumps(lead["tags"])
            enrich_status = "Needs Review" if lead["is_youtube_low"] or not clean_email_val else "Enriched"
            
            if enr_row:
                # Update existing enrichment
                cursor.execute("""
                    UPDATE lead_enrichment
                    SET industry = ?,
                        subcategory = ?,
                        city = ?,
                        country = ?,
                        acquisition_source = ?,
                        campaign_origin = ?,
                        tags_json = ?,
                        enrichment_status = ?,
                        enrichment_version = 'rules_v1',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE contact_id = ?
                """, (
                    lead["inferred_industry"], lead["inferred_subcategory"],
                    lead["inferred_city"], lead["inferred_country"],
                    lead["inferred_source"], lead["campaign_origin"],
                    tags_json_str, enrich_status, contact_id
                ))
                real_enrichments_updated += 1
            else:
                # Create new enrichment
                cursor.execute("""
                    INSERT INTO lead_enrichment (
                        contact_id, industry, subcategory, city, country,
                        acquisition_source, campaign_origin, tags_json,
                        classification_confidence, classification_reason,
                        enrichment_status, enrichment_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.8, 'Heuristic classification rules_v1', ?, 'rules_v1')
                """, (
                    contact_id, lead["inferred_industry"], lead["inferred_subcategory"],
                    lead["inferred_city"], lead["inferred_country"],
                    lead["inferred_source"], lead["campaign_origin"],
                    tags_json_str, enrich_status
                ))
                real_enrichments_created += 1
                
        # Commit transaction
        conn.commit()
        conn.close()
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.close()
                print("❌ SQLite Error detected: Transaction rolled back completely.")
            except: pass
        return {
            "status": "error",
            "message": f"Write transaction aborted and rolled back: {str(e)}",
            "files_processed": metrics["files_processed"],
            "backup_path": backup_file
        }
        
    return {
        "status": "success",
        "dry_run": False,
        "backup_created": True,
        "backup_path": backup_file,
        "metrics": {
            "files_processed": metrics["files_processed"],
            "rows_scanned": metrics["rows_scanned"],
            "new_contacts_inserted": real_inserted,
            "existing_contacts_updated": real_updated,
            "duplicates_skipped": metrics["estimated_duplicates_skipped"],
            "invalid_rows_skipped": metrics["estimated_invalid_rows_skipped"],
            "enrichments_created": real_enrichments_created,
            "enrichments_updated": real_enrichments_updated,
            "errors": 0
        },
        "breakdown": breakdown,
        "warnings": warnings
    }
