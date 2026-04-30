from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import uvicorn

# Importiamo la lavagna condivisa
from shared_memory import state

app = FastAPI()

class TlsRequest(BaseModel):
    tls_ids: List[str]

class TrafficLightCommand(BaseModel):
    tl_id: str
    phase_index: int

@app.post("/compute_stress_index")
def get_stress_index(request: TlsRequest):
    """Calcola lo Stress Index leggendo dalla memoria condivisa."""
    if not request.tls_ids: 
        return {"stress_index": 0.0}
    
    # Leggiamo i dati aggiornati da SUMO
    intersections = [state.simulation_state[t_id] for t_id in request.tls_ids if t_id in state.simulation_state]
    
    if not intersections: 
        return {"stress_index": 0.0}
        
    total_stress = 0
    for inter in intersections:
        total_v = inter.get("total_vehicles", 0)
        if total_v == 0: continue
            
        capacita_totale_incrocio = 0
        for l_data in inter.get("lanes_status", {}).values():
            lane_length = l_data.get("length", 150)
            capacita_totale_incrocio += (lane_length / 7.5)
                
        capacita_totale_incrocio = max(capacita_totale_incrocio, 1)
        saturation = min(inter.get("total_queue", 0) / capacita_totale_incrocio, 1.0)
        
        moving = sum(l["moving"] for l in inter.get("lanes_status", {}).values())
        halting_ratio = (total_v - moving) / total_v
        
        inter_stress = (saturation * 60) + (halting_ratio * 40)
        total_stress += inter_stress

    final_stress = round(total_stress / len(intersections), 2)
    return {"stress_index": final_stress}

@app.post("/set_traffic_light")
def set_traffic_light(command: TrafficLightCommand):
    state.pending_commands.append({
        "tls_id": command.tl_id,
        "phase_index": command.phase_index
    })

    return {
        "status": "queued",
        "tl_id": command.tl_id,
        "phase_index": command.phase_index
    }

def run_fastapi():
    """Avvia il server con gestione degli errori sulla porta."""
    try:
        print("🌐 [API] Tentativo di avvio server sulla porta 5000...", flush=True)
        uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")
    except Exception as e:
        print(f"⚠️ [API] Errore critico server: {e}", flush=True)
        print("⚠️ [API] Se l'errore è 'Address already in use', significa che lo script è in esecuzione altrove.", flush=True)