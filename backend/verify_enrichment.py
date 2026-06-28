import sqlite3
import json

DB_PATH = 'state/contacts.db'

def run_verification():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Conteo por enrichment_status
    cursor.execute('''SELECT enrichment_status, COUNT(*) as count FROM lead_enrichment GROUP BY enrichment_status''')
    status_counts = dict(cursor.fetchall())
    
    # 2. Conteo por industry, separado por status
    cursor.execute('''
        SELECT industry, enrichment_status, COUNT(*) as count 
        FROM lead_enrichment 
        GROUP BY industry, enrichment_status
    ''')
    industry_breakdown = {}
    for row in cursor.fetchall():
        ind = row['industry']
        stat = row['enrichment_status']
        count = row['count']
        if ind not in industry_breakdown:
            industry_breakdown[ind] = {'Enriched': 0, 'Needs Review': 0}
        industry_breakdown[ind][stat] = count

    # 3. Conteo por city, separado por status
    cursor.execute('''
        SELECT city, enrichment_status, COUNT(*) as count 
        FROM lead_enrichment 
        GROUP BY city, enrichment_status
    ''')
    city_breakdown = {}
    for row in cursor.fetchall():
        cit = row['city']
        stat = row['enrichment_status']
        count = row['count']
        if cit not in city_breakdown:
            city_breakdown[cit] = {'Enriched': 0, 'Needs Review': 0}
        city_breakdown[cit][stat] = count

    # 4. 10 filas reales
    cursor.execute('''
        SELECT contact_id, industry, city, acquisition_source, classification_confidence, enrichment_status, classification_reason
        FROM lead_enrichment
        LIMIT 10
    ''')
    sample_rows = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    print("=== VERIFICATION REPORT ===")
    print("STATUS COUNTS:")
    print(json.dumps(status_counts, indent=2))
    
    print("\nINDUSTRY BREAKDOWN:")
    print(json.dumps(industry_breakdown, indent=2))
    
    print("\nCITY BREAKDOWN:")
    print(json.dumps(city_breakdown, indent=2))
    
    print("\n10 REAL ROWS:")
    print(json.dumps(sample_rows, indent=2))

if __name__ == "__main__":
    run_verification()
