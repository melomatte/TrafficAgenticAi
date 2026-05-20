import argparse
import glob
import os
import time
import traci
import threading
import requests
from mcp_server import run_mcp_server
from shared_memory import state

"""
comando per esecuzione (da root progetto): 
    python3 sumo_engine/simulationManager.py --gui "true"

Script per simulazione SUMO + avvio thread mcp server su localhost porta 8001
"""

# ---------------------------------------------------------------------------
# Configurazioni Locali
# ---------------------------------------------------------------------------
ORCHESTRATOR_URL = "http://localhost:8080/trigger_agentic"
BASE_DIR = os.path.join(os.getcwd(), "sumo_engine", "urbanNetworks")

def find_sumocfg(sim_path):
    files = glob.glob(os.path.join(sim_path, "*.sumocfg"))
    if not files:
        raise FileNotFoundError(f"Nessun .sumocfg in {sim_path}")
    return files[0]

def initialize_static_data():
    print("[SUMO] 📏 Estrazione dati statici della rete...", flush=True)
    for tls_id in traci.trafficlight.getIDList():
        lanes = list(set(traci.trafficlight.getControlledLanes(tls_id)))
        for l_id in lanes:
            if l_id not in state.static_lane_lengths:
                state.static_lane_lengths[l_id] = traci.lane.getLength(l_id)

def run_simulation(simulation_name, decision_interval, gui):
    # 1. Avvio MCP Server nel thread separato passando il logger
    print("[SUMO] Inizializzazione thread MCP Server...", flush=True)
    api_thread = threading.Thread(target=run_mcp_server, daemon=True)
    api_thread.start()
    
    # 2. Avvio SUMO Localmente
    sim_path = os.path.join(BASE_DIR, simulation_name)
    sumocfg_file = find_sumocfg(sim_path)

    if gui == "true":
        sumo_cmd = ["sumo-gui", "-c", sumocfg_file, "--step-length", "1", "--start"]
    else: 
        sumo_cmd = ["sumo", "-c", sumocfg_file, "--step-length", "1", "--start"]
        
    print(f"[SUMO] 🚗 Avvio simulazione: {simulation_name}", flush=True)
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

        # ESECUZIONE COMANDI MCP
        while state.pending_commands:
            cmd = state.pending_commands.pop(0)

            try:
                tl_id = cmd["tls_id"]

                if cmd.get("type") == "set_duration":
                    traci.trafficlight.setPhaseDuration(tl_id, cmd["duration"])
                    print(f"⏱️ [SUMO] Durata fase cambiata: {tl_id} -> {cmd['duration']}s", flush=True)

                else:
                    target_phase = cmd["phase_index"]
                    current_phase = traci.trafficlight.getPhase(tl_id)

                    # Controllo per errore 0xc2 (Fasi Inesistenti)
                    logic = traci.trafficlight.getCompleteRedYellowGreenDefinition(tl_id)
                    num_phases = len(logic[0].phases)

                    if target_phase >= num_phases or target_phase < 0:
                        print(
                            f"⚠️ [SUMO] Rifiutato: l'agente ha chiesto la fase {target_phase} "
                            f"su {tl_id}, ma esistono solo {num_phases} fasi (da 0 a {num_phases-1}).",
                            flush=True
                        )
                        continue

                    # Controllo per frenate d'emergenza
                    if current_phase != target_phase:
                        current_state = logic[0].phases[current_phase].state
                        
                        # Se il semaforo è attualmente verde per qualcuno, forziamo il giallo invece di passare di colpo alla fase target
                        if 'G' in current_state or 'g' in current_state:
                            traci.trafficlight.setPhaseDuration(tl_id, 0)
                            print(f"🔄 [SUMO] Avvio transizione sicura per {tl_id}: chiusura fase verde in corso.", flush=True)
                        
                        else:
                            # Se siamo già in una fase di transizione (giallo o tutto rosso), è sicuro applicare direttamente il target
                            traci.trafficlight.setPhase(tl_id, target_phase)
                            print(f"🚦 [SUMO] Fase cambiata in sicurezza: {tl_id} -> {target_phase}",flush=True)
                    else: 
                        print(f"🟢 [SUMO] {tl_id} è già nella fase {target_phase}.", flush=True)

            except Exception as e:
                print(f"⚠️ [SUMO] Errore comando: {e}", flush=True)

        if step == decision_interval:
            try:
                # Questa richiesta HTTP è veloce perché l'Orchestratore avvia il loop in background
                response = requests.post(
                    ORCHESTRATOR_URL,
                    json={"step": 0, "simulation_id": simulation_name},
                    timeout=10.0
                )
                response.raise_for_status()
                print("[SUMO] ✅ Loop agentico innescato con successo!")
            except Exception as e:
                print(f"[SUMO] ❌ ERRORE CRITICO: Impossibile contattare l'Orchestratore: {e}")
                print("La simulazione fisica partirà, ma l'IA non è attiva.")
                
        time.sleep(0.5)
        step += 1

    print("[SUMO] 🏁 Simulazione completata.", flush=True)
    traci.close()
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SUMO simulation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--simulation_name", default="2cross", help="Nome della simulazione")
    parser.add_argument("--decision_interval", type=int, default=60, help="Step SUMO inizio sistema di monitoraggio agentico")
    parser.add_argument("--gui", default="false", choices=["true", "false"], help="Abilita la GUI di SUMO")
    args = parser.parse_args()
    run_simulation(args.simulation_name, args.decision_interval, args.gui)