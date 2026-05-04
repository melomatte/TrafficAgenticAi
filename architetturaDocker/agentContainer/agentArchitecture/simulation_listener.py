import os
import glob
import json
import asyncio

from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List

from agent import TrafficAgent
from orchestrator import Orchestrator

TOPOLOGIES_DIR = os.getenv("TOPOLOGIES_DIR", "/app/agentArchitecture/agent_topologies")
MODEL_NAME = os.getenv("MODEL_NAME")
PROVIDER = os.getenv("PROVIDER")
HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "5"))


def get_directive_for_agent(global_directive, agent_id):
    if not global_directive:
        return None

    for directive in global_directive.get("directives", []):
        if directive.get("target_agent") == agent_id:
            return directive

    return None


class SumoTrigger(BaseModel):
    step: int
    simulation_id: str


class SumoListener:

    def __init__(self, provider: str, model_name: str, agents_dir: str):
        self.provider = provider
        self.model_name = model_name
        self.agents_dir = agents_dir
        self.agents: List[TrafficAgent] = []
        self.global_orch = Orchestrator(model_name=model_name, provider=provider)
        self.global_directive = None

        # finestra storica degli ultimi N vettori agenti
        self.history_window = []
        self.history_size = HISTORY_SIZE

    async def __aenter__(self):
        print(f"[SUMO LISTENER] 🔌 Inizializzazione agenti da {self.agents_dir}")

        topology_files = glob.glob(os.path.join(self.agents_dir, "*_topology.json"))

        if not topology_files:
            print(f"⚠️ Nessun file topologia trovato in {self.agents_dir}")

        for filepath in topology_files:
            filename = os.path.basename(filepath)
            agent_id = filename.replace("_topology.json", "")

            agent = TrafficAgent(
                agent_id=agent_id,
                topology_file=filepath,
                model_name=self.model_name,
                provider=self.provider
            )

            self.agents.append(agent)
            print(f"   🤖 Agente [{agent_id}] inizializzato.")

        print("[SUMO LISTENER] 🌐 Apertura connessioni MCP agenti")
        await asyncio.gather(*[agent.__aenter__() for agent in self.agents])

        print("[SUMO LISTENER] 🌐 Apertura connessione MCP orchestratore")
        await self.global_orch.__aenter__()

        print(f"[SUMO LISTENER] ✅ Sistema pronto. {len(self.agents)} agenti attivi.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("[SUMO LISTENER] 🔌 Chiusura connessioni MCP agent")

        await asyncio.gather(*[
            agent.__aexit__(exc_type, exc_val, exc_tb)
            for agent in self.agents
        ])

        print("[SUMO LISTENER] 🌐 Chiusura connessione MCP orchestratore")
        await self.global_orch.__aexit__(exc_type, exc_val, exc_tb)

        print("[SUMO LISTENER] 🛑 Spegnimento completato.")

    async def workflow(self, step: int):
        print(f"\n[SUMO LISTENER] ⏱️ Step {step} - avvio workflow\n")

        if not self.agents:
            print("[SUMO LISTENER] ⚠️ Nessun agente configurato.")
            return

        print(f"\n[SUMO LISTENER] Avvio lavoro di {len(self.agents)} agent per lo step {step}")

        tasks = [
            agent.decide(
                step=step,
                global_directive=get_directive_for_agent(self.global_directive, agent.id)
            )
            for agent in self.agents
        ]

        # Ricezione della risposta e stampa dell'operazione eseguita (se effettivamente è stata eseguita)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        print(f"\n[SUMO LISTENER] Fine lavoro dei {len(self.agents)} agent per lo step {step}")
    
        agent_outputs = []

        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                print(f"   ❌ Errore in {agent.id}: {result}")
                continue

            print(f"   ✅ {agent.id} completato.")
            
            actions = result.get("actions_taken", [])
            agent_outputs.append({
                "agent_id": agent.id,
                "zone": agent.id,
                "stress_index": result.get("stress_index", 0),
                "prompt_text": result.get("prompt_text", ""),
                "actions_taken": actions
            })

            # Stampa delle operazioni eseguite dall'agent (se effettivamente ha eseguito delle azioni)

            if actions:
                print(f"   ⚙️ Azioni intraprese dall'agente {agent.id}:")
                for action in actions:
                    tl_id = action.get("intersection_id")
                    policy = action.get("policy")
                    phase_index = action.get("phase_index_applied")

                    print(f"        🚦 {tl_id} → {policy} → fase {phase_index}")
            else:
                print(f"   💤 {agent.id} non ha ritenuto necessario cambiare alcuna fase.")

        print(f"\n[SUMO LISTENER] Inizio lavoro orchestratore per lo step {step}")
        print(f"\n[SUMO LISTENER] L'orchestratore deve lavorare i seguenti dati:\n")
        print(json.dumps(agent_outputs, indent=2, ensure_ascii=False))

        decision = self.global_orch.decide(
            agent_outputs=agent_outputs,
            step=step,
            history_size=HISTORY_SIZE
        )

        if asyncio.iscoroutine(decision):
            global_decision = await decision
        else:
            global_decision = decision

        print(f"\n[SUMO LISTENER] Fine lavoro dell'orchestratore per lo step {step}:\n")
        print(f"\n[SUMO LISTENER] Direttive globali prodotte:\n")
        print(json.dumps(global_decision, indent=2, ensure_ascii=False))

        # Setting delle nuove direttive globali
        self.global_directive = global_decision

        print(f"[SUMO LISTENER] 🏁 Workflow step {step} terminato.")

@asynccontextmanager
async def lifespan(app: FastAPI):

    async with SumoListener(
        agents_dir=TOPOLOGIES_DIR,
        model_name=MODEL_NAME,
        provider=PROVIDER
    ) as orch:
        print("[SUMO LISTENER] 🚀 Server pronto.")
        app.state.orch = orch
        yield

app = FastAPI(lifespan=lifespan)


@app.post("/trigger_step")
async def trigger_step(event: SumoTrigger, background_tasks: BackgroundTasks):
    background_tasks.add_task(app.state.orch.workflow, event.step)

    return {
        "status": "acknowledged",
        "message": f"Workflow for step {event.step} started in background"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)