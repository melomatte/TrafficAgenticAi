import json
from llm_connector import AgentConnector
from agent.agent_policies import PROMPT_MCP
from fastmcp import Client
import os
from datetime import datetime

# Cartella dove vengono salvate le interazioni degli agent
LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Parametri per evitare looping e hallucination
MAX_ITERATIONS = 5
REQUIRED_TOOLS = {"compute_stress_index"}


class TrafficAgent:

    def __init__(self, agent_id: str, topology_file: str, mcp_url="http://mcp_server:8080", model_name="gemini-2.5-pro", provider="cloud"):
        self.id = f"TrafficAgent-{agent_id}"
        # Lettura del file della topologia per vedere gli incroci gestiti dall'agent
        with open(topology_file, "r") as f:
            self.topology = json.load(f)
        self.managed_intersections = self._extract_intersections()
        self.connector = AgentConnector(agent_name=self.id, provider=provider, model_name=model_name)
        self.mcp_url = mcp_url
        self.prompt = PROMPT_MCP.format(managed_intersections=self.managed_intersections)
        self.openai_tools = self._define_tools()
        # Client MCP inizializzato in __aenter__, None finché l'agente non è attivo
        self._mcp_client: Client | None = None

    # --- Gestione ciclo di vita del client MCP ---

    async def __aenter__(self):
        """Apre la connessione SSE una sola volta. Chiamato automaticamente da 'async with'."""
        endpoint = f"{self.mcp_url}/sse"
        print(f"🔌 [{self.id}] Apertura connessione SSE persistente verso {endpoint}...")
        self._mcp_client = Client(endpoint)
        await self._mcp_client.__aenter__()
        print(f"✅ [{self.id}] Connessione SSE aperta con successo.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Chiude la connessione SSE. Chiamato automaticamente da 'async with' anche in caso di eccezione."""
        if self._mcp_client:
            print(f"🔌 [{self.id}] Chiusura connessione SSE persistente...")
            await self._mcp_client.__aexit__(exc_type, exc_val, exc_tb)
            self._mcp_client = None

    # --- Definizione tools MCP ---

    def _define_tools(self):
        """Definisce il JSON Schema dei tool per l'LLM."""
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "compute_stress_index",
                    "description": "Compute the stress level (0.0-100.0) of the intersections you manage.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tls_ids": {
                                "type": "array", 
                                "items": {"type": "string"}
                            },
                        },
                        "required": ["tls_ids"]
                    }
                }
            }
        ]
        return openai_tools
    
    # --- Definizione funzioni di utilità per l'agent ---

    def _log_interaction(self, step, prompt, response):
        filename = f"{LOG_DIR}/{self.id}.log"

        with open(filename, "a", encoding="utf-8") as f:

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"START LOGGING STEP: {step} | TIME: {datetime.now()}\n")
            f.write("=" * 80 + "\n")
   
            f.write("PROMPT TO LLM :\n\n")
            f.write(prompt)
            f.write("-" * 80 + "\n")

            f.write("RESPONSE RECEIVED:\n\n")
            f.write(str(response) + "\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"FINISH LOGGING: {step}\n")
            f.write("=" * 80 + "\n")
    
    def _extract_intersections(self) -> list[str]:
        topo_intersections = []
        for line in self.topology.get("graph", []):
            if ":" in line:
                inter_id = line.split(":")[0].strip()
                topo_intersections.append(inter_id)
        return topo_intersections
    
    # --- Loop agentico dei TrafficAgent ---
    """
    L'agent entra in azione ogni volta che il simulation_listener è stato triggerato dalla simulazione sumo.
    Per iniziare il loop agentico (guidato dalla system_instruction -> sempre uguale e definita nelle policy)
    viene dato all'agent un messaggio iniziale del tipo:
        Current Step ID: NUMERO_STEP
        Global directive: DIRETTIVA_GLOBALE_ORCHESTRATORE
    Questo messaggio iniziale avvia la system instruction dell'agent che, seguendo il suo worflow, ragiona su quali
    tool chiamare in una o più interazioni. Esempio di function_call riceve dall'agent:

        Iterazione 1: function_calls = [compute_stress_index]
            → esegui il tool, manda i risultati al modello
            → il modello risponde con la predizione in testo
        Iterazione 2: function_calls = []  → condizione while falsa, si esce
        
    In casi meno comuni il modello può chiamare i tool uno alla volta (una iterazione per tool),
    per questo MAX_ITERATIONS deve essere impostato ad un numero superiore ai tool che ci si aspetta che vengano chiamati
    """

    async def decide(self, step, global_directive=None):
        if not self._mcp_client:
            raise RuntimeError(f"[{self.id}] Client MCP non inizializzato.")

        print(f"\n🔮 [{self.id}] Inizio ciclo autonomo per step {step}...")

        # Conversione della direttiva globale dell'orchestratore in formato testuale
        directive_text = json.dumps(global_directive,
                                    ensure_ascii=False) if global_directive else "No global directive yet."

        chat = self.connector.create_agentic_chat(
            system_instruction=self.prompt,
            openai_tools=self.openai_tools
        )

        # Invio del messaggi iniziale per innescare ragionamento agent 
        initial_message = (
            "New simulation step triggered.\n"
            f"Current Step ID: {step}\n"
            f"Global directive: {directive_text}"
        )

        response = await chat.send_message(initial_message)

        # Verifica dei tool da invocare
        if not response.function_calls:
            print(f"⚠️ [{self.id}] L'LLM ha ignorato i tool.")
            return {
                "stress_index": 0,
                "priority_score": 0,
                "prompt_text": "Tool call missing",
                "actions": []
            }

        # Loop agentico
        called_tools = set()
        iteration = 0
        last_stress = 0.0

        while response.function_calls and iteration < MAX_ITERATIONS:
            iteration += 1
            tool_responses = []

            for function_call in response.function_calls:
                func_name = function_call.name
                args = function_call.args
                call_id = function_call.id

                print(f"🤖 [{self.id}] Tool Calling: {func_name}")
                called_tools.add(func_name)

                try:
                    tool_result = await self._execute_mcp_call(func_name, args)

                    if func_name == "compute_stress_index":
                        try:
                            last_stress = float(tool_result)
                        except Exception:
                            last_stress = 0.0

                except Exception as e:
                    print(f"❌ [{self.id}] Errore MCP Tool '{func_name}': {e}")
                    tool_result = {"error": str(e)}

                formatted_response = self.connector.format_tool_response(
                    func_name,
                    tool_result,
                    call_id
                )
                tool_responses.append(formatted_response)

            response = await chat.send_message(tool_responses)

        missing_tools = REQUIRED_TOOLS - called_tools
        if missing_tools:
            print(f"⚠️ [{self.id}] Tool obbligatori non chiamati: {missing_tools}")
            return {
                "stress_index": 0,
                "priority_score": 0,
                "prompt_text": "Required tool missing",
                "actions": []
            }

        raw_response = response.text

        # Logging interazione con l'agent
        full_logged_prompt = (
            f"SYSTEM INSTRUCTION:\n{self.prompt}\n\n"
            f"EVENT TRIGGERED MESSAGE:\n{initial_message}"
        )
        self._log_interaction(step, full_logged_prompt, raw_response)

        # Parsing della risposta
        if not raw_response:
            return {
                "stress_index": last_stress,
                "priority_score": last_stress,
                "prompt_text": "Empty model response",
                "actions": []
            }

        raw_response = raw_response.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(raw_response)

            parsed.setdefault("stress_index", last_stress)
            parsed.setdefault("priority_score", last_stress)
            parsed.setdefault("prompt_text", f"Stress index: {last_stress}")
            parsed.setdefault("actions", [])

            return parsed

        except Exception:
            print(f"⚠️ [{self.id}] JSON non valido:\n{raw_response}")
            return {
                "stress_index": last_stress,
                "priority_score": last_stress,
                "prompt_text": raw_response[:200],
                "actions": []
            }

    async def _execute_mcp_call(self, tool_name: str, args: dict):
        """Esegue la chiamata MCP riutilizzando la connessione SSE persistente."""
        result = await self._mcp_client.call_tool(tool_name, args)
        return str(result)