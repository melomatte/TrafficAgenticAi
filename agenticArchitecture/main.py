import argparse
import traci
from agent import TrafficAgent
from simulation.sumo_adapter import SumoAdapter
from simulation.metrics import get_agent_metrics

def run_simulation(topology_path, sumo_cfg, sumo_bin, decision_interval):
    
    # Inizializzazione dell'agent
    print("🧠 Inizializzazione Agent...")
    agent = TrafficAgent(topology_path)
    print(f"✅ Agente {agent.id} pronto per {len(agent.topo['intersections'])} incroci.")

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
                decisione_json = agent.decide(current_metrics)
                
                if decisione_json.get("action") != "error":
                    print("✅ DECISIONE PRESA:")
                    print(f"  ➡️ AZIONE:      {decisione_json.get('action')}")
                    print(f"  ➡️ INCROCIO:    {decisione_json.get('intersection_id')}")
                    print(f"  ➡️ POLICY:      {decisione_json.get('policy')}")
                    print(f"  ➡️ MOTIVAZIONE: {decisione_json.get('reasoning')}")
                else:
                    print("⚠️ L'agente ha saltato il turno per un errore di ragionamento.")

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
    parser.add_argument("--interval", type=int, default=60, help="Frequenza decisionale")
    
    args = parser.parse_args()
    run_simulation(args.topology, args.sumo_cfg, args.sumo_bin, args.interval)