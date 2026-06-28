#!/usr/bin/env python3
"""
run_canary_ads_reviews.py — Canary test para Ads (30 leads) + Reviews (100 leads)

Ejecuta:
  python scripts/run_canary_ads_reviews.py results/tu_csv.csv

Produce:
  - results/canary_ads_reviews_report.csv (datos brutos)
  - results/canary_ads_reviews_summary.txt (resumen legible)

Reglas:
  - Ads: 30 leads, Meta primero, Google separado, timeout por plataforma
  - Reviews: 100 leads, solo agregados (nunca texto ni nombres)
  - No sobreescribir datos buenos con null si falla un agente
  - Rate limiting entre leads
  - scan_status y scan_error por agente
  - Paralelo: Meta y Google en paralelo, Reviews secuencial
"""

import sys
import os
import asyncio
import argparse
import pandas as pd
import uuid
import time
import random
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.db import db_conn, migrate_intel_columns
from agents.intel_ads import (
    _scan_meta_ads, _scan_google_ads, _assess_landing_quality,
    _infer_spend_signal, format_ads_summary
)
from agents.intel_reviews import mine_review_pain, format_review_summary

# ─── Timeouts ─────────────────────────────────────────────────────────────────
META_TIMEOUT = 35       # Meta Ad Library is slow
GOOGLE_TIMEOUT = 30     # Google Ads Transparency
LANDING_TIMEOUT = 12    # Landing page quality check
REVIEWS_TIMEOUT = 75    # Reviews can be slow (scrolling)

DELAY_ADS = 3.0         # segundos entre leads para Ads (evitar rate limit)
DELAY_REVIEWS = 2.5     # segundos entre leads para Reviews


async def _run_with_timeout(coro, timeout: float, label: str):
    """Runs a coroutine with a hard timeout. Returns (result, error_string)."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result, None
    except asyncio.TimeoutError:
        return {}, f"TIMEOUT_{label}_{timeout}s"
    except Exception as e:
        return {}, f"{type(e).__name__}: {str(e)[:200]}"


async def run_ads_canary(df: pd.DataFrame, limit: int = 30) -> list[dict]:
    """
    Runs Ads Intelligence scan on up to `limit` leads.
    Returns list of result dicts (one per lead).
    """
    leads = df.head(limit)
    total = len(leads)
    results = []

    print(f"\n{'═'*65}")
    print(f"📡 ADS INTELLIGENCE CANARY — {total} leads")
    print(f"   Meta timeout: {META_TIMEOUT}s | Google timeout: {GOOGLE_TIMEOUT}s")
    print(f"   Delay entre leads: {DELAY_ADS}s")
    print(f"{'═'*65}")

    for i, (_, lead) in enumerate(leads.iterrows()):
        name = str(lead.get("name", "") or "")
        website = str(lead.get("website", "") or "")
        domain = website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

        if not name:
            continue

        print(f"\n[{i+1}/{total}] 🏢 {name[:55]}")
        t_start = time.time()

        meta_result = {}
        google_result = {}
        meta_err = ""
        google_err = ""

        # ─── Meta Ad Library ──────────────────────────────────────────
        print(f"  📣 Scanning Meta Ad Library...")
        meta_result, meta_err = await _run_with_timeout(
            _scan_meta_ads(name), META_TIMEOUT, "META"
        )
        if meta_err:
            print(f"  ⚠️  Meta: {meta_err}")
        else:
            found = meta_result.get("found", False)
            count = meta_result.get("ad_count", 0)
            print(f"  {'✅' if found else '❌'} Meta: {'ACTIVE' if found else 'no ads'} ({count} ads)")

        # ─── Google Ads Transparency ──────────────────────────────────
        print(f"  🔍 Scanning Google Ads Transparency...")
        google_result, google_err = await _run_with_timeout(
            _scan_google_ads(name), GOOGLE_TIMEOUT, "GOOGLE"
        )
        if google_err:
            print(f"  ⚠️  Google: {google_err}")
        else:
            gfound = google_result.get("found", False)
            print(f"  {'✅' if gfound else '❌'} Google: {'ACTIVE' if gfound else 'no ads'}")

        # ─── Compose ads result ───────────────────────────────────────
        has_meta = meta_result.get("found", False) if not meta_err else False
        has_google = google_result.get("found", False) if not google_err else False
        ads_active = has_meta or has_google

        ads_platform = "none"
        if has_meta and has_google:
            ads_platform = "both"
        elif has_meta:
            ads_platform = "meta"
        elif has_google:
            ads_platform = "google"

        ads_landing_url = meta_result.get("landing_url", "") if has_meta else ""
        ads_landing_quality = "unknown"
        if ads_landing_url:
            print(f"  🔗 Checking landing: {ads_landing_url[:60]}")
            quality, lq_err = await _run_with_timeout(
                _assess_landing_quality(ads_landing_url), LANDING_TIMEOUT, "LANDING"
            )
            if lq_err:
                ads_landing_quality = "unknown"
                print(f"  ⚠️  Landing: {lq_err}")
            else:
                ads_landing_quality = quality or "unknown"
                print(f"  {'🔴' if ads_landing_quality == 'weak' else '🟢'} Landing: {ads_landing_quality}")

        ads_category = meta_result.get("category", "") if has_meta else ""
        ads_spend_signal = _infer_spend_signal(
            meta_result if not meta_err else {},
            google_result if not google_err else {}
        )

        # Determine scan status per platform
        errors = []
        if meta_err: errors.append(f"meta:{meta_err}")
        if google_err: errors.append(f"google:{google_err}")

        if not errors:
            ads_scan_status = "ok"
        elif ads_active:
            ads_scan_status = "partial"
        else:
            ads_scan_status = "failed" if (meta_err and google_err) else "partial"

        ads_scan_error = " | ".join(errors)

        elapsed = time.time() - t_start
        tier = "🔴 HOT" if (ads_active and ads_landing_quality in ("weak", "broken")) else (
               "🟠 ACTIVE" if ads_active else "⚪ NO ADS")
        print(f"  💰 {tier} | status={ads_scan_status} | {elapsed:.1f}s")

        results.append({
            "name": name,
            "website": website,
            "email": str(lead.get("email", "") or ""),
            "map_url": str(lead.get("map_url", "") or ""),
            # Ads data
            "ads_active": 1 if ads_active else 0,
            "ads_platform": ads_platform,
            "ads_meta_found": 1 if has_meta else 0,
            "ads_meta_count": meta_result.get("ad_count", 0) if not meta_err else "",
            "ads_google_found": 1 if has_google else 0,
            "ads_landing_url": ads_landing_url,
            "ads_landing_quality": ads_landing_quality,
            "ads_category": ads_category,
            "ads_spend_signal": ads_spend_signal,
            # Validation fields (v2)
            "ads_advertiser_name": meta_result.get("advertiser_name", "") if not meta_err else "",
            "ads_match_confidence": meta_result.get("match_confidence", 0.0) if not meta_err else "",
            "ads_detection_reason": meta_result.get("detection_reason", "") if not meta_err else "",
            "ads_landing_domain": meta_result.get("landing_domain", "") if not meta_err else "",
            # Status tracking
            "ads_scan_status": ads_scan_status,
            "ads_scan_error": ads_scan_error,
        })

        # Rate limiting
        if i < total - 1:
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(DELAY_ADS + jitter)

    return results


async def run_reviews_canary(df: pd.DataFrame, limit: int = 100) -> list[dict]:
    """
    Runs Review Pain Miner on up to `limit` leads.
    Only leads with a map_url are processed.
    Returns list of result dicts (ONLY aggregated counts — no text, no names).
    """
    leads_with_maps = df[df["map_url"].notna() & (df["map_url"].str.len() > 10)].head(limit)
    total = len(leads_with_maps)
    results = []

    print(f"\n{'═'*65}")
    print(f"📝 REVIEWS PAIN MINER CANARY — {total} leads con map_url")
    print(f"   Timeout: {REVIEWS_TIMEOUT}s | Delay entre leads: {DELAY_REVIEWS}s")
    print(f"   ⚠️  Solo se guardan AGREGADOS — sin texto ni nombres de pacientes")
    print(f"{'═'*65}")

    for i, (_, lead) in enumerate(leads_with_maps.iterrows()):
        name = str(lead.get("name", "") or "")
        map_url = str(lead.get("map_url", "") or "")

        print(f"\n[{i+1}/{total}] 🏢 {name[:55]}")
        t_start = time.time()

        review_data, err = await _run_with_timeout(
            mine_review_pain(map_url), REVIEWS_TIMEOUT, "REVIEWS"
        )

        review_scan_status = "failed"
        review_scan_error = ""

        if err:
            review_scan_error = err
            review_scan_status = "failed"
            print(f"  ❌ Reviews: {err}")
            review_data = {}
        else:
            total_rev = review_data.get("review_total", 0)
            avg = review_data.get("review_avg_rating", 0.0)
            pain = review_data.get("review_pain_score", 0.0)
            review_scan_status = "ok" if total_rev > 0 else "empty"
            print(f"  ✅ {format_review_summary(review_data)}")

        elapsed = time.time() - t_start

        # Never store review text or reviewer identifiers — ONLY aggregated counts
        results.append({
            "name": name,
            "website": str(lead.get("website", "") or ""),
            "email": str(lead.get("email", "") or ""),
            "map_url": map_url,
            # Aggregated counts only
            "review_total": review_data.get("review_total", ""),
            "review_avg_rating": review_data.get("review_avg_rating", ""),
            "review_pain_phone": review_data.get("review_pain_phone", ""),
            "review_pain_booking": review_data.get("review_pain_booking", ""),
            "review_pain_web": review_data.get("review_pain_web", ""),
            "review_pain_wait": review_data.get("review_pain_wait", ""),
            "review_pain_score": review_data.get("review_pain_score", ""),
            # Status
            "review_scan_status": review_scan_status,
            "review_scan_error": review_scan_error,
            "elapsed_s": round(elapsed, 1),
        })

        if i < total - 1:
            jitter = random.uniform(0.5, 1.0)
            await asyncio.sleep(DELAY_REVIEWS + jitter)

    return results


def generate_summary(ads_results: list, reviews_results: list, output_dir: str):
    """
    Generates the comprehensive CSV + human-readable summary report.
    """
    ads_df = pd.DataFrame(ads_results) if ads_results else pd.DataFrame()
    rev_df = pd.DataFrame(reviews_results) if reviews_results else pd.DataFrame()

    # ─── Ads summary stats ────────────────────────────────────────────
    ads_total = len(ads_df)
    ads_active = int(ads_df["ads_active"].sum()) if ads_total > 0 else 0
    ads_pct = round(ads_active / ads_total * 100, 1) if ads_total > 0 else 0
    landing_weak = int(ads_df[ads_df["ads_landing_quality"] == "weak"].shape[0]) if ads_total > 0 else 0
    landing_broken = int(ads_df[ads_df["ads_landing_quality"] == "broken"].shape[0]) if ads_total > 0 else 0
    ads_hot = int(ads_df[(ads_df["ads_active"] == 1) & (ads_df["ads_landing_quality"].isin(["weak","broken"]))].shape[0]) if ads_total > 0 else 0
    ads_ok_pct = int(ads_df[ads_df["ads_scan_status"] == "ok"].shape[0]) if ads_total > 0 else 0
    ads_failed_pct = int(ads_df[ads_df["ads_scan_status"] == "failed"].shape[0]) if ads_total > 0 else 0

    # ─── Reviews summary stats ────────────────────────────────────────
    rev_total = len(rev_df)
    rev_ok = int(rev_df[rev_df["review_scan_status"] == "ok"].shape[0]) if rev_total > 0 else 0
    rev_empty = int(rev_df[rev_df["review_scan_status"] == "empty"].shape[0]) if rev_total > 0 else 0
    rev_failed = int(rev_df[rev_df["review_scan_status"] == "failed"].shape[0]) if rev_total > 0 else 0

    pain_scores = []
    if rev_total > 0 and "review_pain_score" in rev_df.columns:
        pain_scores = pd.to_numeric(rev_df["review_pain_score"], errors="coerce").dropna()

    pain_high = int((pain_scores >= 10).sum()) if len(pain_scores) > 0 else 0
    pain_med = int(((pain_scores >= 3) & (pain_scores < 10)).sum()) if len(pain_scores) > 0 else 0
    pain_low = int((pain_scores < 3).sum()) if len(pain_scores) > 0 else 0

    # ─── Write summary text ───────────────────────────────────────────
    summary_path = os.path.join(output_dir, "canary_ads_reviews_summary.txt")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"{'═'*65}\n")
        f.write(f" REVENUE LEAKAGE — ADS + REVIEWS CANARY REPORT\n")
        f.write(f" Generated: {ts}\n")
        f.write(f"{'═'*65}\n\n")

        # ─── ADS ──────────────────────────────────────────────────────
        f.write(f"📡 ADS INTELLIGENCE ({ads_total} leads)\n")
        f.write(f"{'─'*45}\n")
        f.write(f"  Ads detectados:           {ads_active}/{ads_total} ({ads_pct}%)\n")
        f.write(f"  🔴 HOT (ads + weak/broken landing): {ads_hot}\n")
        f.write(f"  Landing weak:             {landing_weak}\n")
        f.write(f"  Landing broken:           {landing_broken}\n")
        f.write(f"  Scan OK:                  {ads_ok_pct}\n")
        f.write(f"  Scan failed:              {ads_failed_pct}\n")

        if ads_total > 0 and "ads_scan_error" in ads_df.columns:
            errors = ads_df[ads_df["ads_scan_error"] != ""]["ads_scan_error"].value_counts()
            if not errors.empty:
                f.write(f"\n  Errores detectados:\n")
                for err, cnt in errors.head(5).items():
                    f.write(f"    [{cnt}x] {str(err)[:80]}\n")

        # Top ads leads (hot = active + weak landing)
        if ads_total > 0:
            hot_leads = ads_df[(ads_df["ads_active"] == 1) & 
                               (ads_df["ads_landing_quality"].isin(["weak","broken"]))]
            if not hot_leads.empty:
                f.write(f"\n  🔥 HOT LEADS (ads activos + landing débil):\n")
                for _, r in hot_leads.iterrows():
                    f.write(f"    - {r['name'][:40]} | {r['ads_platform']} | landing={r['ads_landing_quality']}\n")

        # ─── REVIEWS ──────────────────────────────────────────────────
        f.write(f"\n\n📝 REVIEWS PAIN MINER ({rev_total} leads)\n")
        f.write(f"{'─'*45}\n")
        f.write(f"  Scan OK:                  {rev_ok}\n")
        f.write(f"  Sin reseñas (vacío):      {rev_empty}\n")
        f.write(f"  Fallidos:                 {rev_failed}\n")

        if len(pain_scores) > 0:
            f.write(f"\n  Distribución de review_pain_score:\n")
            f.write(f"    Alta (>=10):  {pain_high}\n")
            f.write(f"    Media (3-9):  {pain_med}\n")
            f.write(f"    Baja (<3):    {pain_low}\n")
            f.write(f"    Avg score:    {round(float(pain_scores.mean()), 2)}\n")
            f.write(f"    Max score:    {round(float(pain_scores.max()), 2)}\n")

        if rev_total > 0 and "review_scan_error" in rev_df.columns:
            errors = rev_df[rev_df["review_scan_error"] != ""]["review_scan_error"].value_counts()
            if not errors.empty:
                f.write(f"\n  Errores detectados:\n")
                for err, cnt in errors.head(5).items():
                    f.write(f"    [{cnt}x] {str(err)[:80]}\n")

        # Top pain leads
        if rev_total > 0 and "review_pain_score" in rev_df.columns:
            top_pain = rev_df.copy()
            top_pain["review_pain_score"] = pd.to_numeric(top_pain["review_pain_score"], errors="coerce")
            top_pain = top_pain.sort_values("review_pain_score", ascending=False).head(10)
            if not top_pain.empty:
                f.write(f"\n  🔥 TOP PAIN LEADS:\n")
                for _, r in top_pain.iterrows():
                    f.write(f"    [{r['review_pain_score']:.1f}] {r['name'][:40]} | "
                            f"phone={r.get('review_pain_phone',0)} booking={r.get('review_pain_booking',0)} "
                            f"wait={r.get('review_pain_wait',0)}\n")

        f.write(f"\n{'═'*65}\n")

    print(f"\n📄 Summary written to: {summary_path}")
    return summary_path


async def main(csv_path: str, ads_limit: int = 30, reviews_limit: int = 100):
    print("📦 Running DB migration...")
    migrate_intel_columns()

    print(f"📂 Loading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"   Total rows: {len(df)}")

    output_dir = os.path.dirname(csv_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ─── Run Ads Canary ───────────────────────────────────────────────
    ads_results = await run_ads_canary(df, limit=ads_limit)

    # Save ads CSV immediately (don't wait for reviews)
    if ads_results:
        ads_df = pd.DataFrame(ads_results)
        ads_csv = os.path.join(output_dir, f"canary_ads_{ts}.csv")
        ads_df.to_csv(ads_csv, index=False)
        print(f"\n✅ Ads results saved: {ads_csv}")

    # ─── Run Reviews Canary ───────────────────────────────────────────
    reviews_results = await run_reviews_canary(df, limit=reviews_limit)

    # Save reviews CSV immediately
    if reviews_results:
        rev_df = pd.DataFrame(reviews_results)
        rev_csv = os.path.join(output_dir, f"canary_reviews_{ts}.csv")
        rev_df.to_csv(rev_csv, index=False)
        print(f"\n✅ Reviews results saved: {rev_csv}")

    # ─── Generate combined summary ────────────────────────────────────
    summary_path = generate_summary(ads_results, reviews_results, output_dir)

    # ─── Print summary to terminal ────────────────────────────────────
    with open(summary_path, "r", encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ads + Reviews Canary Test")
    parser.add_argument("csv_path", help="Path to the scraped CSV file")
    parser.add_argument("--ads-limit", type=int, default=30)
    parser.add_argument("--reviews-limit", type=int, default=100)
    args = parser.parse_args()

    asyncio.run(main(args.csv_path, ads_limit=args.ads_limit, reviews_limit=args.reviews_limit))
