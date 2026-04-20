"""
Estrae i dati reali da SUMO filtrandoli in base alla topologia dell'agente 
e calcola gli indici di performance (Priority e Stress).
"""
import traci # Importante: ci serve per interrogare SUMO direttamente sulle corsie

def _extract_intersections_from_agent(agent):
    """Estrae gli ID degli incroci dal grafo testuale della topologia dell'agente."""
    topo_intersections = []
    for line in agent.topo.get("graph", []):
        if ":" in line:
            inter_id = line.split(":")[0].strip()
            topo_intersections.append(inter_id)
    return topo_intersections

def compute_priority_score(intersections):
    """Metrica Legacy: basata sul conteggio lineare di code e veicoli."""
    total_queue = sum(inter.get("total_queue", 0) for inter in intersections)
    total_vehicles = sum(inter.get("total_vehicles", 0) for inter in intersections)
    return round(total_queue * 2 + total_vehicles * 0.5, 2)

def compute_stress_index(intersections):
    """
    Nuova Metrica Corretta (Dinamica): Calcola lo Stress Index (0-100) 
    usando la VERA capacità delle strade calcolata tramite la loro lunghezza.
    """
    if not intersections: return 0
    
    total_stress = 0
    for inter in intersections:
        total_v = inter.get("total_vehicles", 0)
        
        if total_v == 0:
            continue
            
        # Calcoliamo la vera capacità sommando quella di ogni corsia
        capacita_totale_incrocio = 0
        
        for l_data in inter.get("lanes_status", {}).values():
            # Usiamo la lunghezza appena estratta, assumendo 7.5m per auto
            lane_length = l_data.get("length", 150) # Fallback a 150m se per caso manca
            lane_capacity = lane_length / 7.5
            capacita_totale_incrocio += lane_capacity
                
        # Evitiamo divisioni per zero
        capacita_totale_incrocio = max(capacita_totale_incrocio, 1)
        
        # Saturazione basata sulla topologia reale (cappata a 1.0)
        saturation = min(inter.get("total_queue", 0) / capacita_totale_incrocio, 1.0)
        
        # Tasso di blocco (quanti fermi sul totale)
        moving = sum(l["moving"] for l in inter.get("lanes_status", {}).values())
        halting_ratio = (total_v - moving) / total_v
        
        # Stress dell'incrocio (Scala 0-100)
        inter_stress = (saturation * 60) + (halting_ratio * 40)
        total_stress += inter_stress

    return round(total_stress / len(intersections), 2)

def get_enriched_agent_metrics(agent, adapter):
    """
    Funzione principale: riceve l'agente, estrae gli incroci e calcola tutto.
    """

    # Estrazione delle informazioni per il calcolo delle metriche
    inter_ids = _extract_intersections_from_agent(agent)
    metrics = {"intersections": []}
    
    for tls_id in inter_ids:
        try:
            state = adapter.get_state(tls_id)
            int_data = {
                "id": tls_id,
                "total_vehicles": state.get("total_vehicles", 0),
                "total_queue": state.get("total_queue", 0),
                "lanes_status": {
                    l_id: {
                        "queue": d["halting"], 
                        "moving": d["vehicles"] - d["halting"],
                        "length": traci.lane.getLength(l_id) # Chiamata diretta a SUMO
                    }
                    for l_id, d in state.get("lanes", {}).items() if d["vehicles"] > 0
                }
            }
            metrics["intersections"].append(int_data)
        except Exception:
            pass
            
    # Calcolo delle metriche
    metrics["priority_score"] = compute_priority_score(metrics["intersections"])
    metrics["stress_index"] = compute_stress_index(metrics["intersections"])
            
    return metrics