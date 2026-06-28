const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json());

const PORT = 3001;
const PYTHON_BACKEND = 'http://localhost:8000';

// ── Leads Whitelist ────────────────────────────────────────────────────────────
// Only numbers scraped from our campaigns will be handled by the AI Agent.
// Messages from personal contacts (family, friends) are silently ignored.
const LEADS_DIR = path.join(__dirname, '..', 'backend', 'results');

function loadLeadPhones() {
    const phones = new Set();
    try {
        const files = fs.readdirSync(LEADS_DIR).filter(f => f.startsWith('clean_leads_pre_ia_'));
        for (const file of files) {
            const content = fs.readFileSync(path.join(LEADS_DIR, file), 'utf-8');
            const lines = content.split('\n').slice(1); // skip header
            for (const line of lines) {
                const cols = line.split(',');
                const phone = cols[3]?.trim().replace(/\D/g, ''); // 4th column = phone, digits only
                if (phone && phone.length >= 9) phones.add(phone);
            }
        }
        console.log(`📋  Whitelist cargada: ${phones.size} leads con teléfono.`);
    } catch (err) {
        console.warn('⚠️  No se pudo cargar el whitelist de leads:', err.message);
    }
    return phones;
}

let leadPhones = loadLeadPhones();

// Reload whitelist every 10 minutes so new scraped leads are picked up automatically
setInterval(() => {
    leadPhones = loadLeadPhones();
}, 10 * 60 * 1000);



// ── WhatsApp Client ────────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'sdr-agent' }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
        ],
    },
});

// ── QR Code ────────────────────────────────────────────────────────────────────
client.on('qr', (qr) => {
    console.log('\n\n══════════════════════════════════════════════');
    console.log('📱  Escanea este QR con tu WhatsApp:');
    console.log('    WhatsApp → Ajustes → Dispositivos Vinculados → Vincular un Dispositivo');
    console.log('══════════════════════════════════════════════\n');
    qrcode.generate(qr, { small: true });
});

client.on('authenticated', () => {
    console.log('\n✅  Autenticado. Sesión guardada localmente.');
});

client.on('auth_failure', (msg) => {
    console.error('❌  Error de autenticación:', msg);
});

client.on('ready', () => {
    console.log('\n🚀  WhatsApp Gateway listo y conectado!');
    console.log(`📡  Escuchando mensajes entrantes...`);
    console.log(`🌐  API REST disponible en: http://localhost:${PORT}`);
    console.log(`\n    POST /send  →  Enviar mensaje`);
    console.log(`    GET  /status →  Estado del gateway\n`);
});

client.on('disconnected', (reason) => {
    console.log('⚠️  WhatsApp desconectado:', reason);
});

// ── Mensaje Entrante → Manda al Agent 3 ───────────────────────────────────────
client.on('message', async (msg) => {
    // Ignorar mensajes de grupos, estados y los propios
    if (msg.from.includes('@g.us') || msg.from === 'status@broadcast' || msg.fromMe) return;

    const phone = msg.from.replace('@c.us', '');
    const phoneDigits = phone.replace(/\D/g, '');
    const body  = msg.body;

    // ── Whitelist check: solo procesamos mensajes de leads conocidos ──────────
    const isLead = [...leadPhones].some(p => phoneDigits.endsWith(p) || p.endsWith(phoneDigits));
    if (!isLead) {
        console.log(`🔕  Mensaje ignorado (contacto personal) de ${phone}`);
        return;
    }
    // ─────────────────────────────────────────────────────────────────────────

    console.log(`\n📥  Lead respondió [${phone}]: ${body}`);

    // Notificar al backend Python (Agent 3)
    try {
        const res = await fetch(`${PYTHON_BACKEND}/api/inbound/whatsapp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: 'whatsapp',
                phone,
                message: body,
                timestamp: new Date().toISOString(),
            }),
        });

        if (res.ok) {
            const data = await res.json();
            // Si el Agent 3 devuelve una respuesta, la enviamos
            if (data?.reply) {
                await client.sendMessage(msg.from, data.reply);
                console.log(`📤  Respuesta enviada a ${phone}: ${data.reply}`);
            }
        }
    } catch (err) {
        console.error('⚠️  No se pudo contactar con el backend Python:', err.message);
    }
});

// ── REST API para enviar mensajes desde Python ─────────────────────────────────
app.post('/send', async (req, res) => {
    const { phone, message } = req.body;

    if (!phone || !message) {
        return res.status(400).json({ error: 'Faltan campos: phone, message' });
    }

    const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;

    try {
        const isRegistered = await client.isRegisteredUser(chatId);
        if (!isRegistered) {
            return res.status(404).json({ error: 'Número no registrado en WhatsApp' });
        }

        await client.sendMessage(chatId, message);
        console.log(`📤  Mensaje enviado a ${phone}`);
        res.json({ success: true, phone });
    } catch (err) {
        console.error('Error al enviar mensaje:', err.message);
        res.status(500).json({ error: err.message });
    }
});

// ── Endpoint de estado ─────────────────────────────────────────────────────────
app.get('/status', (req, res) => {
    res.json({
        gateway: 'WhatsApp SDR Gateway',
        state: client.info ? 'connected' : 'disconnected',
        phone: client.info?.wid?.user || null,
        uptime: process.uptime(),
    });
});

// ── Arrancar servidor y cliente ────────────────────────────────────────────────
app.listen(PORT, () => {
    console.log(`\n🌐  Gateway HTTP arrancado en http://localhost:${PORT}`);
    console.log('🔄  Iniciando cliente de WhatsApp...\n');
});

client.initialize();
