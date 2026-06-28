---
marp: true
theme: default
class: lead
style: |
  section {
    background-color: #000000;
    color: #f4f4f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    padding: 60px 80px;
  }
  h1 {
    color: #ffffff;
    font-size: 3.2em;
    letter-spacing: -0.04em;
    margin-bottom: 0.2em;
    font-weight: 800;
  }
  h2 {
    color: #e4e4e7;
    font-size: 2em;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin-bottom: 1em;
  }
  h3 {
    color: #a1a1aa;
    font-size: 1.4em;
    font-weight: 500;
  }
  p, li {
    font-size: 1.2em;
    color: #a1a1aa;
    line-height: 1.6;
  }
  strong {
    color: #ffffff;
  }
  .accent {
    color: #3b82f6;
  }
  .highlight {
    background: linear-gradient(120deg, #3b82f6, #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
---

# AI SDR Agent
### <span class="highlight">Agentic Lead Intelligence for B2B Prospecting</span>

**IE University**
Generative AI Final Project

---

# The Business Problem

B2B sales teams are wasting time on manual labor.

- **Data Hunting:** Finding leads and verifying data.
- **Enrichment:** Manually researching company context.
- **Copywriting:** Writing personalized outreach from scratch.
- **Result:** Sales teams spend a significant amount of time manually finding leads and writing outreach.

---

# Our Solution

An autonomous **GenAI Agentic System** that acts as an SDR.

- **Discovers** highly-targeted leads automatically.
- **Enriches** contact and business data dynamically.
- **Generates** personalized outreach using Gemini.
- **Classifies** incoming replies via Sentiment Analysis.
- **Validates** everything through a human-in-the-loop CRM.

---

# System Architecture
### <span class="accent">Stable MVP Flow</span>

1. **Hunt Agent:** Browser-based lead discovery from public sources.
2. **Enrichment Agent:** Automatically extracts context and contact data.
3. **Outreach Generator:** Creates contextualized drafts for Gmail & WhatsApp.
4. **Inbound Agent:** Reads emails, runs sentiment analysis, and scores intent.
5. **CRM Layer:** Preserves auditability and controlled human approval.

---

# GenAI & Agentic Core

Powered by **Gemini** and structured prompt workflows.

- **Tool-Use & Context:** Agents use enriched data for personalization.
- **Channel Specific:** Tailors copy dynamically (Email vs. WhatsApp).
- **Inbound Classification:** Labels replies as Hot, Warm, or Cold instantly.
- **Guardrails:** Output validation and strict JSON schemas.
- **Human Approval:** Nothing is sent without manual validation.

---

# Live Demo Flow

1. **Data Ingestion Panel:** Start the Hunt.
2. **Lead Enrichment:** See business data populate.
3. **Draft Generation:** Gemini-based personalized outreach.
4. **Channel Splits:** Separate Gmail and WhatsApp drafts.
5. **Inbound Radar:** Watch AI classify live email replies.
6. **CRM Review:** The human approval workflow.

---

# Business Value
### <span class="highlight">Driving Revenue & Efficiency</span>

- **Time Saved:** Prospecting goes from hours to minutes.
- **Prioritization:** SDRs focus only on sending quality, approved outreach.
- **Personalization at Scale:** Every lead gets a tailored hook.
- **Cost Efficiency:** Reduces manual prospecting effort and supports lower CAC.

---

# Limitations & Roadmap

**Currently in Development:** *Advanced Intelligence Agents*

- **Technographic Scanner:** Detects specific software stacks.
- **Ads Intelligence Agent:** Analyzes a company's paid marketing.
- **Review Pain Miner:** Finds customer pain points from public reviews.
- **Revenue Leakage Score:** Prioritizes accounts based on public friction and intent signals.

*Note: These agents are currently being validated and will supercharge our next version.*
