"""
È l'architetto logico dell'orchestratore globale.
Riceve gli output degli agenti locali, li comprime in un contesto testuale
e invia tutto all'LLM per ottenere una direttiva globale.
"""

import json
import asyncio
import os
from datetime import datetime


from llm_connector import AgentConnector
from orchestrator.orchestrator_policies import (
    ORCHESTRATOR_ROLE,
    ORCHESTRATOR_RULES,
    build_orchestrator_response_rules,
)

LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)

class Orchestrator:

    def __init__(self, model_name, provider="local"):
        self.id = "global_orchestrator"
        self.connector = AgentConnector(
            agent_name=self.id,
            provider=provider,
            model_name=model_name
        )

    def _format_agents_to_text(self, agent_outputs):
        lines = ["--- LOCAL AGENT OUTPUTS ---"]

        for out in agent_outputs:
            agent_id = out.get("agent_id", "unknown")
            zone = out.get("zone", "unknown")
            stress_index = out.get("stress_index", 0)
            priority_score = out.get("priority_score", 0)
            prompt_text = out.get("prompt_text", "")
            actions = out.get("actions", [])

            lines.append(
                f"- Agent:{agent_id} | Zone:{zone} | "
                f"StressIndex:{stress_index} | PriorityScore:{priority_score} | "
                f"ProposedActions:{len(actions)}"
            )

            if prompt_text:
                lines.append(f"  Context:{prompt_text}")

            for action in actions:
                lines.append(
                    f"  -> Intersection:{action.get('intersection_id')} | "
                    f"Policy:{action.get('policy')} | "
                    f"Reason:{action.get('reasoning')}"
                )

        return "\n".join(lines)

    def _log_interaction(self, prompt, response):
        filename = f"{LOG_DIR}/orchestrator.log"

        with open(filename, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"TIME: {datetime.now()}\n\n")
            f.write("PROMPT:\n")
            f.write(prompt + "\n\n")
            f.write("RESPONSE:\n")
            f.write(str(response) + "\n")
    async def think(self, prompt):
        chat = self.connector.create_agentic_chat(
            system_instruction=(
                "You are the global traffic orchestrator. "
                "Reply only with valid JSON."
            ),
            openai_tools=[]
        )

        response = await chat.send_message(prompt)
        return response

    async def decide(self, current_vector, history_vectors=None):
        history_vectors = history_vectors or []

        agent_ids = [out.get("agent_id", "unknown") for out in current_vector]

        current_text = json.dumps(current_vector, indent=2, ensure_ascii=False)
        history_text = json.dumps(history_vectors or [], indent=2, ensure_ascii=False)

        final_prompt = (
            f"{ORCHESTRATOR_ROLE}\n\n"
            f"{ORCHESTRATOR_RULES}\n\n"
            f"AVAILABLE AGENTS:\n{agent_ids}\n\n"
            f"CURRENT AGENT VECTOR:\n{current_text}\n\n"
            f"HISTORICAL WINDOW OF PREVIOUS VECTORS:\n{history_text}\n\n"
            "TASK:\n"
            "Analyze current stress levels and recent trends.\n"
            "Return exactly one directive for each available agent.\n\n"
            "Reply ONLY with valid JSON. No markdown.\n"
            "Exact format:\n"
            "{\n"
            '  "global_reasoning": "short reasoning",\n'
            '  "directives": [\n'
            "    {\n"
            '      "target_agent": "agent id",\n'
            '      "action": "prioritize_flow|hold_or_balance|reduce_aggressiveness",\n'
            '      "instruction": "short instruction"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        self._log_interaction(final_prompt, "PENDING")

        raw_response = await self.think(final_prompt)

        text = getattr(raw_response, "text", None) or getattr(raw_response, "content", "") or ""

        self._log_interaction(final_prompt, text)

        if not text:
            return {
                "global_reasoning": "Empty response",
                "directives": [
                    {
                        "target_agent": agent_id,
                        "action": "hold_or_balance",
                        "instruction": "No directive available"
                    }
                    for agent_id in agent_ids
                ]
            }

        text = text.strip().replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(text)
            return parsed
        except Exception:
            print(f"⚠️ [{self.id}] JSON non valido:\n{text}")
            return {
                "global_reasoning": "Invalid JSON",
                "directives": [
                    {
                        "target_agent": agent_id,
                        "action": "hold_or_balance",
                        "instruction": "Invalid orchestrator response"
                    }
                    for agent_id in agent_ids
                ]
            }