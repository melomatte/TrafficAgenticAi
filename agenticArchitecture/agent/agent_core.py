"""
È l'architetto logico (il "Manager") dell'agente.
Si occupa di preparare tutto il contesto necessario affinché LLM possa decidere possa decidere. Traduce la realtà fisica 
della simulazione in concetti che l'IA può capire. Gestisce: Formattazione della topologia, compressione delle metriche in testo 
e la struttura logica del processo decisionale.

3 funzioni principali:

    -  __init__(self, topology_path, model_name, provider) = preparazione del prompt statico. Carica la rete stradale JSON e 
    la converte in un formato testuale denso per massimizzare l'efficienza dei token.

    - _format_metrics_to_text(self, metrics) = Converte le metriche Live (JSON) in un formato testuale denso.
    
    - decide(self, current_metrics) = si sviluppa in 3 fasi:
        1. Assemblaggio prompt da inviare all'LLM (composto da parte statica creata in fase di init e 
        parte dinamica estrapolata dalla simulazione tramite traci al momento dell'interrogazione)
        2. Invio prompt LLM tramite modulo llm_connector.py
        3. Ricezione della risposta
"""

import json
from .policies import TOPOLOGY, OPTIMIZATION_RULES, RESPONSE_RULES
from .llm_connector import AgentBrain

class TrafficAgent:

    def __init__(self, topology_path, model_name, provider="local"):

        with open(topology_path, 'r') as f:
            self.topo = json.load(f)
        
        self.id = self.topo.get('id', 'unknown_agent')
        
        # Passiamo le preferenze al Brain
        self.brain = AgentBrain(provider=provider, model_name=model_name)
        
        # Conversione topologia da JSON a Testo (Adjacency List compatta -> per risparmio token)
        topo_text = f"AREA ID: {self.id}\n"
        
        ingressi = ", ".join(self.topo.get("in", []))
        uscite = ", ".join(self.topo.get("out", []))
        
        topo_text += f"IN (Ingressi Area): {ingressi}\n"
        topo_text += f"OUT (Uscite Area): {uscite}\n"
        topo_text += "GRAPH (Rete degli Incroci):\n"
        
        for line in self.topo.get("graph", []):
            topo_text += f"- {line}\n"

        topology_section = TOPOLOGY.format(topology_text=topo_text)

        # Assemblaggio prompt statico (sarà sempre uguale in ogni prompting) con variabili di policies.py
        self.static_prompt = f"{topology_section}\n\n{OPTIMIZATION_RULES}\n\n{RESPONSE_RULES}"

    def _format_metrics_to_text(self, metrics):
    
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

        # 1. Assemblaggio prompt da inivare all'LLM
        metrics_text = self._format_metrics_to_text(current_metrics)
        final_prompt = f"{self.static_prompt}\n\n{metrics_text}\n\nGenera la tua decisione ora iniziando con la parentesi graffa:"
        
        # 2. Invio prompt al Brain (reale responsabile delle chiamate)
        raw_response = self.brain.think(final_prompt)
        
        # 3. Ricezione della risposta
        if raw_response is None or raw_response.content is None:    # Risposta vuota
            print(f"\n⚠️ [{self.id}] ATTENZIONE: Ricevuta risposta NULLA dal modello.")
        else:                                                       # Risposta piena
            testo_risposta = raw_response.content.strip()

            print("\n" + "═"*60)
            print(f"🧠 AGENTE: {self.id}")
            print(f"📡 RISPOSTA RICEVUTA:")
            print(testo_risposta) 
            print("═"*60 + "\n")