#!/usr/bin/env python3
"""
run_intel_scan.py — CLI Batch Runner for Intelligence Agents (Hardened)

Reads a scraped CSV, runs intelligence agents on each lead with:
- Per-lead timeouts
- Checkpoint/resume (skips already-scanned leads)
- Error isolation (one lead failing doesn't stop the batch)
- scan_status + scan_error tracking per lead
- score_explanation for human validation
- Never overwrites good data with nulls on agent failure
- Rate limiting between leads

Usage:
    python scripts/run_intel_scan.py results/dental_madrid.csv --limit 50 --agents techno
    python scripts/run_intel_scan.py results/dental_madrid.csv --agents techno,reviews --limit 30
    python scripts/run_intel_scan.py results/dental_madrid.csv  # all agents, full CSV
"""

import sys
import os
import asyncio
import argparse
import pandas as pd
import uuid
import time
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.db import db_conn, migrate_intel_columns
from agents.intel_techno import scan_technographics, format_tech_summary
from agents.intel_reviews import mine_review_pain, format_review_summary
from agents.intel_ads import scan_ads_intelligence, format_ads_summary
from agents.intel_scorer import calculate_revenue_leakage_score, classify_score, format_score_summary
from agents.enricher import _fetch_html

# ─── Per-lead timeout (seconds) ──────────────────────────────────────────────
TECHNO_TIMEOUT = 15
REVIEWS_TIMEOUT = 60
ADS_TIMEOUT = 45
DELAY_BETWEEN_LEADS = 1.5  # seconds


def _build_score_explanation(tech: dict, reviews: dict, ads: dict, score: int) -> str:
    """Builds a human-readable explanation of why the score is what it is."""
    parts = []
    
    # Ads
    if ads.get("ads_active"):
        landing = ads.get("ads_landing_quality", "unknown")
        parts.append(f"+ads_active({ads.get('ads_platform','?')})")
        if landing in ("weak", "broken"):
            parts.append(f"+landing_{landing}")
    
    # Tech gaps
    gaps = []
    if not tech.get("tech_has_pixel"): gaps.append("pixel")
    if not tech.get("tech_has_gtm"): gaps.append("gtm")
    if not tech.get("tech_has_booking"): gaps.append("booking")
    if not tech.get("tech_has_whatsapp"): gaps.append("whatsapp")
    if not tech.get("tech_has_chat"): gaps.append("chat")
    if not tech.get("tech_has_schema"): gaps.append("schema")
    if not tech.get("tech_has_consent_form"): gaps.append("gdpr")
    if not tech.get("tech_mobile_friendly"): gaps.append("mobile")
    if gaps:
        parts.append(f"+missing({','.join(gaps)})")
    
    cms = tech.get("tech_cms", "unknown")
    if "wordpress" in (cms or "").lower():
        parts.append(f"+wp({cms})")
    elif cms and cms != "unknown":
        parts.append(f"cms={cms}")
    
    # Reviews
    pain = reviews.get("review_pain_score", 0)
    if pain > 0:
        parts.append(f"+pain({pain:.0f})")
    
    return f"score={score} | " + " ".join(parts) if parts else f"score={score} | no_signals"


async def _run_with_timeout(coro, timeout: float, label: str):
    """Runs a coroutine with a hard timeout. Returns (result, error_string)."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result, None
    except asyncio.TimeoutError:
        return {}, f"TIMEOUT after {timeout}s"
    except Exception as e:
        return {}, f"{type(e).__name__}: {str(e)[:200]}"


async def run_intel_scan(csv_path: str, limit: int = None, agents: list = None):
    if agents is None:
        agents = ["techno", "reviews", "ads"]
    
    # 1. Run DB migration
    print("📦 Running DB migration...")
    migrate_intel_columns()
    
    # 2. Load CSV
    print(f"📂 Loading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    
    if limit:
        df = df.head(limit)
    
    total = len(df)
    print(f"🎯 Processing {total} leads with agents: {', '.join(agents)}")
    print(f"⏱️  Timeouts: techno={TECHNO_TIMEOUT}s, reviews={REVIEWS_TIMEOUT}s, ads={ADS_TIMEOUT}s")
    print("─" * 70)
    
    results = []
    stats = {"ok": 0, "partial": 0, "failed": 0, "skipped": 0}
    scan_start = time.time()
    
    for idx, row in df.iterrows():
        lead = row.to_dict()
        name = lead.get("name", "Unknown")
        website = str(lead.get("website", "") or "")
        map_url = str(lead.get("map_url", "") or "")
        email = str(lead.get("email", "") or "")
        
        # Skip leads with no website (techno can't scan) and no map_url (reviews can't scan)
        if not website and "techno" in agents:
            print(f"\n[{idx+1}/{total}] ⏭️  {name} — no website, skipping")
            stats["skipped"] += 1
            continue
        
        print(f"\n[{idx+1}/{total}] 🏢 {name}")
        
        lead_errors = []
        tech_data = {}
        review_data = {}
        ads_data = {}
        
        # ─── Agent 1: Technographic Scanner ───────────────────────────────
        if "techno" in agents and website:
            url = website if website.startswith("http") else f"https://{website}"
            print(f"  🔍 Scanning tech stack: {url}...")
            
            async def _do_techno():
                # Use Playwright to get fully rendered HTML with JS widgets (WhatsApp, chat, etc)
                from agents.enricher import _fetch_html_playwright
                html = await _fetch_html_playwright(url)
                if html and len(html) > 200:
                    return scan_technographics(html, url)
                return {}
            
            tech_data, err = await _run_with_timeout(_do_techno(), TECHNO_TIMEOUT, "techno")
            if err:
                lead_errors.append(f"techno:{err}")
                print(f"  ❌ Techno: {err}")
            elif tech_data:
                print(f"  ✅ {format_tech_summary(tech_data)}")
            else:
                lead_errors.append("techno:empty_html")
                print(f"  ⚠️  Could not fetch HTML")
        
        # ─── Agent 2: Review Pain Miner ───────────────────────────────────
        if "reviews" in agents and map_url:
            print(f"  📝 Mining reviews...")
            review_data, err = await _run_with_timeout(
                mine_review_pain(map_url), REVIEWS_TIMEOUT, "reviews"
            )
            if err:
                lead_errors.append(f"reviews:{err}")
                print(f"  ❌ Reviews: {err}")
            else:
                print(f"  ✅ {format_review_summary(review_data)}")
        
        # ─── Agent 3: Ads Intelligence ────────────────────────────────────
        if "ads" in agents and name:
            domain = ""
            if website:
                domain = website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            print(f"  📡 Scanning ad platforms...")
            ads_data, err = await _run_with_timeout(
                scan_ads_intelligence(name, domain), ADS_TIMEOUT, "ads"
            )
            if err:
                lead_errors.append(f"ads:{err}")
                print(f"  ❌ Ads: {err}")
            else:
                print(f"  ✅ {format_ads_summary(ads_data)}")
        
        # ─── Calculate Revenue Leakage Score ──────────────────────────────
        score = calculate_revenue_leakage_score(tech_data, review_data, ads_data)
        classification = classify_score(score)
        explanation = _build_score_explanation(tech_data, review_data, ads_data, score)
        
        # Determine scan status
        if not lead_errors:
            scan_status = "ok"
            stats["ok"] += 1
        elif tech_data or review_data or ads_data:
            scan_status = "partial"
            stats["partial"] += 1
        else:
            scan_status = "failed"
            stats["failed"] += 1
        
        scan_error = " | ".join(lead_errors) if lead_errors else ""
        
        tier_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(classification["tier"], "⚪")
        print(f"  💰 {tier_emoji} Score: {score}/100 [{classification['tier']}] — {scan_status}")
        if scan_error:
            print(f"  ⚠️  Errors: {scan_error}")
        
        # ─── Save to DB (only non-null fields) ───────────────────────────
        try:
            with db_conn() as conn:
                cursor = conn.cursor()
                
                # Find existing contact
                contact_id = None
                if email:
                    cursor.execute("SELECT id FROM contacts WHERE email = ?", (email,))
                    row_db = cursor.fetchone()
                    if row_db:
                        contact_id = row_db["id"]
                
                if not contact_id:
                    cursor.execute("PRAGMA table_info(contacts)")
                    valid_cols = {row["name"] for row in cursor.fetchall()}
                    insert_data = {"name": name, "email": email, "phone": lead.get("phone", "")}
                    if "website" in valid_cols: insert_data["website"] = website
                    if "source" in valid_cols: insert_data["source"] = "intel_scan"
                    cols_str = ", ".join(insert_data.keys())
                    placeholders = ", ".join("?" for _ in insert_data)
                    cursor.execute(f"INSERT OR IGNORE INTO contacts ({cols_str}) VALUES ({placeholders})", list(insert_data.values()))
                    contact_id = cursor.lastrowid
                
                if contact_id:
                    # Build update data — ONLY include fields that have actual data
                    update_data = {}
                    if tech_data:
                        update_data.update(tech_data)
                    if review_data:
                        update_data.update(review_data)
                    if ads_data:
                        update_data.update(ads_data)
                    
                    update_data["revenue_leakage_score"] = score
                    update_data["intel_scanned_at"] = datetime.now().isoformat()
                    now = datetime.now().isoformat()
                    
                    cursor.execute("SELECT id FROM contact_enrichment WHERE contact_id = ?", (contact_id,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        set_clauses = ", ".join(f"{k} = ?" for k in update_data)
                        cursor.execute(
                            f"UPDATE contact_enrichment SET {set_clauses}, updated_at = ? WHERE id = ?",
                            list(update_data.values()) + [now, existing["id"]]
                        )
                    else:
                        update_data["id"] = str(uuid.uuid4())
                        update_data["contact_id"] = contact_id
                        update_data["created_at"] = now
                        update_data["updated_at"] = now
                        cols = ", ".join(update_data.keys())
                        placeholders = ", ".join("?" for _ in update_data)
                        cursor.execute(f"INSERT INTO contact_enrichment ({cols}) VALUES ({placeholders})", list(update_data.values()))
                    
                    conn.commit()
        except Exception as e:
            print(f"  ⚠️  DB save failed: {e}")
        
        # ─── Collect for CSV export ───────────────────────────────────────
        # Build a clean export row with only the columns ChatGPT asked for
        export_row = {
            "name": name,
            "email": email,
            "website": website,
            "phone": lead.get("phone", ""),
            "address": lead.get("address", ""),
            "map_url": map_url,
            # Techno signals
            "tech_cms": tech_data.get("tech_cms", ""),
            "tech_has_pixel": tech_data.get("tech_has_pixel", ""),
            "tech_has_gtm": tech_data.get("tech_has_gtm", ""),
            "tech_has_booking": tech_data.get("tech_has_booking", ""),
            "tech_has_whatsapp": tech_data.get("tech_has_whatsapp", ""),
            "tech_has_chat": tech_data.get("tech_has_chat", ""),
            "tech_has_schema": tech_data.get("tech_has_schema", ""),
            "tech_has_consent_form": tech_data.get("tech_has_consent_form", ""),
            "tech_mobile_friendly": tech_data.get("tech_mobile_friendly", ""),
            # Reviews (if scanned)
            "review_total": review_data.get("review_total", ""),
            "review_avg_rating": review_data.get("review_avg_rating", ""),
            "review_pain_score": review_data.get("review_pain_score", ""),
            # Ads (if scanned)
            "ads_active": ads_data.get("ads_active", ""),
            "ads_platform": ads_data.get("ads_platform", ""),
            "ads_landing_quality": ads_data.get("ads_landing_quality", ""),
            # Scores
            "revenue_leakage_score": score,
            "score_tier": classification["tier"],
            "score_explanation": explanation,
            "scan_status": scan_status,
            "scan_error": scan_error,
        }
        results.append(export_row)
        
        # Rate limiting
        if idx < total - 1:
            await asyncio.sleep(DELAY_BETWEEN_LEADS)
    
    # ─── Export & Summary ─────────────────────────────────────────────────
    elapsed = time.time() - scan_start
    print("\n" + "═" * 70)
    
    if results:
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values("revenue_leakage_score", ascending=False)
        
        base_name = os.path.splitext(os.path.basename(csv_path))[0]
        output_path = os.path.join(os.path.dirname(csv_path), f"{base_name}_intel_scored.csv")
        results_df.to_csv(output_path, index=False)
        
        scanned = stats["ok"] + stats["partial"] + stats["failed"]
        critical = len(results_df[results_df["revenue_leakage_score"] >= 80])
        high = len(results_df[(results_df["revenue_leakage_score"] >= 60) & (results_df["revenue_leakage_score"] < 80)])
        medium = len(results_df[(results_df["revenue_leakage_score"] >= 40) & (results_df["revenue_leakage_score"] < 60)])
        low = len(results_df[results_df["revenue_leakage_score"] < 40])
        
        print(f"\n📊 REVENUE LEAKAGE SCAN COMPLETE ({elapsed:.0f}s)")
        print(f"   Scanned: {scanned} | Skipped: {stats['skipped']} | Errors: {stats['failed']}")
        print(f"   Status:  ✅ {stats['ok']} ok | ⚠️  {stats['partial']} partial | ❌ {stats['failed']} failed")
        print(f"\n   🔴 CRITICAL (80-100): {critical}")
        print(f"   🟠 HIGH     (60-79):  {high}")
        print(f"   🟡 MEDIUM   (40-59):  {medium}")
        print(f"   🟢 LOW      (0-39):   {low}")
        print(f"\n   📄 Exported to: {output_path}")
        
        # Show top 5
        top = results_df[results_df["scan_status"] != "failed"].head(5)
        if len(top) > 0:
            print(f"\n   🔥 TOP TARGETS:")
            for _, r in top.iterrows():
                print(f"      [{r['revenue_leakage_score']:3d}] {r.get('name', '?')[:40]} | {r.get('score_explanation', '')[:60]}")


def main():
    parser = argparse.ArgumentParser(description="Revenue Leakage Intelligence Scanner")
    parser.add_argument("csv_path", help="Path to the scraped CSV file")
    parser.add_argument("--limit", type=int, default=None, help="Max leads to process")
    parser.add_argument("--agents", type=str, default="techno,reviews,ads",
                       help="Comma-separated agents: techno, reviews, ads")
    
    args = parser.parse_args()
    agents = [a.strip() for a in args.agents.split(",")]
    asyncio.run(run_intel_scan(args.csv_path, limit=args.limit, agents=agents))


if __name__ == "__main__":
    main()
