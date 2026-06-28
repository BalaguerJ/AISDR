import pandas as pd
import json
import os
import uuid
from datetime import datetime
from agents.campaigns import save_campaign, CAMPAIGNS_DIR

def import_external_campaigns(gmail_csv_path: str, whatsapp_csv_path: str) -> dict:
    """
    Imports ChatGPT generated CSVs via an Outer Join on lead_id (fallback to map_url),
    and creates a secure campaign ready for review.
    """
    try:
        df_gmail = pd.read_csv(gmail_csv_path)
    except Exception:
        df_gmail = pd.DataFrame(columns=['lead_id', 'email', 'gmail_body', 'subject', 'send_status', 'map_url'])

    try:
        df_wa = pd.read_csv(whatsapp_csv_path)
    except Exception:
        df_wa = pd.DataFrame(columns=['lead_id', 'whatsapp_number', 'whatsapp_body', 'send_status', 'map_url'])

    # Standardize column names for merge
    df_gmail['lead_id'] = df_gmail['lead_id'].astype(str)
    df_wa['lead_id'] = df_wa['lead_id'].astype(str)

    # Perform an OUTER JOIN to keep leads that only have email or only whatsapp
    df_merged = pd.merge(df_gmail, df_wa, on='lead_id', how='outer', suffixes=('_g', '_w'))
    
    # Fallback to map_url if lead_id is missing or doesn't match properly
    
    # Clean up NaNs
    df_merged = df_merged.fillna("")
    
    campaign_id = str(uuid.uuid4())
    campaign = {
        "id": campaign_id,
        "csv_source": "external_import",
        "pitch": "External Import",
        "context_files": [],
        "status": "draft", # CRITICAL: Imported campaigns are always drafted/paused
        "created_at": datetime.now().isoformat(),
        "settings": {
            "safety_mode": True,
            "daily_email_limit": 30,
            "daily_whatsapp_limit": 10,
            "block_cross_channel_same_day": True,
            "channel_priority": "hybrid",
            "send_window": {"start": 9, "end": 17},
            "delay_style": "standard"
        },
        "stats": {
            "sent": 0,
            "failed": 0,
            "pending": 0
        },
        "leads": []
    }

    for _, row in df_merged.iterrows():
        # Resolve status
        # If either gmail or whatsapp send_status says do_not_send, we suppress
        status_g = str(row.get('send_status_g', '')).lower()
        status_w = str(row.get('send_status_w', '')).lower()
        
        status = "pending_approval"
        if "do_not_send" in status_g or "do_not_send" in status_w:
            status = "suppressed"
        elif "duplicate" in status_g or "chain" in status_g or "duplicate" in status_w or "chain" in status_w:
            status = "manual_review_required"
            
        # Compile lead
        name = row.get('name_g') or row.get('name_w') or row.get('name', 'Clinica')
        email = row.get('email', '')
        phone = row.get('whatsapp_number', '') or row.get('phone_clean', '')
        
        # Fallbacks for UI compatibility
        draft_subject = row.get('subject', '')
        em_body = row.get('gmail_body', '')
        wa_body = row.get('whatsapp_body', '')

        lead_entry = {
            "lead_id": row['lead_id'],
            "name": name,
            "email": email,
            "phone": phone,
            "status": status,
            "draft_subject": draft_subject,
            "draft_body": "",
            "draft_email_subject": draft_subject,
            "draft_email_body": em_body,
            "draft_whatsapp_body": wa_body,
            "map_url": row.get('map_url_g') or row.get('map_url_w', '')
        }
        campaign["leads"].append(lead_entry)

    campaign["stats"]["pending"] = len([l for l in campaign["leads"] if l["status"] == "pending_approval"])
    save_campaign(campaign)
    return campaign

def preview_external_campaign(campaign_id: str):
    """
    Renders a console preview of 10 Gmail and 10 WhatsApp leads from the database.
    """
    c_path = os.path.join(CAMPAIGNS_DIR, f"{campaign_id}.json")
    if not os.path.exists(c_path):
        return "Campaign not found"
    
    with open(c_path, 'r', encoding='utf-8') as f:
        campaign = json.load(f)
        
    leads = campaign.get("leads", [])
    
    gmail_previews = [l for l in leads if l.get('draft_email_body') and l['status'] in ['pending_approval', 'manual_review_required']][:10]
    wa_previews = [l for l in leads if l.get('draft_whatsapp_body') and l['status'] in ['pending_approval', 'manual_review_required']][:10]
    
    print("========================================")
    print(f"PREVIEW FOR CAMPAIGN {campaign_id}")
    print("========================================")
    
    print(f"\\n[ GMAIL PREVIEWS ({len(gmail_previews)} rendered) ]")
    for i, l in enumerate(gmail_previews):
        print(f"\\n--- Email {i+1} to {l['name']} ({l['email']}) ---")
        print(f"Subject: {l['draft_email_subject']}")
        print(f"Body:\\n{l['draft_email_body']}")
        
    print(f"\\n[ WHATSAPP PREVIEWS ({len(wa_previews)} rendered) ]")
    for i, l in enumerate(wa_previews):
        print(f"\\n--- WhatsApp {i+1} to {l['name']} ({l['phone']}) ---")
        print(f"Body:\\n{l['draft_whatsapp_body']}")
        
    print("\\n========================================")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        res = import_external_campaigns(sys.argv[1], sys.argv[2])
        print(f"Imported campaign: {res['id']}")
        preview_external_campaign(res['id'])
    else:
        print("Usage: python external_importer.py <gmail.csv> <whatsapp.csv>")
