import sqlite3
import json
from datetime import datetime

DB_PATH = 'state/contacts.db'

def classify_lead(lead):
    name = str(lead.get('name') or '').lower()
    email = str(lead.get('email') or '').lower()
    csv_source = str(lead.get('csv_source') or '').lower()
    map_url = str(lead.get('map_url') or '').lower()
    
    industry = 'Unclassified'
    city = 'Unknown'
    country = 'Unknown'
    confidence = 0.0
    reason = []
    
    # --- ACQUISITION SOURCE ---
    acquisition_source = 'Unknown'
    if 'youtube.com' in map_url:
        acquisition_source = 'YouTube API'
    elif 'google.com/maps' in map_url:
        acquisition_source = 'Google Maps'
    elif csv_source:
        if 'youtube' in csv_source:
            acquisition_source = 'YouTube API'
        elif 'web' in csv_source:
            acquisition_source = 'Web Search'
        elif 'maps' in csv_source:
            acquisition_source = 'Google Maps'
        else:
            acquisition_source = 'Google Maps' # Defaulting historical data to Maps mostly
            
    # --- INDUSTRY RULES ---
    if any(k in csv_source for k in ['fisioterapia', 'physio', 'rehabilitacion', 'clinic', 'clínica']):
        industry = 'Healthcare / Physiotherapy'
        confidence += 0.4
        reason.append("csv_source indicates physiotherapy")
        
    if any(k in name for k in ['studio', 'studios', 'recording', 'rehearsal', 'music', 'band']):
        industry = 'Music Studio'
        confidence += 0.4
        reason.append("name indicates music studio")
        
    if any(k in csv_source or k in name for k in ['dance', 'salsa', 'bachata', 'baile', 'academy', 'academia']):
        industry = 'Dance Academy'
        confidence += 0.4
        reason.append("name or source indicates dance academy")
        
    if any(k in csv_source or k in name for k in ['club', 'discoteca', 'nightlife', 'dj', 'latino']):
        industry = 'Nightlife / Club'
        confidence += 0.4
        reason.append("name or source indicates nightlife")
        
    # --- LOCATION RULES ---
    if any(k in csv_source or k in name for k in ['palma', 'mallorca']):
        city = 'Palma de Mallorca'
        country = 'Spain'
        confidence += 0.3
        reason.append("detected palma/mallorca in name or source")
        
    if any(k in csv_source or k in name or k in email for k in ['london', 'camden', '.co.uk']):
        city = 'London'
        country = 'United Kingdom'
        confidence += 0.3
        reason.append("detected london in name, source, or email")
        
    status = 'Enriched' if confidence > 0.5 else 'Needs Review'
    
    return {
        'contact_id': lead['id'],
        'industry': industry,
        'city': city,
        'country': country,
        'acquisition_source': acquisition_source,
        'campaign_origin': lead.get('campaign_id'),
        'classification_confidence': min(1.0, confidence),
        'classification_reason': " | ".join(reason) if reason else "No matching rules",
        'enrichment_status': status,
        'enrichment_version': 'rules_v1'
    }

def run_batch():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.*, cc.campaign_id, camp.csv_source
        FROM contacts c
        LEFT JOIN campaign_contacts cc ON c.id = cc.lead_id
        LEFT JOIN campaigns camp ON cc.campaign_id = camp.id
        GROUP BY c.id
    ''')
    leads = cursor.fetchall()
    
    stats = {
        'processed': 0,
        'enriched': 0,
        'needs_review': 0,
        'industries': {},
        'cities': {},
        'unclassified_count': 0
    }
    
    for lead in leads:
        lead_dict = dict(lead)
        data = classify_lead(lead_dict)
        
        # Upsert logic
        cursor.execute('''
            INSERT INTO lead_enrichment (
                contact_id, industry, city, country, acquisition_source, 
                campaign_origin, classification_confidence, classification_reason, 
                enrichment_status, enrichment_version, enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(contact_id) DO UPDATE SET
                industry = excluded.industry,
                city = excluded.city,
                country = excluded.country,
                acquisition_source = excluded.acquisition_source,
                campaign_origin = excluded.campaign_origin,
                classification_confidence = excluded.classification_confidence,
                classification_reason = excluded.classification_reason,
                enrichment_status = excluded.enrichment_status,
                enrichment_version = excluded.enrichment_version,
                enriched_at = excluded.enriched_at
            WHERE lead_enrichment.enrichment_version = 'rules_v1' OR lead_enrichment.enrichment_version IS NULL
        ''', (
            data['contact_id'], data['industry'], data['city'], data['country'], 
            data['acquisition_source'], data['campaign_origin'], 
            data['classification_confidence'], data['classification_reason'], 
            data['enrichment_status'], data['enrichment_version']
        ))
        
        # Collect stats
        stats['processed'] += 1
        if data['enrichment_status'] == 'Enriched':
            stats['enriched'] += 1
        else:
            stats['needs_review'] += 1
            
        if data['industry'] == 'Unclassified':
            stats['unclassified_count'] += 1
            
        stats['industries'][data['industry']] = stats['industries'].get(data['industry'], 0) + 1
        stats['cities'][data['city']] = stats['cities'].get(data['city'], 0) + 1
        
    conn.commit()
    conn.close()
    
    print("=== BATCH ENRICHMENT REPORT ===")
    print(f"Total Leads Processed: {stats['processed']}")
    print(f"Total Enriched: {stats['enriched']}")
    print(f"Total Needs Review: {stats['needs_review']}")
    print(f"Unclassified Industries: {stats['unclassified_count']}")
    print("\n-- Industries Detected --")
    for k, v in stats['industries'].items():
        print(f"  {k}: {v}")
    print("\n-- Cities Detected --")
    for k, v in stats['cities'].items():
        print(f"  {k}: {v}")
        
    print("\nDone.")

if __name__ == "__main__":
    run_batch()
