"""
Prompt base dell'orchestratore globale.
La parte dinamica dipende dal numero di agenti caricati.
"""

ORCHESTRATOR_ROLE = """
You are the Global Traffic Orchestrator.
Your task is to coordinate multiple local traffic agents and choose one global action.
"""

ORCHESTRATOR_RULES = """
GLOBAL DECISION RULES:
1. If one agent has clearly higher congestion, prioritize that agent.
2. If congestion is similar across agents, balance the load.
3. If no urgent condition emerges, keep the current strategy.
"""


def build_orchestrator_response_rules(agent_ids):
    agents_str = ", ".join(agent_ids)

    return f"""
Reply ONLY with valid JSON.

Exact format:
{
  "global_reasoning": "short reasoning",
  "directives": [
    {
      "target_agent": "agent id",
      "action": "prioritize_flow|hold_or_balance|reduce_aggressiveness",
      "instruction": "short instruction"
    }
  ]
}

Constraints:
- Return exactly one directive for each available agent.
- target_agent must match one of the available agent IDs.
"""