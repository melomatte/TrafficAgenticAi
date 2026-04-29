import os
import glob
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List
from agent import TrafficAgent
from orchestrator import Orchestrator

# --- CONFIGURAZIONI ---
TOPOLOGIES_DIR = os.getenv("TOPOLOGIES_DIR", "/app/agentArchitecture/agent_topologies")
MODEL_NAME = os.getenv("MODEL_NAME")
PROVIDER = os.getenv("PROVIDER")

# Modello per il trigger ricevuto dal container sumo_simulation
class SumoTrigger(BaseModel):
    step: int
    simulation_id: str

class SumoListener:

    def __init__(self, provider: str, model_name: str, agents_dir: str):
        self.provider = provider
        self.model_name = model_name
        self.agents_dir = agents_dir
        self.agents: List[TrafficAgent] = []
        #self.global_orch = Orchestrator(model_name=model_name, provider=provider)

    async def __aenter__(self):
        print(f"[SUMO LISTENER] 🔌 Inizializzazione TrafficAgent con topologie presenti nella cartella {self.agents_dir}")
        
        # Estrapolazione file topologici
        search_pattern = os.path.join(self.agents_dir, "*_topology.json")
        topology_files = glob.glob(search_pattern)

        if not topology_files:
            print(f"⚠️ ATTENZIONE: Nessun file topologia trovato in {self.agents_dir}")
        
        # Per ogni file trovato viene inizializzato un TrafficAgent
        for filepath in topology_files:
            # Estraiamo l'ID dell'agente dal nome del file (es: "agent_0" da "agent_0_topology.json")
            filename = os.path.basename(filepath)
            agent_id = filename.replace("_topology.json", "")
            
            agent = TrafficAgent(
                agent_id=agent_id,
                topology_file=filepath,
                model_name=self.model_name,
                provider=self.provider
            )

            self.agents.append(agent)
            print(f"   🤖 Agente [{agent_id}] inizializzato con successo.")
        
        # Avviamo le connessioni SSE per MCP in parallelo
        print(f"[SUMO LISTENER] 🌐 Avvio connessioni SSE degli agent in parallelo")
        connect_tasks = [agent.__aenter__() for agent in self.agents]
        await asyncio.gather(*connect_tasks)
        print(f"[SUMO LISTENER] ✅ Tutte le connessioni SSE aperte correttamente")
        
        # Da aggiungere aperta connessione SSE per MCP dell'orchestratore

        print(f"[SUMO LISTENER] ✅ Sistema pronto. {len(self.agents)} agenti attivi.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("[SUMO LISTENER] 🔌 Chiusura connessioni MCP (in parallelo) in corso")
        disconnect_tasks = [agent.__aexit__(exc_type, exc_val, exc_tb) for agent in self.agents]
        await asyncio.gather(*disconnect_tasks)
        # Da aggiungere orchestratore
        print("[SUMO LISTENER] 🛑 Spegnimento completato.")

    async def workflow(self, step: int):
        """
        Workflow asincrono: fa decidere tutti gli agenti in PARALLELO.
        """
        print(f"\n[SUMO LISTENER] ⏱️ Inizio elaborazione Step {step} per {len(self.agents)} agenti")
        
        if not self.agents:
            print("[SUMO LISTENER] ⚠️ Nessun agente configurato per agire.")
            return

        # Prepariamo la lista dei task asincroni (ovvero loop agentico) per mandarli in esecuzione contemporaneamente
        # return_exceptions=True evita che se un agente va in errore, si blocchino anche gli altri
        tasks = []
        for agent in self.agents:
            tasks.append(agent.decide(step=step))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Controllo degli esiti
        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                print(f"   ❌ Errore critico in {agent.id}: {result}")
            else:
                print(f"   ✅ {agent.id} ha completato il suo turno.")
            
        # Da aggiungere logica orchestratore

        print(f"[SUMO LISTENER] 🏁 Elaborazione Step {step} terminata.")

# --- Lifespan: gestisce startup e shutdown dell'intera applicazione ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inizializziamo l'orchestratore usando le variabili d'ambiente
    async with SumoListener(agents_dir=TOPOLOGIES_DIR, model_name=MODEL_NAME, provider=PROVIDER) as orch:
        print("[SUMO LISTENER] 🚀 Server pronto a ricevere eventi.")
        app.state.orch = orch
        yield

app = FastAPI(lifespan=lifespan)

@app.post("/trigger_step")
async def trigger_step(event: SumoTrigger, background_tasks: BackgroundTasks):
    """
    Riceve il trigger da SUMO, avvia il workflow in background e risponde subito -> comportamento per non bloccare simulazione
    """
    # Aggiunge il workflow alla coda asincrona di FastAPI
    background_tasks.add_task(app.state.orch.workflow, event.step)
    
    return {
        "status": "acknowledged", 
        "message": f"Workflow for step {event.step} started in background"
    }

# Permette di lanciare lo script direttamente per fare test fuori da Docker
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)