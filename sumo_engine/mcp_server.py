from fastmcp import FastMCP
from typing import List
from pydantic import BaseModel
from shared_memory import state

class TrafficLightCommand(BaseModel):
    tl_id: str
    phase_index: int

# Inizializziamo il server MCP
mcp = FastMCP("SUMO_Traffic_Gateway")

@mcp.tool()
def compute_stress_index(tls_ids: List[str]) -> float:
    """Calcola lo Stress Index per gli incroci specificati leggendo dalla memoria condivisa."""
    if not tls_ids: 
        return 0.0
    
    # Leggiamo i dati aggiornati da SUMO
    intersections = [state.simulation_state[t_id] for t_id in tls_ids if t_id in state.simulation_state]
    
    if not intersections: 
        return 0.0
        
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
    return final_stress


@mcp.tool()
def set_traffic_light(tl_id: str, phase_index: int):
    state.pending_commands.append({
        "tls_id": tl_id,
        "phase_index": phase_index
    })

    return {
        "status": "queued",
        "tl_id": tl_id,
        "phase_index": phase_index
    }

@mcp.tool()
def set_traffic_light_duration(tl_id: str, duration: float):
    state.pending_commands.append({
        "type": "set_duration",
        "tls_id": tl_id,
        "duration": duration
    })
    return {"status": "queued"}


@mcp.tool()
async def compute_phase_duration(stress_index: float) -> float:
    """
    Compute an adaptive traffic light duration
    starting from the stress index.
    """

    duration = min(60, max(15, 20 + stress_index))

    return round(duration, 1)


def run_mcp_server():
    """Avvia il server con logging dedicato."""
    try:
        print("🌐 [MCP] Tentativo di avvio server SSE sulla porta 8001...", flush=True)
        mcp.run(transport='sse', host="0.0.0.0", port=8001)
    except Exception as e:
        print(f"⚠️ [MCP] Errore critico server: {e}", flush=True)
        