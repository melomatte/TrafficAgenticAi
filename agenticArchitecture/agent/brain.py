# agent/brain.py
import json
from openai import OpenAI

class AgentBrain:
    def __init__(self, base_url="http://localhost:1234/v1"):
        self.client = OpenAI(base_url=base_url, api_key="lm-studio")

    def think(self, system_prompt, user_status):
        response = self.client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Stato traffico: {json.dumps(user_status)}\n\nGenera la tua decisione SOLO ed ESCLUSIVAMENTE in formato JSON."}
            ],
            temperature=0.0,
            
            # --- I NUOVI PARAMETRI FRENO ---
            
            # 1. MAX TOKENS: Un JSON di risposta sarà lungo al massimo 60-80 token.
            # Impostando 150, se il modello impazzisce, l'API taglia la connessione forzatamente.
            # Lascia il max_tokens a 150
            max_tokens=150, 
            
            # Semplifica l'array di stop
            stop=[
                "}\n",  # Cerca la parentesi seguita da un a capo
                "```"   # Ferma il blocco di codice
            ]
        )
        return response.choices[0].message