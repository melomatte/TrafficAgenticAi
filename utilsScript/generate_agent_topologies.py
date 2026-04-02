import json
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Genera file topology.json per ogni agente.")
    parser.add_argument("--clusters", required=True, help="File clusters.json generato dal K-Means")
    parser.add_argument("--junctions", required=True, help="File junction.json generato da extract_junction.py")
    parser.add_argument("--outdir", required=True, help="Cartella dove salvare le topologie degli agenti")
    
    args = parser.parse_args()

    if not os.path.exists(args.clusters) or not os.path.exists(args.junctions):
        print("Errore: file di input non trovati.")
        return

    with open(args.clusters, "r") as f:
        clusters = json.load(f)
        
    with open(args.junctions, "r") as f:
        junctions_data = json.load(f)

    junctions_dict = {j["id"]: j for j in junctions_data}
    os.makedirs(args.outdir, exist_ok=True)

    for agent_id, data in clusters.items():
        agent_tls = data["tls"]
        agent_edges = set(data["edges"])
        
        topology = {
            "agent_id": agent_id,
            "intersections": [],
            "internal_edges": list(agent_edges),
            "entry_points": [], # NUOVO: Strade che portano traffico DENTRO la giurisdizione
            "exit_points": []   # Strade che portano traffico FUORI dalla giurisdizione
        }
        
        entry_edges_set = set()
        exit_edges_set = set()

        for j_id in agent_tls:
            if j_id not in junctions_dict:
                continue
                
            j_data = junctions_dict[j_id]
            connections = []
            seen_connections = set()
            
            for program in j_data.get("tlLogics", []):
                for lane in program.get("controlledLanes", []):
                    from_edge = lane.get("fromEdge")
                    to_edge = lane.get("toEdge")
                    
                    if from_edge and to_edge:
                        conn_tuple = (from_edge, to_edge)
                        if conn_tuple not in seen_connections:
                            seen_connections.add(conn_tuple)
                            connections.append({
                                "from": from_edge,
                                "to": to_edge
                            })
                            
                            # Logica ENTRY POINT: l'origine non è mia, ma entra in un mio incrocio
                            if from_edge not in agent_edges:
                                entry_edges_set.add(from_edge)

                            # Logica EXIT POINT: la destinazione non è mia, ma esce da un mio incrocio
                            if to_edge not in agent_edges:
                                exit_edges_set.add(to_edge)

            topology["intersections"].append({
                "id": j_id,
                "type": j_data.get("type", "traffic_light"),
                "connections": connections
            })
            
        topology["entry_points"] = list(entry_edges_set)
        topology["exit_points"] = list(exit_edges_set)

        out_file = os.path.join(args.outdir, f"{agent_id}_topology.json")
        with open(out_file, "w") as f:
            json.dump(topology, f, indent=2)
            
        print(f"Salvato: {out_file} (Entry: {len(topology['entry_points'])}, Exit: {len(topology['exit_points'])})")

if __name__ == "__main__":
    main()