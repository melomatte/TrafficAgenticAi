import os
import glob
import json
import asyncio
import shutil

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




def reset_logs():
    log_dir = "logs"

    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)   # elimina TUTTO (anche sottocartelle)

    os.makedirs(log_dir, exist_ok=True)  # ricrea vuota

def policy_to_phase(policy: str) -> int:
    return {
        "PRIORITY_MAIN": 0,
        "FAIR_BALANCE": 1,
        "CLEAR_QUEUES": 2,
    }.get(policy, 1)


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

        print(f"[SUMO LISTENER] ✅ Sistema pronto. {len(self.agents)} agenti attivi.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("[SUMO LISTENER] 🔌 Chiusura connessioni MCP")

        await asyncio.gather(*[
            agent.__aexit__(exc_type, exc_val, exc_tb)
            for agent in self.agents
        ])

        print("[SUMO LISTENER] 🛑 Spegnimento completato.")

    async def workflow(self, step: int):
        print(f"\n[SUMO LISTENER] ⏱️ Step {step} - avvio workflow")

        if not self.agents:
            print("[SUMO LISTENER] ⚠️ Nessun agente configurato.")
            return

        tasks = [
            agent.decide(
                step=step,
                global_directive=get_directive_for_agent(self.global_directive, agent.id)
            )
            for agent in self.agents
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_outputs = []

        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                print(f"   ❌ Errore in {agent.id}: {result}")
                continue

            print(f"   ✅ {agent.id} completato.")

            actions = result.get("actions", [])

            agent_outputs.append({
                "agent_id": agent.id,
                "zone": agent.id,
                "stress_index": result.get("stress_index", 0),
                "priority_score": result.get("priority_score", 0),
                "prompt_text": result.get("prompt_text", ""),
                "actions": actions
            })

            for action in actions:
                tl_id = action.get("intersection_id")
                policy = action.get("policy")

                if not tl_id or not policy:
                    continue

                phase_index = policy_to_phase(policy)

                mcp_result = await agent._mcp_client.call_tool(
                    "set_traffic_light",
                    {
                        "tl_id": tl_id,
                        "phase_index": phase_index
                    }
                )

                print(f"🚦 {tl_id} → {policy} → fase {phase_index} | MCP: {mcp_result}")


        if not agent_outputs:
            print("[SUMO LISTENER] ⚠️ Nessun output valido dagli agenti.")
            return

        print("\n📡 VETTORE CORRENTE AGENTI:")
        print(json.dumps(agent_outputs, indent=2, ensure_ascii=False))

        stress_vector = {
            out["agent_id"]: out["stress_index"]
            for out in agent_outputs
        }

        history_context = self.history_window[-self.history_size:]

        maybe_decision = self.global_orch.decide(
            current_vector=agent_outputs,  # JSON completo attuale
            history_vectors=history_context  # storico compatto
        )

        self.history_window.append(stress_vector)
        self.history_window = self.history_window[-self.history_size:]


        if asyncio.iscoroutine(maybe_decision):
            global_decision = await maybe_decision
        else:
            global_decision = maybe_decision

        print("\n🧭 DIRETTIVE GLOBALI:")
        print(json.dumps(global_decision, indent=2, ensure_ascii=False))

        self.global_directive = global_decision

        print(f"[SUMO LISTENER] 🏁 Step {step} terminato.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_logs()

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