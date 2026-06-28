"use client";

import React, { useState, useEffect, useRef } from "react";
import CampaignSettings from "../components/CampaignSettings";

interface Lead {
  name: string;
  category: string;
  phone: string;
  email: string;
  website: string;
  address: string;
  is_good_lead: boolean;
  ai_notes: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_BASE = API_BASE.replace('http', 'ws');

export default function Dashboard() {
  const [goal, setGoal] = useState("");
  const [limit, setLimit] = useState<number | string>(10);
  const [isSearching, setIsSearching] = useState(false);
  const [unifiedLogs, setUnifiedLogs] = useState<any[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filename, setFilename] = useState("");
  const [activeMode, setActiveMode] = useState<"hunt" | "outreach" | "inbound" | "intelligence">("hunt");

  // CRM Intelligence States
  const [crmLeads, setCrmLeads] = useState<any[]>([]);
  const [crmTotal, setCrmTotal] = useState(0);
  const [crmPage, setCrmPage] = useState(0);
  const [crmSearch, setCrmSearch] = useState("");
  const [crmSelectedLead, setCrmSelectedLead] = useState<any>(null);
  const [crmTimeline, setCrmTimeline] = useState<any[]>([]);
  const [crmStats, setCrmStats] = useState<any>(null);

  // CRM Filter States
  const [filterIndustry, setFilterIndustry] = useState("All Industries");
  const [filterCity, setFilterCity] = useState("All Cities");
  const [filterSource, setFilterSource] = useState("All Sources");
  const [filterEnrichmentStatus, setFilterEnrichmentStatus] = useState("All");
  const [filterGlobalStatus, setFilterGlobalStatus] = useState("All");

  // Dynamic CRM Metadata
  const [crmMetadata, setCrmMetadata] = useState({ industries: [], cities: [], sources: [] });

  // CRM Ingest Modal States
  const [isIngestModalOpen, setIsIngestModalOpen] = useState(false);
  const [ingestPreviewData, setIngestPreviewData] = useState<any>(null);
  const [ingestPreviewLoading, setIngestPreviewLoading] = useState(false);
  const [selectedIngestFile, setSelectedIngestFile] = useState("all");
  const [ingestLimit, setIngestLimit] = useState<number | string>(100);
  const [understandRisk, setUnderstandRisk] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<any>(null);
  const [expandedSampleCsv, setExpandedSampleCsv] = useState<string | null>(null);

  const [skipExisting, setSkipExisting] = useState(true);
  const [useAiEnrichment, setUseAiEnrichment] = useState(false);
  const [scraperMode, setScraperMode] = useState<"maps" | "web" | "youtube">("maps");
  const [isDarkMode, setIsDarkMode] = useState(true);

  // Outreach States
  const [availableCampaigns, setAvailableCampaigns] = useState<any[]>([]);

  const [selectedCampaign, setSelectedCampaign] = useState<any>(null);
  const [previewData, setPreviewData] = useState<any>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  const [isDrafting, setIsDrafting] = useState(false);
  const [availableLists, setAvailableLists] = useState<any[]>([]);
  const [pitch, setPitch] = useState("");
  const [senderName, setSenderName] = useState(""); // Your Identity / Signature
  const [selectedList, setSelectedList] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Inbound Intelligence (Agent 3)
  const [inboundMessages, setInboundMessages] = useState<any[]>([]);
  const [isInboundLoading, setIsInboundLoading] = useState(false);
  const [radarActive, setRadarActive] = useState(true);
  const [activeFilter, setActiveFilter] = useState("ALL");
  const [activeCampaignFilter, setActiveCampaignFilter] = useState("ALL");
  const [isCampaignDropdownOpen, setIsCampaignDropdownOpen] = useState(false);
  const [inboundSearch, setInboundSearch] = useState("");

  const addLog = (source: 'HUNT' | 'OUTREACH' | 'RADAR', message: string) => {
    setUnifiedLogs(prev => [
      ...prev,
      {
        source,
        message,
        timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }
    ]);
  };

  const logEndRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const FILTER_GROUPS: Record<string, string[]> = {
    HOT: ['interested_now'],
    WARM: ['interested_later', 'needs_info'],
    REFERRAL: ['referral', 'wrong_person'],
    COLD: ['not_interested', 'objection', 'unclear']
  };

  // Initial Load & Theme Persistence
  useEffect(() => {
    // Theme initialization
    const savedTheme = localStorage.getItem("neural-theme");
    if (savedTheme === "light") setIsDarkMode(false);

    fetchLists();
    fetchCampaigns();
    fetchInbound();
    fetchRadarStatus();
    const interval = setInterval(() => {
      fetchCampaigns();
      fetchInbound();
      fetchRadarStatus();
    }, 10000);
    return () => {
      stopLimitHold();
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (isDarkMode) {
      document.body.classList.remove('light-mode');
      localStorage.setItem("neural-theme", "dark");
    } else {
      document.body.classList.add('light-mode');
      localStorage.setItem("neural-theme", "light");
    }
  }, [isDarkMode]);

  // Real-time polling for the currently viewed campaign details (updates "Delivered" stats live)
  useEffect(() => {
    if (!selectedCampaign?.id) return;
    const interval = setInterval(() => {
      fetchCampaignDetail(selectedCampaign.id);
    }, 5000);
    return () => clearInterval(interval);
  }, [selectedCampaign?.id]);

  const fetchRadarStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/radar/status`);
      const data = await res.json();
      setRadarActive(data.active);
    } catch (e) {
      console.error("Failed to fetch radar status", e);
    }
  };

  const toggleRadar = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/radar/toggle`, { method: "POST" });
      const data = await res.json();
      setRadarActive(data.active);
    } catch (e) {
      console.error("Failed to toggle radar", e);
    }
  };

  const fetchInbound = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/inbound`);
      const data = await res.json();
      setInboundMessages(data.messages || []);
    } catch (e) {
      console.error("Failed to fetch inbound", e);
    }
  };


  const fetchLists = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/lists`);
      const data = await res.json();
      setAvailableLists(data.lists || []);
    } catch (e) {
      console.error("Failed to fetch lists", e);
    }
  };

  const fetchCrmStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/crm/stats`);
      const data = await res.json();
      setCrmStats(data);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchCrmMetadata = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/crm/metadata`);
      const data = await res.json();
      setCrmMetadata({
        industries: data.industries || [],
        cities: data.cities || [],
        sources: data.sources || []
      });
    } catch (e) {
      console.error(e);
    }
  };

  const fetchCrmLeads = async (
    page = 0,
    search = crmSearch,
    ind = filterIndustry,
    cit = filterCity,
    src = filterSource,
    enrStat = filterEnrichmentStatus,
    glbStat = filterGlobalStatus
  ) => {
    try {
      const query = new URLSearchParams({
        limit: "20",
        offset: (page * 20).toString(),
        search: search,
        industry: ind,
        city: cit,
        source: src,
        enrichment_status: enrStat,
        status: glbStat
      });
      const res = await fetch(`${API_BASE}/api/crm/leads?${query.toString()}`);
      const data = await res.json();
      setCrmLeads(data.data || []);
      setCrmTotal(data.total || 0);
      setCrmPage(page);
    } catch (e) {
      console.error("Failed to fetch CRM leads", e);
    }
  };

  const fetchCrmLeadDetail = async (id: number) => {
    try {
      const [detailRes, timelineRes] = await Promise.all([
        fetch(`${API_BASE}/api/crm/leads/${id}`),
        fetch(`${API_BASE}/api/crm/leads/${id}/timeline`)
      ]);
      const detailData = await detailRes.json();
      const timelineData = await timelineRes.json();

      setCrmSelectedLead(detailData);
      setCrmTimeline(timelineData.timeline || []);
    } catch (e) {
      console.error("Failed to fetch CRM lead detail", e);
    }
  };

  // Initial CRM load
  useEffect(() => {
    if (activeMode === "intelligence") {
      fetchCrmStats();
      fetchCrmMetadata();
      fetchCrmLeads(crmPage, crmSearch, filterIndustry, filterCity, filterSource, filterEnrichmentStatus, filterGlobalStatus);
    }
  }, [activeMode]);

  // CRM Ingest Modal Actions
  const fetchIngestPreview = async () => {
    try {
      setIngestPreviewLoading(true);
      setIngestPreviewData(null);
      const res = await fetch(`${API_BASE}/api/crm/ingest/preview`);
      const data = await res.json();
      setIngestPreviewData(data);
    } catch (e) {
      console.error("Failed to fetch Ingest Preview", e);
    } finally {
      setIngestPreviewLoading(false);
    }
  };

  const runIngestAction = async (isDryRun: boolean) => {
    try {
      setIsIngesting(true);
      setIngestResult(null);
      const payload = {
        filename: selectedIngestFile,
        dry_run: isDryRun,
        limit: ingestLimit === "null" || ingestLimit === null || ingestLimit === "" ? null : Number(ingestLimit)
      };

      const res = await fetch(`${API_BASE}/api/crm/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || "Unknown Server Error");
      }

      setIngestResult(data);

      // Scroll modal body to top so the result card is immediately visible
      setTimeout(() => {
        document.getElementById("ingest-modal-body")?.scrollTo({ top: 0, behavior: "smooth" });
      }, 100);

      // Auto-refresh stats and list on successful real ingest
      if (!isDryRun && data.status === "success") {
        fetchCrmStats();
        fetchCrmLeads(0, crmSearch, filterIndustry, filterCity, filterSource, filterEnrichmentStatus, filterGlobalStatus);
      }
    } catch (e) {
      console.error("Ingestion failed", e);
      setIngestResult({ status: "error", message: String(e) });
    } finally {
      setIsIngesting(false);
    }
  };

  useEffect(() => {
    if (isIngestModalOpen) {
      fetchIngestPreview();
      setSelectedIngestFile("all");
      setIngestLimit(100);
      setUnderstandRisk(false);
      setIngestResult(null);
      setExpandedSampleCsv(null);
    }
  }, [isIngestModalOpen]);


  const fetchCampaigns = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/campaigns`);
      const data = await res.json();
      setAvailableCampaigns(data.campaigns || []);

      // If we have a selected campaign, refresh its full state
      if (selectedCampaign) {
        const detailRes = await fetch(`${API_BASE}/api/campaigns/${selectedCampaign.id}`);
        const detailData = await detailRes.json();
        setSelectedCampaign(detailData || null);
      }
    } catch (e) {
      console.error("Failed to fetch campaigns", e);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setAttachments(prev => [...prev, ...Array.from(e.target.files!)]);
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
  };

  const uploadAttachments = async () => {
    if (attachments.length === 0) return [];

    const formData = new FormData();
    attachments.forEach(file => formData.append("files", file));

    const res = await fetch(`${API_BASE}/api/upload-context`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    return data.filenames?.map((f: string) => `${API_BASE}/context_uploads/${f}`) || [];
  };

  const startLimitHold = (delta: number) => {
    if (isSearching) return;

    // Immediate first click
    setLimit(prev => {
      const val = typeof prev === 'number' ? prev : (parseInt(prev) || 10);
      return Math.min(100000, Math.max(1, val + delta));
    });

    // Wait 400ms before starting rapid ultra-scroll (matching native OS behavior)
    intervalRef.current = setTimeout(() => {
      intervalRef.current = setInterval(() => {
        setLimit(prev => {
          const val = typeof prev === 'number' ? prev : (parseInt(prev) || 10);
          return Math.min(100000, Math.max(1, val + delta));
        });
      }, 70); // 70ms rapid increment
    }, 400);
  };

  const stopLimitHold = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      clearTimeout(intervalRef.current);
    }
  };

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [unifiedLogs.length]);


  const startProspecting = () => {
    if (!goal) return;

    addLog("HUNT", "━━━ NEW PROSPECTING MISSION INITIALIZED ━━━");
    setLeads([]);
    setIsSearching(true);

    ws.current = new WebSocket(`${WS_BASE}/ws/prospect`);

    ws.current.onopen = () => {
      ws.current?.send(JSON.stringify({ goal, limit, use_hunt: true, skip_existing: skipExisting, scraper_mode: scraperMode, use_ai_enrichment: useAiEnrichment }));
    };

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "log") {
        addLog("HUNT", data.message);
      } else if (data.type === "ping") {
        // Keepalive heartbeat — ignore silently (prevents timeout)
      } else if (data.type === "result") {
        setLeads(data.data?.leads || []);
        setFilename(data.data?.filename || "");
        setTimeout(() => {
          setIsSearching(false);
          ws.current?.close();
        }, 2000);
      } else if (data.type === "error") {
        addLog("HUNT", "❌ Error: " + data.message);
        setTimeout(() => {
          setIsSearching(false);
        }, 2500);
      }
    };

    ws.current.onerror = () => {
      addLog("HUNT", "❌ Connection error. Backend may be unreachable.");
      setIsSearching(false);
    };

    ws.current.onclose = (e) => {
      if (e.code !== 1000 && isSearching) {
        addLog("HUNT", "⚠️ Connection closed unexpectedly. Please retry.");
        setIsSearching(false);
      }
    };
  };

  const stopProspecting = () => {
    if (ws.current) {
      ws.current.close();
      ws.current = null;
    }
    setIsSearching(false);
    addLog("HUNT", "🛑 MISSION TERMINATED BY OPERATOR.");
  };

  const startCampaignDrafting = async () => {
    if (!selectedList || !pitch || isDrafting) return;

    setIsDrafting(true);
    setUnifiedLogs([]); // Clear logs for new drafting session

    try {
      // 1. Upload context files if any
      const contextFiles = await uploadAttachments();

      // 2. Open Websocket for drafting
      const socket = new WebSocket(`${WS_BASE}/ws/campaign`);
      ws.current = socket;

      socket.onopen = () => {
        socket.send(JSON.stringify({
          csv_filename: selectedList,
          pitch: pitch,
          sender_name: senderName,
          context_files: contextFiles
        }));
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "log") {
          addLog("OUTREACH", data.message);
        } else if (data.type === "result") {
          setSelectedCampaign(data.campaign || null);
          setIsDrafting(false);
          fetchCampaigns();
          socket.close();
        } else if (data.type === "error") {
          addLog("OUTREACH", "❌ Error: " + data.message);
          setIsDrafting(false);
        }
      };

      socket.onerror = () => {
        addLog("OUTREACH", "❌ WebSocket Connection Error.");
        setIsDrafting(false);
      };

      socket.onclose = () => {
        setIsDrafting(false);
      };
    } catch (error) {
      console.error("Drafting failed", error);
      addLog("OUTREACH", "❌ Failed to initiate drafting engine.");
      setIsDrafting(false);
    }
  };

  const fetchCampaignDetail = async (id: string) => {
    try {
      const detailRes = await fetch(`${API_BASE}/api/campaigns/${id}`);
      const detailData = await detailRes.json();
      setSelectedCampaign(detailData || null);
    } catch (e) {
      console.error("Failed to fetch campaign details", e);
    }
  };


  const handlePreviewEnqueue = async (id: string) => {
    setIsPreviewing(true);
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/${id}/preview_enqueue`);
      const data = await res.json();
      setPreviewData(data);
    } catch (e) {
      console.error(e);
      alert("Failed to preview enqueue");
    } finally {
      setIsPreviewing(false);
    }
  };

  const confirmEnqueue = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/${id}/enqueue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true })
      });
      const data = await res.json();
      alert(`Enqueued: ${data.jobs_created} jobs created. (${data.already_exists} already existed)`);
      setPreviewData(null);
      // Now actually start the legacy loop or mark active (we will keep the old start so UI updates)
      await controlCampaign(id, "start");
    } catch (e) {
      console.error(e);
      alert("Failed to enqueue jobs");
    }
  };

  const controlCampaign = async (id: string, action: "start" | "pause" | "stop") => {

    try {
      await fetch(`${API_BASE}/api/campaigns/${id}/${action}`, { method: "POST" });
      await fetchCampaignDetail(id);
      fetchCampaigns();
    } catch (e) {
      console.error(`Failed to ${action} campaign`, e);
    }
  };

  const updateSettings = async (id: string, settings: any) => {
    try {
      await fetch(`${API_BASE}/api/campaigns/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings)
      });
      fetchCampaigns();
    } catch (e) {
      console.error("Failed to update settings", e);
    }
  };

  const resolveQuarantine = async (id: number) => {
    try {
      await fetch(`${API_BASE}/api/inbound/${id}/resolve`, { method: "POST" });
      fetchInbound();
    } catch (e) {
      console.error("Failed to resolve quarantine", e);
    }
  };

  const updateIntent = async (id: number, intent: string, action: string) => {
    try {
      await fetch(`${API_BASE}/api/inbound/${id}/intent`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent, action })
      });
      fetchInbound();
    } catch (e) {
      console.error("Failed to update intent", e);
    }
  };

  // ── New Inbound Panel Actions ──────────────────────────────────────
  const [replyOpenId, setReplyOpenId] = useState<number | null>(null);
  const [replySuccessId, setReplySuccessId] = useState<number | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [replySending, setReplySending] = useState(false);
  const [noteValues, setNoteValues] = useState<Record<number, string>>({});
  const [expandedCards, setExpandedCards] = useState<Set<number>>(new Set());

  // ── Campaign Lead Actions ─────────────────────────────────────────────
  const [editingLead, setEditingLead] = React.useState<{ email: string; subject: string; body: string; type: "gmail" | "whatsapp" } | null>(null);
  const [messageView, setMessageView] = useState<"gmail" | "whatsapp">("gmail");
  const [visibleCount, setVisibleCount] = useState(50);

  const deleteCampaignLead = async (campaignId: string, email: string) => {
    try {
      await fetch(`${API_BASE}/api/campaigns/${campaignId}/leads/${encodeURIComponent(email)}`, { method: 'DELETE' });
      setSelectedCampaign((prev: any) => prev ? {
        ...prev,
        leads: prev.leads.filter((l: any) => l.email !== email)
      } : prev);
    } catch (e) { console.error('Failed to delete lead', e); }
  };

  const saveCampaignLead = async (campaignId: string) => {
    if (!editingLead) return;
    try {
      await fetch(`${API_BASE}/api/campaigns/${campaignId}/leads/${encodeURIComponent(editingLead.email)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          editingLead.type === 'gmail' 
            ? { draft_email_subject: editingLead.subject, draft_email_body: editingLead.body }
            : { draft_whatsapp_body: editingLead.body }
        )
      });
      setSelectedCampaign((prev: any) => prev ? {
        ...prev,
        leads: prev.leads.map((l: any) => l.email === editingLead.email
          ? { 
              ...l, 
              ...(editingLead.type === 'gmail' 
                  ? { draft_email_subject: editingLead.subject, draft_email_body: editingLead.body }
                  : { draft_whatsapp_body: editingLead.body }
              )
            }
          : l
        )
      } : prev);
      setEditingLead(null);
    } catch (e) { console.error('Failed to save lead', e); }
  };

  const archiveMessage = async (id: number) => {
    try {
      await fetch(`${API_BASE}/api/inbound/${id}`, { method: "DELETE" });
      setInboundMessages(prev => prev.filter(m => m.id !== id));
    } catch (e) { console.error("Failed to archive", e); }
  };

  const toggleStar = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/inbound/${id}/star`, { method: "POST" });
      const data = await res.json();
      setInboundMessages(prev => prev.map(m => m.id === id ? { ...m, is_starred: data.is_starred } : m)
        .sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime())
      );
    } catch (e) { console.error("Failed to toggle star", e); }
  };

  const markAsRead = async (id: number) => {
    try {
      await fetch(`${API_BASE}/api/inbound/${id}/read`, { method: "POST" });
      setInboundMessages(prev => prev.map(m => m.id === id ? { ...m, is_read: 1 } : m));
    } catch (e) { console.error("Failed to mark read", e); }
  };

  const saveNote = async (id: number, note: string) => {
    try {
      await fetch(`${API_BASE}/api/inbound/${id}/note`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note })
      });
    } catch (e) { console.error("Failed to save note", e); }
  };

  const sendReply = async (id: number) => {
    if (!replyBody.trim() || replySending) return;
    setReplySending(true);
    try {
      const res = await fetch(`${API_BASE}/api/inbound/${id}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: replyBody, sender_name: senderName })
      });
      if (!res.ok) throw new Error("Send failed");
      setReplyOpenId(null);
      setReplyBody("");
      setReplySuccessId(id);
      setTimeout(() => setReplySuccessId(null), 3000);
    } catch (e) {
      console.error("Failed to send reply", e);
      alert("Failed to send reply. Please try again.");
    } finally {
      setReplySending(false);
    }
  };

  return (
    <main className="min-h-screen px-10 py-16 max-w-[1200px] mx-auto space-y-28 relative overflow-hidden">
      {/* Global Neural Switch (Top Right) */}
      <div className="fixed top-8 right-8 z-[100]">
        <div
          onClick={() => setIsDarkMode(!isDarkMode)}
          className="group flex flex-col items-center gap-3 cursor-pointer transition-all duration-300 active:scale-90"
        >
          <div className="text-[14px] transition-all duration-500 overflow-hidden h-5 flex items-center justify-center">
            {isDarkMode ? (
              /* Futuristic Minimalistic Moon */
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="text-[var(--text-muted)] group-hover:text-white transition-colors duration-300">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              /* Futuristic Minimalistic Sun */
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="text-[#1565C0] group-hover:scale-110 transition-all duration-300">
                <circle cx="12" cy="12" r="5" stroke="currentColor" strokeWidth="2" />
                <path d="M12 1V3M12 21V23M4.22 4.22L5.64 5.64M18.36 18.36L19.78 19.78M1 12H3M21 12H23M4.22 19.78L5.64 18.36M18.36 5.64L19.78 4.22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            )}
          </div>
          <div className={`w-12 h-6 rounded-full relative transition-all duration-500 border border-[var(--glass-border)] ${isDarkMode ? 'bg-black/[0.2] shadow-inner' : 'bg-[#1565C0]/10'}`}>
            <div
              className={`absolute top-1 w-3.5 h-3.5 rounded-full transition-all duration-500 shadow-xl ${isDarkMode ? 'left-1 bg-white/20' : 'left-7 bg-[#1565C0] shadow-[0_0_10px_#1565C0]'}`}
            />
          </div>
        </div>
      </div>
      <style dangerouslySetInnerHTML={{
        __html: `
        @keyframes fire-motion {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        .animate-fire {
          background-size: 200% 200% !important;
          animation: fire-motion 1.5s ease infinite !important;
        }
      `}} />


      {/* ━━ Header / Status HUD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <header className="flex justify-between items-center gap-12 relative">
        <div className="flex items-center gap-10">
          {/* Brand Logo Square */}
          <div
            className="w-20 h-20 shrink-0 transition-transform hover:scale-105 duration-500 flex items-center justify-center shadow-2xl"
            style={{
              borderRadius: "1.6rem",
              background: 'linear-gradient(145deg, #1c1c1f 0%, #111113 100%)'
            }}
          >
            <div
              style={{
                width: '44px',
                height: '44px',
                backgroundColor: (isSearching || (unifiedLogs?.length || 0) > 0 || (leads?.length || 0) > 0) ? '#1565C0' : '#ffffff',
                maskImage: 'url(/logo.svg)',
                maskSize: 'contain',
                maskRepeat: 'no-repeat',
                maskPosition: 'center',
                WebkitMaskImage: 'url(/logo.svg)',
                WebkitMaskSize: 'contain',
                WebkitMaskRepeat: 'no-repeat',
                WebkitMaskPosition: 'center',
                transition: 'background-color 0.6s ease',
              }}
            />
          </div>

          <div className="space-y-3">
            <h1 className="text-5xl font-black tracking-[-0.05em] leading-none text-[var(--text-primary)]">
              SDR <span className="text-[var(--text-muted)]">Agent</span>
            </h1>
            <p className="text-[var(--text-muted)] font-black uppercase text-[9px] tracking-[0.5em] leading-none">
              Autonomous Outbound Intelligence & Neural Prospecting
            </p>
          </div>
        </div>

        <div className="flex items-center gap-10">
          <div className="flex flex-col items-end gap-6">
            <div className="flex bg-white/[0.03] p-1.5 rounded-2xl border border-[var(--glass-border)] shadow-inner">
              <button
                onClick={() => setActiveMode("hunt")}
                className={`px-8 py-3 rounded-xl text-[10px] uppercase font-black tracking-[0.4em] transition-all duration-300 ${activeMode === "hunt" ? "bg-[var(--accent-blue)] text-white shadow-xl" : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"}`}
              >Hunt</button>
              <button
                onClick={() => setActiveMode("outreach")}
                className={`px-8 py-3 rounded-xl text-[10px] uppercase font-black tracking-[0.4em] transition-all duration-300 ${activeMode === "outreach" ? "bg-[var(--accent-blue)] text-white shadow-xl" : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"}`}
              >Outreach</button>
              <button
                onClick={() => setActiveMode("inbound")}
                className={`px-8 py-3 rounded-xl text-[10px] uppercase font-black tracking-[0.4em] transition-all duration-300 ${activeMode === "inbound" ? "bg-[var(--accent-blue)] text-white shadow-xl" : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"}`}
              >Inbound</button>
              <button
                onClick={() => setActiveMode("intelligence")}
                className={`px-8 py-3 rounded-xl text-[10px] uppercase font-black tracking-[0.4em] transition-all duration-300 ${activeMode === "intelligence" ? "bg-[var(--accent-blue)] text-white shadow-xl" : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"}`}
              >Lead Intelligence</button>
            </div>

            <div
              className={`glass px-8 py-2.5 flex items-center gap-5 shadow-2xl transition-all duration-500 border border-[var(--glass-border)]`}
              style={{
                borderColor: 'var(--glass-border)',

              }}
            >
              <div
                className={`w-2.5 h-2.5 rounded-full transition-all duration-500 ${(isSearching || selectedCampaign?.status === 'active' || activeMode === 'inbound') ? 'animate-neural-pulse' : ''}`}
                style={{
                  backgroundColor: (isSearching || selectedCampaign?.status === 'active' || activeMode === 'inbound') ? '#00E676' : '#1B5E20',
                  opacity: (isSearching || selectedCampaign?.status === 'active' || activeMode === 'inbound') ? 1 : 0.3,
                  boxShadow: (isSearching || selectedCampaign?.status === 'active' || activeMode === 'inbound') ? '0 0 16px rgba(0, 230, 118, 0.8)' : 'none'
                }}
              />
              <span className="text-[10px] uppercase font-black tracking-[0.5em] text-[var(--text-muted)]">
                {isSearching ? "Neural Hunt Active" : selectedCampaign?.status === 'active' ? "Virtual SDR Drip Engaged" : activeMode === 'inbound' ? "Inbound Intelligence Live" : "System Idle"}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* ━━ CRM Intelligence Mode (Agent 4) ━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {activeMode === "intelligence" && (
        <section className="space-y-12 animate-in fade-in slide-in-from-bottom-5 duration-700">
          {!crmSelectedLead ? (
            <div className="glass p-12 space-y-8 h-[800px] flex flex-col">
              <div className="pb-6 border-b border-[var(--glass-border)] flex flex-col gap-6">
                <div className="flex justify-between items-start w-full">
                  <div className="space-y-1">
                    <h2 className="text-xl font-black tracking-tight uppercase text-[var(--text-primary)]">Lead Intelligence</h2>
                    <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">Global CRM Registry</p>
                  </div>
                  <button
                    onClick={() => setIsIngestModalOpen(true)}
                    className="px-6 py-2.5 rounded-xl text-[9px] uppercase font-black tracking-[0.2em] transition-all duration-300 bg-[var(--accent-blue)] text-white hover:bg-[var(--accent-blue-hover)] hover:shadow-lg border border-[var(--accent-blue)] hover:-translate-y-0.5 cursor-pointer shrink-0 font-bold"
                  >
                    Ingest Cold Leads
                  </button>
                </div>

                <div className="flex justify-between items-center gap-6 w-full">
                  {/* KPI Cards */}
                  {crmStats && (
                    <div className="flex gap-4 items-center flex-1">
                      <div className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 flex gap-3 items-center flex-1 justify-center">
                        <span className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Total Leads</span>
                        <span className={`text-base font-black ${crmStats.total_leads === 0 ? 'text-[var(--text-dim)]' : 'text-[var(--text-primary)]'}`}>{crmStats.total_leads}</span>
                      </div>
                      <div className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 flex gap-3 items-center flex-1 justify-center">
                        <span className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Contacted</span>
                        <span className={`text-base font-black ${crmStats.contacted === 0 ? 'text-[var(--text-dim)]' : 'text-[var(--text-primary)]'}`}>{crmStats.contacted}</span>
                      </div>
                      <div className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 flex gap-3 items-center flex-1 justify-center">
                        <span className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Replies</span>
                        <span className={`text-base font-black ${crmStats.replies === 0 ? 'text-[var(--text-dim)]' : 'text-[var(--text-primary)]'}`}>{crmStats.replies}</span>
                      </div>
                      <div className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 flex gap-3 items-center flex-1 justify-center">
                        <span className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Interested</span>
                        <span className={`text-base font-black ${crmStats.interested === 0 ? 'text-[var(--text-dim)]' : 'text-[var(--text-primary)]'}`}>{crmStats.interested}</span>
                      </div>
                      <div className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 flex gap-3 items-center flex-1 justify-center opacity-70">
                        <span className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Suppressed</span>
                        <span className={`text-base font-black ${crmStats.suppressed === 0 ? 'text-[var(--text-dim)]' : 'text-[var(--text-primary)]'}`}>{crmStats.suppressed}</span>
                      </div>
                    </div>
                  )}

                  <div className="w-[300px] relative shrink-0">
                    <input
                      type="text"
                      value={crmSearch}
                      onChange={(e) => {
                        setCrmSearch(e.target.value);
                        fetchCrmLeads(0, e.target.value, filterIndustry, filterCity, filterSource, filterEnrichmentStatus, filterGlobalStatus);
                      }}
                      placeholder="Search by name, email, or phone..."
                      className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-5 py-3 outline-none text-xs transition-all focus:border-[#1565C0]/50 text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
                    />
                    <svg className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                  </div>
                </div>
              </div>

              <div className="flex gap-4 items-center pb-6 border-b border-[var(--glass-border)] flex-wrap">
                <select
                  value={filterIndustry}
                  onChange={(e) => { setFilterIndustry(e.target.value); fetchCrmLeads(0, crmSearch, e.target.value, filterCity, filterSource, filterEnrichmentStatus, filterGlobalStatus); }}
                  className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2 text-[10px] uppercase font-black tracking-widest text-[var(--text-primary)] outline-none cursor-pointer"
                >
                  <option value="All Industries">All Industries</option>
                  {crmMetadata.industries.map((ind: string) => (
                    <option key={ind} value={ind}>{ind}</option>
                  ))}
                </select>

                <select
                  value={filterCity}
                  onChange={(e) => { setFilterCity(e.target.value); fetchCrmLeads(0, crmSearch, filterIndustry, e.target.value, filterSource, filterEnrichmentStatus, filterGlobalStatus); }}
                  className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2 text-[10px] uppercase font-black tracking-widest text-[var(--text-primary)] outline-none cursor-pointer"
                >
                  <option value="All Cities">All Cities</option>
                  {crmMetadata.cities.map((city: string) => (
                    <option key={city} value={city}>{city}</option>
                  ))}
                </select>

                <select
                  value={filterSource}
                  onChange={(e) => { setFilterSource(e.target.value); fetchCrmLeads(0, crmSearch, filterIndustry, filterCity, e.target.value, filterEnrichmentStatus, filterGlobalStatus); }}
                  className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2 text-[10px] uppercase font-black tracking-widest text-[var(--text-primary)] outline-none cursor-pointer"
                >
                  <option value="All Sources">All Sources</option>
                  {crmMetadata.sources.map((src: string) => (
                    <option key={src} value={src}>{src}</option>
                  ))}
                </select>

                <select
                  value={filterEnrichmentStatus}
                  onChange={(e) => { setFilterEnrichmentStatus(e.target.value); fetchCrmLeads(0, crmSearch, filterIndustry, filterCity, filterSource, e.target.value, filterGlobalStatus); }}
                  className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2 text-[10px] uppercase font-black tracking-widest text-[var(--text-primary)] outline-none cursor-pointer"
                >
                  <option value="All">All Enrichment</option>
                  <option value="Enriched">Enriched</option>
                  <option value="Needs Review">Needs Review</option>
                </select>

                <select
                  value={filterGlobalStatus}
                  onChange={(e) => { setFilterGlobalStatus(e.target.value); fetchCrmLeads(0, crmSearch, filterIndustry, filterCity, filterSource, filterEnrichmentStatus, e.target.value); }}
                  className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2 text-[10px] uppercase font-black tracking-widest text-[var(--text-primary)] outline-none cursor-pointer"
                >
                  <option value="All">All Status</option>
                  <option value="active">Active</option>
                  <option value="suppressed">Suppressed</option>
                </select>

                {(filterIndustry !== "All Industries" || filterCity !== "All Cities" || filterSource !== "All Sources" || filterEnrichmentStatus !== "All" || filterGlobalStatus !== "All" || crmSearch !== "") && (
                  <button
                    onClick={() => {
                      setFilterIndustry("All Industries");
                      setFilterCity("All Cities");
                      setFilterSource("All Sources");
                      setFilterEnrichmentStatus("All");
                      setFilterGlobalStatus("All");
                      setCrmSearch("");
                      fetchCrmLeads(0, "", "All Industries", "All Cities", "All Sources", "All", "All");
                    }}
                    className="px-4 py-2 rounded-xl text-[10px] uppercase font-black tracking-widest text-[var(--text-muted)] hover:text-white hover:bg-white/5 transition-all ml-auto"
                  >Clear Filters</button>
                )}
              </div>

              <div className="flex-1 overflow-auto overflow-x-auto pr-2 custom-scrollbar">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--glass-border)]">
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Lead Name</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Contact Info</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Website</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Industry</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">City</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Source</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] text-center">Touches</th>
                      <th className="pb-4 px-4 text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {crmLeads.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="py-20 text-center text-[var(--text-muted)] italic text-sm">No leads found in database.</td>
                      </tr>
                    ) : (
                      crmLeads.map(lead => (
                        <tr
                          key={lead.id}
                          onClick={() => fetchCrmLeadDetail(lead.id)}
                          className="border-b border-[var(--glass-border)] hover:bg-white/[0.02] cursor-pointer transition-colors group"
                        >
                          <td className="py-5 px-4 w-[20%]">
                            <p className="font-bold text-sm text-[var(--text-primary)] group-hover:text-[#1565C0] transition-colors truncate">{lead.name || 'Unknown'}</p>
                          </td>
                          <td className="py-5 px-4 space-y-1 w-[20%]">
                            <p className="text-xs text-[var(--text-secondary)] truncate">{lead.email}</p>
                            {lead.phone && <p className="text-[10px] text-[var(--text-muted)] truncate">{lead.phone.replace('tel:', '')}</p>}
                          </td>
                          <td className="py-5 px-4 w-[15%]">
                            {lead.website ? (
                              <a href={lead.website.startsWith('http') ? lead.website : `https://${lead.website}`} target="_blank" rel="noopener noreferrer" className="text-[10px] text-[#1565C0] hover:underline truncate block" onClick={(e) => e.stopPropagation()}>
                                {lead.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
                              </a>
                            ) : (
                              <span className="text-[10px] text-[var(--text-dim)] italic">-</span>
                            )}
                          </td>
                          <td className="py-5 px-4">
                            <span className={`text-[9px] font-medium ${lead.industry === 'Unclassified' ? 'text-[var(--text-dim)] italic' : 'text-[var(--text-primary)]'}`}>
                              {lead.industry || 'Unclassified'}
                            </span>
                          </td>
                          <td className="py-5 px-4">
                            <span className={`text-[9px] font-medium ${lead.city === 'Unknown' ? 'text-[var(--text-dim)] italic' : 'text-[var(--text-primary)]'}`}>
                              {lead.city || 'Unknown'}
                            </span>
                          </td>
                          <td className="py-5 px-4">
                            <span className={`text-[9px] font-medium ${lead.acquisition_source === 'Unknown' ? 'text-[var(--text-dim)] italic' : 'text-[var(--text-primary)]'}`}>
                              {lead.acquisition_source || 'Unknown'}
                            </span>
                          </td>
                          <td className="py-5 px-4 text-center">
                            <span className={`text-[10px] font-black tabular-nums px-2 py-1 rounded ${lead.touch_count > 0 ? 'bg-[#1565C0]/10 text-[#1565C0]' : 'text-[var(--text-dim)]'}`}>{lead.touch_count}</span>
                          </td>
                          <td className="py-5 px-4">
                            <div className="flex flex-col gap-1 items-start">
                              <span className={`text-[8px] px-2 py-0.5 rounded uppercase tracking-widest font-black border ${lead.global_status === 'active' ? 'border-emerald-500/30 text-emerald-500 bg-emerald-500/5' :
                                  lead.global_status === 'suppressed' ? 'border-red-500/30 text-red-500 bg-red-500/5' :
                                    'border-[var(--glass-border)] text-[var(--text-muted)] bg-[var(--input-bg)]'
                                }`}>{lead.global_status}</span>
                              {lead.enrichment_status === 'Needs Review' && (
                                <span className="text-[7px] uppercase tracking-widest font-black text-amber-500">Needs Review</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-between items-center pt-4 border-t border-[var(--glass-border)]">
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                  Showing {crmTotal === 0 ? 0 : crmPage * 20 + 1} - {Math.min((crmPage + 1) * 20, crmTotal)} of {crmTotal}
                </p>
                <div className="flex gap-4">
                  <button
                    onClick={() => fetchCrmLeads(Math.max(0, crmPage - 1))}
                    disabled={crmPage === 0}
                    className="px-6 py-2 border border-[var(--glass-border)] rounded-xl text-[9px] uppercase font-black text-[var(--text-muted)] hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >Prev</button>
                  <button
                    onClick={() => fetchCrmLeads(crmPage + 1)}
                    disabled={(crmPage + 1) * 20 >= crmTotal}
                    className="px-6 py-2 border border-[var(--glass-border)] rounded-xl text-[9px] uppercase font-black text-[var(--text-muted)] hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >Next</button>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
              {/* Profile Panel */}
              <div className="lg:col-span-1 glass p-10 flex flex-col space-y-8 h-[800px] overflow-y-auto custom-scrollbar">
                <button
                  onClick={() => setCrmSelectedLead(null)}
                  className="text-[var(--text-muted)] hover:text-white uppercase text-[9px] tracking-widest font-black flex items-center gap-2 transition-all w-fit"
                >
                  ← Back to Database
                </button>

                <div className="space-y-1">
                  <h2 className="text-2xl font-black tracking-tight leading-tight text-[var(--text-primary)]">{crmSelectedLead.name || 'Unknown Lead'}</h2>
                  <div className="flex items-center gap-2 flex-wrap pt-2">
                    <span className={`text-[8px] px-2 py-0.5 rounded uppercase tracking-widest font-black border ${crmSelectedLead.global_status === 'active' ? 'border-emerald-500/30 text-emerald-500 bg-emerald-500/5' :
                        crmSelectedLead.global_status === 'suppressed' ? 'border-red-500/30 text-red-500 bg-red-500/5' :
                          'border-[var(--glass-border)] text-[var(--text-muted)] bg-[var(--input-bg)]'
                      }`}>{crmSelectedLead.global_status}</span>
                    <span className="text-[8px] uppercase tracking-widest font-black text-[var(--text-dim)]">•</span>
                    <span className="text-[8px] uppercase tracking-widest font-black text-[var(--text-dim)]">{crmSelectedLead.touch_count} TOUCHES</span>
                    {crmSelectedLead.campaigns?.length > 0 && (
                      <>
                        <span className="text-[8px] uppercase tracking-widest font-black text-[var(--text-dim)]">•</span>
                        <span className="text-[8px] uppercase tracking-widest font-black text-[#1565C0]">{crmSelectedLead.campaigns[0].current_lead_status.replace('_', ' ')}</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="space-y-6">
                  <div>
                    <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-1">Email</p>
                    <p className="text-sm font-medium text-[var(--text-secondary)]">{crmSelectedLead.email}</p>
                  </div>
                  {crmSelectedLead.phone && (
                    <div>
                      <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-1">Phone</p>
                      <p className="text-sm font-medium text-[var(--text-secondary)]">{crmSelectedLead.phone.replace('tel:', '')}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-1">Engagement</p>
                    <div className="flex gap-4">
                      <div className="bg-[var(--input-bg)] px-4 py-2 rounded-xl border border-[var(--glass-border)]">
                        <p className="text-lg font-black text-[#1565C0]">{crmSelectedLead.touch_count}</p>
                        <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] font-black">Touches</p>
                      </div>
                    </div>
                  </div>
                  {crmSelectedLead.map_url && (
                    <div>
                      <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-1">Source Link</p>
                      <a href={crmSelectedLead.map_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#1565C0] hover:underline truncate block">View Original Source ↗</a>
                    </div>
                  )}
                </div>

                <div className="pt-6 border-t border-[var(--glass-border)] space-y-4">
                  <h3 className="text-[10px] uppercase tracking-widest font-black text-[var(--text-primary)]">Associated Campaigns</h3>
                  {crmSelectedLead.campaigns?.length === 0 ? (
                    <p className="text-xs text-[var(--text-muted)] italic">No campaigns yet.</p>
                  ) : (
                    crmSelectedLead.campaigns?.map((camp: any, i: number) => (
                      <div key={i} className="bg-[var(--input-bg)] p-4 rounded-xl border border-[var(--glass-border)] space-y-2">
                        <p className="text-[11px] font-bold truncate text-[var(--text-secondary)]" title={camp.csv_source}>
                          {camp.csv_source.replace('.csv', '').replace(/_/g, ' ').replace('leads', '').trim() || camp.csv_source}
                        </p>
                        <div className="flex justify-between items-center">
                          <span className={`text-[8px] uppercase tracking-widest font-black ${camp.current_lead_status === 'pending_approval' ? 'text-amber-500' :
                              camp.current_lead_status === 'approved' ? 'text-[#1565C0]' :
                                camp.current_lead_status === 'sent' ? 'text-emerald-500' :
                                  'text-[var(--text-muted)]'
                            }`}>{camp.current_lead_status.replace('_', ' ')}</span>
                          <span className="text-[8px] uppercase tracking-widest font-black text-[var(--text-dim)]">{camp.last_touch_at ? new Date(camp.last_touch_at).toLocaleDateString() : 'No touch'}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Timeline Panel */}
              <div className="lg:col-span-2 glass p-10 flex flex-col h-[800px]">
                <h3 className="text-lg font-black uppercase tracking-widest text-[var(--text-primary)] mb-8 border-b border-[var(--glass-border)] pb-6">Interaction Timeline</h3>

                <div className="flex-1 overflow-y-auto space-y-8 pr-4 custom-scrollbar">
                  {crmTimeline.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center space-y-4">
                      <svg className="w-12 h-12 text-[var(--text-muted)]/30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
                      <p className="text-sm text-[var(--text-muted)] italic text-center">This lead exists in the CRM but has not received any outbound message yet.</p>
                    </div>
                  ) : (
                    crmTimeline.map((event, i) => (
                      <div key={i} className={`flex gap-6 ${event.type === 'outbound' ? 'flex-row-reverse' : ''}`}>
                        {/* Icon Indicator */}
                        <div className="shrink-0 pt-1">
                          {event.type === 'outbound' ? (
                            <div className="w-8 h-8 rounded-full bg-[#1565C0]/10 flex items-center justify-center border border-[#1565C0]/30 shadow-[0_0_15px_rgba(21,101,192,0.15)]">
                              <svg className="w-4 h-4 text-[#1565C0]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
                            </div>
                          ) : (
                            <div className="w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.15)]">
                              <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                            </div>
                          )}
                        </div>

                        {/* Message Card */}
                        <div className={`flex-1 max-w-[80%] space-y-2 ${event.type === 'outbound' ? 'items-end text-right' : 'items-start text-left'}`}>
                          <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">
                            {new Date(event.timestamp).toLocaleString()}
                          </p>

                          <div className={`p-6 rounded-2xl border ${event.type === 'outbound'
                              ? 'bg-[var(--input-bg)] border-[var(--glass-border)] rounded-tr-sm'
                              : 'bg-white/[0.02] border-[var(--glass-border)] rounded-tl-sm'
                            }`}>
                            <h4 className="font-bold text-[var(--text-primary)] text-sm mb-3">{event.subject}</h4>

                            {event.type === 'inbound' && event.body_clean && (
                              <p className="text-xs text-[var(--text-secondary)] font-light leading-relaxed mb-4 whitespace-pre-wrap text-left">
                                {event.body_clean}
                              </p>
                            )}

                            {event.type === 'outbound' && event.body && (
                              <p className="text-xs text-[var(--text-secondary)] font-light leading-relaxed mb-4 whitespace-pre-wrap text-right">
                                {event.body}
                              </p>
                            )}

                            {/* AI Classifications for Inbound */}
                            {event.type === 'inbound' && event.intent_class && (
                              <div className="flex gap-3 items-center justify-start mt-4 pt-4 border-t border-[var(--glass-border)]">
                                <span className={`text-[8px] px-3 py-1 rounded-full uppercase tracking-widest font-black ${event.intent_class === 'interested_now' ? 'bg-[#1565C0]/20 text-[#1565C0]' :
                                    event.intent_class === 'interested_later' ? 'bg-amber-500/20 text-amber-500' :
                                      event.intent_class === 'needs_info' ? 'bg-emerald-500/20 text-emerald-500' :
                                        event.intent_class === 'wrong_person' ? 'bg-purple-500/20 text-purple-500' :
                                          event.intent_class === 'referral' ? 'bg-pink-500/20 text-pink-500' :
                                            event.intent_class === 'not_interested' ? 'bg-red-500/20 text-red-600' :
                                              event.intent_class === 'objection' ? 'bg-orange-500/20 text-orange-600' :
                                                'bg-[var(--input-bg)] text-[var(--text-muted)]'
                                  }`}>
                                  {event.intent_class.replace('_', ' ')}
                                </span>
                                <span className="text-[10px] text-[var(--text-dim)] font-black">
                                  {((event.confidence || 0) * 100).toFixed(0)}% Conf
                                </span>
                                <span className="text-[9px] uppercase tracking-widest font-bold text-[var(--text-muted)] ml-auto truncate max-w-[200px]">
                                  Act: {event.suggested_action}
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ━━ Inbound Intelligence Mode (Agent 3) ━━━━━━━━━━━━━━━━━━━━━━ */}

      {activeMode === "inbound" && (
        <section className="space-y-12 animate-in fade-in slide-in-from-bottom-5 duration-700">
          <div className="flex justify-between items-end border-b border-[var(--glass-border)] pb-6">
            <div className="space-y-1">
              <h2 className="text-3xl font-black tracking-[-0.04em] text-[var(--text-primary)]">Neural Triage Console</h2>
              <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-[0.2em] font-black">Strategic Sentiment Analysis & Signal Actioning</p>
            </div>

            <div
              onClick={toggleRadar}
              className="flex items-center gap-4 cursor-pointer group/radar"
            >
              <div className="text-right">
                <p className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] group-hover/radar:text-[var(--text-primary)] transition-colors">Inbound Radar</p>
                <p className={`text-[8px] font-black uppercase tracking-widest ${radarActive ? 'text-[#00E676]' : 'text-[#1B5E20]/50'}`}>
                  {radarActive ? 'Live Heartbeat' : 'Radar Offline'}
                </p>
              </div>
              <div className={`w-12 h-6 rounded-full relative transition-all duration-500 ${radarActive ? 'bg-[#00E676]/20' : 'bg-[var(--input-bg)]'}`}>
                <div className={`absolute top-1.5 w-3 h-3 rounded-full transition-all duration-500 shadow-sm ${radarActive ? 'right-1.5 bg-[#00E676] shadow-[0_0_12px_rgba(0,230,118,1)]' : 'left-1.5 bg-[#1B5E20] opacity-40'}`} />
              </div>
            </div>
          </div>

          {/* Stats Header */}
          {(() => {
            const campaignFiltered = activeCampaignFilter === "ALL" 
              ? inboundMessages 
              : inboundMessages.filter(m => m.campaign_name === activeCampaignFilter);
              
            const unread = campaignFiltered.filter(m => !m.is_read).length;
            const hot = campaignFiltered.filter(m => m.intent_class === 'interested_now').length;
            const needsAction = campaignFiltered.filter(m => m.requires_review === 1 || m.processing_status === 'quarantined').length;
            const starred = campaignFiltered.filter(m => m.is_starred).length;
            return (
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: 'Total Replies', val: campaignFiltered.length, color: 'text-[var(--text-primary)]' },
                  { label: 'Unread', val: unread, color: unread > 0 ? 'text-[#1565C0]' : 'text-[var(--text-dim)]' },
                  { label: 'Hot Leads', val: hot, color: hot > 0 ? 'text-emerald-400' : 'text-[var(--text-dim)]' },
                  { label: 'Needs Action', val: needsAction, color: needsAction > 0 ? 'text-amber-500' : 'text-[var(--text-dim)]' },
                ].map(stat => (
                  <div key={stat.label} className="glass p-5 flex flex-col gap-1 border border-[var(--glass-border)]">
                    <span className="text-[8px] uppercase font-black tracking-widest text-[var(--text-muted)]">{stat.label}</span>
                    <span className={`text-3xl font-black tabular-nums leading-none ${stat.color}`}>{stat.val}</span>
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Search Bar */}
          <div className="relative">
            <svg className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
            <input
              type="text"
              value={inboundSearch}
              onChange={e => setInboundSearch(e.target.value)}
              placeholder="Search by sender, subject, or message content..."
              className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-2xl pl-12 pr-6 py-4 outline-none text-sm transition-all focus:border-[#1565C0]/50 text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
            />
            {inboundSearch && (
              <button onClick={() => setInboundSearch('')} className="absolute right-5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-white transition-colors">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            )}
          </div>

          {/* Neural Filter Bar */}
          {(() => {
            const campaignFiltered = activeCampaignFilter === "ALL" 
              ? inboundMessages 
              : inboundMessages.filter(m => m.campaign_name === activeCampaignFilter);
              
            return (
            <div className="flex items-center gap-3 pb-4 relative z-40 w-full">
              {/* Scrollable Filters */}
              <div className="flex items-center gap-3 overflow-x-auto scrollbar-hide flex-1">
                <button
                  onClick={() => setActiveFilter("ALL")}
                  className={`px-5 py-2.5 shrink-0 flex-1 flex justify-center rounded-2xl text-[9px] uppercase font-black tracking-[0.3em] border transition-all ${activeFilter === 'ALL' ? 'bg-[#1565C0] text-white border-[#1565C0] shadow-[0_0_25px_rgba(21,101,192,0.2)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--glass-border)] hover:border-[var(--accent-blue)]'
                    }`}
                >All Signals</button>

                {Object.keys(FILTER_GROUPS).map(group => {
                  const count = campaignFiltered.filter(msg => FILTER_GROUPS[group]?.includes(msg.intent_class)).length;
                  return (
                    <button
                      key={group}
                      onClick={() => setActiveFilter(group)}
                      className={`px-5 py-2.5 shrink-0 flex-1 flex justify-center rounded-2xl text-[9px] uppercase font-black tracking-[0.3em] border transition-all items-center gap-2 ${activeFilter === group ? 'bg-[#1565C0] text-white border-[#1565C0] shadow-[0_0_25px_rgba(21,101,192,0.3)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--glass-border)] hover:border-[var(--accent-blue)]'
                        }`}
                    >
                      {group}
                      {count > 0 && (
                        <span className={`text-[10px] font-black grid place-items-center min-w-[22px] h-[22px] px-1.5 rounded-full leading-none tracking-normal ${activeFilter === group ? 'bg-white/20 text-white' :
                            group === 'HOT' ? 'bg-[#1565C0]/20 text-[#1565C0]' :
                              group === 'WARM' ? 'bg-amber-500/20 text-amber-500' :
                                group === 'REFERRAL' ? 'bg-pink-500/20 text-pink-500' :
                                  'bg-[var(--glass-border)] text-[var(--text-muted)]'
                          }`}>
                          {count > 99 ? '99+' : count}
                        </span>
                      )}
                    </button>
                  );
                })}

                <button
                  onClick={() => setActiveFilter("STARRED")}
                  className={`px-5 py-2.5 shrink-0 flex-1 flex justify-center rounded-2xl text-[10px] uppercase font-black tracking-[0.3em] border transition-all items-center gap-2 ${activeFilter === 'STARRED' ? 'bg-[#1565C0] text-white border-[#1565C0] shadow-[0_0_25px_rgba(21,101,192,0.3)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--glass-border)] hover:border-[var(--accent-blue)]'
                    }`}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill={activeFilter === 'STARRED' ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2.5">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                  </svg>
                  {campaignFiltered.filter(msg => msg.is_starred).length > 0 && (
                    <span className={`text-[10px] font-black grid place-items-center min-w-[22px] h-[22px] px-1.5 rounded-full leading-none tracking-normal ${activeFilter === 'STARRED' ? 'bg-white/20 text-white' : 'bg-amber-500/20 text-amber-500'
                      }`}>
                      {campaignFiltered.filter(msg => msg.is_starred).length > 99 ? '99+' : campaignFiltered.filter(msg => msg.is_starred).length}
                    </span>
                  )}
                </button>
              </div>

              {/* Campaign Dropdown */}
              <div className="relative shrink-0 flex-1 flex max-w-[200px]">
                <button
                  onClick={() => setIsCampaignDropdownOpen(!isCampaignDropdownOpen)}
                  className={`w-full px-5 py-2.5 rounded-2xl text-[10px] uppercase font-black tracking-[0.3em] border transition-all flex justify-center items-center gap-2 ${activeCampaignFilter !== 'ALL' ? 'bg-[var(--accent-blue)] text-white border-[var(--accent-blue)] shadow-[0_0_25px_rgba(21,101,192,0.3)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--glass-border)] hover:border-[var(--accent-blue)]'
                    }`}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" /></svg>
                  {activeCampaignFilter === 'ALL' ? 'Campaign' : activeCampaignFilter.replace('.csv', '').replace(/_/g, ' ').split(' ').slice(0, 2).join(' ')}
                </button>

                {isCampaignDropdownOpen && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setIsCampaignDropdownOpen(false)}></div>
                    <div className={`absolute right-0 mt-3 w-64 border border-[var(--glass-border)] rounded-2xl shadow-[0_15px_40px_rgba(21,101,192,0.3)] z-[100] flex flex-col p-2 ${isDarkMode ? 'bg-[#0a1d3f] backdrop-blur-2xl text-white' : 'glass text-[var(--text-primary)]'}`}>
                      <button
                        onClick={() => { setActiveCampaignFilter("ALL"); setIsCampaignDropdownOpen(false); }}
                        className={`px-4 py-3 rounded-xl text-[10px] uppercase font-black tracking-widest text-left transition-all ${activeCampaignFilter === 'ALL' ? (isDarkMode ? 'bg-[#1565C0]/40 text-white' : 'bg-[var(--accent-blue)] text-white') : (isDarkMode ? 'text-white/70 hover:bg-white/10 hover:text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-primary)]')
                          }`}
                      >
                        All Campaigns
                      </button>
                      {Array.from(new Set(inboundMessages.map(m => m.campaign_name).filter(Boolean))).map(campName => (
                        <button
                          key={campName}
                          onClick={() => { setActiveCampaignFilter(campName); setIsCampaignDropdownOpen(false); }}
                          className={`px-4 py-3 rounded-xl text-[10px] uppercase font-black tracking-widest text-left transition-all break-words mt-1 ${activeCampaignFilter === campName ? (isDarkMode ? 'bg-[#1565C0]/40 text-white' : 'bg-[var(--accent-blue)] text-white') : (isDarkMode ? 'text-white/70 hover:bg-white/10 hover:text-white' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-primary)]')
                            }`}
                        >
                          {campName.replace('.csv', '').replace(/_/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          )})()}

          <div className="grid grid-cols-1 gap-6">
            {(() => {
              const filtered = inboundMessages.filter(msg => {
                const matchesIntent = activeFilter === "ALL" ||
                  (activeFilter === "STARRED" ? msg.is_starred : FILTER_GROUPS[activeFilter]?.includes(msg.intent_class));
                  
                const matchesCampaign = activeCampaignFilter === "ALL" || msg.campaign_name === activeCampaignFilter;
                  
                const q = inboundSearch.toLowerCase();
                const matchesSearch = !q ||
                  (msg.sender || '').toLowerCase().includes(q) ||
                  (msg.subject || '').toLowerCase().includes(q) ||
                  (msg.body_clean || '').toLowerCase().includes(q);
                  
                return matchesIntent && matchesCampaign && matchesSearch;
              });

              if (filtered.length === 0) {
                return (
                  <div className="glass p-20 flex flex-col items-center justify-center gap-6 text-center">
                    <span className="text-[10px] uppercase font-black tracking-[0.6em] text-[var(--text-muted)]">
                      {inboundSearch ? `No results for "${inboundSearch}"` : `No ${activeFilter === 'ALL' ? 'Signals' : activeFilter + ' Leads'} Detected`}
                    </span>
                    <p className="text-sm text-[var(--text-muted)] font-light max-w-[300px]">The Inbound Intelligence Engine has filtered all signals for this specific intent group.</p>
                  </div>
                );
              }

              return filtered.map((msg, i) => {
                const isExpanded = expandedCards.has(msg.id);
                const toggleExpand = () => {
                  setExpandedCards(prev => {
                    const next = new Set(prev);
                    if (next.has(msg.id)) { next.delete(msg.id); }
                    else {
                      next.add(msg.id);
                      if (!msg.is_read) markAsRead(msg.id);
                    }
                    return next;
                  });
                };

                const intentColor = (cls: string) =>
                  cls === 'interested_now' ? 'bg-[#1565C0]/20 text-[#1565C0]' :
                    cls === 'interested_later' ? 'bg-amber-500/20 text-amber-500' :
                      cls === 'needs_info' ? 'bg-emerald-500/20 text-emerald-500' :
                        cls === 'wrong_person' ? 'bg-purple-500/20 text-purple-500' :
                          cls === 'referral' ? 'bg-pink-500/20 text-pink-500' :
                            cls === 'not_interested' ? 'bg-red-500/20 text-red-600' :
                              cls === 'objection' ? 'bg-orange-500/20 text-orange-600' :
                                'bg-[var(--input-bg)] text-[var(--text-muted)]';

                return (
                  <div
                    key={i}
                    className={`glass group border-[var(--glass-border)] border-l-2 transition-all duration-300 overflow-hidden ${msg.is_starred ? 'border-l-amber-500/60' : !msg.is_read ? 'border-l-[#1565C0]/60' : 'border-l-transparent'
                      }`}
                  >
                    {/* ── Clickable Header (always visible) ─────────────── */}
                    <div
                      className="flex items-center gap-4 px-6 py-4 cursor-pointer hover:bg-white/[0.02] transition-colors select-none"
                      onClick={toggleExpand}
                    >
                      {/* Unread dot */}
                      <div className="shrink-0 w-3 flex justify-center">
                        {!msg.is_read && (
                          <span className="w-2 h-2 rounded-full bg-[#1565C0] shadow-[0_0_8px_rgba(21,101,192,0.9)] animate-pulse" />
                        )}
                      </div>

                      {/* Sender + subject */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 flex-wrap">
                          <div className="flex flex-col items-start justify-center pt-1">
                            <span className={`font-black text-base tracking-tight leading-tight ${!msg.is_read ? 'text-white' : 'text-[var(--text-primary)]'}`}>
                              {msg.sender?.split('<')[0].trim() || msg.sender}
                            </span>
                            {msg.sender?.includes('<') && (
                              <span className="text-[9px] font-mono tracking-widest text-[var(--text-muted)] opacity-60">
                                {msg.sender.split('<')[1].replace('>', '').trim()}
                              </span>
                            )}
                          </div>
                          {msg.intent_class && (
                            <span className={`text-[8px] px-2.5 py-0.5 rounded-full uppercase tracking-widest font-black shrink-0 ${intentColor(msg.intent_class)}`}>
                              {msg.intent_class.replaceAll('_', ' ')}
                            </span>
                          )}
                          {msg.processing_status === 'quarantined' && (
                            <span className="text-[8px] px-2 py-0.5 rounded border border-red-500/30 text-red-500 uppercase font-black tracking-widest shrink-0">quarantined</span>
                          )}
                          {msg.urgency === 'high' && !msg.has_reply && (
                            <span className="text-[8px] px-2 py-0.5 rounded-md font-black uppercase tracking-tighter bg-red-500 text-white animate-pulse shrink-0">urgent</span>
                          )}
                        </div>
                        <p className="text-[10px] text-[var(--text-muted)] font-black tracking-widest mt-0.5 truncate">
                          {msg.subject || '(no subject)'} · {new Date(msg.received_at).toLocaleString()}
                        </p>
                      </div>

                      {/* Actions: star, delete, chevron */}
                      <div className="flex items-center gap-3 shrink-0">
                        {msg.has_reply ? (
                          <div title="You replied to this message" className="text-emerald-500 cursor-help transition-all hover:scale-110 flex items-center">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M3 10h10a8 8 0 018 8v2M3 10l6 6M3 10l6-6"/>
                              <path d="M9 22l-5-5 5-5" className="opacity-0"/> {/* Invisible padding for shape */}
                              <circle cx="19" cy="19" r="4" fill="currentColor" className="text-emerald-500"/>
                              <path d="M17.5 19.5l1 1 2-2" stroke="white" strokeWidth="2"/>
                            </svg>
                          </div>
                        ) : null}
                        <button
                          onClick={e => { e.stopPropagation(); toggleStar(msg.id); }}
                          className={`transition-all duration-200 hover:scale-110 ${msg.is_starred ? 'text-amber-400' : 'text-[var(--text-dim)] hover:text-amber-400'}`}
                          title={msg.is_starred ? 'Unpin' : 'Pin to top'}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill={msg.is_starred ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                          </svg>
                        </button>
                        <button
                          onClick={e => { e.stopPropagation(); archiveMessage(msg.id); }}
                          className="text-[var(--text-dim)] hover:text-red-500 transition-all duration-200 hover:scale-110 opacity-0 group-hover:opacity-100"
                          title="Archive"
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4h6v2" />
                          </svg>
                        </button>
                        <svg
                          className={`w-4 h-4 text-[var(--text-muted)] transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
                          fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </div>

                    {/* ── Expandable Detail Body ──────────────────────────── */}
                    {isExpanded && (
                      <div className="px-6 pb-8 space-y-6 border-t border-[var(--glass-border)] pt-6">
                        {/* Scores row */}
                        <div className="flex items-center gap-6">
                          <div className="flex items-center gap-2">
                            <span className="text-[8px] uppercase font-black text-[var(--text-muted)] tracking-widest">Match</span>
                            <span className={`text-lg font-black tabular-nums ${msg.match_confidence > 0.85 ? 'text-[#1565C0]' : 'text-[var(--text-muted)]'}`}>
                              {((msg.match_confidence || 0) * 100).toFixed(0)}%
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-[8px] uppercase font-black text-[var(--text-muted)] tracking-widest">Intent Conf</span>
                            <span className={`text-lg font-black tabular-nums ${msg.intent_confidence > 0.85 ? 'text-emerald-500' : 'text-[var(--text-muted)]'}`}>
                              {((msg.intent_confidence || 0) * 100).toFixed(0)}%
                            </span>
                          </div>
                          <span className={`text-[8px] px-2 py-0.5 rounded border uppercase font-black tracking-widest ml-auto ${msg.processing_status === 'resolved' || msg.processing_status === 'actioned' ? 'border-green-500/20 text-green-500/40' :
                              msg.processing_status === 'quarantined' ? 'border-red-500/30 text-red-500' :
                                'border-[var(--glass-border)] text-[var(--text-muted)]'
                            }`}>{msg.processing_status}</span>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                          <div className="space-y-4">
                            <h5 className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest">Decision Analysis</h5>
                            <div className="p-6 bg-[var(--input-bg)] rounded-2xl border border-[var(--glass-border)] space-y-4 max-h-[300px] overflow-y-auto overflow-x-hidden">
                              <p className="text-sm text-[var(--text-dim)] leading-relaxed font-light break-words">{msg.body_clean || 'Normalization Pending...'}</p>
                              {msg.reasoning_summary && (
                                <p className="text-[10px] text-emerald-500/60 font-medium italic border-t border-[var(--glass-border)] pt-3 break-words">
                                  AI Logic: "{msg.reasoning_summary}"
                                </p>
                              )}
                            </div>
                            {msg.outbound_body && (
                              <div className="space-y-3">
                                <h5 className="text-[8px] uppercase font-black text-[#1565C0]/60 tracking-widest flex items-center gap-2">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M15 10l-5 5-5-5" /></svg>
                                  Original Message Sent
                                </h5>
                                <div className="p-5 bg-[#1565C0]/5 rounded-2xl border border-dashed border-[#1565C0]/10">
                                  <p className="text-[9px] font-black text-[#1565C0]/40 uppercase mb-2">Subject: {msg.outbound_subject}</p>
                                  <p className="text-[11px] text-[var(--text-muted)] leading-relaxed line-clamp-3 hover:line-clamp-none transition-all cursor-pointer italic font-light">"{msg.outbound_body}"</p>
                                </div>
                              </div>
                            )}
                          </div>
                          <div className="space-y-4">
                            <h5 className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest">Extraction & Workflow</h5>
                            <div className="space-y-3">
                              <div className="flex justify-between items-center bg-[var(--input-bg)] p-4 rounded-xl border border-[var(--glass-border)]">
                                <span className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest">Detection Rule</span>
                                <span className="text-[10px] text-[#1565C0] font-black">{msg.matched_by_rule || 'None'}</span>
                              </div>
                              <div className="bg-[var(--input-bg)] p-4 rounded-xl border border-[var(--glass-border)] space-y-2">
                                <p className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest">Recommended Action</p>
                                <p className="text-[11px] text-[var(--text-dim)] font-bold">{msg.suggested_action || 'Awaiting classification...'}</p>
                              </div>

                              {/* Open Timeline Button */}
                              {msg.contact_id && (
                                <button 
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    fetchCrmLeadDetail(msg.contact_id);
                                    setActiveMode("intelligence");
                                    window.scrollTo({ top: 0, behavior: 'smooth' });
                                  }}
                                  className="w-full flex items-center justify-between p-4 bg-[#1565C0]/5 hover:bg-[#1565C0]/10 rounded-xl border border-[#1565C0]/20 transition-all cursor-pointer group"
                                >
                                  <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-full bg-[#1565C0]/10 flex items-center justify-center">
                                      <svg className="w-4 h-4 text-[#1565C0]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                                    </div>
                                    <div className="text-left">
                                      <p className="text-[10px] uppercase font-black tracking-widest text-[#1565C0]">View CRM Timeline</p>
                                      <p className="text-[9px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text-dim)] transition-colors mt-0.5">See full conversation history</p>
                                    </div>
                                  </div>
                                  <svg className="w-4 h-4 text-[#1565C0]/40 group-hover:text-[#1565C0] group-hover:translate-x-1 transition-all" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" /></svg>
                                </button>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Operator Notes */}
                        <div className="pt-4 border-t border-[var(--glass-border)]" onClick={e => e.stopPropagation()}>
                          <p className="text-[8px] uppercase font-black text-[var(--text-muted)] tracking-widest mb-2 flex items-center gap-2">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                            Operator Note
                          </p>
                          <textarea
                            placeholder="Add a private note..."
                            value={noteValues[msg.id] ?? (msg.operator_note || '')}
                            onChange={e => setNoteValues(prev => ({ ...prev, [msg.id]: e.target.value }))}
                            onBlur={() => saveNote(msg.id, noteValues[msg.id] ?? msg.operator_note ?? '')}
                            rows={2}
                            className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none resize-none focus:border-[#1565C0]/40 transition-colors"
                          />
                        </div>

                        {/* Quick Reply */}
                        <div className="pt-2" onClick={e => e.stopPropagation()}>
                          {replyOpenId === msg.id ? (
                            <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                              <div className="flex justify-between items-center">
                                <p className="text-[8px] uppercase font-black text-[#1565C0]/70 tracking-widest flex items-center gap-2">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 10h10a8 8 0 018 8v2M3 10l6 6M3 10l6-6" /></svg>
                                  Replying to {msg.sender?.split('<')[0].trim()}
                                </p>
                                <button onClick={() => { setReplyOpenId(null); setReplyBody(''); }} className="text-[var(--text-dim)] hover:text-white text-[9px] uppercase font-black tracking-widest transition-colors">Cancel</button>
                              </div>
                              <textarea
                                autoFocus
                                placeholder="Type your reply..."
                                value={replyBody}
                                onChange={e => setReplyBody(e.target.value)}
                                rows={4}
                                className="w-full bg-[var(--input-bg)] border border-[#1565C0]/30 rounded-xl px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none resize-none focus:border-[#1565C0]/60 transition-colors"
                              />
                              <div className="flex justify-end">
                                <button
                                  onClick={() => sendReply(msg.id)}
                                  disabled={replySending || !replyBody.trim()}
                                  className="flex items-center gap-2 px-6 py-2.5 bg-[#1565C0] hover:bg-[#1565C0]/80 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-[9px] uppercase font-black tracking-widest transition-all shadow-[0_0_20px_rgba(21,101,192,0.4)]"
                                >
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
                                  {replySending ? 'Sending...' : 'Send Reply'}
                                </button>
                              </div>
                            </div>
                          ) : replySuccessId === msg.id ? (
                            <div className="flex items-center gap-2 text-[10px] uppercase font-black tracking-widest text-emerald-500 animate-in fade-in duration-300">
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                              Sent ✓
                            </div>
                          ) : (
                            <button
                              onClick={() => { setReplyOpenId(msg.id); setReplyBody(''); }}
                              className="flex items-center gap-2 text-[8px] uppercase font-black tracking-widest text-[#1565C0]/60 hover:text-[#1565C0] transition-colors"
                            >
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 10h10a8 8 0 018 8v2M3 10l6 6M3 10l6-6" /></svg>
                              Quick Reply
                            </button>
                          )}
                        </div>

                        {/* LIVE TRIAGE CONTROLS */}
                        <div className="flex flex-wrap gap-4 pt-6 border-t border-[var(--glass-border)] justify-between items-center" onClick={e => e.stopPropagation()}>
                          <div className="flex gap-4">
                            {msg.processing_status === 'quarantined' && (
                              <button
                                onClick={() => resolveQuarantine(msg.id)}
                                className="px-6 py-2 bg-[#1565C0]/80 hover:bg-[#1565C0] rounded-xl text-[8px] uppercase font-black tracking-widest transition-all shadow-[0_0_20px_rgba(21,101,192,0.3)]"
                              >Confirm Match</button>
                            )}
                            {msg.requires_review === 1 && (
                              <span className="flex items-center gap-2 text-[8px] text-red-500 uppercase font-black tracking-widest px-4 py-2 bg-red-500/10 rounded-xl">
                                <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                                Operator Attention Required
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-3 bg-[var(--input-bg)] px-4 py-2 rounded-xl border border-[var(--glass-border)]">
                            <span className="text-[8px] text-[var(--text-muted)] uppercase font-black tracking-widest mr-2">Override Intent:</span>
                            <div className="flex gap-3">
                              {['interested_now', 'interested_later', 'needs_info', 'wrong_person', 'not_interested', 'objection', 'unclear'].map(intent => (
                                <button
                                  key={intent}
                                  onClick={() => updateIntent(msg.id, intent, `Human Triage: ${intent.replace('_', ' ')}`)}
                                  className={`text-[8px] uppercase font-black tracking-tighter hover:text-white transition-colors ${msg.intent_class === intent ? 'text-emerald-500' : 'text-[var(--text-muted)]'
                                    }`}
                                >{intent.split('_')[0]}{intent.includes('_') ? '+' : ''}</button>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              });
            })()}
          </div>
        </section>
      )}

      {/* ━━ Hunt Mode (Agent 1) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {activeMode === "hunt" && (
        <section className="glass p-12 space-y-12 relative group/panel shadow-2xl">
          <div className="space-y-6">
            <div className="flex justify-between items-end ml-1">
              <label className="text-[10px] uppercase tracking-[0.6em] text-[var(--text-muted)] font-black">Define Mission Parameter</label>

              <div className="flex items-center gap-6">
                {/* Neural Memory Toggle */}
                <div
                  onClick={() => !isSearching && setSkipExisting(!skipExisting)}
                  className={`flex items-center gap-3 cursor-pointer transition-all duration-300 ${isSearching ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-80'}`}
                >
                  <span className="text-[8px] uppercase tracking-[0.4em] font-black text-[var(--text-muted)]">Neural Memory</span>
                  <div className={`w-8 h-4 rounded-full relative transition-colors duration-500 ${skipExisting ? 'bg-[#1565C0]/40' : 'bg-[var(--input-bg)]'}`}>
                    <div className={`absolute top-1 w-2 h-2 rounded-full transition-all duration-500 shadow-sm ${skipExisting ? 'right-1 bg-[#ffffff] shadow-[0_0_8px_rgba(21,101,192,0.8)]' : 'left-1 bg-[var(--text-muted)]'}`} />
                  </div>
                </div>

                {/* AI Enrichment Toggle */}
                <div
                  onClick={() => !isSearching && setUseAiEnrichment(!useAiEnrichment)}
                  className={`flex items-center gap-3 cursor-pointer transition-all duration-300 ${isSearching ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-80'}`}
                >
                  <span className="text-[8px] uppercase tracking-[0.4em] font-black text-[var(--text-muted)]">AI Enrichment</span>
                  <div className={`w-8 h-4 rounded-full relative transition-colors duration-500 ${useAiEnrichment ? 'bg-[#1565C0]/40' : 'bg-[var(--input-bg)]'}`}>
                    <div className={`absolute top-1 w-2 h-2 rounded-full transition-all duration-500 shadow-sm ${useAiEnrichment ? 'right-1 bg-[#ffffff] shadow-[0_0_8px_rgba(21,101,192,0.8)]' : 'left-1 bg-[var(--text-muted)]'}`} />
                  </div>
                </div>
              </div>
            </div>

            {/* ── Scraper Mode Selector ────────────────────────────────────── */}
            <div className="flex items-center justify-between">
              <div className="flex bg-white/[0.03] p-1 rounded-2xl border border-[var(--glass-border)] shadow-inner">
                {([
                  { id: "maps", label: "Maps" },
                  { id: "web", label: "Web Search" },
                  { id: "youtube", label: "YouTube" },
                ] as const).map(mode => (
                  <button
                    key={mode.id}
                    id={`scraper-mode-${mode.id}`}
                    onClick={() => !isSearching && setScraperMode(mode.id)}
                    disabled={isSearching}
                    className={`px-5 py-2.5 rounded-xl text-[9px] uppercase font-black tracking-[0.25em] transition-all duration-300 ${scraperMode === mode.id
                        ? "bg-[var(--accent-blue)] text-white shadow-[0_0_20px_rgba(21,101,192,0.35)]"
                        : "text-[var(--text-dim)] hover:text-[var(--text-muted)] disabled:opacity-40"
                      }`}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
              <p className="text-[8px] text-[var(--text-muted)] uppercase font-black tracking-widest transition-all duration-300">
                {scraperMode === "maps" ? "Physical businesses via Google Maps" : scraperMode === "web" ? "Digital targets via DuckDuckGo & Web" : "YouTube channels & creators via API"}
              </p>
            </div>

            <div className="flex gap-8 items-center">
              <div className="relative flex-1 group/input">
                <textarea
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  rows={goal.includes("\n") ? Math.min(goal.split("\n").length, 5) : 1}
                  placeholder={
                    scraperMode === "maps"
                      ? "e.g. Luxury interior design studios in Barcelona...\n(Tip: Paste multiple queries, one per line, for Batch Mode!)"
                      : scraperMode === "web"
                        ? "e.g. Latin music blogs and playlist curators worldwide..."
                        : "e.g. Salsa mambo music channels, Latin DJs on YouTube..."
                  }
                  className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-2xl px-10 py-7 outline-none focus:border-[var(--accent-blue)] focus:bg-[var(--input-focus)] transition-all duration-300 text-2xl font-extralight tracking-[-0.02em] placeholder:text-[var(--text-muted)] text-[var(--text-primary)] placeholder:opacity-20 resize-none overflow-y-auto"
                  disabled={isSearching}
                  style={{ minHeight: '88px' }}
                />
              </div>

              <div className="flex items-center gap-5 ios-btn px-6 py-5 h-full group/limit hover:bg-[#0B3A82] hover:border-[#1565C0] hover:shadow-[0_0_30px_rgba(21,101,192,0.3)] transition-all duration-300">
                <span className="text-[8px] text-[var(--text-muted)] uppercase font-black tracking-[0.5em] shrink-0 group-hover/limit:text-white/60">Limit</span>
                <div className="flex items-center gap-4">
                  <button
                    onMouseDown={() => startLimitHold(-1)} onMouseUp={stopLimitHold} onMouseLeave={stopLimitHold}
                    disabled={isSearching}
                    className="stepper-btn select-none group-hover/limit:bg-[#1565C0] group-hover/limit:border-white/80 active:!border-transparent"
                  >−</button>
                  <input
                    type="number"
                    value={limit}
                    onChange={(e) => setLimit(e.target.value === '' ? '' : Math.min(100000, Math.max(1, parseInt(e.target.value) || 1)))}
                    className="font-black text-xl text-[var(--text-primary)] group-hover/limit:text-white w-14 text-center tabular-nums bg-transparent outline-none transition-colors hide-arrows"
                  />
                  <button
                    onMouseDown={() => startLimitHold(1)} onMouseUp={stopLimitHold} onMouseLeave={stopLimitHold}
                    disabled={isSearching}
                    className="stepper-btn select-none group-hover/limit:bg-[#1565C0] group-hover/limit:border-white/80 active:!border-transparent"
                  >+</button>
                </div>
              </div>
            </div>
          </div>

          <div className="flex justify-center items-center py-8">
            <button
              onClick={startProspecting}
              disabled={isSearching || !goal}
              className={`
              relative w-28 h-28 rounded-full flex items-center justify-center transition-all duration-700 group/button
              ${isSearching
                  ? 'cursor-not-allowed shadow-[0_0_60px_rgba(21,101,192,0.6)]'
                  : 'cursor-pointer active:scale-90 shadow-2xl'
                }
            `}
              style={{
                background: isSearching
                  ? 'linear-gradient(145deg, #1565C0 0%, #0D47A1 100%)'
                  : 'linear-gradient(145deg, #1c1c1f 0%, #111113 100%)',
                boxShadow: isSearching
                  ? '0 0 50px rgba(21,101,192,0.3), 0 10px 30px rgba(0,0,0,0.2)'
                  : '0 15px 40px rgba(0,0,0,0.4), 0 4px 8px rgba(0,0,0,0.2)'
              }}
            >
              <div className="relative w-[40px] h-[40px] transition-all duration-700">
                {/* Base Bird (White -> Blue) */}
                <div
                  style={{
                    width: '40px',
                    height: '40px',
                    maskImage: 'url(/logo.svg)',
                    maskSize: 'contain',
                    maskRepeat: 'no-repeat',
                    maskPosition: 'center',
                    WebkitMaskImage: 'url(/logo.svg)',
                    WebkitMaskSize: 'contain',
                    WebkitMaskRepeat: 'no-repeat',
                    WebkitMaskPosition: 'center',
                    transition: 'all 0.7s cubic-bezier(0.16, 1, 0.3, 1)',
                    filter: isSearching ? 'drop-shadow(0 0 8px rgba(255,255,255,0.8))' : 'none',
                  }}
                  className={`absolute inset-0 group-hover/panel:bg-[#1565C0] ${isSearching ? 'bg-[#ffffff] opacity-100' : 'bg-white opacity-80'}`}
                />

                {/* Fire Bird Overlay (Smooth Fade-in) */}
                <div
                  style={{
                    width: '40px',
                    height: '40px',
                    maskImage: 'url(/logo.svg)',
                    maskSize: 'contain',
                    maskRepeat: 'no-repeat',
                    maskPosition: 'center',
                    WebkitMaskImage: 'url(/logo.svg)',
                    WebkitMaskSize: 'contain',
                    WebkitMaskRepeat: 'no-repeat',
                    WebkitMaskPosition: 'center',
                    transition: 'all 0.7s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                  className="absolute inset-0 bg-gradient-to-b from-cyan-300 via-cyan-400 to-sky-500 opacity-0 group-hover/button:opacity-100"
                />
              </div>

              {/* Orbital Pulse (Only during search) */}
              {isSearching && (
                <div className="absolute inset-[-12px] border-2 border-[#1565C0]/30 rounded-full animate-ping pointer-events-none" />
              )}
            </button>

            {/* Manual Mission Termination Button */}
            {isSearching && (
              <button
                onClick={stopProspecting}
                className="absolute -bottom-24 left-1/2 -translate-x-1/2 flex items-center gap-3 px-6 py-2 rounded-full border border-red-500/30 bg-red-500/5 text-red-500/60 hover:text-red-500 hover:bg-red-500/10 hover:border-red-500/50 transition-all duration-300 animate-in fade-in slide-in-from-top-2 group/stop whitespace-nowrap z-50"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shadow-[0_0_8px_#ef4444]" />
                <span className="text-[9px] uppercase tracking-[0.4em] font-black">Terminate Mission</span>
              </button>
            )}
          </div>
        </section>
      )}

      {/* ━━ Outreach Mode (Agent 2) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {activeMode === "outreach" && !selectedCampaign && (
        <section className="space-y-12 animate-in fade-in slide-in-from-bottom-5 duration-700">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-stretch">
            <div className="glass p-12 flex flex-col h-full space-y-12">
              <h2 className="text-xl font-black tracking-tight uppercase text-[var(--text-primary)]">New Campaign</h2>
              <div className="space-y-12 flex flex-col flex-1">
                <div className="space-y-6">
                  <div className="flex justify-between items-center">
                    <label className="text-[10px] uppercase tracking-[0.5em] text-[var(--text-muted)] font-black">Select Scraped List</label>
                    <button
                      onClick={fetchLists}
                      className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-muted)] transition-colors"
                    >
                      ↻ Refresh
                    </button>
                  </div>
                  <select
                    value={selectedList}
                    onChange={(e) => setSelectedList(e.target.value)}
                    className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-2xl px-6 py-5 outline-none text-[var(--text-secondary)]"
                  >
                    <option value="">Select a list...</option>
                    {availableLists.map((l: any) => (
                      <option key={l.filename} value={l.filename}>{l.filename} ({l.contactable} leads)</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-6">
                  <div className="flex justify-between items-center">
                    <label className="text-[10px] uppercase tracking-[0.5em] text-[var(--text-muted)] font-black">Global Pitch / Offer</label>
                  </div>
                  <div className="relative">
                    <textarea
                      value={pitch}
                      onChange={(e) => setPitch(e.target.value)}
                      placeholder="What are we offering?"
                      className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-2xl px-6 py-5 outline-none h-48 text-sm leading-relaxed transition-all focus:border-[#1565C0]/50 pr-16"
                    />

                    {/* Paperclip Upload Trigger */}
                    <div className="absolute bottom-4 right-4 flex items-center gap-4">
                      <input
                        type="file"
                        multiple
                        ref={fileInputRef}
                        onChange={handleFileChange}
                        className="hidden"
                      />
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="p-3 bg-white/5 hover:bg-[#1565C0]/20 rounded-xl border border-white/5 transition-all group/clip shadow-lg"
                        title="Attach context (PDFs, Images)"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--text-muted)] group-hover/clip:text-[#1565C0]">
                          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>

                <div className="space-y-6">
                  <div className="flex justify-between items-center">
                    <label className="text-[10px] uppercase tracking-[0.5em] text-[var(--text-muted)] font-black">Your Identity / Signature Name</label>
                  </div>
                  <input
                    type="text"
                    value={senderName}
                    onChange={(e) => setSenderName(e.target.value)}
                    placeholder="e.g. Alex from UTOMi"
                    className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-2xl px-6 py-4 outline-none text-sm transition-all focus:border-[#1565C0]/50"
                  />
                </div>

                {/* Attachment Chips */}
                {attachments.length > 0 && (
                  <div className="flex flex-wrap gap-3">
                    {attachments.map((file, i) => (
                      <div key={i} className="flex items-center gap-3 bg-[var(--input-bg)] border border-[var(--glass-border)] px-4 py-2 rounded-xl">
                        <span className="text-[9px] uppercase font-black text-[var(--text-secondary)] truncate max-w-[120px]">{file.name}</span>
                        <button onClick={() => removeAttachment(i)} className="text-red-500/50 hover:text-red-500 transition-colors">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M18 6L6 18M6 6l12 12"></path></svg>
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex-1 flex flex-col items-center justify-center py-6 transition-all duration-700">
                  <button
                    onClick={startCampaignDrafting}
                    disabled={isDrafting || !selectedList || !pitch}
                    className={`
                          relative w-28 h-28 rounded-full flex items-center justify-center transition-all duration-700 group/button
                          ${isDrafting
                        ? 'cursor-not-allowed shadow-[0_0_60px_rgba(21,101,192,0.6)]'
                        : 'cursor-pointer active:scale-90 shadow-2xl'
                      }
                        `}
                    style={{
                      background: isDrafting
                        ? 'linear-gradient(145deg, #1565C0 0%, #0D47A1 100%)'
                        : 'linear-gradient(145deg, #1c1c1f 0%, #111113 100%)',
                      boxShadow: isDrafting
                        ? '0 0 50px rgba(21,101,192,0.3), 0 10px 30px rgba(0,0,0,0.2)'
                        : '0 15px 40px rgba(0,0,0,0.4), 0 4px 8px rgba(0,0,0,0.2)'
                    }}
                  >
                    <div className="relative w-[40px] h-[40px] transition-all duration-700">
                      {/* Base Bird */}
                      <div
                        style={{
                          width: '40px',
                          height: '40px',
                          maskImage: 'url(/logo.svg)',
                          maskSize: 'contain',
                          maskRepeat: 'no-repeat',
                          maskPosition: 'center',
                          WebkitMaskImage: 'url(/logo.svg)',
                          WebkitMaskSize: 'contain',
                          WebkitMaskRepeat: 'no-repeat',
                          WebkitMaskPosition: 'center',
                          transition: 'all 0.7s cubic-bezier(0.16, 1, 0.3, 1)',
                          filter: isDrafting ? 'drop-shadow(0 0 8px rgba(255,255,255,0.8))' : 'none',
                        }}
                        className={`absolute inset-0 ${isDrafting ? 'bg-[#ffffff] opacity-100' : 'bg-[#1565C0] group-hover/button:bg-[#1565C0] opacity-80'}`}
                      />

                      {/* Fire Bird Overlay */}
                      <div
                        style={{
                          width: '40px',
                          height: '40px',
                          maskImage: 'url(/logo.svg)',
                          maskSize: 'contain',
                          maskRepeat: 'no-repeat',
                          maskPosition: 'center',
                          WebkitMaskImage: 'url(/logo.svg)',
                          WebkitMaskSize: 'contain',
                          WebkitMaskRepeat: 'no-repeat',
                          WebkitMaskPosition: 'center',
                          transition: 'all 0.7s cubic-bezier(0.16, 1, 0.3, 1)',
                        }}
                        className="absolute inset-0 bg-gradient-to-b from-cyan-300 via-cyan-400 to-sky-500 opacity-0 group-hover/button:opacity-100"
                      />
                    </div>

                    {/* Orbital Pulse (Only during drafting) */}
                    {isDrafting && (
                      <div className="absolute inset-[-12px] border-2 border-[#1565C0]/30 rounded-full animate-ping pointer-events-none" />
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="glass p-12 flex flex-col h-full space-y-8">
              <h2 className="text-xl font-black tracking-tight uppercase text-[var(--text-primary)]">Active Campaigns</h2>
              <div className="space-y-1 max-h-[600px] overflow-y-auto pr-1">
                {availableCampaigns.length === 0 && <p className="text-[var(--text-muted)] italic text-center py-20">No campaigns found.</p>}
                {availableCampaigns.map((camp, idx) => (
                  <div
                    key={camp.id}
                    onClick={() => fetchCampaignDetail(camp.id)}
                    className={`px-4 py-3.5 cursor-pointer transition-all duration-200 flex justify-between items-center hover:bg-white/[0.025] rounded-xl ${idx !== availableCampaigns.length - 1 ? 'border-b border-[var(--glass-border)]' : ''
                      }`}
                  >
                    <div className="space-y-0.5">
                      <h4 className="font-semibold text-[13px] text-[var(--text-primary)] truncate max-w-[200px] tracking-tight">{camp.csv_source}</h4>
                      <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-[0.2em]">{new Date(camp.created_at).toLocaleDateString()}</p>
                    </div>
                    <div className="flex gap-3 items-center">
                      <span className={`text-[7px] px-2.5 py-1 rounded-full uppercase tracking-widest font-black ${camp.status === 'active' ? 'bg-[#1565C0]/15 text-[#1565C0]' : 'bg-[var(--glass-border)] text-[var(--text-muted)]'
                        }`}>{camp.status}</span>
                      <div className="text-right">
                        <p className="text-[12px] font-black text-[var(--text-dim)] tabular-nums">{(camp.stats?.sent || 0)} / {(camp.stats?.sent || 0) + (camp.stats?.pending || 0)}</p>
                        <p className="text-[7px] uppercase text-[var(--text-muted)] font-black tracking-widest">Delivered</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}


      {/* ━━ Campaign Details / Review Queue / Virtual SDR HUD ━━━━━━━━ */}

      {previewData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="glass p-8 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto relative animate-in zoom-in-95 duration-300">
            <h2 className="text-[12px] font-black tracking-[0.4em] text-[var(--text-primary)] uppercase mb-6">Preview de Envío (Dry Run)</h2>

            <div className="grid grid-cols-2 gap-4 mb-8">
              <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                <p className="text-[10px] text-gray-400 uppercase tracking-widest font-black mb-1">Leads Contactables</p>
                <p className="text-3xl font-black text-white">{previewData.jobs_iniciales_a_crear}</p>
                <p className="text-[10px] text-gray-500 mt-2">De {previewData.total_leads_pending} pendientes</p>
              </div>
              <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                <p className="text-[10px] text-gray-400 uppercase tracking-widest font-black mb-1">Ya en cola</p>
                <p className="text-3xl font-black text-white">{previewData.already_queued}</p>
              </div>
            </div>

            <div className="space-y-4 mb-8">
              <div className="flex justify-between items-center p-3 rounded-lg bg-white/5 text-sm">
                <span className="text-gray-400">Descartados (Bounced/Suppressed/Replied)</span>
                <span className="font-bold text-red-400">{previewData.leads_suppressed + previewData.leads_bounced + previewData.leads_replied + previewData.leads_unsubscribed}</span>
              </div>
              <div className="flex justify-between items-center p-3 rounded-lg bg-white/5 text-sm">
                <span className="text-gray-400">Sin Email</span>
                <span className="font-bold text-yellow-400">{previewData.leads_sin_email}</span>
              </div>
              <div className="flex justify-between items-center p-3 rounded-lg bg-[#1565C0]/20 border border-[#1565C0]/30 text-sm">
                <span className="text-[#1565C0] font-black uppercase tracking-widest text-[10px]">Primer Envío Estimado</span>
                <span className="font-bold text-white">{previewData.primer_scheduled_at ? new Date(previewData.primer_scheduled_at).toLocaleString() : 'N/A'}</span>
              </div>
              <div className="flex justify-between items-center p-3 rounded-lg bg-[#1565C0]/20 border border-[#1565C0]/30 text-sm">
                <span className="text-[#1565C0] font-black uppercase tracking-widest text-[10px]">Último Envío Estimado</span>
                <span className="font-bold text-white">{previewData.ultimo_scheduled_at ? new Date(previewData.ultimo_scheduled_at).toLocaleString() : 'N/A'}</span>
              </div>
            </div>

            {previewData.warnings && previewData.warnings.length > 0 && (
              <div className="mb-8 p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/30 text-yellow-500 text-sm">
                <span className="font-bold uppercase text-[10px] tracking-widest">Advertencias:</span>
                <ul className="list-disc pl-5 mt-2">
                  {previewData.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}

            <div className="flex justify-end gap-4">
              <button
                onClick={() => setPreviewData(null)}
                className="px-6 py-3 rounded-xl border border-gray-600 text-gray-300 font-bold text-xs uppercase tracking-widest hover:bg-gray-800 transition-all"
              >Cancelar</button>
              <button
                onClick={() => confirmEnqueue(selectedCampaign.id)}
                disabled={previewData.jobs_iniciales_a_crear === 0}
                className="px-6 py-3 rounded-xl bg-[#1565C0] text-white font-black text-xs uppercase tracking-widest hover:bg-[#0B3A82] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >Confirmar y Encolar</button>
            </div>
          </div>
        </div>
      )}

      {activeMode === "outreach" && selectedCampaign && (
        <section className="space-y-12 animate-in fade-in slide-in-from-bottom-5 duration-700">
          <div className="flex justify-between items-center">
            <button
              onClick={() => setSelectedCampaign(null)}
              className="text-[var(--text-muted)] hover:text-white uppercase text-[10px] tracking-widest font-black flex items-center gap-4 transition-all"
            >
              ← Back to List
            </button>
            <div className="flex gap-4">
              {selectedCampaign.status !== 'active' ? (
                <button
                  onClick={() => controlCampaign(selectedCampaign.id, "start")}
                  className="px-10 py-4 bg-transparent border border-[var(--glass-border)] text-[var(--text-primary)] hover:bg-[var(--accent-blue)] hover:border-[var(--accent-blue)] hover:text-white rounded-xl font-black text-[10px] uppercase tracking-[0.4em] transition-all duration-300 active:scale-[0.985] shadow-sm hover:shadow-[0_0_30px_rgba(21,101,192,0.3)]"
                >Activate Virtual SDR</button>
              ) : (
                <button
                  onClick={() => controlCampaign(selectedCampaign.id, "pause")}
                  className="px-10 py-4 bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl font-black text-[10px] uppercase tracking-[0.4em] text-[var(--text-primary)] hover:bg-white/5 transition-all"
                >Pause Campaign</button>
              )}
              <button
                onClick={() => controlCampaign(selectedCampaign.id, "stop")}
                className="px-10 py-4 border border-red-900/30 text-red-500/50 hover:bg-red-500/10 rounded-xl font-black text-[10px] uppercase tracking-[0.4em]"
              >Terminate</button>
            </div>
          </div>

          {selectedCampaign && selectedCampaign.leads ? (
            <div className="space-y-10">
              {/* Virtual SDR Control Panel */}
              <div className="space-y-10">
                <div className="glass p-12 space-y-12 relative group shadow-2xl">
                  <h2 className="text-[10px] font-black tracking-[0.6em] text-[var(--text-primary)] uppercase ml-1">Virtual SDR Parameters</h2>
                  <CampaignSettings
                    settings={selectedCampaign.settings}
                    totalLeads={(selectedCampaign?.leads || []).length}
                    onUpdate={(newSettings) => updateSettings(selectedCampaign.id, newSettings)}
                  />
                </div>

                {/* Personalized Review Queue */}
                <div className="glass p-12 space-y-12 relative group shadow-2xl">
                  <div className="flex justify-between items-end">
                    <h2 className="text-[10px] font-black tracking-[0.6em] text-[var(--text-primary)] uppercase ml-1">Review Queue</h2>
                    
                    {/* Channel Filter Toggle */}
                    <div className="flex bg-[var(--input-bg)] p-1 rounded-xl border border-[var(--glass-border)]">
                      <button
                        onClick={() => { setMessageView("gmail"); setVisibleCount(50); }}
                        className={`px-4 py-1.5 rounded-lg text-[9px] uppercase font-black tracking-widest transition-all ${messageView === "gmail" ? "bg-[#1565C0] text-white" : "text-[var(--text-dim)] hover:text-white"}`}
                      >
                        GMAIL
                      </button>
                      <button
                        onClick={() => { setMessageView("whatsapp"); setVisibleCount(50); }}
                        className={`px-4 py-1.5 rounded-lg text-[9px] uppercase font-black tracking-widest transition-all ${messageView === "whatsapp" ? "bg-[#128C7E] text-white" : "text-[var(--text-dim)] hover:text-white"}`}
                      >
                        WHATSAPP
                      </button>
                    </div>

                    <span className="text-[10px] font-black text-[var(--text-muted)] tracking-[0.2em] uppercase">
                      {((selectedCampaign?.leads || []).filter((l: any) => messageView === 'gmail' ? !!l.draft_email_body : !!l.draft_whatsapp_body)).length} {messageView === 'gmail' ? 'Gmails' : 'WhatsApps'}
                    </span>
                  </div>
                  <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2 p-4">
                    {((selectedCampaign?.leads || []).filter((l: any) => messageView === 'gmail' ? !!l.draft_email_body : !!l.draft_whatsapp_body))
                      .slice(0, visibleCount)
                      .map((lead: any, idx: number) => (
                      <div key={idx} className="p-8 border border-[var(--glass-border)] rounded-3xl space-y-6 group/card">
                        <div className="flex justify-between items-start">
                          <div className="space-y-2">
                            <div className="flex items-center gap-3">
                              <h4 className="font-black text-lg tracking-tight">{lead.name}</h4>
                              <span className="bg-[var(--input-bg)] text-[var(--text-secondary)] text-[8px] uppercase px-2 py-0.5 rounded-md font-bold">Score: {lead.ai_score || 50}</span>
                              {lead.touch_count > 0 && <span className="bg-yellow-500/20 text-yellow-500 text-[8px] uppercase px-2 py-0.5 rounded-md font-bold">Review (T{lead.touch_count})</span>}
                            </div>
                            <div className="flex items-center gap-4">
                              <p className={`text-[9px] uppercase font-black tracking-widest ${messageView === 'whatsapp' ? 'text-[#128C7E]' : 'text-[#1565C0]'}`}>
                                {messageView === 'gmail' ? lead.email : `+${lead.phone}`}
                              </p>
                              <span className="text-[8px] text-[var(--text-muted)] uppercase font-black tracking-widest border border-[var(--glass-border)] px-2 py-0.5 rounded-lg">
                                {messageView === 'gmail' ? 'Gmail Draft' : 'WhatsApp Draft'}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className={`text-[8px] px-3 py-1 rounded-full font-black uppercase tracking-widest ${lead.status === 'sent' ? 'bg-green-500/10 text-green-500' : lead.status === 'pending_approval' ? 'bg-[var(--input-bg)] text-[var(--text-muted)]' : 'bg-red-500/10 text-red-500'}`}>{lead.status}</span>
                            {lead.status !== 'sent' && (
                              <button onClick={() => setEditingLead({ email: lead.email, subject: lead.draft_email_subject || '', body: messageView === 'gmail' ? (lead.draft_email_body || '') : (lead.draft_whatsapp_body || ''), type: messageView })} className="text-[var(--text-dim)] hover:text-[#1565C0] transition-all duration-200 hover:scale-110 opacity-0 group-hover/card:opacity-100" title="Edit draft">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                              </button>
                            )}
                            {lead.status !== 'sent' && (
                              <button onClick={() => deleteCampaignLead(selectedCampaign.id, lead.email)} className="text-[var(--text-dim)] hover:text-red-500 transition-all duration-200 hover:scale-110 opacity-0 group-hover/card:opacity-100" title="Remove lead">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4h6v2" /></svg>
                              </button>
                            )}
                          </div>
                        </div>
                        {editingLead?.email === lead.email ? (
                          <div className="space-y-3 bg-[var(--input-bg)] p-6 rounded-2xl border border-[#1565C0]/40">
                            {editingLead.type === 'gmail' && (
                              <div className="space-y-1">
                                <label className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Asunto</label>
                                <input className="w-full bg-transparent border border-[var(--glass-border)] rounded-xl px-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#1565C0] transition-colors" value={editingLead.subject} onChange={e => setEditingLead(prev => prev ? { ...prev, subject: e.target.value } : null)} />
                              </div>
                            )}
                            <div className="space-y-1">
                              <label className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cuerpo ({editingLead.type})</label>
                              <textarea rows={6} className="w-full bg-transparent border border-[var(--glass-border)] rounded-xl px-4 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[#1565C0] transition-colors resize-none" value={editingLead.body} onChange={e => setEditingLead(prev => prev ? { ...prev, body: e.target.value } : null)} />
                            </div>
                            <div className="flex gap-3 justify-end pt-1">
                              <button onClick={() => setEditingLead(null)} className="text-[9px] uppercase font-black tracking-widest text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors px-4 py-2 rounded-xl border border-[var(--glass-border)]">Cancelar</button>
                              <button onClick={() => saveCampaignLead(selectedCampaign.id)} className="text-[9px] uppercase font-black tracking-widest text-white bg-[#1565C0] hover:bg-[#1976D2] transition-colors px-6 py-2 rounded-xl">Guardar</button>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-3 bg-[var(--input-bg)] p-6 rounded-2xl border border-[var(--glass-border)]">
                            {messageView === 'gmail' && <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest border-b border-[var(--glass-border)] pb-3">Subject: <span className="text-[var(--text-secondary)] ml-2">{lead.draft_email_subject}</span></p>}
                            <p className="text-sm text-[var(--text-dim)] leading-relaxed font-light whitespace-pre-wrap">{messageView === 'gmail' ? lead.draft_email_body : lead.draft_whatsapp_body}</p>
                          </div>
                        )}
                      </div>
                    ))}
                    
                    {visibleCount < ((selectedCampaign?.leads || []).filter((l: any) => messageView === 'gmail' ? !!l.draft_email_body : !!l.draft_whatsapp_body)).length && (
                      <div className="pt-4 flex justify-center">
                        <button 
                          onClick={() => setVisibleCount(prev => prev + 50)}
                          className="px-6 py-2 bg-[var(--input-bg)] hover:bg-white/5 border border-[var(--glass-border)] rounded-xl text-[9px] uppercase font-black tracking-[0.3em] text-[var(--text-muted)] transition-all"
                        >
                          Load More
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Real-time Drip Feed */}
              <div className="glass p-12 space-y-12 relative group shadow-2xl">
                <h3 className="text-[10px] font-black tracking-[0.6em] text-[var(--text-primary)] uppercase ml-1">Live Drip Feed</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
                  <div className="space-y-6">
                    <div className="flex justify-between items-end">
                      <span className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest">Delivered</span>
                      <span className="text-3xl font-black tabular-nums">{selectedCampaign?.stats?.sent || 0}</span>
                    </div>
                    <div className="h-1 bg-[var(--input-bg)] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#1565C0] transition-all duration-1000 shadow-[0_0_20px_#1565C0]"
                        style={{ width: `${((selectedCampaign?.stats?.sent || 0) / ((selectedCampaign?.stats?.sent || 0) + (selectedCampaign?.stats?.pending || 0)) || 0) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div className="space-y-4">
                    {selectedCampaign.status === 'active' && (
                      <div className="p-6 bg-transparent border border-[var(--glass-border)] rounded-2xl">
                        <p className="text-[9px] uppercase font-black text-[var(--text-muted)] tracking-widest mb-1">System Status</p>
                        <p className="text-[11px] text-[var(--text-primary)] font-bold flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#1565C0] animate-pulse"></span> Virtual SDR is active and analyzing patterns
                        </p>
                      </div>
                    )}
                    <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-bold text-center italic">
                      Mimicking human response intervals...
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="glass p-20 flex items-center justify-center">
              <span className="text-[10px] uppercase font-black tracking-widest text-[var(--text-muted)] animate-pulse">Scanning Campaign Data...</span>
            </div>
          )}
        </section>
      )}

      {/* ━━ Terminal / Live Feed ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div
        style={{
          opacity: (unifiedLogs.length > 0 || isSearching || isDrafting || (selectedCampaign?.logs?.length > 0)) ? 1 : 0,
          transform: (unifiedLogs.length > 0 || isSearching || isDrafting || (selectedCampaign?.logs?.length > 0)) ? 'translateY(0)' : 'translateY(12px)',
          transition: 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.2, 0.8, 0.2, 1)',
          willChange: 'opacity, transform',
          pointerEvents: (unifiedLogs.length > 0 || isSearching || isDrafting || (selectedCampaign?.logs?.length > 0)) ? 'auto' : 'none',
          minHeight: (unifiedLogs.length > 0 || isSearching || isDrafting || (selectedCampaign?.logs?.length > 0)) ? '300px' : 0,
        }}
      >
        <div className="glass p-10 bg-black/[0.15] border-[var(--glass-border)] max-h-[500px] overflow-y-auto font-mono text-[10px] space-y-3 leading-relaxed shadow-inner">
          <div className="flex justify-between items-center mb-8 pb-4 border-b border-[var(--glass-border)]">
            <h3 className="text-[var(--text-primary)] uppercase tracking-[0.6em] text-[12px] font-black">AI Runtime Neural Trace</h3>
            <div className="flex gap-4">
              {isDrafting && <span className="text-[9px] uppercase tracking-[0.2em] text-[#1565C0] animate-pulse">Drafting Strategy</span>}
            </div>
          </div>

          <div className="space-y-4">
            {unifiedLogs.map((log, i) => (
              <div key={i} className="text-[var(--text-secondary)] flex gap-4 items-start group">
                <span className="text-[var(--text-muted)] shrink-0 tabular-nums tracking-widest text-[9px] pt-0.5">
                  [{log.timestamp}]
                </span>
                <span className={`text-[8px] font-black px-2 py-0.5 rounded-md shrink-0 uppercase tracking-widest ${log.source === 'HUNT' ? 'bg-[#00E676]/10 text-[#00E676] border border-[#00E676]/20' :
                    log.source === 'OUTREACH' ? 'bg-[#1565C0]/10 text-[#1565C0] border border-[#1565C0]/20' :
                      'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--glass-border)]'
                  }`}>
                  {log.source}
                </span>
                <span className="leading-relaxed tracking-tight break-all font-medium py-0.5">{log.message}</span>
              </div>
            ))}

            {/* Display campaign-specific background logs if available and no session in progress */}
            {!isSearching && !isDrafting && selectedCampaign?.logs && (
              <div className="border-t border-[var(--glass-border)] pt-4 mt-4 opacity-70">
                <p className="text-[8px] uppercase tracking-widest text-[#1565C0] font-black mb-4 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#1565C0] animate-pulse"></span>
                  Live Virtual SDR Trace
                </p>
                {selectedCampaign.logs.map((log: string, i: number) => {
                  const match = log.match(/^\[(.*?)\]\s*(.*)$/);
                  const timestamp = match ? match[1] : '';
                  const message = match ? match[2] : log;
                  return (
                    <div key={`arch-${i}`} className="text-[var(--text-secondary)] flex gap-4 items-start group mb-2">
                      <span className="text-[var(--text-muted)] shrink-0 tabular-nums tracking-widest text-[9px] pt-0.5">
                        [{timestamp || 'SYS'}]
                      </span>
                      <span className="text-[8px] font-black px-2 py-0.5 rounded-md shrink-0 uppercase tracking-widest bg-[#1565C0]/10 text-[#1565C0] border border-[#1565C0]/20">
                        OUTREACH
                      </span>
                      <span className="leading-relaxed tracking-tight break-all font-medium py-0.5 text-[var(--text-dim)]">{message}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div ref={logEndRef} />
        </div>
      </div>

      {/* ━━ Leads Grid ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {leads.length > 0 && (
        <section className="space-y-10 animate-in fade-in slide-in-from-bottom-5 duration-700 pt-8">
          <div className="flex justify-between items-end border-b border-[var(--glass-border)] pb-6">
            <h2 className="text-3xl font-black tracking-[-0.04em]">Discovered Intelligence</h2>
            <div className="flex items-center gap-4 text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
              <span>Output: <span className="text-[#1565C0]">{filename}</span></span>
              {filename && (
                <a
                  href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/download/${encodeURIComponent(filename)}`}
                  download={filename}
                  className="p-2 hover:bg-[#1565C0]/10 rounded-lg transition-all group"
                  title="Download CSV Intelligence"
                >
                  <svg className="w-3.5 h-3.5 text-[#1565C0] group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                </a>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {leads.map((lead, i) => (
              <div key={i} className="glass p-8 space-y-6 premium-card-hover group">
                <div className="space-y-2">
                  <div className="flex justify-between items-start gap-3">
                    <h4 className="font-black text-xl tracking-tighter leading-tight">{lead.name}</h4>
                    {lead.is_good_lead && (
                      <span className="bg-[#1565C0]/10 text-[#1565C0] text-[8px] uppercase tracking-[0.2em] px-2 py-1 rounded-full border border-[#1565C0]/20 font-black">Elite</span>
                    )}
                  </div>
                  <p className="text-[9px] text-[var(--text-muted)] uppercase font-black tracking-[0.3em]">{lead.category}</p>
                </div>

                <p className="text-[12px] text-[var(--text-dim)] leading-relaxed font-medium italic border-l-2 border-[var(--glass-border)] pl-5 py-1">
                  "{lead.ai_notes}"
                </p>

                <div className="space-y-3 pt-5 border-t border-[var(--glass-border)]">
                  {[
                    { label: "Phone", value: lead.phone },
                    { label: "Email", value: lead.email },
                    { label: "Web", value: lead.website, href: lead.website }
                  ].map((item, idx) => item.value && (
                    <div key={idx} className="flex items-center gap-4 text-[10px]">
                      <span className="text-[var(--text-muted)] uppercase font-black tracking-[0.3em] w-12 shrink-0">{item.label}</span>
                      {item.href ? (
                        <a href={item.href} target="_blank" className="text-[#1565C0]/80 truncate hover:text-[#1565C0] hover:underline transition-colors duration-300 font-bold">{item.value}</a>
                      ) : (
                        <span className="text-[var(--text-dim)] font-bold tracking-tight">{item.value}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ━━ Ingest Cold Leads Glassmorphic Modal ━━━━━━━━━━━━━━━━━━━━ */}
      {isIngestModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-300">
          <div className={`w-full max-w-4xl max-h-[90vh] flex flex-col shadow-[0_0_50px_rgba(21,101,192,0.15)] border border-[var(--glass-border)] rounded-2xl overflow-hidden animate-in zoom-in-95 duration-300 ${isDarkMode ? 'bg-[#071126]' : 'bg-[#fdfbf7]'}`}>

            {/* Header */}
            <div className={`p-6 border-b border-[var(--glass-border)] flex justify-between items-center shrink-0 ${isDarkMode ? 'bg-black/20' : 'bg-[var(--glass-bg)]'}`}>
              <div className="space-y-1">
                <h3 className="text-base font-black tracking-wider uppercase text-[var(--text-primary)]">Ingest Cold Leads Pipeline</h3>
                <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">AI Normalization, Deduplication & Ingestion Engine</p>
              </div>
              <button
                onClick={() => setIsIngestModalOpen(false)}
                className="w-8 h-8 rounded-full border border-[var(--glass-border)] bg-[var(--input-bg)] flex items-center justify-center text-[var(--text-dim)] hover:text-white hover:border-[#1565C0]/40 transition-colors duration-200 cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* ━━ PINNED STATUS BANNER ━━ Always visible, above scroll area */}
            {isIngesting && (
              <div className="flex items-center gap-3 px-6 py-3 bg-[#1565C0]/10 border-b border-[#1565C0]/30 shrink-0">
                <div className="w-4 h-4 border-2 border-[#1565C0] border-t-transparent rounded-full animate-spin flex-shrink-0"></div>
                <span className="text-[10px] uppercase font-black tracking-widest text-[#1565C0] animate-pulse">Running Simulation...</span>
              </div>
            )}
            {!isIngesting && ingestResult && (
              <div className={`flex items-center justify-between gap-3 px-6 py-3 shrink-0 border-b ${ingestResult.status === "success" ? "bg-emerald-500/10 border-emerald-500/30" : "bg-red-500/10 border-red-500/30"}`}>
                <div className="flex items-center gap-3">
                  <span className={`text-lg ${ingestResult.status === "success" ? "text-emerald-400" : "text-red-400"}`}>
                    {ingestResult.status === "success" ? "✅" : "❌"}
                  </span>
                  <div>
                    <p className={`text-[10px] uppercase font-black tracking-widest ${ingestResult.status === "success" ? "text-emerald-400" : "text-red-400"}`}>
                      {ingestResult.status === "success" ? (ingestResult.dry_run ? "DRY RUN COMPLETE" : "INGEST COMPLETE") : "ERROR OCCURRED"}
                    </p>
                    {ingestResult.metrics && (
                      <p className="text-[9px] text-[var(--text-dim)]">
                        {ingestResult.metrics.estimated_new_contacts ?? ingestResult.metrics.new_contacts_inserted ?? 0} new contacts · {ingestResult.metrics.estimated_duplicates_skipped ?? ingestResult.metrics.duplicates_skipped ?? 0} duplicates skipped · {ingestResult.metrics.rows_scanned} rows scanned
                      </p>
                    )}
                    {ingestResult.message && <p className="text-[9px] text-red-400">{ingestResult.message}</p>}
                  </div>
                </div>
                <button onClick={() => setIngestResult(null)} className="text-[var(--text-muted)] hover:text-white text-xs cursor-pointer px-2">✕</button>
              </div>
            )}

            {/* Content Scroll Area */}
            <div id="ingest-modal-body" className="flex-1 overflow-y-auto p-6 space-y-6">

              {/* Loader */}
              {ingestPreviewLoading && (
                <div className="py-20 flex flex-col items-center justify-center space-y-4">
                  <div className="relative w-16 h-16">
                    <div className="absolute inset-0 rounded-full border-4 border-[#1565C0]/20 border-t-[#00E676] animate-spin"></div>
                    <div className="absolute inset-2 rounded-full bg-[var(--input-bg)] border border-[var(--glass-border)]"></div>
                  </div>
                  <span className="text-[10px] uppercase font-black tracking-[0.4em] text-[var(--text-muted)] animate-pulse">Running Neural Scan...</span>
                </div>
              )}

              {/* Preview Content */}
              {!ingestPreviewLoading && ingestPreviewData && (
                <>
                  {/* KPI Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                    {[
                      { label: "Total CSVs", val: ingestPreviewData.total_csv_files, color: "text-[var(--text-primary)]" },
                      { label: "Total Rows Scanned", val: ingestPreviewData.total_leads_scanned, color: "text-[var(--text-primary)]" },
                      { label: "Estimated New", val: ingestPreviewData.estimated_new_contacts, color: "text-[var(--text-primary)]" },
                      { label: "Estimated Duplicates", val: ingestPreviewData.estimated_duplicates, color: "text-[var(--text-primary)]" },
                      { label: "Valid Emails", val: ingestPreviewData.valid_real_emails, color: "text-[var(--text-primary)]" },
                      { label: "Contactable Leads", val: ingestPreviewData.contactable_leads, color: "text-[var(--text-primary)]" },
                    ].map((kpi, idx) => (
                      <div key={idx} className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-3 text-center space-y-1">
                        <p className="text-[8px] uppercase tracking-widest font-black text-[var(--text-muted)]">{kpi.label}</p>
                        <p className={`text-base font-black ${kpi.color}`}>{kpi.val}</p>
                      </div>
                    ))}
                  </div>

                  {/* Contactability Breakdowns */}
                  <div className="bg-[var(--input-bg)]/50 border border-[var(--glass-border)] rounded-xl p-4">
                    <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-3 pb-2 border-b border-[var(--glass-border)]">Contactability Metrics</p>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                      {[
                        { label: "Email Contactable", val: ingestPreviewData.email_contactable, color: "text-[var(--text-primary)]" },
                        { label: "Phone Contactable", val: ingestPreviewData.phone_contactable || 0, color: "text-[var(--text-primary)]" },
                        { label: "Website Only", val: ingestPreviewData.website_only_leads, color: "text-[var(--text-primary)]" },
                        { label: "Low Contactability", val: ingestPreviewData.low_contactability || 0, color: "text-[var(--text-primary)]" },
                        { label: "No Direct Contact", val: ingestPreviewData.no_direct_contact_leads, color: "text-[var(--text-primary)]" }
                      ].map((item, idx) => (
                        <div key={idx} className="space-y-0.5">
                          <p className="text-[8px] uppercase font-bold text-[var(--text-dim)]">{item.label}</p>
                          <p className={`text-sm font-black ${item.color}`}>{item.val}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Scraped CSVs List */}
                  <div className="space-y-3">
                    <p className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)] pl-1">Scraped Lists Repository ({ingestPreviewData.files?.length || 0} Files)</p>
                    <div className="space-y-3 max-h-[30vh] overflow-y-auto pr-1">
                      {ingestPreviewData.files?.map((file: any, index: number) => (
                        <div key={index} className="bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl p-4 space-y-3 hover:border-[#1565C0]/20 transition-colors">
                          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                            <div className="space-y-0.5">
                              <h4 className="text-xs font-bold text-[var(--text-primary)] truncate max-w-md">{file.filename}</h4>
                              <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] uppercase font-black text-[var(--text-dim)]">
                                <span>Rows: <strong className="text-[var(--text-primary)]">{file.total_rows}</strong></span>
                                <span className="text-[var(--text-primary)]">New: <strong>{file.estimated_new}</strong></span>
                                <span className="text-[var(--text-primary)]">Dups: <strong>{file.estimated_duplicates}</strong></span>
                              </div>
                            </div>

                            <div className="flex items-center gap-2">
                              <span className="bg-[#1565C0]/10 border border-[#1565C0]/20 text-[#1565C0] text-[8px] uppercase tracking-wider px-2 py-0.5 rounded-full font-black">
                                {file.inferred_industry}
                              </span>
                              <button
                                onClick={() => setExpandedSampleCsv(expandedSampleCsv === file.filename ? null : file.filename)}
                                className="px-3 py-1 rounded-lg border border-[var(--glass-border)] bg-[var(--input-bg)] text-[9px] uppercase font-black tracking-widest text-[var(--text-dim)] hover:text-white hover:bg-[#1565C0]/10 transition-colors cursor-pointer"
                              >
                                {expandedSampleCsv === file.filename ? "Hide Samples" : "View Samples"}
                              </button>
                            </div>
                          </div>

                          {/* Warnings if any */}
                          {file.warnings && file.warnings.length > 0 && (
                            <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-2.5 space-y-1">
                              {file.warnings.map((w: string, wIdx: number) => (
                                <p key={wIdx} className="text-[9px] text-red-400 font-medium">⚠️ {w}</p>
                              ))}
                            </div>
                          )}

                          {/* Expanded Sample Leads Grid */}
                          {expandedSampleCsv === file.filename && file.sample_leads && (
                            <div className={`${isDarkMode ? 'bg-black/20' : 'bg-[var(--input-bg)]'} border border-[var(--glass-border)] rounded-lg p-3 space-y-2 mt-2 max-h-[200px] overflow-y-auto animate-in slide-in-from-top-2 duration-200`}>
                              <p className="text-[8px] uppercase tracking-widest font-black text-[var(--text-muted)] mb-1">Scrape Sample Leads (Up to 5)</p>
                              <div className="space-y-2 divide-y divide-[var(--glass-border)]">
                                {file.sample_leads.map((sample: any, sIdx: number) => (
                                  <div key={sIdx} className="pt-2 first:pt-0 flex flex-col sm:flex-row sm:justify-between gap-1 text-[10px]">
                                    <div className="space-y-0.5">
                                      <p className="font-bold text-[var(--text-secondary)]">{sample.name}</p>
                                      <p className="text-[9px] text-[var(--text-dim)] truncate max-w-sm">
                                        Email: <strong className="text-[var(--text-primary)]">{sample.email}</strong> | Phone: <strong>{sample.phone}</strong>
                                      </p>
                                    </div>
                                    <div className="flex items-center gap-1.5 self-start sm:self-center">
                                      <span className="text-[8px] uppercase tracking-wider text-[var(--text-dim)] bg-[var(--input-bg)] border border-[var(--glass-border)] px-1.5 py-0.5 rounded">
                                        {sample.inferred_subcategory}
                                      </span>
                                      {sample.inferred_tags?.map((tag: string, tIdx: number) => (
                                        <span key={tIdx} className="bg-amber-500/10 border border-amber-500/20 text-amber-500 text-[7px] uppercase tracking-widest px-1 py-0.2 rounded font-black">
                                          {tag}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

            </div>

            {/* Safety Control Footer */}
            <div className={`p-6 border-t border-[var(--glass-border)] flex flex-col gap-4 shrink-0 ${isDarkMode ? 'bg-black/40' : 'bg-[var(--glass-bg)]'}`}>

              {/* Configurations select */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Target Scraped CSV</label>
                  <select
                    value={selectedIngestFile}
                    onChange={(e) => {
                      setSelectedIngestFile(e.target.value);
                      setUnderstandRisk(false);
                      setIngestResult(null);
                    }}
                    className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-primary)] outline-none cursor-pointer focus:border-[#1565C0]/50"
                  >
                    <option value="all">All Scraped Lists (Merge & Deduplicate)</option>
                    {ingestPreviewData?.files?.map((f: any) => (
                      <option key={f.filename} value={f.filename}>{f.filename}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-[9px] uppercase tracking-widest font-black text-[var(--text-muted)]">Ingestion Limit (Cap)</label>
                  <select
                    value={String(ingestLimit)}
                    onChange={(e) => {
                      setIngestLimit(e.target.value);
                      setIngestResult(null);
                    }}
                    className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-primary)] outline-none cursor-pointer focus:border-[#1565C0]/50"
                  >
                    <option value="10">10 Leads Max</option>
                    <option value="50">50 Leads Max</option>
                    <option value="100">100 Leads Max</option>
                    <option value="null">All Leads (Unlimited)</option>
                  </select>
                </div>
              </div>

              {/* Ingest all warning alert */}
              {selectedIngestFile === "all" && (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-3 flex gap-3 items-start animate-in fade-in duration-300">
                  <span className="text-base">⚠️</span>
                  <div className="space-y-0.5">
                    <p className="text-[10px] uppercase font-black tracking-widest text-amber-500">MASSIVE INGESTION WARNING</p>
                    <p className="text-[9px] text-[var(--text-dim)] font-medium leading-relaxed">
                      You are about to merge and import all scraped lists. This will scan hundreds of leads.
                      Enforcing a Dry Run Check first is highly recommended before performing this action.
                    </p>
                  </div>
                </div>
              )}

              {/* Checkbox and Actions buttons */}
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-2 border-t border-[var(--glass-border)]/50">
                <label className="flex items-start gap-3 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={understandRisk}
                    onChange={(e) => setUnderstandRisk(e.target.checked)}
                    className="mt-0.5 w-4 h-4 rounded border-[var(--glass-border)] bg-[var(--input-bg)] text-[#1565C0] focus:ring-0 focus:ring-offset-0 cursor-pointer"
                  />
                  <div className="space-y-0.5">
                    <p className="text-[10px] font-bold text-[var(--text-secondary)]">I understand this will write to the CRM database.</p>
                    <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">Automatic preventive backup will be created inside backend/state/</p>
                  </div>
                </label>

                <div className="flex items-center gap-3 self-end md:self-auto shrink-0">
                  <button
                    disabled={isIngesting || ingestPreviewLoading}
                    onClick={() => runIngestAction(true)}
                    className="px-5 py-2.5 rounded-xl border border-[var(--glass-border)] bg-[var(--input-bg)] text-[9px] uppercase font-black tracking-[0.2em] text-[var(--text-primary)] hover:bg-[#1565C0]/10 hover:border-[#1565C0]/30 transition-all cursor-pointer disabled:opacity-50 shrink-0"
                  >
                    {isIngesting ? "Simulating..." : "Dry Run Check"}
                  </button>

                  <button
                    disabled={isIngesting || ingestPreviewLoading || !understandRisk}
                    onClick={() => {
                      if (selectedIngestFile === "all") {
                        const confirmFirst = window.confirm("🚨 CRITICAL WARNING 🚨\n\nYou are about to ingest ALL scraped files into the database.\nAre you absolutely sure you want to proceed?");
                        if (!confirmFirst) return;
                        const confirmSecond = window.confirm("Double Check: Are you 100% sure you have inspected the Dry Run Check report?");
                        if (!confirmSecond) return;
                      } else {
                        const confirmSingle = window.confirm(`Confirm real ingestion of lead file: ${selectedIngestFile}?`);
                        if (!confirmSingle) return;
                      }
                      runIngestAction(false);
                    }}
                    className={`px-6 py-2.5 rounded-xl text-[9px] uppercase font-black tracking-[0.2em] transition-all cursor-pointer disabled:opacity-40 shrink-0 ${understandRisk ? "bg-[#1565C0] text-white hover:bg-[#1976D2] hover:shadow-lg hover:-translate-y-0.5 font-bold" : "bg-red-500/10 border border-red-500/20 text-red-400/70"}`}
                  >
                    {isIngesting ? "Ingesting..." : selectedIngestFile === "all" ? "INGEST ALL (HIGH RISK)" : "Execute Real Ingest"}
                  </button>
                </div>
              </div>

            </div>
          </div>
        </div>
      )}
    </main>
  );
}
