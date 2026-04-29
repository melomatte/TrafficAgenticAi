import argparse
import glob
import os
import time
import requests
import traci
import threading
from fastapi import FastAPI
import uvicorn

# --- CONFIGURAZIONI ---
AGENT_URL = os.getenv("AGENT_URL", "http://traffic_agents:8000/trigger_step")
USE_GUI = os.getenv("USE_GUI", "true").lower() == "true"
BASE_DIR = "/app/simulations"

# --- IL SERVER INTERNO PER RICEVERE COMANDI DALL'MCP ---
app = FastAPI()

# Variabili condivise (Thread-safe) per i comandi in attesa
pending_commands = []
metrics_cache = {}

@app.post("/set_phase")
def set_phase(tls_id: str, phase_index: int):
    # Riceviamo il comando dall'MCP e lo mettiamo in coda
    pending_commands.append({"tls_id": tls_id, "phase_index": phase_index})
    return {"status": "queued"}

@app.get("/get_metrics/{tls_id}")
def get_metrics(tls_id: str):
    # Rispondiamo istantaneamente con l'ultimo dato noto
    return metrics_cache.get(tls_id, {"error": "No data yet"})

def run_fastapi():
    # Avvia il server in ascolto sulla porta 5000 (dentro il container sumo)
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")

def find_sumocfg(sim_path):
    files = glob.glob(os.path.join(sim_path, "*.sumocfg"))
    if not files:
        raise FileNotFoundError(f"Nessun .sumocfg in {sim_path}")
    return files[0]

def run_simulation(simulation_name, decision_interval):
    # Avvia il server API in un thread separato
    threading.Thread(target=run_fastapi, daemon=True).start()

    sim_path = os.path.join(BASE_DIR, simulation_name)
    sumocfg_file = find_sumocfg(sim_path)

    # Comando pulito: UN SOLO CLIENT!
    sumo_cmd = ["sumo-gui", "-c", sumocfg_file, "--step-length", "1", "--start"]

    print("🚗 [SUMO] Avvio engine fisico (Unico Client)...")
    traci.start(sumo_cmd)
    
    step = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        
        # 1. AGGIORNAMENTO CACHE METRICHE (Per l'MCP)
        # Supponiamo di aggiornare l'incrocio "center1" per esempio. 
        # In un caso reale, cileresti su tutti i semafori d'interesse.
        try:
            lanes = traci.trafficlight.getControlledLanes("center1")
            queue = sum(traci.lane.getLastStepHaltingNumber(l) for l in set(lanes))
            metrics_cache["center1"] = {"tls_id": "center1", "total_queue": queue}
        except Exception:
            pass

        # 2. ESECUZIONE COMANDI IN SOSPESO (Dall'MCP)
        while pending_commands:
            cmd = pending_commands.pop(0)
            try:
                traci.trafficlight.setPhase(cmd["tls_id"], cmd["phase_index"])
                print(f"🚦 [SUMO] Comando MCP Eseguito: {cmd['tls_id']} -> Fase {cmd['phase_index']}")
            except Exception as e:
                print(f"⚠️ Errore applicazione fase: {e}")

        # 3. TRIGGER ALL'IA
        if step % decision_interval == 0 and step > 0:
            try:
                requests.post(AGENT_URL, json={"step": step}, timeout=1)
            except Exception:
                pass
        
        time.sleep(0.1) 
        step += 1

    print("🏁 [SUMO] Simulazione completata.")
    traci.close()
    
    # Spegniamo il container brutalmente quando la simulazione finisce
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_name", required=True)
    parser.add_argument("--decision_interval", required=True, type=int, default=60)
    args = parser.parse_args()

    run_simulation(args.simulation_name, args.decision_interval)