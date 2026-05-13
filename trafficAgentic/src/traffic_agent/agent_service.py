import os
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
from agent_core import TrafficAgent
from prometheus_fastapi_instrumentator import Instrumentator # <-- 1. AGGIUNGI QUESTO IMPORT

# Configurazioni da ambiente
AGENT_ID = os.getenv("AGENT_ID")
MODEL_NAME = os.getenv("MODEL_NAME")
PROVIDER = os.getenv("PROVIDER")
BACKEND_API_URL = os.getenv("BACKEND_API_URL")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL")

# NUOVO: L'URL dell'orchestratore a cui l'agente deve inviare i risultati.
# In K8s sarà qualcosa tipo "http://orchestrator-service.default.svc.cluster.local:8080"
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://host.minikube.internal:8080")

class EvaluatePayload(BaseModel):
    step: int
    global_directive: Optional[Dict[str, Any]] = None

class AgentListener:
    def __init__(self, agent_id: str, provider: str, model_name: str):
        self.agent_id = agent_id
        self.provider = provider
        self.model_name = model_name
        self.http_client = httpx.AsyncClient(timeout=60.0) 
            
    # --------------------------------------
    # Funzioni per gestione connessioni
    # --------------------------------------

    async def __aenter__(self):
        print(f"[AgentListener-{self.agent_id}] 🔌 Inizializzazione agenti da topologia in backend")
        topology = await self.fetch_topology_from_backend()
        self.agent = TrafficAgent(agent_id=self.agent_id, topology=topology, mcp_url=MCP_SERVER_URL, provider=self.provider, model_name=self.model_name)
        print(f"[AgentListener-{self.agent_id}] 🌐 Apertura connessione MCP agente")
        await self.agent.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print(f"[AgentListener-{self.agent_id}] 🌐 Chiusura connessione MCP e HTTP agent")
        await self.agent.__aexit__(exc_type, exc_val, exc_tb)
        await self.http_client.aclose()
        print(f"[AgentListener-{self.agent_id}] 🛑 Spegnimento completato.")
    
    # --------------------------------------
    # Funzioni mappate sul server
    # --------------------------------------

    async def evaluate_and_push(self, step: int, global_directive: dict):
        print(f"\n[AgentListener-{self.agent_id}] ⏱️ Step {step} - Inizio reasoning...")
        
        try:
            # 1. Loop agentico
            result = await self.agent.decide(step=step, global_directive=global_directive)
            print(f"[AgentListener-{self.agent_id}] ⏱️ Step {step} - Fine reasoning. Invio risultati all'orchestratore...")

            # 2. Prepara il payload per l'orchestratore
            payload = {
                "step": step,
                "agent_id": self.agent_id,
                "result": result
            }

            # 3. Invia i risultati all'orchestratore
            resp = await self.http_client.post(f"{ORCHESTRATOR_URL}/stress_comunication", json=payload)
            resp.raise_for_status()
            print(f"[AgentListener-{self.agent_id}] ✅ Dati per Step {step} consegnati all'orchestratore.")

        except Exception as e:
            print(f"[AgentListener-{self.agent_id}] ❌ Errore durante reasoning o invio dati: {e}")

    async def fetch_topology_from_backend(self) -> dict:
        """Scarica la topologia dal backend (Single Source of Truth)."""
        try:
            response = await self.http_client.get(f"{BACKEND_API_URL}/topology/{self.agent_id}")

            # Ricezione della nuova topologia e aggiornamento dell'agent    
            if response.status_code == 200:
                new_topo = response.json()
                # Questo if distingue due casi: fase di recupero iniziale della topologia e fase di aggiornamento
                if hasattr(self, 'agent'):
                    self.agent.change_topology(new_topo)

                print(f"Topologia scaricata con {len(new_topo.get('intersections', []))} incroci.")
                return new_topo
            else:
                print(f"Errore HTTP: {response.status_code} - {response.text}")

        except httpx.HTTPError as e:
            print(f"[AgentListener-{self.agent_id}] ❌ Errore download topologia: {e}")
            raise e

# --- FastAPI App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AgentListener(AGENT_ID, PROVIDER, MODEL_NAME) as agent_server:
        app.state.agent_server = agent_server
        yield

app = FastAPI(lifespan=lifespan)

Instrumentator().instrument(app).expose(app)

# --- ROTTA 1: Esecuzione Step ---
# MODIFICATO: Usa BackgroundTasks per non bloccare la risposta HTTP
@app.post("/evaluate")
async def evaluate_step(payload: EvaluatePayload, background_tasks: BackgroundTasks):
    try:
        # Mettiamo il lavoro pesante in background
        background_tasks.add_task(
            app.state.agent_server.evaluate_and_push,
            step=payload.step,
            global_directive=payload.global_directive
        )
        # Rispondiamo immediatamente all'Orchestratore per sbloccarlo
        return {
            "status": "processing", 
            "message": f"Step {payload.step} ricevuto. Reasoning avviato in background."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTTA 2: Aggiornamento Topologia ---
@app.post("/reload_topology")
async def reload_topology():
    try:
        new_topo = await app.state.agent_server.fetch_topology_from_backend()
        return {"status": "success", "message": "Topologia ricaricata", "intersections": len(new_topo.get('intersections', []))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "agent_id": AGENT_ID}

if __name__ == "__main__":
    import uvicorn
    # Imposta la porta coerente con i tuoi manifest K8s (solitamente 8080 per gli agenti)
    uvicorn.run(app, host="0.0.0.0", port=8080)