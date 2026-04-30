import json

from llm_connector import AgentConnector
from agent.agent_policies import PROMPT_MCP
from fastmcp import Client
import os
from datetime import datetime

LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)

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

    def _log_interaction(self, step, prompt, response):
        safe_id = self.id.replace("[", "").replace("]", "").replace(" ", "_")
        filename = f"{LOG_DIR}/{safe_id}.log"

        with open(filename, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"STEP: {step} | TIME: {datetime.now()}\n\n")
            f.write("PROMPT:\n")
            f.write(prompt + "\n\n")
            f.write("RESPONSE:\n")
            f.write(str(response) + "\n")

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

    async def decide(self, step, global_directive=None):
        if not self._mcp_client:
            raise RuntimeError(f"[{self.id}] Client MCP non inizializzato.")

        print(f"\n🔮 [{self.id}] Inizio ciclo autonomo per step {step}...")

        directive_text = json.dumps(global_directive,
                                    ensure_ascii=False) if global_directive else "No global directive yet."

        chat = self.connector.create_agentic_chat(
            system_instruction=self.prompt,
            openai_tools=self.openai_tools
        )

        initial_message = (
            "New simulation step triggered.\n"
            f"Current Step ID: {step}\n"
            f"Global directive: {directive_text}\n"
            "Use your tools to evaluate traffic stress.\n"
            "Then reply ONLY with valid JSON in this format:\n"
            "{"
            "\"stress_index\": number, "
            "\"priority_score\": number, "
            "\"prompt_text\": \"short traffic summary\", "
            "\"actions\": ["
            "{\"action\":\"set_intersection_policy\", "
            "\"intersection_id\":\"...\", "
            "\"policy\":\"PRIORITY_MAIN|FAIR_BALANCE|CLEAR_QUEUES\", "
            "\"reasoning\":\"...\"}"
            "]}"
        )

        full_logged_prompt = (
            f"SYSTEM PROMPT:\n{self.prompt}\n\n"
            f"USER MESSAGE:\n{initial_message}\n"
        )
        self._log_interaction(step, full_logged_prompt, "PENDING")

        response = await chat.send_message(initial_message)

        if not response.function_calls:
            print(f"⚠️ [{self.id}] L'LLM ha ignorato i tool.")
            return {
                "stress_index": 0,
                "priority_score": 0,
                "prompt_text": "Tool call missing",
                "actions": []
            }

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
        self._log_interaction(step, full_logged_prompt, raw_response)

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