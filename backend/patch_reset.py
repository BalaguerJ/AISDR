import re

with open("backend/agents/scheduler.py", "r") as f:
    content = f.read()

reset_func = """
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
"""

if "def reset_simulated_outbox_jobs" not in content:
    content = content + "\n" + reset_func
    with open("backend/agents/scheduler.py", "w") as f:
        f.write(content)

with open("backend/main.py", "r") as f:
    main_content = f.read()
    
main_import = "from agents.scheduler import preview_enqueue_pending_campaign_jobs, enqueue_pending_campaign_jobs, reset_simulated_outbox_jobs, delete_campaign_outbox_jobs"
main_content = main_content.replace("from agents.scheduler import preview_enqueue_pending_campaign_jobs, enqueue_pending_campaign_jobs", main_import)

endpoint_injection = """
@app.post("/api/campaigns/{campaign_id}/reset_dry_run")
async def reset_dry_run_jobs(campaign_id: str):
    return reset_simulated_outbox_jobs(campaign_id)

@app.delete("/api/campaigns/{campaign_id}/jobs")
async def delete_campaign_jobs(campaign_id: str):
    return delete_campaign_outbox_jobs(campaign_id)
"""

if "@app.post(\"/api/campaigns/{campaign_id}/reset_dry_run\")" not in main_content:
    main_content = main_content.replace("@app.post(\"/api/campaigns/{campaign_id}/start\")", endpoint_injection + "\n@app.post(\"/api/campaigns/{campaign_id}/start\")")
    with open("backend/main.py", "w") as f:
        f.write(main_content)
