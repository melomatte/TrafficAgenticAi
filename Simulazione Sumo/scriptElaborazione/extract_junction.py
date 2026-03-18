"""
Estrae ogni junction con almeno un semaforo dal file osm.net.xml.gz
e produce un file JSON con:
  - id junction
  - coordinate x, y della junction
  - lane in ingresso (incLanes)
  - per ogni tlLogic collegato:
      - id, tipo, programID
      - fasi (durata + stato) = lo stato è una stringa del tipo GGrrGGrr e ad ogni carattere 
        corrisponde un linkIndex. 
            Immagina un incrocio semplice a 4 braccia con 2 corsie per direzione:
            state="GGrrGGrr"
                    ││  ││
                    ││  │└─ linkIndex 7 → via Zamboni corsia sinistra → rosso
                    ││  └── linkIndex 6 → via Zamboni corsia destra → rosso  
                    │└───── linkIndex 5 → via Indipendenza corsia sinistra → verde
                    └────── linkIndex 4 → via Indipendenza corsia destra → verde
      - lane controllate da ogni semaforo (dalla sezione <connection>)

Comando per esecuzione:
python3 scriptElaborazione/extract_junction.py --net Prova_VialeAldini/osm.net.xml.gz --output output/junction.json
"""

import gzip
import argparse
import json
import xml.etree.ElementTree as ET
import sys
import os


# Supporta anche file non compressi
def open_net(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")

def main():
    parser = argparse.ArgumentParser(description="Script per individuare incroci semaforici")
    parser.add_argument("--net", required=True, help="File .net contenente la topologia della strada")
    parser.add_argument("--output", required=True, help="File .json dove viene stampato l'output del programma")

    args = parser.parse_args()
    net_file = args.net
    output_file = args.output

    if not os.path.exists(net_file):
        print(f"Errore: file '{net_file}' non trovato.")
        sys.exit(1)

    print(f"Caricamento {net_file} ...")
    with open_net(net_file) as f:
        tree = ET.parse(f)
    root = tree.getroot()
    print("File caricato.")

    # -------------------------------------------------------
    # 1. Raccogli tutte le junction di tipo traffic_light -> contengono almeno 1 semaforo
    # -------------------------------------------------------
    
    tl_junctions = {}
    for junc in root.findall("junction"):
        jtype = junc.get("type", "")
        if jtype not in ("traffic_light", "traffic_light_unregulated", "traffic_light_right_on_red"):
            continue

        jid = junc.get("id")
        inc_lanes = junc.get("incLanes", "")
        int_lanes = junc.get("intLanes", "")

        tl_junctions[jid] = {
            "id": jid,
            "type": jtype,
            "x": float(junc.get("x", 0)),
            "y": float(junc.get("y", 0)),
            "incLanes": inc_lanes.split() if inc_lanes else [],
            "intLanes": int_lanes.split() if int_lanes else [],
            "tlLogics": []
        }

    print(f"Trovate {len(tl_junctions)} junction con semafori.")

    # -------------------------------------------------------
    # 2. Raccogli tutti i tlLogic -> id del tlLogic corrisponde all'id della junction
    # -------------------------------------------------------
    tl_logics = {}
    for tl in root.findall("tlLogic"):
        tl_id = tl.get("id")
        if tl_id not in tl_junctions:
            continue

        phases = []
        for phase in tl.findall("phase"):
            phases.append({
                "duration": float(phase.get("duration", 0)),
                "state": phase.get("state", ""),
                "minDur": phase.get("minDur"),
                "maxDur": phase.get("maxDur"),
            })
            # Rimuovi chiavi None
            phases[-1] = {k: v for k, v in phases[-1].items() if v is not None}

        tl_logics.setdefault(tl_id, []).append({
            "programID": tl.get("programID", "0"),
            "type": tl.get("type", "static"),
            "offset": float(tl.get("offset", 0)),
            "phases": phases,
            "controlledLanes": []   # verrà popolato dopo
        })

    # -------------------------------------------------------
    # 3. Raccogli le connessioni con linkIndex
    #    <connection from="edgeA" to="edgeB" fromLane="0" toLane="0"
    #                via=":juncID_0_0" tl="juncID" linkIndex="3"/>
    #    linkIndex indica la posizione nel campo state del semaforo
    # -------------------------------------------------------
    # Struttura: tl_connections[tl_id] = dict(linkIndex -> info lane)
    tl_connections = {}
    for conn in root.findall("connection"):
        tl_id = conn.get("tl")
        if not tl_id or tl_id not in tl_junctions:
            continue

        link_index = conn.get("linkIndex")
        if link_index is None:
            continue
        link_index = int(link_index)

        from_edge = conn.get("from", "")
        from_lane_idx = conn.get("fromLane", "0")
        to_edge = conn.get("to", "")
        to_lane_idx = conn.get("toLane", "0")
        via = conn.get("via", "")

        lane_info = {
            "linkIndex": link_index,
            "fromLane": f"{from_edge}_{from_lane_idx}",
            "toLane": f"{to_edge}_{to_lane_idx}",
            "via": via,
            "fromEdge": from_edge,
            "toEdge": to_edge,
        }

        tl_connections.setdefault(tl_id, {})[link_index] = lane_info

    # -------------------------------------------------------
    # 4. Associa le lane controllate a ogni programma tlLogic
    #    Ogni carattere dello "state" nella prima fase
    #    corrisponde a linkIndex 0, 1, 2, ...
    # -------------------------------------------------------
    for tl_id, programs in tl_logics.items():
        connections = tl_connections.get(tl_id, {})
        for program in programs:
            # Determina il numero di segnali dal primo phase state
            n_signals = len(program["phases"][0]["state"]) if program["phases"] else 0
            controlled = []
            for idx in range(n_signals):
                lane_info = connections.get(idx)
                if lane_info:
                    controlled.append(lane_info)
                else:
                    # Segnale interno all'incrocio senza connessione esplicita
                    controlled.append({
                        "linkIndex": idx,
                        "fromLane": None,
                        "toLane": None,
                        "via": None,
                        "note": "internal / no explicit connection"
                    })
            program["controlledLanes"] = controlled

    # -------------------------------------------------------
    # 5. Assembla il risultato finale
    # -------------------------------------------------------
    result = []
    for jid, jdata in sorted(tl_junctions.items()):
        programs = tl_logics.get(jid, [])
        entry = {
            "id": jid,
            "type": jdata["type"],
            "x": jdata["x"],
            "y": jdata["y"],
            "incLanes": jdata["incLanes"],
            "intLanes": jdata["intLanes"],
            "tlLogics": programs
        }
        result.append(entry)

    # -------------------------------------------------------
    # 6. Scrivi JSON
    # -------------------------------------------------------
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nOutput scritto in: {output_file}")
    print(f"Junction totali con semafori: {len(result)}")
    total_programs = sum(len(j["tlLogics"]) for j in result)
    total_lanes = sum(
        sum(len(p["controlledLanes"]) for p in j["tlLogics"])
        for j in result
    )
    print(f"Programmi semaforo totali:    {total_programs}")
    print(f"Lane controllate totali:      {total_lanes}")

if __name__ == "__main__":
    main()