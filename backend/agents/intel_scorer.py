from __future__ import annotations
"""
intel_scorer.py — Revenue Leakage Score Calculator

Combines signals from all 3 intelligence agents into a single composite score (0-100).
Higher score = more revenue leaking = better lead to contact.

Score breakdown:
  Ads active + landing weak:  max 30 pts
  Tech stack gaps:            max 20 pts
  Review pain signals:        max 15 pts
  No booking/WhatsApp:        max 15 pts
  Compliance gaps:            max 10 pts
  Design debt / old CMS:      max 10 pts
"""


def calculate_revenue_leakage_score(
    tech: dict = None,
    reviews: dict = None,
    ads: dict = None,
) -> int:
    """
    Composite score 0-100. Higher = more revenue leaking = better lead.
    
    Args:
        tech: Output from intel_techno.scan_technographics()
        reviews: Output from intel_reviews.mine_review_pain()
        ads: Output from intel_ads.scan_ads_intelligence()
    
    Returns:
        Integer score 0-100.
    """
    tech = tech or {}
    reviews = reviews or {}
    ads = ads or {}
    
    score = 0
    breakdown = {}
    
    # ─── Ads Intelligence (max 30) ────────────────────────────────────────
    ads_points = 0
    if ads.get("ads_active"):
        ads_points += 15  # Has budget = strongest signal
        landing = ads.get("ads_landing_quality", "unknown")
        if landing == "weak":
            ads_points += 10   # Paying for traffic + can't convert
        elif landing == "broken":
            ads_points += 15   # Paying for traffic + page is broken
    breakdown["ads"] = ads_points
    score += ads_points
    
    # ─── Technographic Gaps (max 20) ──────────────────────────────────────
    tech_points = 0
    if not tech.get("tech_has_pixel"):       tech_points += 4
    if not tech.get("tech_has_gtm"):         tech_points += 3
    if not tech.get("tech_has_schema"):      tech_points += 3
    if not tech.get("tech_mobile_friendly"): tech_points += 5
    breakdown["tech_gaps"] = tech_points
    score += tech_points
    
    # ─── Review Pain (max 15) ─────────────────────────────────────────────
    pain_score = reviews.get("review_pain_score", 0)
    review_points = min(int(pain_score * 0.15), 15)
    breakdown["review_pain"] = review_points
    score += review_points
    
    # ─── Booking/Contact Friction (max 15) ────────────────────────────────
    friction_points = 0
    if not tech.get("tech_has_booking"):   friction_points += 8
    if not tech.get("tech_has_whatsapp"):  friction_points += 7
    breakdown["friction"] = friction_points
    score += friction_points
    
    # ─── Compliance (max 10) ──────────────────────────────────────────────
    compliance_points = 0
    if not tech.get("tech_has_consent_form"): compliance_points += 5
    if not tech.get("tech_has_ssl"):          compliance_points += 5
    breakdown["compliance"] = compliance_points
    score += compliance_points
    
    # ─── Design Debt (max 10) ─────────────────────────────────────────────
    debt_points = 0
    load_time = tech.get("tech_load_time") or 0
    if load_time and load_time > 5:   debt_points += 5
    if not tech.get("tech_has_chat"):  debt_points += 5
    breakdown["design_debt"] = debt_points
    score += debt_points
    
    return min(score, 100)


def classify_score(score: int) -> dict:
    """
    Classifies a Revenue Leakage Score into priority tiers.
    
    Returns:
        dict with 'tier', 'label', 'color', and 'action'.
    """
    if score >= 80:
        return {
            "tier": "CRITICAL",
            "label": "🔴 CRITICAL",
            "color": "#ef4444",
            "action": "Contact FIRST — bleeding money now",
        }
    elif score >= 60:
        return {
            "tier": "HIGH",
            "label": "🟠 HIGH",
            "color": "#f97316",
            "action": "Strong lead — clear pain signals",
        }
    elif score >= 40:
        return {
            "tier": "MEDIUM",
            "label": "🟡 MEDIUM",
            "color": "#eab308",
            "action": "Nurturing / second wave",
        }
    else:
        return {
            "tier": "LOW",
            "label": "🟢 LOW",
            "color": "#22c55e",
            "action": "Not prioritized",
        }


def format_score_summary(score: int, breakdown: dict = None) -> str:
    """Human-readable summary for logs."""
    classification = classify_score(score)
    summary = f"Revenue Leakage Score: {score}/100 → {classification['label']} — {classification['action']}"
    return summary
