import json
import os
import argparse
import numpy as np
from sklearn.cluster import KMeans

def main():
    # 1. Configurazione degli argomenti da riga di comando
    parser = argparse.ArgumentParser(description="Dividi la mappa SUMO in N zone gestite da Agent.")
    parser.add_argument("--k", type=int, required=True, help="Numero di aree/agenti desiderato")
    parser.add_argument("--tls", required=True, help="Percorso al file tls.json")
    parser.add_argument("--edges", required=True, help="Percorso al file edges.json")
    parser.add_argument("--out", required=True, help="Percorso dove salvare clusters.json")
    
    args = parser.parse_args()

    # 2. Caricamento dei dati
    if not os.path.exists(args.tls) or not os.path.exists(args.edges):
        print("Errore: file tls.json o edges.json non trovati.")
        return

    with open(args.tls, "r") as f:
        tls_data = json.load(f)
    with open(args.edges, "r") as f:
        edges_data = json.load(f)

    # 3. Preparazione delle coordinate per il K-Means
    # Estraiamo [x, y] per semafori e archi
    tls_coords = np.array([[t["x"], t["y"]] for t in tls_data])
    edges_coords = np.array([[e["x"], e["y"]] for e in edges_data])

    # Uniamo tutte le coordinate per far capire all'algoritmo la forma dell'intera mappa
    all_coords = np.vstack((tls_coords, edges_coords))

    print(f"Calcolo dei {args.k} cluster su {len(all_coords)} punti spaziali...")

    # 4. Esecuzione del Clustering K-Means
    # random_state assicura che eseguendo lo script più volte otterrai le stesse zone
    kmeans = KMeans(n_clusters=args.k, random_state=42, n_init="auto")
    kmeans.fit(all_coords)

    # 5. Assegnazione di TLS ed Edges al rispettivo Cluster
    tls_labels = kmeans.predict(tls_coords)
    edges_labels = kmeans.predict(edges_coords)

    # 6. Costruzione del dizionario di output
    # Creiamo una struttura {"agent_0": {"tls": [], "edges": []}, "agent_1": ...}
    clusters = {f"agent_{i}": {"tls": [], "edges": []} for i in range(args.k)}

    for t, label in zip(tls_data, tls_labels):
        clusters[f"agent_{label}"]["tls"].append(t["id"])

    for e, label in zip(edges_data, edges_labels):
        clusters[f"agent_{label}"]["edges"].append(e["id"])

    # 7. Salvataggio del risultato
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(clusters, f, indent=2)

    print(f"Cluster creati con successo → {args.out}")
    for agent_id, data in clusters.items():
        print(f" - {agent_id}: {len(data['tls'])} semafori, {len(data['edges'])} strade.")

if __name__ == "__main__":
    main()