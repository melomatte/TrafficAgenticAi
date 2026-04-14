# topology_builder.py
import gzip
import xml.etree.ElementTree as ET
import numpy as np
import traci
from sklearn.cluster import KMeans

def extract_traci_data(sumo_bin, sumocfg):
    """Estrae in un'unica sessione TraCI sia gli archi (edges) che i semafori (tls)."""
    traci.start([sumo_bin, "-c", sumocfg])
    
    edges_data = []
    tls_data = []
    
    try:
        # 1. Estrazione Strade (Edges)
        for e in traci.edge.getIDList():
            if e.startswith(":"): 
                continue
            try:
                lane = f"{e}_0"
                shape = traci.lane.getShape(lane)
                xs = [p[0] for p in shape]
                ys = [p[1] for p in shape]
                x, y = sum(xs)/len(xs), sum(ys)/len(ys)
                edges_data.append({"id": e, "x": x, "y": y})
            except Exception:
                pass

        # 2. Estrazione Semafori (TLS)
        for t in traci.trafficlight.getIDList():
            x, y = traci.junction.getPosition(t)
            tls_data.append({"id": t, "x": x, "y": y})
            
    finally:
        traci.close()
        
    return edges_data, tls_data

def extract_junction_data(net_file_path):
    """Analizza il file .net.xml e restituisce la struttura semaforica."""
    open_func = gzip.open if net_file_path.endswith(".gz") else open
    
    with open_func(net_file_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    tl_junctions = {}
    for junc in root.findall("junction"):
        jtype = junc.get("type", "")
        if jtype not in ("traffic_light", "traffic_light_unregulated", "traffic_light_right_on_red"):
            continue
        jid = junc.get("id")
        tl_junctions[jid] = {
            "id": jid, "type": jtype,
            "x": float(junc.get("x", 0)), "y": float(junc.get("y", 0)),
            "tlLogics": []
        }

    tl_logics = {}
    for tl in root.findall("tlLogic"):
        tl_id = tl.get("id")
        if tl_id not in tl_junctions: continue
        phases = [{"duration": float(p.get("duration", 0)), "state": p.get("state", "")} for p in tl.findall("phase")]
        tl_logics.setdefault(tl_id, []).append({
            "programID": tl.get("programID", "0"),
            "type": tl.get("type", "static"),
            "phases": phases,
            "controlledLanes": []
        })

    tl_connections = {}
    for conn in root.findall("connection"):
        tl_id = conn.get("tl")
        link_idx = conn.get("linkIndex")
        if not tl_id or tl_id not in tl_junctions or link_idx is None: continue
        
        tl_connections.setdefault(tl_id, {})[int(link_idx)] = {
            "fromEdge": conn.get("from", ""),
            "toEdge": conn.get("to", "")
        }

    for tl_id, programs in tl_logics.items():
        conns = tl_connections.get(tl_id, {})
        for prog in programs:
            n_signals = len(prog["phases"][0]["state"]) if prog["phases"] else 0
            prog["controlledLanes"] = [conns.get(i, {"fromEdge": None, "toEdge": None}) for i in range(n_signals)]

    result = []
    for jid, jdata in tl_junctions.items():
        jdata["tlLogics"] = tl_logics.get(jid, [])
        result.append(jdata)

    return result

def compute_clusters(k, tls_data, edges_data):
    """Applica il K-Means per dividere la mappa in aree per gli Agenti."""
    tls_coords = np.array([[t["x"], t["y"]] for t in tls_data])
    edges_coords = np.array([[e["x"], e["y"]] for e in edges_data])
    all_coords = np.vstack((tls_coords, edges_coords))

    kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
    kmeans.fit(all_coords)

    tls_labels = kmeans.predict(tls_coords)
    edges_labels = kmeans.predict(edges_coords)

    clusters = {f"agent_{i}": {"tls": [], "edges": []} for i in range(k)}
    
    for t, label in zip(tls_data, tls_labels):
        clusters[f"agent_{label}"]["tls"].append(t["id"])
    for e, label in zip(edges_data, edges_labels):
        clusters[f"agent_{label}"]["edges"].append(e["id"])

    return clusters

# topology_builder.py (solo la parte da sostituire in fondo)
# ... [lascia invariato tutto il codice precedente: extract_traci_data, extract_junction_data, compute_clusters] ...

def build_agent_topologies(clusters, junctions_data):
    """Genera i dizionari di topologia per ogni singolo agente in formato COMPATTO (Token-Slim)."""
    edge_to_destination = {}
    junctions_dict = {j["id"]: j for j in junctions_data}
    
    # Mappatura globale: ogni edge_in porta al suo junction_id
    for j in junctions_data:
        for prog in j.get("tlLogics", []):
            for lane in prog.get("controlledLanes", []):
                from_edge = lane.get("fromEdge")
                if from_edge: edge_to_destination[from_edge] = j["id"]

    topologies = {}
    for agent_id, data in clusters.items():
        agent_edges = set(data["edges"])
        # Inizializziamo il dizionario con le chiavi corte
        topology = {
            "id": agent_id, 
            "in": set(), 
            "out": set(),
            "graph": [] 
        }
        
        for j_id in data["tls"]:
            if j_id not in junctions_dict: continue
            
            j_data = junctions_dict[j_id]
            conn_strings = []
            seen = set()
            
            for prog in j_data.get("tlLogics", []):
                for lane in prog.get("controlledLanes", []):
                    f_edge, t_edge = lane.get("fromEdge"), lane.get("toEdge")
                    if f_edge and t_edge and (f_edge, t_edge) not in seen:
                        seen.add((f_edge, t_edge))
                        
                        # Aggiorniamo gli entry/exit point dell'area
                        if f_edge not in agent_edges: topology["in"].add(f_edge)
                        if t_edge not in agent_edges: topology["out"].add(t_edge)
                        
                        # Calcoliamo la destinazione e abbreviamo se esterna
                        leads_to = edge_to_destination.get(t_edge, "EXT")
                        target = leads_to if leads_to != "EXT" else "EXT"
                        
                        # Stringa compatta: E_IN>E_OUT(DEST)
                        conn_strings.append(f"{f_edge}>{t_edge}({target})")

            # Aggiungiamo l'incrocio come singola riga testuale
            topology["graph"].append(f"{j_id}: " + ", ".join(conn_strings))
            
        topology["in"] = list(topology["in"])
        topology["out"] = list(topology["out"])
        topologies[agent_id] = topology
        
    return topologies