import re

with open("frontend/app/page.tsx", "r") as f:
    content = f.read()

# 1. Add state for preview data
state_injection = """
  const [selectedCampaign, setSelectedCampaign] = useState<any>(null);
  const [previewData, setPreviewData] = useState<any>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
"""
content = re.sub(r"  const \[selectedCampaign, setSelectedCampaign\] = useState<any>\(null\);", state_injection, content)

# 2. Add functions to handle preview and enqueue
functions_injection = """
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
"""
content = re.sub(r"  const controlCampaign = async \(id: string, action: \"start\" \| \"pause\" \| \"stop\"\) => \{", functions_injection, content)

# 3. Change Activate button to trigger Preview
button_replace = """
                     <button 
                     onClick={() => handlePreviewEnqueue(selectedCampaign.id)}
                     disabled={isPreviewing}
                     className="px-10 py-4 bg-transparent border border-[var(--glass-border)] text-[var(--text-primary)] hover:bg-[var(--accent-blue)] hover:border-[var(--accent-blue)] hover:text-white rounded-xl font-black text-[10px] uppercase tracking-[0.4em] transition-all duration-300 active:scale-[0.985] shadow-sm hover:shadow-[0_0_30px_rgba(21,101,192,0.3)]"
                    >{isPreviewing ? "Calculando..." : "Activate Virtual SDR"}</button>
"""
content = re.sub(
    r"                     <button \n                     onClick=\{\(\) => controlCampaign\(selectedCampaign\.id, \"start\"\)\}\n                     className=\"px-10 py-4 bg-transparent border border-\[var\(--glass-border\)\] text-\[var\(--text-primary\)\] hover:bg-\[var\(--accent-blue\)\] hover:border-\[var\(--accent-blue\)\] hover:text-white rounded-xl font-black text-\[10px\] uppercase tracking-\[0\.4em\] transition-all duration-300 active:scale-\[0\.985\] shadow-sm hover:shadow-\[0_0_30px_rgba\(21,101,192,0\.3\)\]\"\n                    >Activate Virtual SDR</button>",
    button_replace,
    content
)

# 4. Inject Modal HTML
modal_injection = """
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
"""
content = content.replace("{/* ━━ Campaign Details / Review Queue / Virtual SDR HUD ━━━━━━━━ */}", modal_injection)

with open("frontend/app/page.tsx", "w") as f:
    f.write(content)
