import glob
import os
import json
import clusteringTopology.topology_library as tb

BASE_DIR = "simulationContainer/urbanNetworks"

def find_net_file(sim_folder):
    files = glob.glob(os.path.join(sim_folder, "*.net.xml"))
    if not files:
        # Corretto il testo dell'errore da .sumocfg a .net.xml
        raise FileNotFoundError(f"Nessun .net.xml in {sim_folder}")
    return files[0]

def build_topologies(simulation_name: str, k: int, outdir: str):
    """
    Funzione principale importabile da altri script.
    Esegue l'intera pipeline di clustering e generazione topologie.
    
    Ritorna True se ha successo, False in caso di errore.
    """
    
    sim_folder = os.path.join(BASE_DIR, simulation_name)
    
    # Creiamo unicamente la cartella specificata da outdir
    os.makedirs(outdir, exist_ok=True)

    net_file = find_net_file(sim_folder)
    if not net_file or not os.path.exists(net_file):
        print(f"❌ Errore: File di rete non trovato in {sim_folder}")
        return False

    print("1. Estrazione di tutta la rete da XML (senza TraCI)...")
    edges_data, tls_data, junctions_data = tb.extract_network_data(net_file)
    # Salvataggio dei file JSON intermedi rimosso

    print(f"2. Calcolo dei Cluster K-Means (k={k})...")
    clusters = tb.compute_clusters(k, tls_data, edges_data)
    # Salvataggio del file clusters.json rimosso

    print("3. Generazione Mappe Topologiche per Agenti...")
    topologies = tb.build_agent_topologies(clusters, junctions_data)
    
    # I file di topologia degli agenti vengono salvati direttamente in 'outdir'
    for agent_id, topo in topologies.items():
        filepath = os.path.join(outdir, f"{agent_id}_topology.json")
        
        with open(filepath, "w") as f:
            json.dump(topo, f, indent=2)

        print(f"   ✅ Salvato: {filepath} (Incroci: {len(topo['graph'])})")

    print("\n🎉 Pipeline completata!")
    return True