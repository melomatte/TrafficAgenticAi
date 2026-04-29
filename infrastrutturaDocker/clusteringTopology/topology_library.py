"""
Libreria necessaria per topology_builder.py. Contiene tutta la logica matematica:
1. Estrazione Dati: Implementa le chiamate a TraCI per ottenere coordinate spaziali e l'analisi XML per estrarre la logica dei semafori.
2. Clustering Spaziale: Utilizza l'algoritmo K-Means per dividere geograficamente la mappa tra i vari agenti AI.
3. Ottimizzazione Topologica: Trasforma i dati complessi della rete stradale nel formato "Token-Slim" (E_IN>E_OUT), rendendo la mappa leggibile ed efficiente per la context window dell'LLM.
"""

import gzip
import xml.etree.ElementTree as ET
import numpy as np
from sklearn.cluster import KMeans

def extract_network_data(net_file_path):
    """
    Legge il file .net.xml in un'unica passata ed estrae:
    - coordinate archi (edges_data)
    - coordinate semafori (tls_data)
    - collegamenti incroci (junctions_data)
    Senza usare TraCI.
    """
    open_func = gzip.open if net_file_path.endswith(".gz") else open
    with open_func(net_file_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    edges_data = []
    tls_data = []
    tl_junctions = {}

    # 1. Estrazione Archi e calcolo del loro centroide
    for edge in root.findall("edge"):
        e_id = edge.get("id")
        # Saltiamo gli archi interni (che iniziano con ":")
        if not e_id or e_id.startswith(":"):
            continue
        
        # Prendiamo la forma della prima corsia per calcolare il centro
        lane = edge.find("lane")
        if lane is not None:
            shape_str = lane.get("shape", "")
            if shape_str:
                # La forma è una stringa del tipo "x1,y1 x2,y2 ..."
                points = [tuple(map(float, p.split(","))) for p in shape_str.split()]
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                # Calcoliamo il punto medio (come faceva il vecchio script)
                x_center, y_center = sum(xs)/len(xs), sum(ys)/len(ys)
                edges_data.append({"id": e_id, "x": x_center, "y": y_center})

    # 2. Estrazione Semafori e Incroci
    for junc in root.findall("junction"):
        jtype = junc.get("type", "")
        if jtype not in ("traffic_light", "traffic_light_unregulated", "traffic_light_right_on_red"):
            continue
        jid = junc.get("id")
        x, y = float(junc.get("x", 0)), float(junc.get("y", 0))
        
        # Popoliamo tls_data per il K-Means
        tls_data.append({"id": jid, "x": x, "y": y})
        
        # Prepariamo la struttura per i collegamenti
        tl_junctions[jid] = {
            "id": jid, "type": jtype,
            "x": x, "y": y,
            "tlLogics": []
        }

    # 3. Estrazione Fasi e Connessioni (Mantenuto intatto dal tuo codice originale)
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

    junctions_data = []
    for jid, jdata in tl_junctions.items():
        jdata["tlLogics"] = tl_logics.get(jid, [])
        junctions_data.append(jdata)

    return edges_data, tls_data, junctions_data

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