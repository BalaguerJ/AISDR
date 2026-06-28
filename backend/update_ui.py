import re

with open("frontend/components/CampaignSettings.tsx", "r") as f:
    content = f.read()

# I will add the default calendar settings
default_settings_injection = """
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
"""

content = re.sub(
    r"  useEffect\(\(\) => \{\n    if \(!settings.control_mode\) \{\n      onUpdate\(\{ ...settings, control_mode: \"reputation_first\" \}\);\n    \}\n  \}, \[\]\);",
    default_settings_injection,
    content
)

# Replace the limits block with the new Campaign Calendar
calendar_ui = """
      {/* ── Row 1: Campaign Calendar ───────────────────────────────────────────── */}
      <div className="space-y-6">
        <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">📅 Campaign Calendar</label>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
            onClick={() => set("daily_quota_mode", "auto")}
            className={`p-5 rounded-2xl border text-left transition-all duration-200 ${settings.daily_quota_mode === "auto" || !settings.daily_quota_mode
                ? "bg-[#1565C0] border-[#1565C0] text-white"
                : "bg-[var(--input-bg)] border-[var(--glass-border)] hover:bg-white/[0.04]"
            }`}
            >
            <p className="text-[11px] font-black uppercase tracking-widest mb-1 flex items-center gap-2">
                Auto-Distribute <span className="px-2 py-0.5 rounded bg-white/20 text-[8px]">Recomendado</span>
            </p>
            <p className={`text-[9px] font-normal leading-relaxed ${settings.daily_quota_mode === "auto" || !settings.daily_quota_mode ? "text-white/80" : "text-[var(--text-muted)]"}`}>
                Usa un único límite de correos al día para todos los días activos. Ideal para campañas consistentes.
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
                Asigna límites diferentes según el día de la semana (ej. más volumen los martes, menos los viernes).
            </p>
            </button>
        </div>

        {/* Auto Limit (shown if auto) */}
        {(settings.daily_quota_mode === "auto" || !settings.daily_quota_mode) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-10 mt-4">
                <div className="space-y-4">
                <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Límite Diario de Emails</label>
                <div className="flex items-center justify-center gap-6 ios-btn px-6 py-5 !shadow-none group/limit hover:bg-[#0B3A82] hover:border-[#1565C0] transition-all duration-300">
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_email_limit", -1)} onMouseUp={stopHold} onMouseLeave={stopHold}>−</button>
                    <input type="number" value={settings.daily_email_limit} onChange={e => set("daily_email_limit", Math.min(500, Math.max(1, parseInt(e.target.value) || 1)))} className={stepperVal} />
                    <button className={stepperBtn} onMouseDown={() => startHold("daily_email_limit", 1)} onMouseUp={stopHold} onMouseLeave={stopHold}>+</button>
                </div>
                <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-bold text-center">Máximo recomendado según reputación: 50/día</p>
                </div>
            </div>
        )}

        {/* Custom Limit (shown if custom) */}
        {settings.daily_quota_mode === "custom" && (
            <div className="grid grid-cols-5 gap-2 mt-4">
                {["monday", "tuesday", "wednesday", "thursday", "friday"].map((day, idx) => (
                    <div key={day} className="space-y-2">
                        <label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1 flex justify-center">{day.substring(0,3)}</label>
                        <input 
                            type="number" 
                            className="w-full bg-[var(--input-bg)] border border-[var(--glass-border)] rounded-xl py-3 text-center text-[12px] font-black text-[var(--text-primary)] outline-none focus:border-[#1565C0]"
                            value={(settings.custom_daily_quotas || {})[day] ?? settings.daily_email_limit}
                            onChange={(e) => {
                                const val = parseInt(e.target.value) || 0;
                                set("custom_daily_quotas", { ...(settings.custom_daily_quotas || {}), [day]: val });
                            }}
                        />
                    </div>
                ))}
            </div>
        )}

        <div className="space-y-4 mt-6">
            <label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-black ml-1">Días Activos (Envío)</label>
            <div className="flex gap-2">
                {["L", "M", "X", "J", "V", "S", "D"].map((day, idx) => {
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
"""

content = re.sub(
    r"      \{\/\* ── Row 1: Daily Limits ───────────────────────────────────────────── \*\/\}.*?      \{\/\* ── Row 2: Channel Strategy ───────────────────────────────────────── \*\/\}",
    calendar_ui + "\n\n      {/* ── Row 2: Channel Strategy ───────────────────────────────────────── */}",
    content,
    flags=re.DOTALL
)

with open("frontend/components/CampaignSettings.tsx", "w") as f:
    f.write(content)
