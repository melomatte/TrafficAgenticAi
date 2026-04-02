import json
from openai import OpenAI

class AreaAgent:
    def __init__(self, topology_file, base_url="http://localhost:1234/v1", api_key="lm-studio"):
        """
        Inizializza l'agente caricando la sua mappa mentale e connettendosi al LLM locale.
        """
        try:
            with open(topology_file, "r") as f:
                self.topology = json.load(f)
        except FileNotFoundError:
            raise Exception(f"File topologia {topology_file} non trovato!")

        self.agent_id = self.topology.get("agent_id", "Unknown_Agent")
        
        # Inizializza il client verso LM Studio
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        
        # Pre-calcola le stringhe per il prompt
        self.internal_edges = ", ".join(self.topology.get("internal_edges", []))
        self.entry_points = ", ".join(self.topology.get("entry_points", []))
        self.exit_points = ", ".join(self.topology.get("exit_points", []))

    def _get_system_prompt(self):
        """
        Costruisce il System Prompt iniettando la topologia e le regole (Indice di Stress).
        """
        return f"""Sei un Traffic AI Agent avanzato. Il tuo ID è {self.agent_id}.
Gestisci un'area con le seguenti caratteristiche:
- Strade interne: {self.internal_edges}
- Punti di ingresso (traffico in arrivo): {self.entry_points}
- Punti di uscita (per deviare il traffico): {self.exit_points}

Il tuo obiettivo è minimizzare l'Indice di Stress (IS) degli incroci.
L'IS tiene conto sia del numero di veicoli (efficienza) sia del tempo di attesa al quadrato (equità).
Regole decisionali:
1. Se un incrocio ha code moderate, usa l'ottimizzazione locale (cambia i tempi del semaforo).
2. Se un incrocio ha un Indice di Stress Critico su una strada, favorisci quella strada.
3. Se un'intera area è bloccata, prova a suggerire un rerouting verso i Punti di Uscita.

Analizza i dati ricevuti e scegli lo STRUMENTO (tool) più adatto per risolvere la situazione."""

    def _get_tools(self):
        """
        Definisce i Macro-Tools (simili a MCP) che l'agente può chiamare.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "set_intersection_policy",
                    "description": "Imposta la politica semaforica per un incrocio per gestire il traffico locale.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "intersection_id": {
                                "type": "string",
                                "description": "L'ID dell'incrocio da modificare"
                            },
                            "policy_type": {
                                "type": "string",
                                "enum": ["PRIORITY_MAIN_ROAD", "FAIR_BALANCE", "CLEAR_QUERIES"],
                                "description": "La strategia: PRIORITY_MAIN_ROAD per flussi pesanti, FAIR_BALANCE per equità, CLEAR_QUERIES per smaltire lunghe attese."
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Breve spiegazione del perché hai scelto questa policy."
                            }
                        },
                        "required": ["intersection_id", "policy_type", "reasoning"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "request_rerouting",
                    "description": "Devia il traffico in arrivo se l'area è troppo satura.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entry_edge": {
                                "type": "string",
                                "description": "L'entry_point da cui bloccare/deviare il traffico."
                            },
                            "target_exit_edge": {
                                "type": "string",
                                "description": "L'exit_point verso cui deviare i veicoli."
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Motivazione del rerouting."
                            }
                        },
                        "required": ["entry_edge", "target_exit_edge", "reasoning"]
                    }
                }
            }
        ]

    def process_simulation_step(self, traffic_state_json):
        """
        Invia i dati correnti all'LLM e restituisce la decisione presa (Tool Call).
        """
        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": f"Stato attuale del traffico (JSON):\n{json.dumps(traffic_state_json, indent=2)}\nScegli l'azione migliore."}
        ]

        print(f"\n[{self.agent_id}] Analisi dello stato in corso...")
        
        # Chiamata al modello locale
        response = self.client.chat.completions.create(
            model="local-model", # Con LM Studio il nome non è rilevante, userà quello caricato in memoria
            messages=messages,
            tools=self._get_tools(),
            tool_choice="auto", # Lascia decidere all'LLM se usare un tool
            temperature=0.1     # Bassa temperatura per risposte deterministiche e logiche
        )

        response_message = response.choices[0].message
        
        # Estrai le chiamate ai tool
        tool_calls = response_message.tool_calls

        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                print(f"[{self.agent_id}] 🛠️  DECISIONE PRESA: Chiama '{function_name}'")
                print(f"[{self.agent_id}] 📋 Parametri: {json.dumps(function_args, indent=2)}")
        else:
            print(f"[{self.agent_id}] ℹ️  L'agente non ha ritenuto necessario usare alcuno strumento. Risposta testuale:")
            print(response_message.content)

# ==========================================
# SEZIONE DI TEST ISOLATO (MOCK)
# ==========================================
if __name__ == "__main__":
    # 1. Crea un file topology fittizio per il test se non esiste
    mock_topology = {
        "agent_id": "agent_0",
        "intersections": [{"id": "INT_01"}],
        "internal_edges": ["edge_center_N", "edge_center_S"],
        "entry_points": ["edge_ext_N"],
        "exit_points": ["edge_ext_S"]
    }
    with open("mock_topology.json", "w") as f:
        json.dump(mock_topology, f)

    # 2. Inizializza l'agente
    agent = AreaAgent("mock_topology.json")

    # 3. Simula il pacchetto dati in arrivo da SUMO (calcolato dal tuo Abstraction Layer)
    mock_traffic_state = {
        "timestamp_sec": 120,
        "intersections_status": [
            {
                "id": "INT_01",
                "directions": [
                    {
                        "edge": "edge_center_N",
                        "vehicles_in_queue": 45,
                        "max_waiting_time_sec": 110,
                        "stress_index": 850,
                        "status": "CRITICO"
                    },
                    {
                        "edge": "edge_center_S",
                        "vehicles_in_queue": 3,
                        "max_waiting_time_sec": 10,
                        "stress_index": 15,
                        "status": "REGOLARE"
                    }
                ]
            }
        ]
    }

    # 4. Esegui il ciclo
    agent.process_simulation_step(mock_traffic_state)