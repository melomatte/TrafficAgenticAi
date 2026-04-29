import argparse
import glob
import os
import time
import requests
import traci
import threading

# Importiamo il server e la memoria condivisa dai nostri nuovi file
from api_server import run_fastapi
from shared_memory import state

AGENT_URL = os.getenv("AGENT_URL", "http://agentic_system:8000/trigger_step")
BASE_DIR = "/app/simulations"

def find_sumocfg(sim_path):
    files = glob.glob(os.path.join(sim_path, "*.sumocfg"))
    if not files:
        raise FileNotFoundError(f"Nessun .sumocfg in {sim_path}")
    return files[0]

def initialize_static_data():
    """Estrae le lunghezze delle corsie e le salva nella memoria condivisa."""
    print("📏 [SUMO] Estrazione dati statici della rete...", flush=True)
    for tls_id in traci.trafficlight.getIDList():
        lanes = list(set(traci.trafficlight.getControlledLanes(tls_id)))
        for l_id in lanes:
            if l_id not in state.static_lane_lengths:
                state.static_lane_lengths[l_id] = traci.lane.getLength(l_id)

def run_simulation(simulation_name, decision_interval):
    # 1. Avvio API Server nel thread separato
    api_thread = threading.Thread(target=run_fastapi, daemon=True)
    api_thread.start()

    # 2. Avvio SUMO
    sim_path = os.path.join(BASE_DIR, simulation_name)
    sumocfg_file = find_sumocfg(sim_path)
    sumo_cmd = ["sumo-gui", "-c", sumocfg_file, "--step-length", "1", "--start"]
    
    print(f"🚗 [SUMO] Avvio simulazione: {simulation_name}", flush=True)
    traci.start(sumo_cmd)
    initialize_static_data()
    
    step = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        
        # Aggiornamento memoria condivisa  
        for tls_id in traci.trafficlight.getIDList():
            lanes = list(set(traci.trafficlight.getControlledLanes(tls_id)))
            tot_vehicles, tot_queue, lanes_status = 0, 0, {}
            
            for l_id in lanes:
                vehs = traci.lane.getLastStepVehicleNumber(l_id)
                halt = traci.lane.getLastStepHaltingNumber(l_id)
                tot_vehicles += vehs
                tot_queue += halt
                if vehs > 0:
                    lanes_status[l_id] = {
                        "queue": halt,
                        "moving": vehs - halt,
                        "length": state.static_lane_lengths.get(l_id, 150)
                    }
                    
            state.simulation_state[tls_id] = {
                "id": tls_id,
                "total_vehicles": tot_vehicles,
                "total_queue": tot_queue,
                "lanes_status": lanes_status
            }

        # ESECUZIONE COMANDI MCP (Letti dalla memoria condivisa)
        """while state.pending_commands:
            cmd = state.pending_commands.pop(0)
            try:
                traci.trafficlight.setPhase(cmd["tls_id"], cmd["phase_index"])
                print(f"🚦 [SUMO] Fase cambiata: {cmd['tls_id']} -> {cmd['phase_index']}", flush=True)
            except Exception as e:
                print(f"⚠️ [SUMO] Errore comando: {e}", flush=True)"""

        # 5. TRIGGER AGENTI
        if step % decision_interval == 0 and step > 0:
            print(f"📡 [SUMO] Step {step}: Invio trigger agli agenti...", flush=True)
            try:
                requests.post(AGENT_URL, json={"step": step, "simulation_id": simulation_name}, timeout=1)
            except Exception as e:
                print(f"⚠️ [SUMO] Agenti non raggiungibili: {e}", flush=True)
        
        time.sleep(0.5) 
        step += 1

    print("🏁 [SUMO] Simulazione completata.", flush=True)
    traci.close()
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_name", required=True)
    parser.add_argument("--decision_interval", type=int, default=60)
    args = parser.parse_args()

    run_simulation(args.simulation_name, args.decision_interval)