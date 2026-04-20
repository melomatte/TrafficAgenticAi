"""
Estrae i dati reali da SUMO filtrandoli in base alla topologia dell'agente 
e calcola gli indici di performance (Priority e Stress).
"""

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
    Nuova Metrica Corretta: Calcola lo Stress Index (0-100).
    Risolve il bug del doppio moltiplicatore e gestisce gli incroci vuoti.
    """
    if not intersections: return 0
    
    total_stress = 0
    for inter in intersections:
        total_v = inter.get("total_vehicles", 0)
        
        # FIX 1: Se l'incrocio è completamente vuoto, lo stress è 0.
        if total_v == 0:
            continue
            
        # FIX 2: Calcolo saturazione cappato a 1.0. 
        # Se ci sono 30 auto su una capacità di 20, la saturazione massima è comunque 100%.
        num_lanes = len(inter.get("lanes_status", {}))
        capacity = max(num_lanes * 20, 1)
        saturation = min(inter.get("total_queue", 0) / capacity, 1.0)
        
        # FIX 3: Tasso di blocco (quanti veicoli sono fermi rispetto al totale)
        moving = sum(l["moving"] for l in inter.get("lanes_status", {}).values())
        halting_ratio = (total_v - moving) / total_v
        
        # Stress dell'incrocio (Scala 0-100 pura)
        # 60 punti dati dalla quantità di auto in coda rispetto allo spazio fisico
        # 40 punti dati dalla percentuale di auto ferme sul totale
        inter_stress = (saturation * 60) + (halting_ratio * 40)
        total_stress += inter_stress

    # FIX 4: Media semplice. Nessuna ulteriore moltiplicazione per 100!
    return round(total_stress / len(intersections), 2)

def get_enriched_agent_metrics(agent, adapter):
    """
    Funzione principale: riceve l'agente, estrae gli incroci e calcola tutto.
    """
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
                    l_id: {"queue": d["halting"], "moving": d["vehicles"] - d["halting"]}
                    for l_id, d in state.get("lanes", {}).items() if d["vehicles"] > 0
                }
            }
            metrics["intersections"].append(int_data)
        except Exception:
            pass
            
    # Calcolo degli score
    metrics["priority_score"] = compute_priority_score(metrics["intersections"])
    metrics["stress_index"] = compute_stress_index(metrics["intersections"])
    metrics["zone"] = getattr(agent, "zone", "unknown")
            
    return metrics