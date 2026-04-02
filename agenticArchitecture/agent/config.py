# agent/config.py
import json
from .policies import TOPOLOGY, OPTIMIZATION_RULES, RESPONSE_RULES
#from .policies_soft import SYSTEM_PROMPT_TEMPLATE
from .brain import AgentBrain

class TrafficAgent:
    def __init__(self, topology_path):

        # Lettura del file .json contenente la topologia della strada
        with open(topology_path, 'r') as f:
            self.topo = json.load(f)
        
        self.id = self.topo['agent_id']
        self.brain = AgentBrain()
        
        # Modifica da applicare dentro agent/config.py nel metodo __init__

        # 1. Costruiamo la stringa leggendo direttamente il JSON pre-calcolato
        intersections_info = ""
        for inter in self.topo.get("intersections", []):
            int_id = inter.get("id")
            intersections_info += f"- Incrocio: {int_id}\n"
            
            for conn in inter.get("connections", []):
                f_edge = conn["from_edge"]
                t_edge = conn["to_edge"]
                target = conn["leads_to_intersection"]
                
                intersections_info += f"  * Da [{f_edge}] verso [{t_edge}] (che porta a: {target})\n"

        # 2. Formattiamo la prima parte del prompt (Topologia)
        topology_section = TOPOLOGY.format(
            agent_id=self.id,
            intersections_info=intersections_info.strip(),
            internal_edges=", ".join(self.topo.get('internal_edges', [])),
            entry_points=", ".join(self.topo.get('entry_points', [])),
            exit_points=", ".join(self.topo.get('exit_points', []))
        )

        # 3. Assembliamo il System Prompt finale unendo i 3 blocchi
        self.system_prompt = f"{topology_section}\n\n{OPTIMIZATION_RULES}\n\n{RESPONSE_RULES}"

        '''
        --> per policies_soft.py

        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            agent_id=self.id,
            entry_points=self.topo.get('entry_points', []),
            exit_points=self.topo.get('exit_points', [])
        )
        '''

    def decide(self, current_metrics):
        """
        Interroga l'LLM, pulisce la risposta testuale e restituisce un dizionario Python.
        """
        raw_response = self.brain.think(self.system_prompt, current_metrics)
        testo_risposta = raw_response.content.strip()

        # Pulizia markdown
        if testo_risposta.startswith("```json"):
            testo_risposta = testo_risposta[7:-3].strip()
        elif testo_risposta.startswith("```"):
            testo_risposta = testo_risposta[3:-3].strip()
            
        # Fix parentesi
        if not testo_risposta.endswith("}"):
            testo_risposta += "\n}"

        # Parsing sicuro
        try:
            decisione_json = json.loads(testo_risposta)
            return decisione_json
        except json.JSONDecodeError:
            print(f"[{self.id}] ⚠️ Errore di decodifica JSON interno. Risposta grezza: {testo_risposta}")
            return {
                "action": "error",
                "intersection_id": "none",
                "policy": "none",
                "reasoning": "Fallimento nel parsing della risposta dell'LLM."
            }