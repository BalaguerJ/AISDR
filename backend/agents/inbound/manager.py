from __future__ import annotations
"""
manager.py — Agent 3: The Inbound Orchestrator

This module provides the main execution loop for the Inbound Intelligence 
Engine, coordinating the listener, normalizer, matcher, and router.
"""

import asyncio
import time
from datetime import datetime
from typing import List

# Internal components
from .listener import poll_inbox_durable
from .normalizer import run_normalization_v2
from .matcher import run_matching_v2
from .router import run_triage_v2
from .classifier import run_classification_v2
from agents.db import db_conn

POLL_INTERVAL = 300 # 5 minutes

async def run_inbound_intelligence_loop(once: bool = False):
    """
    Main background loop for Agent 3.
    Polls, Normalizes, Matches, and Triages every inbound signal.
    """
    print(f"🧠 Agent 3: Inbound Intelligence Engine is starting... (Mode: {'Single-Pass' if once else 'Continuous'})")
    
    while True:
        try:
            print(f"📡 [{datetime.now().strftime('%H:%M:%S')}] Polling inbox for new signals...")
            
            # 1. Poll for New Messages (Durable + Idempotency)
            new_count = await poll_inbox_durable()
            
            if new_count and new_count > 0:
                print(f"📥 Found {new_count} new messages. Starting Intelligence Pipeline...")
                await process_pending_inbound()
            else:
                # Still check for any stuck messages in the pipeline
                await process_pending_inbound()
                print("💤 No new signals detected.")

        except Exception as e:
            print(f"❌ Orchestrator Error: {str(e)}")
            
        if once:
            print("🏁 Neural Sweep Complete. Terminating Single-Pass Mode.")
            break
            
        await asyncio.sleep(POLL_INTERVAL)

async def process_pending_inbound():
    """
    Processes all messages currently in intermediate states.
    Hardened Lifecycle: received -> normalized -> matched -> classified -> actioned -> resolved
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        
        # We process in the order they were received
        cursor.execute('''
            SELECT id, processing_status FROM inbound_messages 
            WHERE processing_status NOT IN ('resolved', 'error')
            ORDER BY id ASC
        ''')
        pending = cursor.fetchall()
        
    for p in pending:
        msg_id = p['id']
        status = p['processing_status']
        
        try:
            # 1. NORMALIZATION
            if status == 'received':
                run_normalization_v2(msg_id)
                status = 'normalized'
                
            # 2. MATCHING (Internal status update to 'matched' or 'quarantined')
            if status == 'normalized':
                run_matching_v2(msg_id)
                with db_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT processing_status FROM inbound_messages WHERE id = ?", (msg_id,))
                    status = cursor.fetchone()['processing_status']
                
            # 3. CLASSIFICATION (Neural Intent Detection)
            if status == 'matched':
                await run_classification_v2(msg_id)
                status = 'classified'
            
            # 4. ACTIONING (Router - Campaign Controls & Workflow Signals)
            if status == 'classified':
                # Router will move to 'actioned' or 'resolved'
                run_triage_v2(msg_id)
                with db_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT processing_status FROM inbound_messages WHERE id = ?", (msg_id,))
                    status = cursor.fetchone()['processing_status']

            # 5. RESOLVER (Final Cleanup / Task Management)
            if status == 'actioned':
                # Final state transition
                with db_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE inbound_messages SET processing_status = 'resolved' WHERE id = ?", (msg_id,))
                    conn.commit()
                
        except Exception as e:
            print(f"💥 Failed to process message {msg_id}: {str(e)}")
            with db_conn() as conn:
                conn.cursor().execute("UPDATE inbound_messages SET processing_status = 'error' WHERE id = ?", (msg_id,))
                conn.commit()

# Main entry point for standalone testing
if __name__ == "__main__":
    asyncio.run(run_inbound_intelligence_loop())
