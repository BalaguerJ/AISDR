import re

with open("backend/agents/outbox_worker.py", "r") as f:
    content = f.read()

log_patch = """
    # In dry-run, we simulate it
    if OUTREACH_WORKER_MODE == "outbox_dry_run":
        msg = f"[{datetime.now().strftime('%H:%M:%S')}] [DRY-RUN] Simulated JIT email generation and send to {contact['email']}"
        print(msg)
        if 'logs' not in camp: camp['logs'] = []
        camp['logs'].insert(0, msg)
        camp['logs'] = camp['logs'][:50] # Keep last 50
        save_campaign(camp)
        
        cursor.execute("UPDATE outbox_jobs SET status = 'simulated_sent', sent_at = ? WHERE id = ?", (datetime.now().isoformat(), job['id']))
        conn.commit()
        return
"""

content = re.sub(
    r"    # In dry-run, we simulate it.*?conn\.commit\(\)\n        return",
    log_patch,
    content,
    flags=re.DOTALL
)

with open("backend/agents/outbox_worker.py", "w") as f:
    f.write(content)
