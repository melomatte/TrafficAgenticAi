'''
python3 clusteringTopology/create_topologies.py --sumocfg urbanNetworks/2cross/sim.sumocfg --k 1 --outdir urbanNetworks/2cross/data
'''

import os
import argparse
import json
import xml.etree.ElementTree as ET

# Importiamo la nostra libreria unificata
import topology_builder as tb 

def find_net_file(sumocfg_path):
    """Trova il percorso del .net.xml analizzando il sumocfg."""
    tree = ET.parse(sumocfg_path)
    net_node = tree.find('.//net-file')
    if net_node is not None:
        return os.path.join(os.path.dirname(sumocfg_path), net_node.get('value'))
    return None

def save_json(data, filepath):
    """Utility per salvare i file json."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Generatore Topologie Agenti via Libreria Unica")
    parser.add_argument("--sumocfg", required=True, help="Percorso del file .sumocfg")
    parser.add_argument("--k", type=int, required=True, help="Numero di cluster/agenti desiderato")
    parser.add_argument("--sumo_bin", default="/usr/share/sumo/bin/sumo", help="Eseguibile sumo (no gui)")
    parser.add_argument("--outdir", required=True, help="Cartella di output")
    
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    agent_dir = os.path.join(args.outdir, "agent_topologies")
    os.makedirs(agent_dir, exist_ok=True)

    net_file = find_net_file(args.sumocfg)
    if not net_file or not os.path.exists(net_file):
        print(f"❌ Errore: File di rete non trovato da {args.sumocfg}")
        return

    print("1. Estrazione dati stradali da TraCI...")
    edges_data, tls_data = tb.extract_traci_data(args.sumo_bin, args.sumocfg)
    save_json(edges_data, os.path.join(args.outdir, "edges.json"))
    save_json(tls_data, os.path.join(args.outdir, "tls.json"))

    print("2. Estrazione dati incroci (XML Parsing)...")
    junctions_data = tb.extract_junction_data(net_file)
    save_json(junctions_data, os.path.join(args.outdir, "junction.json"))

    print(f"3. Calcolo dei Cluster K-Means (k={args.k})...")
    clusters = tb.compute_clusters(args.k, tls_data, edges_data)
    save_json(clusters, os.path.join(args.outdir, "clusters.json"))

    print("4. Generazione Mappe Topologiche (Modo Compatto) per Agenti...")
    topologies = tb.build_agent_topologies(clusters, junctions_data)
    
    for agent_id, topo in topologies.items():
        filepath = os.path.join(agent_dir, f"{agent_id}_topology.json")
        save_json(topo, filepath)
        # NOTA: qui ho aggiornato topo['intersections'] in topo['graph']
        print(f"   ✅ Salvato: {filepath} (Incroci: {len(topo['graph'])})")

    print("\n🎉 Pipeline completata! Tutti i file sono pronti per la simulazione.")

if __name__ == "__main__":
    main()