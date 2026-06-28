# AI SDR Command Center (Generative AI Final Project)

An end-to-end, multi-agent AI system built for automated B2B prospecting, data enrichment, personalized outreach, and intent classification. Developed for the Generative AI course final project.

## 🚀 Project Overview

The AI SDR Command Center solves the real-world business problem of high Customer Acquisition Cost (CAC) and time-consuming manual B2B prospecting. By utilizing a **Generative AI Agentic Architecture**, the system automates:
1. **Hunting (Agent 1):** Performs browser-based lead discovery from public business sources and enriches them.
2. **Outreach (Agent 2):** Generates highly personalized, human-like outreach drafts using LLMs (Gemini).
3. **Inbound (Agent 3):** Reads replies, classifies intent (e.g., *interested*, *not_interested*), and manages the CRM.
4. **CRM & Intelligence:** A Read-Only Ledger CRM that is designed to preserve auditability, review status, and controlled human approval.

## 🏗️ Architecture & Frameworks

* **Backend:** FastAPI (Python), SQLite (WAL mode), Playwright, Gemini (LLM for intent classification and draft generation).
* **Frontend:** Next.js (TypeScript, TailwindCSS), designed with Glassmorphism and Real-Time WebSocket integration to visualize logs and AI reasoning.
* **Database Design:** Read-Only Ledger pattern using SQLite, ensuring concurrent operations without data corruption.

## 🛠️ How to Run the Project Locally

### 1. Prerequisites
* Python 3.9+
* Node.js 18+
* Environment variables properly configured in `.env` (API Keys, SMTP config).

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 4. Access the App
Open your browser and navigate to `http://localhost:3000`. You can switch between the **Hunt Panel**, **Outreach Manager**, **Inbound Radar**, and **Intelligence CRM** directly from the UI.

## 📈 Roadmap 2026
* **Advanced Intelligence Agents:** Technographic Scanner, Ads Intelligence, and Revenue Leakage Score modules (currently in development/validation phase).
* **Multi-Tenancy:** PostgreSQL migration for multiple users.
* **Unified Smart Inbox:** Managing Email + WhatsApp replies directly from the UI.
* **Self-Optimizing Agent:** A/B testing loops that automatically iterate on outreach drafts based on conversion rates.
