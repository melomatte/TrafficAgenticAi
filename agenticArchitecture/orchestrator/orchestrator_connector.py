"""
Motore tecnico dell'orchestratore.
Gestisce la chiamata al modello LLM.
"""

import os
from openai import OpenAI

KEY_FILE = "gemini_key.txt"


class OrchestratorBrain:
    def __init__(self, model_name, provider="local"):
        self.provider = provider

        if self.provider == "cloud":
            api_key = self._load_key_logic(KEY_FILE)

            if api_key == "no-key-found":
                raise ValueError(
                    "\n❌ ERRORE CRITICO: Chiave API non trovata.\n"
                    f"Assicurati che il file '{KEY_FILE}' sia nella root del progetto "
                    "o imposta la variabile d'ambiente GEMINI_API_KEY."
                )

            base_url = "https://litellm-proxy-1013932759942.europe-west8.run.app"
            self.model = model_name
        else:
            base_url = "http://localhost:1234/v1"
            api_key = "lm-studio"
            self.model = "local-model"

        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _load_key_logic(self, filename):
        path_root = os.path.abspath(filename)
        path_agent = os.path.abspath(os.path.join(os.path.dirname(__file__), filename))

        for path in [path_root, path_agent]:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    key = f.read().strip()
                    if key:
                        print(f"✅ Chiave API orchestratore caricata da: {path}")
                        return key

        env_key = os.getenv("GEMINI_API_KEY")
        if env_key:
            print("✅ Chiave API orchestratore caricata da variabile d'ambiente.")
            return env_key

        return "no-key-found"

    def think(self, full_prompt):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.0,
            )

            print("\n🔍 --- ISPEZIONE RISPOSTA API ORCHESTRATORE ---")
            print(f"ID Risposta: {response.id}")
            print(f"Motivo termine (finish_reason): {response.choices[0].finish_reason}")

            return response.choices[0].message

        except Exception as e:
            print(f"❌ Eccezione API orchestratore: {e}")

            class Fallback:
                content = '{"action":"hold_current","target_agent":null,"reasoning":"API exception"}'

            return Fallback()