import asyncio
import json
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
from agents.main import run_prospecting_agent
from agents.campaigns import list_scraped_csvs, draft_campaign, get_campaign, save_campaign, run_campaign_loop, list_campaigns
from agents.outreach_ai import generate_cold_email, score_leads
from agents.outreach_sender import send_gmail_human_like, send_whatsapp_human_like, MAX_DAILY_EMAIL, MAX_DAILY_WHATSAPP, send_gmail_reply
from agents.db import get_contact_info, record_contact, db_conn
from agents.scheduler import preview_enqueue_pending_campaign_jobs, enqueue_pending_campaign_jobs, reset_simulated_outbox_jobs, delete_campaign_outbox_jobs
from agents.inbound.manager import run_inbound_intelligence_loop, process_pending_inbound
from agents.ingestor import run_dry_run_report, execute_ingest_pipeline

class IngestRequest(BaseModel):
    filename: str = "all"
    dry_run: bool = True
    limit: Optional[int] = None

class WhatsAppWebhookPayload(BaseModel):
    source: str
    phone: str
    message: str
    timestamp: str


# Resolve absolute paths to avoid 404s depending on CWD
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
CONTEXT_UPLOADS_DIR = os.path.join(BASE_DIR, "context_uploads")
os.makedirs(CONTEXT_UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="AI Agent Command Center API")

# Enable CORS for the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the frontend URL
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Starts the Agent 3 Inbound Intelligence Engine heartbeat on startup."""
    global inbound_radar_task
    inbound_radar_task = asyncio.create_task(run_inbound_intelligence_loop())
    print("🚀 Agent 3: Inbound Intelligence Heartbeat started.")

# In-memory store for active tasks
active_campaign_tasks = {}
inbound_radar_task = None

class ProspectRequest(BaseModel):
    goal: str
    limit: int = 10
    use_hunt: bool = True
    skip_existing: bool = True

@app.get("/")
async def root():
    return {"status": "online", "agent": "Agent 1: The Prospector"}

@app.websocket("/ws/prospect")
async def websocket_prospect(websocket: WebSocket):
    await websocket.accept()
    agent_task = None
    keepalive_task = None
    try:
        data = await websocket.receive_text()
        params = json.loads(data)
        
        goal = params.get("goal")
        limit = params.get("limit", 10)
        use_hunt = params.get("use_hunt", True)
        skip_existing = params.get("skip_existing", True)
        scraper_mode = params.get("scraper_mode", "maps")
        
        if not goal:
            await websocket.send_json({"type": "error", "message": "No goal provided"})
            return

        # ── Keepalive heartbeat ─────────────────────────────────────────────
        async def keepalive():
            while True:
                await asyncio.sleep(15)
                try:
                    await websocket.send_json({"type": "ping", "message": "⏳ Agent processing..."})
                except Exception:
                    break

        async def run_and_stream():
            async for update in run_prospecting_agent(
                goal=goal,
                limit=limit,
                use_hunt=use_hunt,
                skip_existing=skip_existing,
                headless=True,
                scraper_mode=scraper_mode
            ):
                try:
                    if isinstance(update, str):
                        print(f"[WS LOG] {update}")
                        await websocket.send_json({"type": "log", "message": update})
                    else:
                        print(f"[WS RESULT] Yielded {len(update)} leads")
                        await websocket.send_json({"type": "result", "data": update})
                except Exception as e:
                    print(f"⚠️ Websocket send failed: {e}")
                    pass  # Client disconnected, continue scraping silently

        keepalive_task = asyncio.create_task(keepalive())
        agent_task = asyncio.create_task(run_and_stream())
        
        # Monitor for disconnect while task is running
        while not agent_task.done():
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                print("⚡ Client disconnected during active mission. Disconnecting UI, but Agent will continue in background.")
                keepalive_task.cancel()
                break
        
        # ── Check if agent_task crashed with an exception ──
        if agent_task.done() and agent_task.exception():
            err = agent_task.exception()
            print(f"❌ Agent task crashed: {err}")
            try:
                await websocket.send_json({"type": "error", "message": str(err)})
            except: pass
                
    except WebSocketDisconnect:
        print("⚡ Tactical Disconnect: Client closed window.")
    except Exception as e:
        print(f"❌ WebSocket Error: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except: pass
    finally:
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
            try: await keepalive_task
            except asyncio.CancelledError: pass

        if agent_task and not agent_task.done():
            print("🛡️ Client disconnected, but background Agent 1 task will continue running to finish the CSV!")
            # Intentionally NOT cancelling the task so it finishes the batch
        
        try:
            await websocket.close()
        except: pass



@app.get("/api/lists")
async def get_lists():
    """Returns all available scraped lead CSVs"""
    return {"lists": list_scraped_csvs()}

@app.get("/api/campaigns")
async def get_all_campaigns():
    """Returns a list of all existing campaigns."""
    return {"campaigns": list_campaigns()}

@app.get("/api/campaigns/{campaign_id}")
async def get_campaign_endpoint(campaign_id: str):
    """Returns the state of a specific campaign"""
    camp = get_campaign(campaign_id)
    if not camp:
        return {"error": "Campaign not found"}
    return camp

@app.websocket("/ws/campaign")
async def websocket_campaign_endpoint(websocket: WebSocket):
    """Websocket for drafting campaigns and streaming progress logs."""
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        params = json.loads(data)
        
        csv_filename = params.get("csv_filename")
        pitch = params.get("pitch")
        sender_name = params.get("sender_name", "")
        context_files = params.get("context_files", [])
        
        if not csv_filename or not pitch:
            await websocket.send_json({"type": "error", "message": "Missing csv_filename or pitch"})
            return

        async def ws_log(msg: str):
            await websocket.send_json({"type": "log", "message": msg})

        campaign = await draft_campaign(csv_filename, pitch, sender_name=sender_name, context_files=context_files, log_callback=ws_log)
        await websocket.send_json({"type": "result", "campaign": campaign})
        
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        await websocket.close()
@app.patch("/api/campaigns/{campaign_id}")
async def update_campaign_settings(campaign_id: str, settings: dict):
    """Updates campaign settings (daily limits, delay style, etc.)"""
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Merge settings
    camp["settings"].update(settings)
    save_campaign(camp)
    return camp

@app.get("/api/campaigns/{campaign_id}/preview_enqueue")
async def preview_enqueue(campaign_id: str):
    """Previews the jobs that would be created for pending leads (dry-run)."""
    return preview_enqueue_pending_campaign_jobs(campaign_id)

@app.post("/api/campaigns/{campaign_id}/enqueue")
async def enqueue_jobs(campaign_id: str, data: dict = None):
    """Actually enqueues the pending jobs into outbox_jobs."""
    confirm = (data or {}).get("confirm", False)
    if not confirm:
        raise HTTPException(status_code=400, detail="Must explicitly set confirm=true in payload")
    
    result = enqueue_pending_campaign_jobs(campaign_id, confirm=True)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/campaigns/{campaign_id}/reset_dry_run")
async def reset_dry_run_jobs(campaign_id: str):
    return reset_simulated_outbox_jobs(campaign_id)

@app.delete("/api/campaigns/{campaign_id}/jobs")
async def delete_campaign_jobs(campaign_id: str):
    return delete_campaign_outbox_jobs(campaign_id)

@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign_endpoint(campaign_id: str):
    """Starts the campaign execution loop in the background."""
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    if camp["status"] == "active":
        return {"message": "Campaign is already running"}
    
    camp["status"] = "active"
    save_campaign(camp)
    
    # Start background task
    task = asyncio.create_task(run_campaign_loop(campaign_id))
    active_campaign_tasks[campaign_id] = task
    
    return {"message": "Campaign started", "id": campaign_id}

@app.post("/api/campaigns/{campaign_id}/pause")
async def pause_campaign_endpoint(campaign_id: str):
    """Pauses the campaign."""
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    camp["status"] = "paused"
    save_campaign(camp)
    
    if campaign_id in active_campaign_tasks:
        active_campaign_tasks[campaign_id].cancel()
        del active_campaign_tasks[campaign_id]
        
    return {"message": "Campaign paused", "id": campaign_id}

@app.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign_endpoint(campaign_id: str):
    """Stops and archives the campaign."""
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    camp["status"] = "stopped"
    save_campaign(camp)
    
    if campaign_id in active_campaign_tasks:
        active_campaign_tasks[campaign_id].cancel()
        del active_campaign_tasks[campaign_id]
        
    return {"message": "Campaign stopped", "id": campaign_id}

@app.delete("/api/campaigns/{campaign_id}/leads/{lead_email:path}")
async def delete_campaign_lead(campaign_id: str, lead_email: str):
    """Removes a single lead from the campaign review queue."""
    from urllib.parse import unquote
    lead_email = unquote(lead_email)
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    original_len = len(camp["leads"])
    camp["leads"] = [l for l in camp["leads"] if l.get("email") != lead_email]
    if len(camp["leads"]) == original_len:
        raise HTTPException(status_code=404, detail="Lead not found in campaign")
    camp["stats"]["pending"] = len([l for l in camp["leads"] if l["status"] == "pending_approval"])
    save_campaign(camp)
    return {"message": "Lead removed", "email": lead_email}

@app.patch("/api/campaigns/{campaign_id}/leads/{lead_email:path}")
async def edit_campaign_lead(campaign_id: str, lead_email: str, data: dict):
    """Edits the draft subject and/or body of a single campaign lead."""
    from urllib.parse import unquote
    lead_email = unquote(lead_email)
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for lead in camp["leads"]:
        if lead.get("email") == lead_email:
            if "draft_subject" in data:
                lead["draft_subject"] = data["draft_subject"]
            if "draft_body" in data:
                lead["draft_body"] = data["draft_body"]
            if "draft_email_subject" in data:
                lead["draft_email_subject"] = data["draft_email_subject"]
            if "draft_email_body" in data:
                lead["draft_email_body"] = data["draft_email_body"]
            if "draft_whatsapp_body" in data:
                lead["draft_whatsapp_body"] = data["draft_whatsapp_body"]
            save_campaign(camp)
            return {"message": "Lead updated", "lead": lead}
    raise HTTPException(status_code=404, detail="Lead not found in campaign")

@app.post("/api/inbound/whatsapp")
async def receive_whatsapp_webhook(payload: WhatsAppWebhookPayload, background_tasks: BackgroundTasks):
    """Webhook to receive messages from the local Node.js WhatsApp Gateway."""
    clean_phone = "".join(filter(str.isdigit, payload.phone))
    
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # 1. Try to find the contact by phone number
        # Note: phone numbers in DB might have '+' or spaces. We'll do a simple LIKE check.
        cursor.execute('''
            SELECT id FROM contacts 
            WHERE REPLACE(REPLACE(REPLACE(phone, '+', ''), ' ', ''), '-', '') LIKE ?
            LIMIT 1
        ''', (f"%{clean_phone[-9:]}%",))
        
        contact = cursor.fetchone()
        contact_id = contact['id'] if contact else None
        
        # 2. Insert into inbound_messages
        # We generate a pseudo rfc_message_id to track it
        import hashlib
        msg_hash = hashlib.md5(f"wa_{payload.phone}_{payload.timestamp}_{payload.message}".encode()).hexdigest()
        pseudo_rfc_id = f"wa-{msg_hash}@whatsapp.local"
        
        cursor.execute('''
            INSERT INTO inbound_messages (
                provider_message_id, rfc_message_id, sender, 
                received_at, contact_id, body_raw, processing_status
            ) VALUES (?, ?, ?, ?, ?, ?, 'received')
        ''', (
            f"wa_{msg_hash}", pseudo_rfc_id, payload.phone,
            payload.timestamp, contact_id, payload.message
        ))
        conn.commit()
    
    # 3. Trigger the inbound intelligence pipeline in the background
    background_tasks.add_task(process_pending_inbound)
    
    return {"status": "received", "queued_for_processing": True}

@app.get("/api/inbound")
async def get_inbound_feed():
    """Returns the full inbound feed with high-resolution intent metadata."""
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # Join with campaigns to get the campaign name. Since campaigns are JSON files, we will extract it 
        # from the campaigns table if present.
        cursor.execute('''
            SELECT i.*, 
                   c.intent_class, c.confidence as intent_confidence, c.suggested_action, c.human_override,
                   o.subject as outbound_subject, o.body as outbound_body,
                   camp.csv_source as campaign_name,
                   EXISTS(SELECT 1 FROM outbound_messages WHERE in_reply_to = i.rfc_message_id) as has_reply
            FROM inbound_messages i
            LEFT JOIN classifications c ON c.id = (
                SELECT id FROM classifications WHERE inbound_message_id = i.id ORDER BY id DESC LIMIT 1
            )
            LEFT JOIN outbound_messages o ON o.id = COALESCE(
                (SELECT id FROM outbound_messages WHERE rfc_message_id = i.in_reply_to LIMIT 1),
                (SELECT id FROM outbound_messages WHERE conversation_id = i.conversation_id ORDER BY sent_at DESC LIMIT 1)
            )
            LEFT JOIN campaigns camp ON camp.id = o.campaign_id
            WHERE i.is_archived = 0
            ORDER BY i.received_at DESC
        ''')
        rows = cursor.fetchall()
        return {"messages": [dict(r) for r in rows]}

@app.post("/api/inbound/{id}/resolve")
async def resolve_quarantine(id: int, data: dict = None):
    """Manually resolves a quarantined message and logs the adjudication."""
    note = (data or {}).get("note", "Manual Match Approval")
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # 1. Fetch current state for logging
        cursor.execute("SELECT processing_status FROM inbound_messages WHERE id = ?", (id,))
        old_status = cursor.fetchone()
        
        # 2. Update to 'matched' to resume pipeline and clear review flag
        cursor.execute("UPDATE inbound_messages SET processing_status = 'matched', requires_review = 0 WHERE id = ?", (id,))
        
        # 3. Log Adjudication
        cursor.execute('''
            INSERT INTO human_adjudications (message_id, original_intent, chosen_intent, action_taken, operator_note, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (id, 'quarantined', 'matched', 'resolved_match', note, datetime.now().isoformat()))
        
        conn.commit()
    return {"status": "resolved", "id": id}

@app.patch("/api/inbound/{id}/intent")
async def override_intent(id: int, data: dict):
    """Overrides neural classification and logs the adjudication event."""
    new_intent = data.get("intent")
    action = data.get("action")
    note = data.get("note", "Manual Intent Override")
    
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # 1. Get original for history
        cursor.execute("SELECT intent_class FROM classifications WHERE inbound_message_id = ?", (id,))
        orig_row = cursor.fetchone()
        orig_intent = orig_row['intent_class'] if orig_row else 'unclassified'
        
        # 2. Upsert Classification with override flag (manual since no UNIQUE constraint)
        cursor.execute("SELECT id FROM classifications WHERE inbound_message_id = ?", (id,))
        existing_class = cursor.fetchone()
        
        if existing_class:
            cursor.execute('''
                UPDATE classifications SET
                    intent_class = ?,
                    suggested_action = ?,
                    human_override = 1,
                    processed_at = ?
                WHERE inbound_message_id = ?
            ''', (new_intent, action, datetime.now().isoformat(), id))
        else:
            cursor.execute('''
                INSERT INTO classifications (inbound_message_id, intent_class, suggested_action, processed_at, human_override)
                VALUES (?, ?, ?, ?, 1)
            ''', (id, new_intent, action, datetime.now().isoformat()))
        
        # 3. Log Adjudication
        cursor.execute('''
            INSERT INTO human_adjudications (message_id, original_intent, chosen_intent, action_taken, operator_note, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (id, orig_intent, new_intent, 'override_intent', note, datetime.now().isoformat()))
        
        # 4. Trigger manual actioning status and clear review flag
        cursor.execute("UPDATE inbound_messages SET processing_status = 'resolved', requires_review = 0 WHERE id = ?", (id,))
        
        conn.commit()
    return {"status": "overridden", "id": id}

@app.delete("/api/inbound/{id}")
async def archive_inbound_message(id: int):
    """Soft-archives an inbound message (hides from panel, preserves for compliance)."""
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE inbound_messages SET is_archived = 1 WHERE id = ?", (id,))
        conn.commit()
    return {"status": "archived", "id": id}

@app.post("/api/inbound/{id}/star")
async def toggle_star(id: int):
    """Toggles the star/pin state of an inbound message."""
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_starred FROM inbound_messages WHERE id = ?", (id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Message not found")
        new_val = 0 if row['is_starred'] else 1
        cursor.execute("UPDATE inbound_messages SET is_starred = ? WHERE id = ?", (new_val, id))
        conn.commit()
    return {"status": "starred" if new_val else "unstarred", "id": id, "is_starred": new_val}

@app.post("/api/inbound/{id}/read")
async def mark_read(id: int):
    """Marks an inbound message as read."""
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE inbound_messages SET is_read = 1 WHERE id = ?", (id,))
        conn.commit()
    return {"status": "read", "id": id}

@app.patch("/api/inbound/{id}/note")
async def update_operator_note(id: int, data: dict):
    """Saves a private operator note on an inbound message."""
    note = data.get("note", "")
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE inbound_messages SET operator_note = ? WHERE id = ?", (note, id))
        conn.commit()
    return {"status": "saved", "id": id}

class ReplyRequest(BaseModel):
    body: str
    sender_name: str = ""

@app.post("/api/inbound/{id}/reply")
async def send_inbound_reply(id: int, payload: ReplyRequest):
    """Sends a Gmail reply to an inbound message, correctly threaded."""
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender, subject, rfc_message_id, references_header, contact_id, conversation_id FROM inbound_messages WHERE id = ?", 
            (id,)
        )
        msg = cursor.fetchone()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
    
    # Parse clean email from "Name <email>" format
    import email.utils
    _, to_email = email.utils.parseaddr(msg['sender'])
    
    result = await send_gmail_reply(
        to_email=to_email,
        subject=msg['subject'] or "",
        body=payload.body,
        in_reply_to=msg['rfc_message_id'],
        references=msg['references_header'],
        sender_name=payload.sender_name
    )
    
    if result['success']:
        # Record the reply as an outbound message — fully linked to the contact & conversation
        with db_conn() as conn:
            cursor = conn.cursor()
            import uuid

            # ── Bulletproof contact_id resolution ──────────────────────────────
            # Primary: use the contact_id already on the inbound message
            contact_id = msg['contact_id']
            conversation_id = msg['conversation_id']

            # Fallback: if inbound was quarantined or never matched, look up by sender email
            if not contact_id and to_email:
                cursor.execute(
                    "SELECT id FROM contacts WHERE LOWER(email) = LOWER(?) LIMIT 1",
                    (to_email,)
                )
                found = cursor.fetchone()
                if found:
                    contact_id = found['id']
                    # Also backfill the inbound_messages row so future lookups work
                    cursor.execute(
                        "UPDATE inbound_messages SET contact_id = ? WHERE id = ?",
                        (contact_id, id)
                    )
                    print(f"🔗 Backfilled contact_id={contact_id} on inbound message {id} (sender: {to_email})")

            # Build references chain: previous references + the message we're replying to
            existing_refs = msg['references_header'] or ""
            new_references = f"{existing_refs} {msg['rfc_message_id']}".strip()

            reply_subject = msg['subject'] or ""
            # Strip newlines that cause SMTP Header ValueError
            reply_subject = reply_subject.replace('\n', ' ').replace('\r', '').strip()
            
            if not reply_subject.lower().startswith("re:"):
                reply_subject = f"Re: {reply_subject}"

            cursor.execute('''
                INSERT INTO outbound_messages 
                    (id, channel, subject, body, status, sent_at, rfc_message_id,
                     contact_id, conversation_id, in_reply_to, references_header)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                f"reply_{uuid.uuid4().hex[:12]}", 
                'email', 
                reply_subject,
                payload.body,
                'sent', 
                datetime.now().isoformat(),
                result['message_id'],
                contact_id,
                conversation_id,
                msg['rfc_message_id'],
                new_references
            ))
            
            # Mark message as actioned/resolved and clear review flag since a reply was sent
            cursor.execute('''
                UPDATE inbound_messages SET processing_status = 'actioned', requires_review = 0 WHERE id = ?
            ''', (id,))

            # Increment touch count for the contact since we sent an outbound message
            if contact_id:
                cursor.execute('''
                    UPDATE contacts SET touch_count = COALESCE(touch_count, 0) + 1 WHERE id = ?
                ''', (contact_id,))

            conn.commit()

        if not contact_id:
            print(f"⚠️  Reply sent to {to_email} but contact not found in CRM — timeline will be incomplete.")

        return {"status": "sent", "message_id": result['message_id'], "contact_id": contact_id}
    else:
        raise HTTPException(status_code=500, detail=result['error'])


@app.post("/api/upload-context")
async def upload_context_files(files: List[UploadFile] = File(...)):
    """Receives context files (PDFs, Images) to enrich AI drafting intelligence."""
    saved_paths = []
    for file in files:
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        file_path = os.path.join(CONTEXT_UPLOADS_DIR, safe_name)
        with open(file_path, "wb") as f:
            f.write(await file.read())
        saved_paths.append(file_path)
    return {"status": "uploaded", "filenames": [os.path.basename(p) for p in saved_paths]}

@app.get("/api/radar/status")
async def get_radar_status():
    """Returns the current heartbeat status of the Inbound Intelligence Radar."""
    active = inbound_radar_task is not None and not inbound_radar_task.done()
    return {"active": active}

@app.post("/api/radar/toggle")
async def toggle_radar():
    """Surgically starts or stops the Inbound Intelligence Radar."""
    global inbound_radar_task
    
    is_active = inbound_radar_task is not None and not inbound_radar_task.done()
    
    if is_active:
        inbound_radar_task.cancel()
        return {"active": False, "message": "Radar Pulse Terminated"}
    else:
        inbound_radar_task = asyncio.create_task(run_inbound_intelligence_loop())
        return {"active": True, "message": "Radar Pulse Activated"}

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Surgically retrieves a generated CSV results file with forced download headers."""
    # Try absolute path first
    file_path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(file_path):
        # Fallback to local 'results' folder relative to CWD
        fallback_path = os.path.join("results", filename)
        if os.path.exists(fallback_path):
            file_path = fallback_path
        else:
            raise HTTPException(status_code=404, detail=f"File Not Found: {filename}")
    
    # Force 'attachment' behavior to prevent browser navigation
    return FileResponse(
        path=file_path, 
        filename=filename, 
        media_type='application/octet-stream',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ==============================================================================
# ━━ CRM INTELLIGENCE / READ-ONLY ENDPOINTS (PHASE 1 & 2.1A) ━━━━━━━━━━━━━━━━━
# ==============================================================================

@app.get("/api/crm/ingest/preview")
async def get_crm_ingest_preview():
    """Read-only preview report of all scraped lists in `/results`"""
    try:
        report = run_dry_run_report(filename="all")
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/crm/ingest")
async def post_crm_ingest(payload: IngestRequest):
    """Controlled Lead Ingestion API (Dry Run or Real transaction write)"""
    try:
        report = execute_ingest_pipeline(
            filename=payload.filename,
            dry_run=payload.dry_run,
            limit=payload.limit
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/crm/stats")

async def get_crm_stats():
    """Read-only high-level KPI metrics for the Intelligence dashboard."""
    try:
        with db_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM contacts")
            total_leads = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM contacts WHERE touch_count > 0")
            contacted = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT contact_id) FROM inbound_messages")
            replies = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(DISTINCT i.contact_id) 
                FROM inbound_messages i
                JOIN classifications c ON i.id = c.inbound_message_id
                WHERE c.intent_class IN ('interested_now', 'interested_later', 'needs_info')
            ''')
            interested = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM contacts WHERE global_status = 'suppressed'")
            suppressed = cursor.fetchone()[0]
            
            return {
                "total_leads": total_leads,
                "contacted": contacted,
                "replies": replies,
                "interested": interested,
                "suppressed": suppressed
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/metadata")
async def get_crm_metadata():
    """Fetch distinct filter values directly from the database."""
    try:
        with db_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT DISTINCT industry FROM lead_enrichment WHERE industry IS NOT NULL AND industry != ''")
            industries = [row[0] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT city FROM lead_enrichment WHERE city IS NOT NULL AND city != ''")
            cities = [row[0] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT acquisition_source FROM lead_enrichment WHERE acquisition_source IS NOT NULL AND acquisition_source != ''")
            sources = [row[0] for row in cursor.fetchall()]
            
            return {
                "industries": sorted(industries),
                "cities": sorted(cities),
                "sources": sorted(sources)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/leads")
async def get_crm_leads(
    limit: int = 50, 
    offset: int = 0, 
    search: str = "",
    industry: str = "",
    city: str = "",
    source: str = "",
    enrichment_status: str = "",
    status: str = ""
):
    """Read-only global view of all contacts with pagination and search."""
    try:
        with db_conn() as conn:
            cursor = conn.cursor()
            
            # Safe parameterized base query with LEFT JOIN
            base_query = """
                FROM contacts c
                LEFT JOIN lead_enrichment le ON c.id = le.contact_id
            """
            conditions = []
            params = []
            
            if search:
                conditions.append("(c.email LIKE ? OR c.name LIKE ? OR c.phone LIKE ?)")
                search_term = f"%{search}%"
                params.extend([search_term, search_term, search_term])
                
            if industry and industry != "All Industries" and industry != "All":
                conditions.append("le.industry = ?")
                params.append(industry)
                
            if city and city != "All Cities" and city != "All":
                conditions.append("le.city = ?")
                params.append(city)
                
            if source and source != "All Sources" and source != "All":
                conditions.append("le.acquisition_source = ?")
                params.append(source)
                
            if enrichment_status and enrichment_status != "All":
                conditions.append("le.enrichment_status = ?")
                params.append(enrichment_status)
                
            if status and status != "All":
                conditions.append("c.global_status = ?")
                params.append(status)
                
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)
                
            # Get total count for pagination
            cursor.execute(f"SELECT COUNT(*) {base_query}", params)
            total = cursor.fetchone()[0]
            
            # Fetch leads with enrichment data
            query = f"""
                SELECT c.*, 
                       le.industry, le.subcategory, le.city, le.country, 
                       le.acquisition_source, le.classification_confidence, 
                       le.enrichment_status
                {base_query} 
                ORDER BY c.last_contacted_at DESC 
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            leads = [dict(row) for row in rows]
            
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "data": leads
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/leads/{lead_id}")
async def get_crm_lead_detail(lead_id: int):
    """Read-only view of a single contact profile."""
    try:
        with db_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT c.*, 
                       le.industry, le.subcategory, le.city, le.country, 
                       le.acquisition_source, le.classification_confidence, 
                       le.enrichment_status, le.classification_reason
                FROM contacts c
                LEFT JOIN lead_enrichment le ON c.id = le.contact_id
                WHERE c.id = ?
            """, (lead_id,))
            row = cursor.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="Lead not found")
                
            lead_data = dict(row)
            
            # Get associated campaigns
            cursor.execute('''
                SELECT c.id, c.csv_source, c.status, cc.current_lead_status, cc.last_touch_at
                FROM campaign_contacts cc
                JOIN campaigns c ON cc.campaign_id = c.id
                WHERE cc.lead_id = ?
            ''', (lead_id,))
            lead_data['campaigns'] = [dict(c) for c in cursor.fetchall()]
            
            return lead_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crm/leads/{lead_id}/timeline")
async def get_crm_lead_timeline(lead_id: int):
    """Read-only unified timeline of outbound and inbound messages for a lead."""
    try:
        with db_conn() as conn:
            cursor = conn.cursor()
            
            # 1. Verify lead exists
            cursor.execute("SELECT id FROM contacts WHERE id = ?", (lead_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Lead not found")
                
            # 2. Get outbound messages (include body so the timeline shows full content)
            cursor.execute('''
                SELECT id, subject, body, sent_at as timestamp, status, 'outbound' as type
                FROM outbound_messages
                WHERE contact_id = ?
            ''', (lead_id,))
            outbound = [dict(row) for row in cursor.fetchall()]
            
            # 3. Get inbound messages with classifications
            cursor.execute('''
                SELECT 
                    i.id, i.subject, i.received_at as timestamp, i.body_clean, 'inbound' as type,
                    c.intent_class, c.confidence, c.suggested_action
                FROM inbound_messages i
                LEFT JOIN classifications c ON i.id = c.inbound_message_id
                WHERE i.contact_id = ?
            ''', (lead_id,))
            inbound = [dict(row) for row in cursor.fetchall()]
            
            # Merge and sort chronologically
            timeline = outbound + inbound
            # Filter out entries with no timestamp to prevent sorting errors
            timeline = [t for t in timeline if t.get('timestamp')]
            timeline.sort(key=lambda x: x['timestamp'])  # Oldest first (chronological, like a chat)
            
            return {"timeline": timeline}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
