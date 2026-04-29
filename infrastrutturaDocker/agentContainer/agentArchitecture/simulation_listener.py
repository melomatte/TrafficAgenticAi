import os
import glob
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List
from agentArchitecture.agent.agent_core import TrafficAgent
from agentArchitecture.orchestrator.orchestrator_core import Orchestrator

# --- CONFIGURAZIONI ---
# Leggiamo la cartella delle topologie dalle variabili d'ambiente (con fallback)
TOPOLOGIES_DIR = os.getenv("TOPOLOGIES_DIR", "/app/agent_topologies")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.0-flash")
PROVIDER = os.getenv("PROVIDER", "cloud")

# Modello per il trigger ricevuto dal container SUMO
class SumoTrigger(BaseModel):
    step: int
    simulation_id: str

class TrafficOrchestrator:
    def __init__(self, agents_dir: str, model_name: str, provider: str):
        self.agents_dir = agents_dir
        self.model_name = model_name
        self.provider = provider
        self.agents: List[TrafficAgent] = []
        self.global_orch = Orchestrator(model_name=model_name, provider=provider)
        self.global_directive = {"action": "hold_current", "reasoning": "Initial state"}

    async def __aenter__(self):
        print(f"[ORCHESTRATOR] 🔌 Inizializzazione sistema nella cartella: {self.agents_dir}")
        
        # 1. Ricerca dinamica dei file di topologia
        search_pattern = os.path.join(self.agents_dir, "*_topology.json")
        topology_files = glob.glob(search_pattern)

        if not topology_files:
            print(f"⚠️ ATTENZIONE: Nessun file topologia trovato in {self.agents_dir}")
        
        # 2. Inizializzazione di un agente per ogni file trovato
        for filepath in topology_files:
            # Estraiamo l'ID dell'agente dal nome del file (es: "agent_0" da "agent_0_topology.json")
            filename = os.path.basename(filepath)
            agent_id = filename.replace("_topology.json", "")
            
            # NOTA: Assicurati che TrafficAgent accetti questi parametri nel suo __init__
            agent = TrafficAgent(
                agent_id=agent_id,
                topology_file=filepath,
                model_name=self.model_name,
                provider=self.provider
            )
            self.agents.append(agent)
            print(f"   🤖 Agente [{agent_id}] inizializzato con successo.")

        print(f"[ORCHESTRATOR] ✅ Sistema pronto. {len(self.agents)} agenti attivi.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("[ORCHESTRATOR] 🔌 Chiusura connessioni MCP in corso...")
        # Qui potrai aggiungere eventuale logica di pulizia delle sessioni
        print("[ORCHESTRATOR] 🛑 Spegnimento completato.")

    async def run_workflow(self, step: int):
        """
        Workflow asincrono: fa decidere tutti gli agenti in PARALLELO.
        """
        print(f"\n[WORKFLOW] ⏱️ Inizio elaborazione Step {step} per {len(self.agents)} agenti...")
        
        if not self.agents:
            print("[WORKFLOW] ⚠️ Nessun agente configurato per agire.")
            return

        # Prepariamo la lista dei task asincroni
        tasks = []
        for agent in self.agents:
            # NOTA: Sostituisci 'evaluate_and_act' con il nome del metodo reale 
            # che avvia il ragionamento dell'LLM all'interno della tua classe TrafficAgent
            tasks.append(agent.evaluate_and_act(step=step))

        # Eseguiamo tutti gli agenti contemporaneamente
        # return_exceptions=True evita che se un agente va in errore, si blocchino anche gli altri
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Controllo degli esiti
        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                print(f"   ❌ Errore critico in {agent.agent_id}: {result}")
            else:
                print(f"   ✅ {agent.agent_id} ha completato il suo turno.")

        print(f"[WORKFLOW] 🏁 Elaborazione Step {step} terminata.")

# --- Gestione Lifespan di FastAPI ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inizializziamo l'orchestratore usando le variabili d'ambiente
    async with TrafficOrchestrator(
        agents_dir=TOPOLOGIES_DIR, 
        model_name=MODEL_NAME, 
        provider=PROVIDER
    ) as orch:
        app.state.orch = orch
        yield

app = FastAPI(lifespan=lifespan)

@app.post("/trigger_step")
async def trigger_step(event: SumoTrigger, background_tasks: BackgroundTasks):
    """
    Riceve il trigger da SUMO, avvia il workflow in background e risponde subito.
    """
    # Aggiunge il workflow alla coda asincrona di FastAPI
    background_tasks.add_task(app.state.orch.run_workflow, event.step)
    
    return {
        "status": "acknowledged", 
        "message": f"Workflow for step {event.step} started in background"
    }

if __name__ == "__main__":
    import uvicorn
    # Permette di lanciare lo script direttamente per fare test fuori da Docker
    uvicorn.run(app, host="0.0.0.0", port=8000)