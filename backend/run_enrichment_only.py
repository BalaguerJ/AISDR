"""
run_enrichment_only.py — Script autónomo con httpx async (nunca se congela)
Lee clean_leads_pre_ia, salta los ya procesados, procesa en batches de 30.
"""

import asyncio
import csv
import os
import random
import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")

SAFE_GOAL   = "clínica_dental_estética_Madrid"
PRE_IA_CSV  = os.path.join(RESULTS_DIR, f"clean_leads_pre_ia_{SAFE_GOAL}.csv")
PARTIAL_CSV = os.path.join(RESULTS_DIR, f"enriched_leads_partial_{SAFE_GOAL}.csv")
FINAL_CSV   = os.path.join(RESULTS_DIR, f"leads_{SAFE_GOAL}_FINAL.csv")
SPINTAX_PATH = os.path.join(BASE_DIR, "spintax_asuntos.txt")

COLUMN_ORDER = ['name', 'category', 'phone', 'email', 'website', 'address',
                'is_good_lead', 'ai_notes', 'map_url', 'asunto_email']
BATCH_SIZE   = 30
CONNECT_T    = 5.0   # connection timeout
READ_T       = 7.0   # read timeout

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
}
CONTACT_PATHS = ['/contacto', '/contact', '/aviso-legal', '/sobre-nosotros']

spintax = []
if os.path.exists(SPINTAX_PATH):
    with open(SPINTAX_PATH, 'r', encoding='utf-8') as f:
        spintax = [l.strip() for l in f if l.strip()]
if not spintax:
    spintax = ["Pregunta rápida", "Duda", "Consulta"]

# ── Extraction helpers ─────────────────────────────────────────────────────────
def extract_emails(html: str) -> list:
    bad = ['.png', '.jpg', '.gif', '.css', '.js', 'sentry', 'example.com', 'schema.org', 'wix.com']
    emails = set()
    for m in re.findall(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html):
        if not any(b in m.lower() for b in bad):
            emails.add(m.lower())
    for m in re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html):
        if not any(b in m.lower() for b in bad):
            emails.add(m.lower())
    return list(emails)

def best_email(emails: list) -> str:
    if not emails: return ''
    for p in ['info@', 'contact@', 'hola@', 'contacto@', 'hello@', 'mail@', 'clinica@', 'dental@']:
        for e in emails:
            if e.startswith(p): return e
    return emails[0]

def html_to_text(html: str) -> str:
    # fast regex strip to avoid BeautifulSoup locking the GIL
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text

def extract_phone(text: str) -> str:
    # A simple, non-backtracking regex for Spanish/general phones
    # e.g., 900 123 456, +34 600 123 456, 600123456
    for m in re.findall(r'(?:\+34|0034)?[\s\-]*[6789](?:[\s\-]*\d){8}', text):
        digits = re.sub(r'\D', '', m)
        if len(digits) >= 9:
            return m.strip()
    return ''

# ── Async fetch with CURL (immune to Python GIL and socket hangs) ──────────────
async def fetch(url: str, timeout: float = 8.0) -> Optional[str]:
    try:
        # -s: silent, -L: follow redirects, -k: insecure, -A: user agent, -m: max time
        cmd = [
            'curl', '-s', '-L', '-k',
            '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            '-m', str(int(timeout)),
            url
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2.0)
            if proc.returncode == 0:
                # Truncate to 150KB to prevent regex from hanging the executor on massive files
                return stdout.decode('utf-8', errors='ignore')[:150000]
            return None
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return None
    except Exception as e:
        return None

# ── Enrich one lead ────────────────────────────────────────────────────────────
async def enrich_one(lead: dict) -> dict:
    url = lead.get('website', '').strip()
    if url and not url.startswith('http'):
        url = 'https://' + url

    emails = []
    phone  = lead.get('phone', '').strip()
    name = lead.get('name', 'Unknown')[:30]

    if url and 'google.com' not in url:
        print(f"    [>] Fetching {url} for {name}...", flush=True)
        html = await fetch(url)
            
        if html:
            loop = asyncio.get_event_loop()
            try:
                emails = await loop.run_in_executor(None, extract_emails, html)
                text = await loop.run_in_executor(None, html_to_text, html)
                if not phone:
                    phone = await loop.run_in_executor(None, extract_phone, text)
            except Exception:
                pass
                
            if not emails:
                from urllib.parse import urlparse
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                for path in CONTACT_PATHS:
                    sub = await fetch(base + path, timeout=6.0)
                    if sub:
                        try:
                            sub_emails = await loop.run_in_executor(None, extract_emails, sub)
                            emails = sub_emails
                            if not phone:
                                sub_text = await loop.run_in_executor(None, html_to_text, sub)
                                phone = await loop.run_in_executor(None, extract_phone, sub_text)
                        except Exception:
                            pass
                        if emails:
                            break

    result = dict(lead)
    result['email']        = best_email(emails) if emails else lead.get('email', '')
    result['phone']        = phone or lead.get('phone', '')
    result['is_good_lead'] = bool(result['email'] or result['phone'])
    result['ai_notes']     = (lead.get('ai_notes') or
                              f"{lead.get('category','Business')} en {lead.get('address','')}.")
    result['asunto_email'] = random.choice(spintax)
    print(f"    [OK] {name} done.", flush=True)
    return result

# ── CSV helpers ────────────────────────────────────────────────────────────────
def load_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))
    return rows

def append_leads(leads: list):
    exists = os.path.exists(PARTIAL_CSV)
    with open(PARTIAL_CSV, 'a', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMN_ORDER, extrasaction='ignore')
        if not exists:
            w.writeheader()
        w.writerows(leads)

# ── Main ───────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{'═'*60}", flush=True)
    print(f"  🚀  ENRICHMENT — {SAFE_GOAL}", flush=True)
    print(f"{'═'*60}\n", flush=True)
    print("📂 Cargando leads...", flush=True)

    loop = asyncio.get_event_loop()
    all_leads    = await loop.run_in_executor(None, load_csv, PRE_IA_CSV)
    print(f"   Total: {len(all_leads)}", flush=True)

    if os.path.exists(PARTIAL_CSV):
        already_done = await loop.run_in_executor(None, load_csv, PARTIAL_CSV)
    else:
        already_done = []

    done_keys = {(r.get('name',''), r.get('map_url','')) for r in already_done}
    print(f"   Ya hechos (se saltan): {len(done_keys)}", flush=True)

    pending = [l for l in all_leads
               if (l.get('name',''), l.get('map_url','')) not in done_keys]
    total   = len(pending)
    print(f"   Pendientes: {total}", flush=True)
    print(f"   Batch size: {BATCH_SIZE} | Connect: {CONNECT_T}s | Read: {READ_T}s\n", flush=True)

    if not pending:
        print("🎉 Todo hecho. Generando CSV final...", flush=True)
        await finalize()
        return

    processed = 0
    async def process_with_timeout(lead):
        try:
            name = lead.get('name', 'Unknown')[:30]
            res = await asyncio.wait_for(enrich_one(lead), timeout=20.0)
            return res
        except Exception as e:
            print(f"    [!] Timeout/Error for {lead.get('name')}: {e}", flush=True)
            lead['is_good_lead'] = bool(lead.get('phone') or lead.get('email'))
            lead['ai_notes']     = lead.get('ai_notes','') or f"{lead.get('category','')} en {lead.get('address','')}."
            lead['asunto_email'] = random.choice(spintax)
            return lead

    for batch_start in range(0, total, BATCH_SIZE):
        batch   = pending[batch_start:batch_start + BATCH_SIZE]
        
        tasks = [process_with_timeout(l) for l in batch]
        clean = []
        for coro in asyncio.as_completed(tasks):
            res = await coro
            clean.append(res)

        await loop.run_in_executor(None, append_leads, clean)
        processed += len(clean)
        pct = processed / total * 100
        print(f"  ✅ {processed}/{total} ({pct:.1f}%) — batch {batch_start//BATCH_SIZE + 1}", flush=True)

    await finalize()


async def finalize():
    all_enriched = load_csv(PARTIAL_CSV) if os.path.exists(PARTIAL_CSV) else []
    valid = [l for l in all_enriched
             if l.get('name','').strip() and
             (l.get('address') or l.get('phone') or l.get('email') or l.get('website'))]

    print(f"\n💾 Guardando → {os.path.basename(FINAL_CSV)}", flush=True)
    with open(FINAL_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMN_ORDER, extrasaction='ignore')
        w.writeheader()
        w.writerows(valid)

    with_email = sum(1 for l in valid if l.get('email'))
    with_phone = sum(1 for l in valid if l.get('phone'))
    print(f"\n{'═'*60}", flush=True)
    print(f"  ✅  LISTO — {len(valid)} leads", flush=True)
    print(f"  📧  Con email:    {with_email}", flush=True)
    print(f"  📞  Con teléfono: {with_phone}", flush=True)
    print(f"  💾  {FINAL_CSV}", flush=True)
    print(f"{'═'*60}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
