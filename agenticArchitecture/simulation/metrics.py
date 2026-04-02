
"""
Estrae i dati reali da SUMO filtrandoli in base alla topologia dell'agente 
e li formatta in un JSON ottimizzato per l'LLM.
"""

def get_agent_metrics(agent_topology, adapter):
    metrics = {"intersections": []}
    
    for intersection in agent_topology.get("intersections", []):
        tls_id = intersection["id"]
        
        try:
            # Interroga SUMO usando la tua classe SumoAdapter
            state = adapter.get_state(tls_id)
            
            int_data = {
                "id": tls_id,
                "total_vehicles": state["total_vehicles"],
                "total_queue": state["total_queue"],
                "lanes_status": {}
            }
            
            for lane_id, data in state["lanes"].items():
                if data["vehicles"] > 0:
                    int_data["lanes_status"][lane_id] = {
                        "queue": data["halting"],
                        "moving": data["vehicles"] - data["halting"]
                    }
                    
            metrics["intersections"].append(int_data)
        except Exception:
            # Ignora silenziosamente se l'incrocio non è ancora caricato
            pass
            
    return metrics