# agent/brain.py
from openai import OpenAI

class AgentBrain:
    def __init__(self, base_url="http://localhost:1234/v1"):
        self.client = OpenAI(base_url=base_url, api_key="lm-studio")

    def think(self, full_prompt):
        """
        Riceve il prompt completo (regole + dati) e lo invia al modello.
        """
        response = self.client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.0, # Massima precisione, nessuna allucinazione
            max_tokens=150, 
            stop=[
                "}\n",  # Cerca la parentesi seguita da un a capo
                "```"   # Ferma il blocco di codice markdown
            ]
        )
        return response.choices[0].message