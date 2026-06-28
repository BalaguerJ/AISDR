import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
# Add parent dir to path if needed, but since we are running from backend, we just import
import sys
sys.path.append(os.path.dirname(__file__))
from agents.ai_brain import call_gemini

campaign_id = "5b42fc17-7ed4-4769-a67a-018276ec09ad"
campaign_path = f"campaigns/{campaign_id}.json"

with open(campaign_path, 'r') as f:
    campaign = json.load(f)

template = """
Hola equipo de {name},

Mi nombre es Aire Balaguer, artista de Palma de Mallorca. Al ver vuestro enfoque en baile latino en Valencia, pensé en vosotros. Acabo de lanzar "OLISE", mi primera canción de salsa urbana junto a músicos de conservatorio de Puerto Rico, y creo que su ritmo podría encajar perfecto en vuestras clases, sociales o alguna coreografía. Si os interesa darle una escucha, ¿os la puedo compartir por aquí?

Gracias por vuestro tiempo.
Un saludo, Aire
"""

system_prompt = (
    "Eres un asistente experto en redacción de cold emails. Se te proporcionará una plantilla dirigida a una academia "
    "de baile específica. Tu tarea es reescribir ese correo asegurando que transmite EXACTAMENTE la misma oferta y mensaje, "
    "y manteniendo la educación y la pregunta final. Sin embargo, debes cambiar ligeramente la redacción, usar diferentes sinónimos, "
    "o alterar la estructura de las frases para que cada correo sea único frente a los filtros anti-spam de Gmail. "
    "IMPORTANTE: DEVUELVE ÚNICAMENTE EL TEXTO EN PLANO. NADA DE SALUDOS EXTRAS NI BLOQUES DE CÓDIGO."
)

async def main():
    pending_leads = [l for l in campaign['leads'] if l['status'] == 'pending_approval']
    print(f"Rewrite starting for {len(pending_leads)} pending leads...")

    for lead in campaign["leads"]:
        if lead["status"] == "pending_approval":
            # Personalize template with lead's name
            lead_name = lead.get("name", "la academia")
            lead_template = template.replace("{name}", lead_name)
            
            prompt = f"{system_prompt}\n\nPLANTILLA ORIGINAL A REESCRIBIR:\n{lead_template}"
            
            try:
                rewritten = await call_gemini(prompt)
                rewritten = rewritten.strip()
                # Update the lead's draft_body
                lead["draft_body"] = rewritten
                print(f"✅ Rewrote email for {lead_name}")
            except Exception as e:
                print(f"❌ Error rewriting for {lead_name}: {str(e)}")

    # Save back to file
    with open(campaign_path, 'w', encoding='utf-8') as f:
        json.dump(campaign, f, indent=4)

    print("🚀 All pending leads rewritten successfully!")

if __name__ == "__main__":
    asyncio.run(main())
