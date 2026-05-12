import os
import asyncio
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from orchestrator_core import Orchestrator
from kubernetes import client, config

# Configurazioni da ambiente
AGENT_ID = os.getenv("AGENT_ID", "global-orchestrator")
MODEL_NAME = os.getenv("MODEL_NAME")
PROVIDER = os.getenv("PROVIDER")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL")
NAMESPACE = os.getenv("NAMESPACE", "default")
AGENT_LABEL = os.getenv("AGENT_LABEL", "app=traffic-agent")

class SumoTrigger(BaseModel):
    step: int
    simulation_id: str 

class AgentPayload(BaseModel):
    step: int
    agent_id: str 
    result: dict

class OrchestratorListener:
    def __init__(self, agent_id: str, provider: str, model_name: str):
        self.agent_id = agent_id
        self.provider = provider
        self.model_name = model_name
        self.global_orch = Orchestrator(mcp_url=MCP_SERVER_URL, model_name=model_name, provider=provider, history_size=5)
        self.global_directive = None

        self.http_client = httpx.AsyncClient(timeout=60.0) 
        self.k8s_api = None
        self.agents = []
        
        # Variabili per l'aggregazione
        self.step_results = {} 
        self.expected_per_step = {}
        self.sync_lock = asyncio.Lock()

    # --------------------------------------
    # Funzioni per gestione connessioni
    # --------------------------------------

    async def __aenter__(self):
        print("[OrchestratorListener] 🔌 Inizializzazione...")
        try:
            config.load_incluster_config()
            self.k8s_api = client.CoreV1Api()
            self.agents = self.get_active_agents()
        except Exception as e:
            print(f"[OrchestratorListener] ❌ Errore config K8s: {e}")

        print("[OrchestratorListener] 🚀 Apertura connessione MCP")
        await self.global_orch.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("[OrchestratorListener] 🚀 Chiusura connessione MCP")
        await self.global_orch.__aexit__(exc_type, exc_val, exc_tb)
        await self.http_client.aclose()

    # --------------------------------------
    # Funzioni di utility
    # --------------------------------------

    def get_active_agents(self):
        if not self.k8s_api:
            return []
        pods = self.k8s_api.list_namespaced_pod(NAMESPACE, label_selector=AGENT_LABEL)
        agents = []
        for pod in pods.items:
            if pod.status.phase == "Running" and pod.metadata.deletion_timestamp is None:
                name = pod.metadata.name
                endpoint = f"http://{name}.agent-service.{NAMESPACE}.svc.cluster.local:8080"
                agents.append({"id": name, "url": endpoint})
        return agents
        
    def get_directive_for_agent(self, agent_id):
        if not self.global_directive:
            return None
        for directive in self.global_directive.get("directives", []):
            if directive.get("target_agent") == agent_id:
                return directive
        return None

    # --------------------------------------
    # Gestione del Loop Infinito
    # --------------------------------------

    async def call_agent(self, agent, step):
        """Invia il segnale di "sveglia" all'agente."""
        try:
            directive = self.get_directive_for_agent(agent['id'])
            
            # Eseguiamo la chiamata HTTP. L'agente risponderà subito 'OK' e inizierà a 
            # calcolare in background. Quando finirà, chiamerà lui /stress_comunication
            resp = await self.http_client.post(
                f"{agent['url']}/evaluate",
                json={"step": step, "global_directive": directive}
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"   ❌ Fallimento trigger per agente {agent['id']}: {e}")
            return False

    async def trigger_all_agents(self, step: int):
        """Funzione helper per svegliare tutti gli agenti in parallelo."""
        print(f"\n[OrchestratorListener] 🚀 Avvio agenti per lo Step {step}...")
        self.agents = self.get_active_agents()
        await asyncio.gather(*(self.call_agent(a, step) for a in self.agents))

    async def start_agentic_looping(self, step: int, simulation_id: str):
        """Entry point iniziale chiamato da SUMO"""
        print(f"\n[OrchestratorListener] 🏁 SUMO ha innescato il loop agentico (Step {step}, Simulazione {simulation_id})")
        await self.trigger_all_agents(step)
        return len(self.agents)

    # --------------------------------------
    # Barriera di Sincronizzazione e Workflow
    # --------------------------------------

    async def process_agent_data(self, step: int, agent_id: str, result: dict):
        """Raccoglie i dati. Ritorna True solo quando TUTTI gli agenti hanno risposto."""
        async with self.sync_lock:

            # Alla prima richiesta viene scattato lo snapshot degli agenti attivi
            if step not in self.step_results:
                self.step_results[step] = {}
                self.agents = self.get_active_agents()
                self.expected_per_step[step] = {a['id'] for a in self.agents}
            
            # Si recuperano gli agenti attivi
            # Alcuni agenti potrebbero essere morti durante l'elaborazione -> in questo modo non vengono considerati
            current_active_agents = {a['id'] for a in self.get_active_agents()}
            self.expected_per_step[step] = self.expected_per_step[step].intersection(current_active_agents)
            
            # Salvataggio dei risultati e verifica di quelli mancanti
            self.step_results[step][agent_id] = result
            received_agent_ids = set(self.step_results[step].keys())
            missing_agents = self.expected_per_step[step] - received_agent_ids
            
            if len(missing_agents) > 0:
                return False, list(missing_agents)
                
            all_results = self.step_results.pop(step)
            self.expected_per_step.pop(step) 
            return True, all_results

    async def workflow(self, step: int, aggregated_results: dict):
        print(f"\n[OrchestratorListener] Inizio Workflow Step {step}")
        
        # 1. Formattiamo l'output aggregato
        agent_outputs = []
        for ag_id, res in aggregated_results.items():
             agent_outputs.append({
                "agent_id": ag_id,
                "zone": ag_id,
                "stress_index": res.get("stress_index", 0),
                "prompt_text": res.get("prompt_text", ""),
                "actions_taken": res.get("actions_taken", [])
            })

        # 2. Reasoning globale dell'orchestratore
        try:
            print("[ORCHESTRATOR] Calcolo della nuova strategia globale...")
            new_directive = await self.global_orch.decide(agent_outputs=agent_outputs, step=step)
            self.global_directive = new_directive
            print(f"[ORCHESTRATOR] Nuova direttiva in memoria calcolata.")
        except Exception as e:
            print(f"[ORCHESTRATOR] Errore durante decide(): {e}")

        # 3. IL LOOP CONTINUA: prepariamo e lanciamo il prossimo step
        next_step = step + 1
        print(f"[ORCHESTRATOR] ✅ Step {step} completato. Innesco automatico dello Step {next_step}...")
        
        # Lanciamo i trigger come task in background per non bloccare la risposta HTTP dell'ultimo agente
        asyncio.create_task(self.trigger_all_agents(next_step))
        
        return next_step


# --- FASTAPI APP ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with OrchestratorListener(agent_id=AGENT_ID, provider=PROVIDER, model_name=MODEL_NAME) as orch:
        app.state.orch = orch
        yield

app = FastAPI(lifespan=lifespan)

@app.post("/trigger_agentic")
async def trigger_agentic(payload: SumoTrigger):
    """
    1. SUMO chiama questo endpoint una volta sola.
    2. Da qui parte il loop infinito tra Orchestratore e Agenti.
    """
    try:
        active_count = await app.state.orch.start_agentic_looping(payload.step, payload.simulation_id)
        return {"status": "success", "message": f"Sistema innescato. Agenti attivi svegliati: {active_count}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stress_comunication")
async def stress_comunication(payload: AgentPayload):
    """
    Gli agenti inviano qui i loro risultati a fine calcolo. 
    L'orchestratore fa da barriera e, quando riceve l'ultimo, prosegue il loop.
    """
    try:
        is_complete, data = await app.state.orch.process_agent_data(
            payload.step, payload.agent_id, payload.result
        )

        if not is_complete:
            missing = data
            return {
                "status": "pending", 
                "message": f"Dato ricevuto da {payload.agent_id}. In attesa di: {missing}"
            }

        # Ultimo agent ha inviato i dati -> può partire worflow orchestratore
        next_step_num = await app.state.orch.workflow(payload.step, data)
        return {
            "status": "success", 
            "message": f"Ultimo dato ricevuto. Orchestratore avviato. Prossimo step {next_step_num} triggerato."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)