import sqlite3
import os
import json
import uuid
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "contacts.db")
CAMPAIGNS_DIR = os.path.join(os.path.dirname(__file__), "..", "campaigns")

def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_campaign_json(campaign_id):
    path = os.path.join(CAMPAIGNS_DIR, f"{campaign_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

import random

def _calculate_schedule(settings, total_valid_leads, limit_key="daily_email_limit", time_offset_hours=0):
    now = datetime.now()
    schedule_mode = settings.get("campaign_schedule_mode", "manual")
    daily_quota_mode = settings.get("daily_quota_mode", "auto")
    active_weekdays = settings.get("active_weekdays", [0, 1, 2, 3, 4]) 
    daily_limit_val = settings.get(limit_key, 50)
    custom_daily_quotas = settings.get("custom_daily_quotas", {})
    send_window = settings.get("send_window", {"start": 9, "end": 17})
    
    start_date_str = settings.get("campaign_start_date")
    end_date_str = settings.get("campaign_end_date")
    
    if start_date_str:
        try:
            start_date = datetime.fromisoformat(start_date_str).date()
        except:
            start_date = now.date()
    else:
        start_date = now.date()
        
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str).date()
        except:
            pass

    start_hour = send_window.get("start", 9)
    end_hour = send_window.get("end", 17)
    if start_hour >= end_hour:
        end_hour = start_hour + 8
        
    scheduled_times = []
    
    current_date = start_date
    if current_date == now.date() and now.hour >= end_hour:
        current_date += timedelta(days=1)
    elif current_date < now.date():
        current_date = now.date()
        
    leads_scheduled = 0
    
    while leads_scheduled < total_valid_leads:
        if end_date and current_date > end_date:
            break # Exceeded campaign end date
            
        if current_date.weekday() not in active_weekdays:
            current_date += timedelta(days=1)
            continue
            
        if daily_quota_mode == "custom":
            day_name = current_date.strftime("%A").lower()
            daily_limit = custom_daily_quotas.get(day_name, daily_limit_val)
        else:
            daily_limit = daily_limit_val
            
        if daily_limit <= 0:
            current_date += timedelta(days=1)
            continue
            
        leads_for_today = min(daily_limit, total_valid_leads - leads_scheduled)
        
        window_minutes = (end_hour - start_hour) * 60
        gap_minutes = window_minutes / max(1, leads_for_today - 1) if leads_for_today > 1 else window_minutes
            
        for i in range(leads_for_today):
            base_time = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=start_hour + time_offset_hours, minutes=i*gap_minutes)
            
            # Apply time jitter if enabled
            if settings.get("time_jitter", False):
                # Max jitter is 15% of the gap between sends (or +/- 5 mins if gap is very small)
                jitter_mins = max(5, gap_minutes * 0.15)
                salt = random.uniform(-jitter_mins, jitter_mins)
                base_time += timedelta(minutes=salt)
                
            if base_time < now:
                base_time = now + timedelta(minutes=random.uniform(2, 8))
            scheduled_times.append(base_time.isoformat())
            leads_scheduled += 1
            
        current_date += timedelta(days=1)
        
    estimated_end = scheduled_times[-1] if scheduled_times else None
    
    return {
        "limit_per_day": daily_limit_val if daily_quota_mode == "auto" else "Custom",
        "estimated_end_date": estimated_end,
        "daily_limit_applied": daily_limit_val,
        "window_applied": f"{start_hour}:00 - {end_hour}:00",
        "active_weekdays": active_weekdays,
        "campaign_schedule_mode": schedule_mode
    }, scheduled_times

def sync_campaign_leads_to_db(campaign_id, camp_json, conn):
    cursor = conn.cursor()
    for lead in camp_json.get("leads", []):
        email = lead.get("email")
        if not email or '@' not in email: continue
        status = lead.get("status", "pending")
        
        # Ensure contact exists
        cursor.execute("INSERT OR IGNORE INTO contacts (email, global_status) VALUES (?, 'active')", (email,))
        
        # Get lead_id
        cursor.execute("SELECT id FROM contacts WHERE email = ?", (email,))
        contact_row = cursor.fetchone()
        if not contact_row: continue
        lead_id = contact_row['id']
        
        # Ensure campaign_contact exists
        cursor.execute("INSERT OR IGNORE INTO campaign_contacts (campaign_id, lead_id, current_lead_status) VALUES (?, ?, ?)",
            (campaign_id, lead_id, status))
    conn.commit()

def preview_enqueue_pending_campaign_jobs(campaign_id):
    camp_json = get_campaign_json(campaign_id)
    if not camp_json:
        return {"error": "Campaign JSON not found"}
        
    if camp_json.get("status") not in ["active", "drafted", "paused"]:
        return {"error": "Campaign is not in a valid state to enqueue."}
        
    with db_conn() as conn:
        sync_campaign_leads_to_db(campaign_id, camp_json, conn)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT cc.id as campaign_contact_id, cc.lead_id as contact_id, cc.current_lead_status,
                   c.email, c.global_status
            FROM campaign_contacts cc
            JOIN contacts c ON cc.lead_id = c.id
            WHERE cc.campaign_id = ?
        """, (campaign_id,))
        
        rows = cursor.fetchall()
        
        total_pending = 0
        contactable = 0
        suppressed = 0
        bounced = 0
        replied = 0
        unsubscribed = 0
        no_email = 0
        already_queued = 0
        
        valid_leads = []
        
        for row in rows:
            if not row['email'] or '@' not in row['email']:
                no_email += 1
                continue
                
            status = row['current_lead_status'] or 'pending_approval'
            global_status = row['global_status']
            
            if status in ['pending_approval', 'pending']:
                total_pending += 1
                
                # Check global suppression list explicitly
                cursor.execute("SELECT email FROM global_suppression_list WHERE email = ?", (row['email'],))
                is_suppressed = cursor.fetchone() is not None
                
                # Full Stop conditions check
                if global_status == 'suppressed' or status == 'suppressed' or is_suppressed:
                    suppressed += 1
                elif global_status == 'bounced' or status == 'bounced':
                    bounced += 1
                elif global_status == 'unsubscribed' or status == 'unsubscribed':
                    unsubscribed += 1
                elif global_status == 'replied' or status == 'replied':
                    replied += 1
                else:
                    # Check if step already sent or queued
                    cursor.execute("SELECT id, status FROM outbox_jobs WHERE campaign_id=? AND campaign_contact_id=? AND step='initial'", 
                                 (campaign_id, row['campaign_contact_id']))
                    existing = cursor.fetchone()
                    if existing:
                        already_queued += 1
                    else:
                        contactable += 1
                        valid_leads.append(row)
                        
    if not valid_leads:
        return {
            "campaign_id": campaign_id,
            "campaign_name": camp_json.get("pitch", "Unnamed"),
            "total_leads_pending": total_pending,
            "leads_contactable": 0,
            "jobs_iniciales_a_crear": 0,
            "already_queued": already_queued,
            "warnings": ["No valid leads left to queue or exceeded end date"]
        }
        
    # Cross reference to see how many have email vs whatsapp
    email_count = 0
    wa_count = 0
    leads_dict = {l.get("email"): l for l in camp_json.get("leads", [])}
    for r in valid_leads:
        l_data = leads_dict.get(r['email'], {})
        if l_data.get("draft_email_body"): email_count += 1
        if l_data.get("draft_whatsapp_body"): wa_count += 1

    plan_e, times_e = _calculate_schedule(camp_json.get("settings", {}), email_count, "daily_email_limit", 0)
    plan_w, times_w = _calculate_schedule(camp_json.get("settings", {}), wa_count, "daily_whatsapp_limit", 0)
    
    total_jobs = len(times_e) + len(times_w)
    
    return {
        "campaign_id": campaign_id,
        "campaign_name": camp_json.get("pitch", "Unnamed"),
        "total_leads_pending": total_pending,
        "leads_contactable": contactable,
        "leads_suppressed": suppressed,
        "leads_bounced": bounced,
        "leads_replied": replied,
        "leads_unsubscribed": unsubscribed,
        "leads_sin_email": no_email,
        "already_queued": already_queued,
        "jobs_iniciales_a_crear": total_jobs,
        "primer_scheduled_at": times_e[0] if times_e else (times_w[0] if times_w else None),
        "ultimo_scheduled_at": times_e[-1] if times_e else (times_w[-1] if times_w else None),
        "emails_por_dia": plan_e["limit_per_day"],
        "whatsapp_por_dia": plan_w["limit_per_day"],
        "daily_limit_aplicado": plan_e["daily_limit_applied"],
        "ventana_horaria_aplicada": plan_e["window_applied"],
        "active_weekdays": plan_e["active_weekdays"],
        "campaign_schedule_mode": plan_e["campaign_schedule_mode"],
        "fecha_estimada_fin": plan_e["estimated_end_date"],
        "warnings": []
    }

def enqueue_pending_campaign_jobs(campaign_id, confirm=False):
    if not confirm:
        return {"error": "Must explicitly set confirm=True"}
        
    preview = preview_enqueue_pending_campaign_jobs(campaign_id)
    if "error" in preview:
        return preview
        
    if preview.get("jobs_iniciales_a_crear", 0) == 0:
        return {"message": "No jobs to create", "preview": preview}
        
    camp_json = get_campaign_json(campaign_id)
    
    with db_conn() as conn:
        sync_campaign_leads_to_db(campaign_id, camp_json, conn)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT cc.id as campaign_contact_id, cc.lead_id as contact_id, cc.current_lead_status,
                   c.email, c.global_status
            FROM campaign_contacts cc
            JOIN contacts c ON cc.lead_id = c.id
            WHERE cc.campaign_id = ?
        """, (campaign_id,))
        
        rows = cursor.fetchall()
        valid_leads = []
        for row in rows:
            if not row['email'] or '@' not in row['email']: continue
            status = row['current_lead_status'] or 'pending_approval'
            global_status = row['global_status']
            
            cursor.execute("SELECT email FROM global_suppression_list WHERE email = ?", (row['email'],))
            is_suppressed = cursor.fetchone() is not None
            
            if status in ['pending_approval', 'pending'] and global_status not in ['suppressed', 'bounced', 'unsubscribed', 'replied'] and status not in ['suppressed', 'bounced', 'unsubscribed', 'replied'] and not is_suppressed:
                valid_leads.append(row)
                
        leads_dict = {l.get("email"): l for l in camp_json.get("leads", [])}
        
        email_queue = []
        wa_queue = []
        for r in valid_leads:
            l_data = leads_dict.get(r['email'], {})
            if l_data.get("draft_email_body"): email_queue.append(r)
            if l_data.get("draft_whatsapp_body"): wa_queue.append(r)
            
        _, times_e = _calculate_schedule(camp_json.get("settings", {}), len(email_queue), "daily_email_limit", 0)
        _, times_w = _calculate_schedule(camp_json.get("settings", {}), len(wa_queue), "daily_whatsapp_limit", 0)
        
        jobs_created = 0
        already_exists = 0
        now = datetime.now().isoformat()
        
        def _insert_jobs(queue, times, channel):
            nonlocal jobs_created, already_exists
            for i, row in enumerate(queue):
                if i >= len(times): break
                try:
                    cursor.execute("""
                        INSERT INTO outbox_jobs (
                            id, campaign_id, campaign_contact_id, contact_id, channel, step, 
                            scheduled_at, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(uuid.uuid4()), campaign_id, row['campaign_contact_id'], row['contact_id'], 
                        channel, "initial", times[i], "pending", now, now
                    ))
                    jobs_created += 1
                except sqlite3.IntegrityError:
                    already_exists += 1
                    
        _insert_jobs(email_queue, times_e, "email")
        _insert_jobs(wa_queue, times_w, "whatsapp")
                
        conn.commit()
        
    return {
        "message": f"Enqueued {jobs_created} jobs. {already_exists} were already queued.",
        "jobs_created": jobs_created,
        "already_exists": already_exists,
        "preview": preview
    }


def reset_simulated_outbox_jobs(campaign_id):
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE outbox_jobs SET status = 'pending', sent_at = NULL WHERE campaign_id = ? AND status = 'simulated_sent'", (campaign_id,))
        updated = cursor.rowcount
        conn.commit()
    return {"message": f"Reseteados {updated} jobs simulados a estado 'pending'", "reseteados": updated}

def delete_campaign_outbox_jobs(campaign_id):
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM outbox_jobs WHERE campaign_id = ?", (campaign_id,))
        deleted = cursor.rowcount
        conn.commit()
    return {"message": f"Eliminados {deleted} jobs de la campaña", "eliminados": deleted}
