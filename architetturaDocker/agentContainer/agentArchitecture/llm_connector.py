"""
AgentConnector — Interfaccia unificata verso il modello LLM (Google Gemini / OpenAI / OpenRouter / Locale).

Questo modulo astrae la comunicazione con il modello linguistico, esponendo due modalità di interazione distinte a 
seconda del tipo di task richiesto.

METODO think():
Chiamata singola stateless (single-turn): invia un prompt e riceve una risposta. Adatta per task semplici che non 
richiedono memoria della conversazione né l'uso di tool esterni. Non supporta il tool calling loop.
Supporta sia Google SDK (aio) che OpenAI SDK, selezionando automaticamente il percorso corretto in base all'sdk 
configurato, senza mai bloccare l'event loop.

METODO create_agentic_chat():
Crea e restituisce una sessione di chat multi-turno configurata con un system prompt e un set di tool.
Questa è la modalità corretta per implementare agenti autonomi con tool calling, per due motivi fondamentali:
    1. STATO CONVERSAZIONALE: la sessione di chat mantiene automaticamente l'intera cronologia dei messaggi 
       (prompt → tool call → tool result → ...) lato SDK, senza che il chiamante debba ricostruirla manualmente.
    2. TOOL CALLING NATIVO: il formato dei messaggi tool_use e tool_result viene gestito correttamente dall'SDK,
       che si aspetta una struttura specifica per alternare risposte del modello e risultati dei tool. Gestirla 
       manualmente con generate_content() sarebbe fragile e soggetto a errori di formato.

La sessione restituita viene poi pilotata dal loop agentico in PredictiveAgent, che invia i risultati dei tool con 
chat.send_message() fino a quando il modello non produce la risposta testuale finale.

AgentConnector è progettato per lavorare in modo trasparente con SDK diversi (Google, OpenAI, OpenRouter, LM Studio locale) 
senza che il codice chiamante (PredictiveAgent) debba conoscere o  gestire le differenze tra i provider. 
Questo è reso possibile dai wrapper definiti in 'adapter_connector.py':

- GoogleChatWrapper / OpenAIChatWrapper: ogni wrapper adatta la sessione di chat del proprio SDK all'interfaccia comune 
send_message() → UnifiedResponse. AgentConnector.create_agentic_chat() istanzia il wrapper corretto in base
all'sdk configurato: da quel momento in poi, PredictiveAgent interagisce
sempre e solo con l'interfaccia unificata, senza sapere quale provider
è attivo sotto.

- UnifiedFunctionCall / UnifiedResponse: oggetti neutrali che standardizzano il formato delle risposte (testo + tool calls) 
eliminando le differenze strutturali tra SDK. Ad esempio, OpenAI espone un call_id obbligatorio per collegare ogni tool 
result al tool call corrispondente, mentre Google non ne ha bisogno: questa differenza è nascosta dentro i wrapper e non emerge 
mainel loop agentico di PredictiveAgent

CONFIGURAZIONE TRAMITE FILE CHIAVE:
Il file api_key.txt deve contenere due righe nel formato:
    <api_key>
    sdk=<google|openai|openrouter>
L'attributo 'provider' distingue invece tra modalità 'cloud' (legge il file) e 'local' (LM Studio via OpenAI compat.).
"""

import json
import os
from openai import AsyncOpenAI
from adapter_connector import OpenAIChatWrapper

# SDK validi accettati nel file di configurazione
VALID_SDKS = {"openai", "openrouter", "litellm"}

class AgentConnector:

    def __init__(self, agent_name, model_name, provider):
        self.provider = provider
        self.agent_name = agent_name

        if self.provider == "local":
            # Modalità locale con LM Studio -> espone un'API compatibile OpenAI.
            # In contesto Docker, 'localhost' punta al container stesso, non all'host -> 'host.docker.internal' è l'indirizzo speciale per raggiungere la rete dell'host.
            print(f"🏠 [{self.agent_name}][CONNECTOR] Inizializzazione in modalità LOCALE (LM Studio)")
            self.sdk = "openai"
            self.client = AsyncOpenAI(base_url="http://host.docker.internal:1234/v1", api_key="lm-studio")
            self.model = model_name
            print(f"✅ [{self.agent_name}][CONNECTOR] Connettore locale inizializzato (Modello: {self.model})")

        else: # Modalità cloud: legge chiave e sdk dal file di configurazione
            
            # Recupero chiave api e nome modello da variabili d'ambiente
            api_key = os.getenv("LLM_API_KEY")
            self.sdk = os.getenv("LLM_SDK", "").strip().lower()

            if api_key and self.sdk in VALID_SDKS:
                print(f"✅ [{self.agent_name}][CONNECTOR] Configurazione caricata da variabili d'ambiente (sdk={self.sdk})")
            else:
                raise ValueError(
                    f"❌ [{self.agent_name}][CONNECTOR] Impossibile caricare la configurazione API.\n"
                    f" crea il file .env (nella root del progetto, di fianco al manager) impostando:\nLLM_API_KEY=<CHIAVE>\nLLM_SDK=litellm\n"
                )

            if self.sdk == "openai":
                self.client = AsyncOpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
                self.model = model_name
                print(f"✅ [{self.agent_name}][CONNECTOR] Connettore inizializzato su OpenAI SDK (Modello: {self.model})")
            
            elif self.sdk == "litellm":
                self.client = AsyncOpenAI(api_key=api_key, base_url="https://litellm-proxy-1013932759942.europe-west8.run.app")
                self.model = model_name
                print(f"✅ [{self.agent_name}][CONNECTOR] Connettore inizializzato su liteLLM (Modello: {self.model})")    

            elif self.sdk == "openrouter":
                self.client = AsyncOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
                self.model = model_name
                print(f"✅ [{self.agent_name}][CONNECTOR] Connettore inizializzato su OpenRouter (Modello: {self.model})")
        
    async def think(self, full_prompt) -> str:

        try:

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.0
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            print(f"❌ [{self.agent_name}][CONNECTOR] Eccezione in think(): {e}")
            return ""

    def create_agentic_chat(self, system_instruction: str, openai_tools: list):
        return OpenAIChatWrapper(self.client, self.model, system_instruction, openai_tools)
    
    def format_tool_response(self, name: str, result: str, call_id: str = None):

        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps({"result": result})
        }