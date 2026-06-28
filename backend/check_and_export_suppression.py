import os
import sqlite3
import json
import csv

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
DB_PATH = os.path.join(STATE_DIR, "contacts.db")

print("Checking backup files sizes:")
for f in ["database_backup_before_phase2_20260526_0341.sqlite", "leads_export_before_phase2_20260526_0341.json", "leads_export_before_phase2_20260526_0341.csv"]:
    path = os.path.join(STATE_DIR, f)
    if os.path.exists(path):
        print(f"{f}: {os.path.getsize(path)} bytes")
    else:
        print(f"{f}: NOT FOUND")

print("\nChecking global_suppression_list in current DB...")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
try:
    cursor.execute("SELECT * FROM global_suppression_list")
    rows = cursor.fetchall()
    if not rows:
        print("global_suppression_list is empty.")
    else:
        print(f"global_suppression_list has {len(rows)} rows. Exporting...")
        cols = [description[0] for description in cursor.description]
        data = [dict(zip(cols, row)) for row in rows]
        
        j_path = os.path.join(STATE_DIR, "suppression_export_before_phase2_20260526_0341.json")
        c_path = os.path.join(STATE_DIR, "suppression_export_before_phase2_20260526_0341.csv")
        
        with open(j_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        with open(c_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(data)
            
        print("Exported to JSON and CSV.")
except Exception as e:
    print(f"Error reading global_suppression_list: {e}")

conn.close()
