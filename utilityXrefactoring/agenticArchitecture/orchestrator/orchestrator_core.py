"""
È l'architetto logico dell'orchestratore globale.
Riceve gli output degli agenti locali, li comprime in un contesto testuale
e invia tutto all'LLM per ottenere una direttiva globale.
"""

import json
from utilityXrefactoring.agenticArchitecture.orchestrator.orchestrator_policies import (
    ORCHESTRATOR_ROLE,
    ORCHESTRATOR_RULES,
    build_orchestrator_response_rules,
)
from .orchestrator_connector import OrchestratorBrain


class GlobalOrchestrator:

    def __init__(self, model_name, provider="local"):
        self.id = "global_orchestrator"
        self.brain = OrchestratorBrain(provider=provider, model_name=model_name)

    def _format_agents_to_text(self, agent_outputs):
        lines = ["--- LOCAL AGENT OUTPUTS ---"]

        for out in agent_outputs:
            agent_id = out.get("agent_id", "unknown")
            zone = out.get("zone", "unknown")
            priority_score = out.get("priority_score", 0)
            actions = out.get("actions", [])

            lines.append(
                f"- Agent:{agent_id} | Zone:{zone} | PriorityScore:{priority_score} | ProposedActions:{len(actions)}"
            )

            for action in actions:
                lines.append(
                    f"  -> Intersection:{action.get('intersection_id')} | "
                    f"Policy:{action.get('policy')} | "
                    f"Reason:{action.get('reasoning')}"
                )

        return "\n".join(lines)

    def decide(self, agent_outputs):
        agent_ids = [out.get("agent_id", "unknown") for out in agent_outputs]
        dynamic_response_rules = build_orchestrator_response_rules(agent_ids)
        agents_text = self._format_agents_to_text(agent_outputs)

        final_prompt = (
            f"{ORCHESTRATOR_ROLE}\n\n"
            f"{ORCHESTRATOR_RULES}\n\n"
            f"{dynamic_response_rules}\n\n"
            f"{agents_text}\n\n"
            f"Generate your global decision now starting with {{:"
        )

        raw_response = self.brain.think(final_prompt)

        if raw_response is None or raw_response.content is None:
            print(f"\n⚠️ [{self.id}] ATTENZIONE: risposta nulla.")
            return {"action": "hold_current", "target_agent": None, "reasoning": "Empty response"}

        text = raw_response.content.strip()

        print("\n" + "═" * 60)
        print(f"🧭 ORCHESTRATORE: {self.id}")
        print("📡 RISPOSTA RICEVUTA:")
        print(text)
        print("═" * 60 + "\n")

        text = text.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(text)

            if parsed.get("target_agent") == "null":
                parsed["target_agent"] = None

            return parsed
        except Exception:
            print(f"⚠️ [{self.id}] JSON non valido.")
            return {"action": "hold_current", "target_agent": None, "reasoning": "Invalid JSON"}