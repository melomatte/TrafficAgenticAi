"""
Comando per l'esecuzione:
    python3 agenticArchitecture/main.py --topology urbanNetworks/2cross/data/agent_topologies/agent_0_topology.json --sumo_cfg urbanNetworks/2cross/sim.sumocfg --provider cloud
"""

import argparse
import traci
from agent import TrafficAgent
from simulation.sumo_adapter import SumoAdapter
from simulation.metrics import get_agent_metrics

def run_simulation(topology_path, sumo_cfg, sumo_bin, decision_interval, provider, model):
    
    # Inizializzazione TrafficAgent con le opzioni scelte
    print(f"🧠 Inizializzazione Agent ({provider})...")
    agent = TrafficAgent(topology_path, provider=provider, model_name=model)

    print(f"✅ Agente {agent.id} pronto per {len(agent.topo['graph'])} incroci.")

    # Avvio simulazione SUMO -> ogni decision_interval viene interrogato l'agent
    print("🚗 Avvio simulazione SUMO...")
    adapter = SumoAdapter(sumo_bin, sumo_cfg)
    adapter.start(use_gui=True, delay="200")

    step = 0
    print("--- SIMULAZIONE AVVIATA ---")

    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            adapter.step()
            
            # Momento decisionale da parte dell'agent
            if step > 0 and step % decision_interval == 0:
                print(f"\n⏱️ [Step {step}] Analisi in corso...")
                
                # Estrazione dei dati dalla simulazione
                current_metrics = get_agent_metrics(agent.topo, adapter)
                
                # Prompting all'agent con le metriche raccolte e restituzione della risposta
                agent.decide(current_metrics)

            step += 1
            
    except traci.exceptions.FatalTraCIError:
        print("Simulazione interrotta.")
    finally:
        adapter.close()
        print("🛑 Simulazione terminata.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Traffic Agent AI - Core Loop")
    parser.add_argument("--topology", required=True, help="Percorso del file topology.json")
    parser.add_argument("--sumo_cfg", required=True, help="Percorso file .sumocfg")
    parser.add_argument("--sumo_bin", default="sumo-gui", help="Eseguibile SUMO")
    parser.add_argument("--decision_interval", type=int, default=60, help="Frequenza decisionale")
    parser.add_argument("--provider", choices=["local", "cloud"], default="cloud", help="Scegli se usare LM Studio (local) o Gemini (cloud)")
    parser.add_argument("--model", default="gemini-2.5-pro", choices=["gemini-2.5-pro", "vertex_ai/mistral-small-2503"], help="Nome del modello cloud")
    
    args = parser.parse_args()
    run_simulation(args.topology, args.sumo_cfg, args.sumo_bin, args.interval, args.provider, args.model)