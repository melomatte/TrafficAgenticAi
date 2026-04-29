import json

from llm_connector import AgentConnector
from agent.agent_policies import PROMPT_MCP
from fastmcp import Client

# Parametri per evitare looping e hallucination
MAX_ITERATIONS = 5
REQUIRED_TOOLS = {"compute_stress_index"}


class TrafficAgent:

    def __init__(self, agent_id: str, topology_file: str, mcp_url="http://mcp_server:8080", model_name="gemini-2.5-pro", provider="cloud"):
        self.id = f"[TrafficAgent - {agent_id}]"
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
    
    def _extract_intersections(self) -> list[str]:
        topo_intersections = []
        for line in self.topology.get("graph", []):
            if ":" in line:
                inter_id = line.split(":")[0].strip()
                topo_intersections.append(inter_id)
        return topo_intersections

    async def decide(self, step):
        if not self._mcp_client:
            raise RuntimeError(f"[{self.id}] Client MCP non inizializzato. ")

        print(f"\n🔮 [{self.id}] Inizio ciclo autonomo per step {step}...")

        chat = self.connector.create_agentic_chat(
            system_instruction=self.prompt,
            openai_tools=self.openai_tools
        )

       # Il messaggio diventa un semplice "Trigger Event"
        initial_message = (
            "New simulation step triggered.\n"
            f"Current Step ID: {step}\n"
            "Please use your tools to evaluate the traffic and provide your final decision."
        )
        response = await chat.send_message(initial_message)

        # Controllo immediato: se l'LLM risponde in testo senza invocare tool, il workflow è fallito
        if not response.function_calls:
            print(f"⚠️ [{self.id}] L'LLM ha ignorato i tool e ha risposto subito in testo!")
            print(f"⚠️ [{self.id}] Testo dell'LLM: {response.text}")
            return []

        # 3. Loop agentico
        #
        # Comportamento atteso: il modello chiama i 3 tool in una o più iterazioni,
        # poi produce la predizione finale in testo puro (function_calls vuoto → uscita dal loop).
        #
        # Iterazione 1: function_calls = [log_session_event, get_session_history, retrieve]
        #     → esegui i 3 tool, manda i risultati al modello
        #     → il modello risponde con la predizione in testo
        # Iterazione 2: function_calls = []  → condizione while falsa, si esce
        #
        # In casi meno comuni il modello può chiamare i tool uno alla volta (una iterazione per tool),
        # per questo MAX_ITERATIONS è 7 e non 3.

        called_tools = set()
        iteration = 0

        while response.function_calls and iteration < MAX_ITERATIONS:
            iteration += 1
            tool_responses = []

            for function_call in response.function_calls:
                func_name = function_call.name
                args = function_call.args
                call_id = function_call.id 

                print(f"🤖 [{self.id}] Tool Calling (iter {iteration}): chiama '{func_name}'")
                called_tools.add(func_name)

                try:
                    tool_result = await self._execute_mcp_call(func_name, args)
                except Exception as e:
                    print(f"❌ [{self.id}] Errore MCP Tool '{func_name}': {e}")
                    tool_result = {"error": str(e)}

                # Il Connector formatta la risposta nel formato corretto per il provider attivo
                formatted_response = self.connector.format_tool_response(func_name, tool_result, call_id)
                tool_responses.append(formatted_response)

            response = await chat.send_message(tool_responses)

        # Verifica anti-loop
        if iteration >= MAX_ITERATIONS:
            print(f"⚠️ [{self.id}] Raggiunto il limite massimo di iterazioni ({MAX_ITERATIONS}). Loop interrotto.")

        # Verifica anti-hallucination: tutti i tool obbligatori devono essere stati chiamati
        missing_tools = REQUIRED_TOOLS - called_tools
        if missing_tools:
            print(f"⚠️ [{self.id}] Tool obbligatori non chiamati: {missing_tools}. Predizione inaffidabile, annullo.")
            return []

        # 4. Estrazione predizione finale
        raw_response = response.text
        if not raw_response:
            print(f"⚠️ [{self.id}] Risposta finale vuota.")
            return []

        print(f"✅ [{self.id}] Computazione eseguita:\n{raw_response}")
        return raw_response

    async def _execute_mcp_call(self, tool_name: str, args: dict):
        """Esegue la chiamata MCP riutilizzando la connessione SSE persistente."""
        result = await self._mcp_client.call_tool(tool_name, args)
        return str(result)