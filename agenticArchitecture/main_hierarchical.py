"""
Entry point gerarchico:
- avvia SUMO
- carica automaticamente un agente per ogni file *_topology.json
- raccoglie metriche locali
- fa decidere gli agenti usando anche la direttiva globale precedente
- invia gli output all'orchestratore
- aggiorna la direttiva globale per il ciclo successivo

Comando per l'esecuzione:
    python3 agenticArchitecture/main_hierarchical.py --sumo_cfg urbanNetworks/2cross/sim.sumocfg --sumo_bin /usr/bin/sumo --agents_dir urbanNetworks/2cross/data/agent_topologies/
"""

import argparse
import glob
import json
import os
import traci
from agenticArchitecture.agent.agent_core import TrafficAgent
from agenticArchitecture.orchestrator.orchestrator_core import GlobalOrchestrator
from agenticArchitecture.simulation.sumo_adapter import SumoAdapter


def load_agents_from_dir(agents_dir, provider, model):
    agents = []

    pattern = os.path.join(agents_dir, "*_topology.json")
    topology_files = sorted(glob.glob(pattern))

    if not topology_files:
        raise FileNotFoundError(f"Nessun file *_topology.json trovato in: {agents_dir}")

    for topo_path in topology_files:
        agent = TrafficAgent(
            topology_path=topo_path,
            model_name=model,
            provider=provider
        )
        agent.zone = "unknown"
        print(f"✅ Agente {agent.id} pronto per {len(agent.topo['graph'])} incroci.")
        agents.append(agent)

    return agents


def compute_priority_score(local_metrics):
    total_queue = 0
    total_vehicles = 0

    for inter in local_metrics.get("intersections", []):
        total_queue += inter.get("total_queue", 0)
        total_vehicles += inter.get("total_vehicles", 0)

    return round(total_queue * 2 + total_vehicles * 0.5, 2)


def extract_intersections_from_topology(agent):
    topo_intersections = []

    for line in agent.topo.get("graph", []):
        if ":" in line:
            inter_id = line.split(":")[0].strip()
            topo_intersections.append(inter_id)

    return topo_intersections


def run_simulation(agents_dir, sumo_cfg, sumo_bin, decision_interval, provider, model):
    
    # Recupero informazioni agent e loro topologie
    print("📂 Agents loaded from:", args.agents_dir)
    agents = load_agents_from_dir(agents_dir, provider, model)

    # Inizializzazione orchestratore
    orchestrator = GlobalOrchestrator(model_name=args.model, provider=args.provider)
    print(f"✅ Orchestratore pronto per coordinare {len(agents)} agent")

    # Direttiva globale iniziale neutra
    global_directive = {
        "action": "hold_current",
        "target_agent": None,
        "reasoning": "Initial neutral directive"
    }

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

                print(f"\n⏱️ [Step {step}] Hierarchical decision...")

                print("\n🧭 GLOBAL DIRECTIVE IN USE:")
                print(json.dumps(global_directive, indent=2, ensure_ascii=False))

                agent_outputs = []

                for agent in agents:
                    topo_intersections = extract_intersections_from_topology(agent)
                    local_metrics = adapter.get_cluster_metrics(topo_intersections)
                    priority_score = compute_priority_score(local_metrics)

                    enriched_metrics = {
                        "zone": getattr(agent, "zone", "unknown"),
                        "priority_score": priority_score,
                        "intersections": local_metrics["intersections"]
                    }

                    # Gli agenti usano la direttiva globale del ciclo precedente
                    decision = agent.decide(enriched_metrics, global_directive=global_directive)

                    actions = decision if decision else []
                    if isinstance(actions, dict):
                        actions = [actions]

                    agent_outputs.append({
                        "agent_id": agent.id,
                        "zone": getattr(agent, "zone", "unknown"),
                        "priority_score": priority_score,
                        "actions": actions
                    })

                print("\n📡 OUTPUT AGENTI:")
                print(json.dumps(agent_outputs, indent=2, ensure_ascii=False))

                # L'orchestratore legge gli output correnti e produce la direttiva per il ciclo successivo
                global_decision = orchestrator.decide(agent_outputs)

                print("\n🧭 DECISIONE GLOBALE:")
                print(json.dumps(global_decision, indent=2, ensure_ascii=False))

                global_directive = global_decision
            
            step += 1

    except traci.exceptions.FatalTraCIError:
        print("Simulazione interrotta.")
    finally:
        adapter.close()
        print("🛑 Simulazione terminata.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sumo_cfg", required=True, help="Percorso file .sumocfg")
    parser.add_argument("--sumo_bin", default="sumo-gui", help="Eseguibile SUMO")
    parser.add_argument("--agents_dir", required=True)
    parser.add_argument("--provider", choices=["local", "cloud"], default="cloud", help="Scegli se usare LM Studio (local) o Gemini (cloud)")
    parser.add_argument("--model", default="gemini-2.5-pro", choices=["gemini-2.5-pro", "vertex_ai/mistral-small-2503"], help="Nome del modello cloud")
    parser.add_argument("--decision_interval", type=int, default=60)
    args = parser.parse_args()

    run_simulation(args.agents_dir, args.sumo_cfg, args.sumo_bin, args.decision_interval, args.provider, args.model)