"use client";

import React, { useState, useEffect } from "react";

interface CampaignSettingsProps {
  settings: {
    daily_email_limit: number;
    daily_whatsapp_limit: number;
    channel_priority?: "hybrid" | "email_only" | "whatsapp_only";
    send_window: { start: number; end: number };
    delay_style: "conservative" | "standard" | "aggressive";
    control_mode?: "reputation_first" | "deadline";
    volume_jitter?: boolean;
    time_jitter?: boolean;
    signature_jitter?: boolean;
  };
  totalLeads?: number; // Passed from parent if available
  onUpdate: (newSettings: any) => void;
  isSaving?: boolean;
}

const DELAY_MODES = {
  conservative: { label: "Conservative", min: 10, max: 20, desc: "10–20 min / email", risk: "Maximum reputation protection" },
  standard:     { label: "Standard",  min: 4,  max: 12, desc: "4–12 min / email",  risk: "Balance between speed and safety" },
  aggressive:   { label: "Aggressive",  min: 1,  max: 3,  desc: "1–3 min / email",   risk: "High risk. Use only with a warmed inbox." },
} as const;

const WINDOW_PRESETS = [
  { label: "Morning",  start: 9,  end: 13, desc: "09:00–13:00" },
  { label: "Afternoon",   start: 15, end: 19, desc: "15:00–19:00" },
  { label: "Evening",   start: 18, end: 21, desc: "18:00–21:00" }, // Adjusted slightly from user suggestion 18:00-21:30 (sliders are whole hours)
  { label: "24h",     start: 0,  end: 23, desc: "No restriction" },
];

const fmt = (h: number) => `${String(h).padStart(2, "0")}:00`;

export default function CampaignSettings({ settings, totalLeads = 100, onUpdate }: CampaignSettingsProps) {
  if (!settings) return null;

  // Set default control mode if not present

  // Set default calendar settings if not present
  useEffect(() => {
    let toUpdate = false;
    let newSettings = { ...settings };
    if (!settings.control_mode) { newSettings.control_mode = "reputation_first"; toUpdate = true; }
    if (!settings.campaign_schedule_mode) { newSettings.campaign_schedule_mode = "manual"; toUpdate = true; }
    if (!settings.daily_quota_mode) { newSettings.daily_quota_mode = "auto"; toUpdate = true; }
    if (!settings.active_weekdays) { newSettings.active_weekdays = [0, 1, 2, 3, 4]; toUpdate = true; } // Mon-Fri
    if (!settings.custom_daily_quotas) { newSettings.custom_daily_quotas = {}; toUpdate = true; }
    if (toUpdate) onUpdate(newSettings);
  }, []);


  const intervalRef = React.useRef<any>(null);

  const startHold = (key: "daily_email_limit" | "daily_whatsapp_limit", delta: number) => {
    const bounds: any = {
      daily_email_limit:    { min: 1, max: 500 },
      daily_whatsapp_limit: { min: 1, max: 250 },
    };
    const tick = () => {
      const cur = (settings as any)[key] || 0;
      onUpdate({ ...settings, [key]: Math.min(bounds[key].max, Math.max(bounds[key].min, cur + delta)) });
    };
    tick();
    intervalRef.current = setTimeout(() => { intervalRef.current = setInterval(tick, 70); }, 400);
  };

  const stopHold = () => {
    clearInterval(intervalRef.current);
    clearTimeout(intervalRef.current);
  };

  const set = (key: string, value: any) => onUpdate({ ...settings, [key]: value });

  // ── Math Calculations ──────────────────────────────────────────────────
  const sessionHours = (settings.send_window.end >= settings.send_window.start) 
    ? settings.send_window.end - settings.send_window.start 
    : (24 - settings.send_window.start) + settings.send_window.end;
  const sessionMinutes = sessionHours * 60;

  const mode = DELAY_MODES[settings.delay_style || "standard"];
  const avgGap = (mode.min + mode.max) / 2;

  // Mathematical capacity
  const emailsByTime = Math.floor(sessionMinutes / avgGap);
  const emailsToday = Math.min(totalLeads, settings.daily_email_limit, emailsByTime);
  const remainingEmails = Math.max(0, totalLeads - emailsToday);
  
  const isConflict = settings.control_mode === "reputation_first" && emailsByTime < Math.min(totalLeads, settings.daily_email_limit);
  
  // Deadline mode gap calculation
  let deadlineGap = 0;
  if (settings.control_mode === "deadline") {
    const emailsToProcess = Math.min(totalLeads, settings.daily_email_limit);
    deadlineGap = emailsToProcess > 1 ? sessionMinutes / (emailsToProcess - 1) : sessionMinutes;
  }
  const isDeadlineWarning = settings.control_mode === "deadline" && deadlineGap < 3;
  const isDeadlineCritical = settings.control_mode === "deadline" && deadlineGap < 1;

  // ── Render Helpers ─────────────────────────────────────────────────────
  const stepperBtn = "w-8 h-8 rounded-xl border border-[var(--glass-border)] text-[var(--text-muted)] text-lg font-black flex items-center justify-center hover:border-[#1565C0] hover:text-[#1565C0] transition-all select-none cursor-pointer";
  const stepperVal = "font-black text-2xl text-[var(--text-primary)] w-16 text-center tabular-nums bg-transparent outline-none hide-arrows";

  return (
    <div className="space-y-12">
      
      {/* ── Row 0: Control Mode ─────────────────────────────────────────── */}
      <div className="space-y-4">
        <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Pace Control Mode</label>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <button
            onClick={() => set("control_mode", "reputation_first")}
            className={`p-5 rounded-2xl border text-left transition-all duration-200 ${settings.control_mode === "reputation_first"
              ? "bg-[#1565C0] border-[#1565C0] text-white"
              : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
            }`}
          >
            <p className="text-[11px] font-black uppercase tracking-widest mb-1 flex items-center gap-2">
              Reputation-first <span className="px-2 py-0.5 rounded bg-white/20 text-[8px]">Recommended</span>
            </p>
            <p className={`text-[9px] font-normal leading-relaxed ${settings.control_mode === "reputation_first" ? "text-white/80" : "text-[var(--text-muted)]"}`}>
              Prioritizes inbox reputation. The system respects the selected pace and pauses automatically if the window ends before completing the campaign.
            </p>
          </button>

          <button
            onClick={() => set("control_mode", "deadline")}
            className={`p-5 rounded-2xl border text-left transition-all duration-200 ${settings.control_mode === "deadline"
              ? "bg-red-500/20 border-red-500 text-white"
              : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
            }`}
          >
            <p className={`text-[11px] font-black uppercase tracking-widest mb-1 ${settings.control_mode === "deadline" ? "text-red-400" : ""}`}>
              Deadline mode <span className="ml-1 text-[8px] font-normal text-red-500/80 uppercase tracking-wider">(Advanced / Higher risk)</span>
            </p>
            <p className={`text-[9px] font-normal leading-relaxed ${settings.control_mode === "deadline" ? "text-red-200" : "text-[var(--text-muted)]"}`}>
              Forces all daily emails to be sent within the selected window by calculating the required gap. Can negatively affect reputation.
            </p>
          </button>
        </div>
      </div>


      {/* ── Row 1: Campaign Calendar ───────────────────────────────────────────── */}
      <div className="space-y-6">
        <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Campaign Calendar</label>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
            onClick={() => set("daily_quota_mode", "auto")}
            className={`p-5 rounded-2xl border text-left transition-all duration-200 ${settings.daily_quota_mode === "auto" || !settings.daily_quota_mode
                ? "bg-[#1565C0] border-[#1565C0] text-white"
                : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
            }`}
            >
            <p className="text-[11px] font-black uppercase tracking-widest mb-1 flex items-center gap-2">
                Auto-Distribute <span className="px-2 py-0.5 rounded bg-white/20 text-[8px]">Recommended</span>
            </p>
            <p className={`text-[9px] font-normal leading-relaxed ${settings.daily_quota_mode === "auto" || !settings.daily_quota_mode ? "text-white/80" : "text-[var(--text-muted)]"}`}>
                Uses a single daily email limit for all active days. Ideal for consistent campaigns.
            </p>
            </button>

            <button
            onClick={() => set("daily_quota_mode", "custom")}
            className={`p-5 rounded-2xl border text-left transition-all duration-200 ${settings.daily_quota_mode === "custom"
                ? "bg-[#1565C0] border-[#1565C0] text-white"
                : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
            }`}
            >
            <p className="text-[11px] font-black uppercase tracking-widest mb-1">
                Custom Daily Quotas
            </p>
            <p className={`text-[9px] font-normal leading-relaxed ${settings.daily_quota_mode === "custom" ? "text-white/80" : "text-[var(--text-muted)]"}`}>
                Assigns different limits depending on the day of the week (e.g. more volume on Tuesdays, less on Fridays).
            </p>
            </button>
        </div>

        {/* Auto Limit (shown if auto) */}
        {(settings.daily_quota_mode === "auto" || !settings.daily_quota_mode) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-10 mt-4">
                <div className="space-y-4">
                <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Daily Email Limit</label>
                <div className="flex items-center justify-center gap-6 ios-btn px-6 py-5 !shadow-none group/limit hover:bg-[#0B3A82] hover:border-[#1565C0] transition-all duration-300">
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_email_limit", -1)} onMouseUp={stopHold} onMouseLeave={stopHold}>−</button>
                    <input type="number" value={settings.daily_email_limit} onChange={e => set("daily_email_limit", Math.min(500, Math.max(1, parseInt(e.target.value) || 1)))} className={stepperVal} />
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_email_limit", 1)} onMouseUp={stopHold} onMouseLeave={stopHold}>+</button>
                </div>
                <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-bold text-center">Maximum recommended based on reputation: 50/day</p>
                </div>
                <div className={`space-y-4 transition-all duration-300 ${settings.channel_priority === "email_only" ? "opacity-30 grayscale pointer-events-none" : ""}`}>
                  <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Daily WhatsApp Limit</label>
                  <div className="flex items-center justify-center gap-6 ios-btn px-6 py-5 !shadow-none group/limit hover:bg-[#0B3A82] hover:border-[#1565C0] transition-all duration-300">
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_whatsapp_limit", -1)} onMouseUp={stopHold} onMouseLeave={stopHold}>−</button>
                    <input type="number" value={settings.daily_whatsapp_limit} onChange={e => set("daily_whatsapp_limit", Math.min(250, Math.max(1, parseInt(e.target.value) || 1)))} className={stepperVal} />
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_whatsapp_limit", 1)} onMouseUp={stopHold} onMouseLeave={stopHold}>+</button>
                  </div>
                  <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-bold text-center">
                    {settings.channel_priority === "email_only" ? "Inactive in Email Only mode" : "Meta Safety: 10/day"}
                  </p>
                </div>
            </div>
        )}

        {/* Custom Limit (shown if custom) */}
        {settings.daily_quota_mode === "custom" && (
            <div className="grid grid-cols-7 gap-2 mt-4">
                {[
                  { key: "monday", label: "MON", idx: 0 },
                  { key: "tuesday", label: "TUE", idx: 1 },
                  { key: "wednesday", label: "WED", idx: 2 },
                  { key: "thursday", label: "THU", idx: 3 },
                  { key: "friday", label: "FRI", idx: 4 },
                  { key: "saturday", label: "SAT", idx: 5 },
                  { key: "sunday", label: "SUN", idx: 6 }
                ].map((day) => {
                    const isActive = (settings.active_weekdays || [0,1,2,3,4]).includes(day.idx);
                    return (
                    <div key={day.key} className={`space-y-2 transition-all ${isActive ? 'opacity-100' : 'opacity-30'}`}>
                        <label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-black flex justify-center">{day.label}</label>
                        <input 
                            type="number" 
                            disabled={!isActive}
                            className={`w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl py-3 text-center text-[12px] font-black text-[var(--text-primary)] outline-none focus:border-[#1565C0] ${!isActive ? 'cursor-not-allowed' : ''}`}
                            value={(settings.custom_daily_quotas || {})[day.key] ?? settings.daily_email_limit}
                            onChange={(e) => {
                                const val = parseInt(e.target.value) || 0;
                                set("custom_daily_quotas", { ...(settings.custom_daily_quotas || {}), [day.key]: val });
                            }}
                        />
                    </div>
                )})}
            </div>
        )}

        <div className="space-y-4 mt-6">
            <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Active Days (Sending)</label>
            <div className="flex gap-2">
                {["M", "T", "W", "T", "F", "S", "S"].map((day, idx) => {
                    const activeDays = settings.active_weekdays || [0,1,2,3,4];
                    const isActive = activeDays.includes(idx);
                    return (
                        <button
                            key={idx}
                            onClick={() => {
                                const newDays = isActive ? activeDays.filter((d:any) => d !== idx) : [...activeDays, idx];
                                set("active_weekdays", newDays);
                            }}
                            className={`w-10 h-10 rounded-xl flex items-center justify-center text-[10px] font-black transition-all ${isActive ? 'bg-[#1565C0] text-white border border-[#1565C0]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--glass-border)]'}`}
                        >
                            {day}
                        </button>
                    )
                })}
            </div>
        </div>
      </div>


      {/* ── Row 2: Channel Strategy ───────────────────────────────────────── */}
      <div className="space-y-6">
        <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Contact Channel</label>
        <div className="grid grid-cols-3 gap-4">
          {[
            { id: "email_only",     label: "Email Only",     desc: "Standard outreach"   },
            { id: "hybrid",         label: "Hybrid",        desc: "Combines Email and WhatsApp"     },
            { id: "whatsapp_only",  label: "WhatsApp Only",  desc: "No email fallback"   },
          ].map(ch => (
            <button
              key={ch.id}
              onClick={() => set("channel_priority", ch.id)}
              className={`py-5 rounded-2xl border text-left px-5 transition-all duration-200 ${(settings.channel_priority || "hybrid") === ch.id
                ? "bg-[#1565C0] border-[#1565C0]"
                : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04] hover:border-[var(--text-dim)]"
              }`}
            >
              <p className={`text-[10px] font-black uppercase tracking-widest ${(settings.channel_priority || "hybrid") === ch.id ? "text-white" : "text-[var(--text-primary)]"}`}>{ch.label}</p>
              <p className={`text-[8px] mt-1 font-normal ${(settings.channel_priority || "hybrid") === ch.id ? "text-white/70" : "text-[var(--text-muted)]"}`}>{ch.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* ── Row 3: Send Velocity & Window ─────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
        
        {/* Send Window */}
        <div className="space-y-5">
          <div className="flex justify-between items-baseline">
            <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Maximum Sending Window Today</label>
            <span className="text-[9px] font-black text-[#1565C0] tabular-nums bg-[#1565C0]/10 px-2 py-1 rounded">
              {fmt(settings.send_window.start)} → {fmt(settings.send_window.end)} 
              {settings.send_window.end <= settings.send_window.start ? " (+1 day)" : ""}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {WINDOW_PRESETS.map(p => {
              const active = settings.send_window.start === p.start && settings.send_window.end === p.end;
              return (
                <button key={p.label} onClick={() => set("send_window", { start: p.start, end: p.end })}
                  className={`py-3 rounded-xl border text-[9px] font-black uppercase tracking-widest transition-all duration-200 ${active
                    ? "bg-[#1565C0] border-[#1565C0] text-white"
                    : "bg-[var(--input-bg)] border-[var(--glass-border)] text-[var(--text-muted)] hover:bg-white/[0.04] hover:border-[var(--text-dim)]"
                  }`}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
          <div className="space-y-3 bg-[var(--input-bg)] rounded-2xl p-5 border border-[var(--glass-border)]">
            <div className="flex justify-between text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1">
              <span>Start</span><span>{fmt(settings.send_window.start)}</span>
            </div>
            <input type="range" min="0" max="23" value={settings.send_window.start} onChange={e => set("send_window", { ...settings.send_window, start: parseInt(e.target.value) })} className="w-full h-[2px] accent-[#1565C0] cursor-pointer" />
            <div className="flex justify-between text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest mt-3 mb-1">
              <span>End</span><span>{fmt(settings.send_window.end)}</span>
            </div>
            <input type="range" min="0" max="23" value={settings.send_window.end} onChange={e => set("send_window", { ...settings.send_window, end: parseInt(e.target.value) })} className="w-full h-[2px] accent-[#1565C0] cursor-pointer" />
          </div>
          {settings.send_window.start === 0 && settings.send_window.end === 23 && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-500 text-[9px] p-3 rounded-lg flex items-start gap-2">
              <span className="text-sm">⚠️</span>
              <p>Sending during the early morning may seem less natural in B2B campaigns. Recommended only for different time zones.</p>
            </div>
          )}
        </div>

        {/* Send Velocity (only visible fully in Reputation First, otherwise grayed out but visible) */}
        <div className={`space-y-5 transition-all duration-300 ${settings.control_mode === "deadline" ? "opacity-50 grayscale pointer-events-none" : ""}`}>
          <div className="flex justify-between items-baseline">
            <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Base Interval between Sends</label>
          </div>
          <div className="flex flex-col gap-3">
            {(Object.entries(DELAY_MODES) as [keyof typeof DELAY_MODES, typeof DELAY_MODES[keyof typeof DELAY_MODES]][]).map(([key, mode]) => {
              const active = settings.delay_style === key;
              return (
                <button key={key} onClick={() => set("delay_style", key)}
                  className={`py-4 px-5 rounded-2xl border text-left flex justify-between items-center transition-all duration-200 ${active
                    ? "bg-[#1565C0] border-[#1565C0]"
                    : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
                  }`}
                >
                  <div>
                    <p className={`text-[10px] font-black uppercase tracking-widest ${active ? "text-white" : "text-[var(--text-primary)]"}`}>{mode.label}</p>
                    <p className={`text-[8px] mt-1 font-normal ${active ? "text-white/60" : "text-[var(--text-muted)]"}`}>{mode.risk}</p>
                  </div>
                  <p className={`text-[11px] font-bold tabular-nums ${active ? "text-white" : "text-[var(--text-secondary)]"}`}>{mode.desc}</p>
                </button>
              );
            })}
          </div>
          {settings.delay_style === "aggressive" && settings.control_mode === "reputation_first" && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-500 text-[9px] p-3 rounded-lg flex items-start gap-2">
              <span className="text-sm">⚠️</span>
              <p>This mode can increase the risk of rate limits or blocks if the domain lacks sufficient reputation.</p>
            </div>
          )}
        </div>

      </div>

      {/* ── Math Calculations / Conflict Blocks ───────────────────────────── */}
      <div className="p-6 rounded-2xl border border-[var(--glass-border)] bg-[var(--input-bg)]">
        <h4 className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black mb-4">Daily Estimate</h4>
        
        {settings.control_mode === "reputation_first" ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
              {/* Email Block */}
              <div className="bg-[#1565C0]/5 p-5 rounded-2xl border border-[#1565C0]/20">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-xl bg-[#1565C0]/20 flex items-center justify-center text-[#1565C0] shadow-inner">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                    </div>
                    <h5 className="text-[11px] uppercase font-black tracking-[0.2em] text-[var(--text-primary)]">Email Queue</h5>
                  </div>
                </div>
                <div className="flex justify-between items-end">
                  <div>
                    <p className="text-[9px] text-[#1565C0] uppercase tracking-wider font-bold mb-1">Daily Volume</p>
                    <p className="text-3xl font-black text-[var(--text-primary)]">{emailsToday} <span className="text-[10px] text-[var(--text-muted)] font-normal uppercase tracking-widest">msg</span></p>
                  </div>
                  <div className="text-right">
                    <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider font-bold mb-1">Cadence</p>
                    <p className="text-sm font-black text-[#1565C0]">~{avgGap} <span className="text-[10px] font-normal uppercase tracking-wider text-[var(--text-muted)]">min/msg</span></p>
                  </div>
                </div>
              </div>

              {/* WhatsApp Block */}
              <div className={`bg-[#128C7E]/5 p-5 rounded-2xl border border-[#128C7E]/20 transition-all duration-300 ${settings.channel_priority === "email_only" ? "opacity-30 grayscale" : ""}`}>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-xl bg-[#128C7E]/20 flex items-center justify-center text-[#128C7E] shadow-inner">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
                    </div>
                    <h5 className="text-[11px] uppercase font-black tracking-[0.2em] text-[var(--text-primary)]">WhatsApp Queue</h5>
                  </div>
                </div>
                <div className="flex justify-between items-end">
                  <div>
                    <p className="text-[9px] text-[#128C7E] uppercase tracking-wider font-bold mb-1">Daily Volume</p>
                    <p className="text-3xl font-black text-[var(--text-primary)]">{settings.channel_priority === "email_only" ? "0" : Math.min(totalLeads, settings.daily_whatsapp_limit, emailsByTime)} <span className="text-[10px] text-[var(--text-muted)] font-normal uppercase tracking-widest">msg</span></p>
                  </div>
                  <div className="text-right">
                    <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider font-bold mb-1">Cadence</p>
                    <p className="text-sm font-black text-[#128C7E]">~{avgGap} <span className="text-[10px] font-normal uppercase tracking-wider text-[var(--text-muted)]">min/msg</span></p>
                  </div>
                </div>
              </div>
            </div>


            
            {isConflict ? (
              <div className="mt-4 bg-[#1565C0]/10 border border-[#1565C0]/30 rounded-xl p-4">
                <p className="text-[10px] font-black text-[#1565C0] uppercase tracking-widest mb-2 flex items-center gap-2">
                  <span>ℹ️</span> Capacity Adjustment
                </p>
                <p className="text-[11px] text-[var(--text-primary)] mb-2">
                  You have selected limits higher than what fits in <strong>{sessionHours}h</strong>. 
                  With a {mode.label.toLowerCase()} pace ({mode.desc}), the combined maximum capacity is approximately <strong>{emailsByTime} messages today</strong>.
                </p>
                <p className="text-[10px] text-[var(--text-muted)]">
                  The system will prioritize until the window is filled and continue tomorrow.
                </p>
              </div>
            ) : (
              <p className="text-[11px] text-[var(--text-primary)] mt-2">
                The system has capacity to process the established limits within the available {sessionHours}h.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-wider">Target daily limit</p>
                <p className="text-sm font-bold text-[var(--text-primary)]">{Math.min(totalLeads, settings.daily_email_limit)} messages</p>
              </div>
              <div>
                <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-wider">Forced dynamic interval</p>
                <p className={`text-sm font-bold ${isDeadlineCritical ? "text-red-500" : isDeadlineWarning ? "text-yellow-500" : "text-[#1565C0]"}`}>
                  ~{deadlineGap.toFixed(1)} min/message
                </p>
              </div>
            </div>
            
            {isDeadlineCritical ? (
              <div className="mt-4 bg-red-500/10 border border-red-500/30 rounded-xl p-4">
                <p className="text-[10px] font-black text-red-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                  <span>⚠️</span> Critical Conflict
                </p>
                <p className="text-[11px] text-red-400">
                  Forcing {Math.min(totalLeads, settings.daily_email_limit)} messages in {sessionHours}h results in 1 message every {deadlineGap.toFixed(1)} minutes.
                  <strong> This will almost certainly cause SMTP blocks.</strong> Reduce the daily limit or increase the window.
                </p>
              </div>
            ) : isDeadlineWarning ? (
              <div className="mt-4 bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4">
                <p className="text-[10px] font-black text-yellow-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                  <span>⚠️</span> Risk Warning
                </p>
                <p className="text-[11px] text-yellow-500/90">
                  1 message every {deadlineGap.toFixed(1)} minutes is a very fast pace. Only recommended if the account is thoroughly warmed up.
                </p>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* ── Row 4: Deliverability Safety Layer ────────────────────────────── */}
      <div className="space-y-6">
        <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Deliverability Safety Layer</label>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { key: "volume_jitter",    title: "Volume Jitter",    desc: "Varies the daily amount ±20% to avoid rigid patterns" },
            { key: "time_jitter",      title: "Time Jitter",      desc: "Adds ±15% random variance to each pause so the pace isn't mechanical" },
            { key: "signature_jitter", title: "Closing Jitter",   desc: "Slightly rotates sign-offs (e.g. 'Best', 'Thanks') keeping identity intact" },
          ].map(({ key, title, desc }) => {
            const on = !!(settings as any)[key];
            return (
              <button
                key={key}
                onClick={() => set(key, !on)}
                className={`p-5 rounded-2xl border flex justify-between items-center transition-all duration-200 ${on
                  ? "bg-[#1565C0]/10 border-[#1565C0]"
                  : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
                }`}
              >
                <div className="text-left">
                  <p className={`text-[10px] font-black uppercase tracking-widest ${on ? "text-[var(--text-primary)]" : "text-[var(--text-muted)]"}`}>{title}</p>
                  <p className="text-[8px] text-[var(--text-muted)] mt-1 font-normal leading-relaxed max-w-[160px]">{desc}</p>
                </div>
                <div className={`w-8 h-4 rounded-full relative transition-colors shrink-0 ml-3 ${on ? "bg-[#1565C0]" : "bg-[var(--glass-border)]"}`}>
                  <div className={`absolute top-1 w-2 h-2 bg-white rounded-full transition-all ${on ? "left-5" : "left-1"}`} />
                </div>
              </button>
            );
          })}
        </div>
        <div className="text-center">
          <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-bold italic">
            Reputation Guard active
          </p>
          <p className="text-[8px] text-[var(--text-muted)] mt-1">The system pauses, reduces speed or blocks leads depending on the type of failure detected.</p>
        </div>
      </div>

    </div>
  );
}
