# agent/config.py
import json
from .policies import TOPOLOGY, OPTIMIZATION_RULES, RESPONSE_RULES
from .brain import AgentBrain

class TrafficAgent:
    def __init__(self, topology_path):

        # 1. Lettura del file .json contenente la topologia
        with open(topology_path, 'r') as f:
            self.topo = json.load(f)
        
        self.id = self.topo.get('id', 'unknown_agent')
        self.brain = AgentBrain()
        
        # 2. Conversione da JSON a Testo (Adjacency List compatta)
        topo_text = f"AREA ID: {self.id}\n"
        
        ingressi = ", ".join(self.topo.get("in", []))
        uscite = ", ".join(self.topo.get("out", []))
        
        topo_text += f"IN (Ingressi Area): {ingressi}\n"
        topo_text += f"OUT (Uscite Area): {uscite}\n"
        topo_text += "GRAPH (Rete degli Incroci):\n"
        
        for line in self.topo.get("graph", []):
            topo_text += f"- {line}\n"

        # 3. Assembliamo la sezione Topologia
        try:
            topology_section = TOPOLOGY.format(topology_text=topo_text)
        except (KeyError, ValueError):
            topology_section = f"{TOPOLOGY}\n{topo_text}"

        # 4. Assembliamo il Prompt Statico (Regole + Mappa)
        self.static_prompt = f"{topology_section}\n\n{OPTIMIZATION_RULES}\n\n{RESPONSE_RULES}"

        '''
        --> per policies_soft.py

        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            agent_id=self.id,
            entry_points=self.topo.get('entry_points', []),
            exit_points=self.topo.get('exit_points', [])
        )
        '''

    def _format_metrics_to_text(self, metrics):
        """
        Converte le metriche Live (JSON) in un formato testuale denso.
        Risparmia token ed è più facile da leggere per il modello.
        """
        lines = ["--- LIVE TRAFFIC METRICS ---"]
        for inter in metrics.get("intersections", []):
            lanes_info = []
            for l_id, l_data in inter.get("lanes_status", {}).items():
                lanes_info.append(f"{l_id}(Q:{l_data['queue']}, M:{l_data['moving']})")
            
            line = (f"- Incrocio: {inter['id']} | Tot_Veicoli:{inter['total_vehicles']}, "
                    f"Tot_Coda:{inter['total_queue']} | Dettaglio Corsie: {', '.join(lanes_info)}")
            lines.append(line)
        return "\n".join(lines)

    def decide(self, current_metrics):
        """
        Assembla il prompt finale, interroga l'LLM e pulisce il JSON in uscita.
        """
        # A. Formatta le metriche correnti in testo
        metrics_text = self._format_metrics_to_text(current_metrics)
        
        # B. Unisce le regole statiche con i dati dinamici
        final_prompt = f"{self.static_prompt}\n\n{metrics_text}\n\nGenera la tua decisione ora iniziando con la parentesi graffa:"
        
        # C. Chiamata al Brain
        raw_response = self.brain.think(final_prompt)
        testo_risposta = raw_response.content.strip()

        # D. Pulizia markdown e Fix parentesi
        if testo_risposta.startswith("```json"):
            testo_risposta = testo_risposta[7:-3].strip()
        elif testo_risposta.startswith("```"):
            testo_risposta = testo_risposta[3:-3].strip()
            
        if not testo_risposta.endswith("}"):
            testo_risposta += "\n}"

        # E. Parsing sicuro
        try:
            decisione_json = json.loads(testo_risposta)
            return decisione_json
        except json.JSONDecodeError:
            print(f"[{self.id}] ⚠️ Errore di decodifica JSON interno. Risposta grezza: \n{testo_risposta}")
            return {
                "action": "error",
                "intersection_id": "none",
                "policy": "none",
                "reasoning": "Fallimento nel parsing della risposta dell'LLM."
            }