# 🚦 TrafficAgenticAI

Un sistema di IA agentica multi-agente per il controllo intelligente e autonomo del traffico urbano, alimentato da SUMO, Modelli Linguistici di Grandi Dimensioni (LLM) e Kubernetes.

---

## 📋 Panoramica

TrafficAgenticAI è un progetto di ricerca e ingegneria che combina l'IA agentica con il simulatore di traffico SUMO (Simulation of Urban MObility) per costruire un sistema di gestione del traffico completamente autonomo e distribuito.

Il sistema divide una rete stradale urbana in zone geografiche tramite clustering K-Means. A ciascuna zona è assegnato un **TrafficAgent** — un agente IA autonomo che osserva la congestione locale, ragiona tramite un LLM e agisce sui semafori in tempo reale attraverso l'interfaccia TraCI di SUMO. Un agente globale **Orchestrator** coordina tutti gli agenti locali, analizzando le tendenze di stress nell'intera rete ed emettendo direttive strategiche.

L'intera infrastruttura degli agenti viene eseguita su Kubernetes (tramite Minikube), con uno stack completo di osservabilità (Prometheus, Grafana, Loki, Promtail) distribuito automaticamente all'avvio.

---

## ✨ Funzionalità Principali

- 🧠 **Processo decisionale basato su LLM** — gli agenti ragionano usando OpenAI, LiteLLM, OpenRouter o modelli locali (LM Studio)
- 🗺️ **Clustering automatico delle zone** — K-Means divide qualsiasi rete SUMO in *k* zone all'avvio
- 🤝 **Gerarchia a due livelli** — i TrafficAgent locali gestiscono la tattica; l'Orchestrator globale gestisce la strategia
- 🔌 **Tool calling MCP** — gli agenti interagiscono con SUMO tramite FastMCP (trasporto SSE)
- 🐳 **Nativo per Kubernetes** — gli agenti vengono eseguiti come StatefulSet, l'orchestratore come Deployment, tutto all'interno di Minikube
- 📊 **Osservabilità completa** — dashboard Grafana per stress, salute, prompt LLM e log, pronte all'uso
- 🏙️ **Reti urbane reali incluse** — centro città di Bologna, Viale Aldini e griglie sintetiche

---

## 🗂️ Struttura del Progetto

```
TrafficAgenticAI/
│
├── agenticTrafficManager.py     ← Entry point principale: avvia K8s, topologia, monitoring
│
├── sumo_engine/                 ← Livello di simulazione SUMO
│   ├── simulationManager.py     ← Esegue SUMO via TraCI + avvia il loop agentico
│   ├── mcp_server.py            ← Server FastMCP: espone strumenti di traffico agli agenti
│   ├── shared_memory.py         ← Stato condiviso thread-safe tra SUMO e MCP
│   └── urbanNetworks/           ← File di rete SUMO
│       ├── cross/               ← Singola intersezione sintetica
│       ├── 2cross/              ← Rete a 2 intersezioni sintetiche
│       ├── Ncross/              ← Griglia larga con 80 nodi
│       ├── Prova_VialeAldini/   ← Via reale di Bologna (OSM)
│       ├── Simplified_bolo/     ← Rete stradale Bologna semplificata
│       └── Simplified_bolo_center/  ← Centro città di Bologna (OSM)
│
├── trafficAgentic/              ← Livello IA agentica
│   ├── clusteringTopology/      ← Partizionamento K-Means della rete
│   │   ├── topology_builder.py  ← Costruisce topologie dal file SUMO .net.xml
│   │   └── topology_library.py  ← Parsing rete, clustering, formato Token-Slim
│   ├── src/
│   │   ├── traffic_agent/       ← Agente locale (gira come K8s StatefulSet)
│   │   │   ├── agent_core.py    ← Loop agentico con MCP tool calling
│   │   │   ├── agent_service.py ← Servizio FastAPI (riceve trigger)
│   │   │   ├── agent_policies.py ← System prompt per l'LLM dell'agente
│   │   │   ├── llm_connector.py ← Interfaccia LLM unificata (OpenAI/LiteLLM/OpenRouter/Locale)
│   │   │   ├── adapter_connector.py ← Adapter SDK + wrapper risposta unificati
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   └── orchestrator/        ← Orchestratore globale (gira come K8s Deployment)
│   │       ├── orchestrator_core.py  ← Aggrega output agenti, emette direttive
│   │       ├── orchestrator_service.py ← Servizio FastAPI
│   │       ├── orchestrator_policies.py ← System prompt per l'LLM dell'orchestratore
│   │       ├── llm_connector.py
│   │       ├── adapter_connector.py
│   │       ├── Dockerfile
│   │       └── requirements.txt
│   └── config/
│       ├── grafana.yaml         ← Valori Helm per lo stack Grafana/Prometheus
│       ├── loki-values.yaml     ← Valori Helm per Loki
│       ├── dashboards/          ← Dashboard Grafana personalizzate (stress, salute, prompt, log)
│       └── k8s/                 ← Manifest Kubernetes
│           ├── agent.yaml       ← StatefulSet per i pod traffic-agent
│           └── orchestrator.yaml ← Deployment per il pod orchestratore
│
└── backend_server/              ← Livello di persistenza (REST API + MCP)
    ├── backend_server.py        ← Server FastAPI + FastMCP (porta 8000)
    └── data/
        ├── agent_topologies/    ← File JSON di topologia per agente
        └── traffic_state.db     ← SQLite: topologie + storico stress
```

---

## 🏗️ Architettura

<img width="807" height="814" alt="Architettura del sistema" src="https://github.com/user-attachments/assets/94d26872-05b9-484b-b441-f80407b6badc" />

---

## 🔄 Flusso di Sistema

### 1. Bootstrap (`agenticTrafficManager.py`)

1. Analizza il file SUMO `.net.xml` della simulazione scelta
2. Applica il **clustering K-Means** (*k* = numero di agenti) per partizionare spazialmente le intersezioni e gli archi stradali
3. Genera una **topologia Token-Slim** per ogni agente (formato compatto `E_IN>E_OUT(DEST)` ottimizzato per il contesto LLM)
4. Carica le topologie sul backend server (SQLite)
5. Avvia Minikube, installa lo stack di monitoring tramite Helm
6. Costruisce le immagini Docker per `agent` e `orchestrator` all'interno di Minikube
7. Applica i manifest K8s e scala il StatefulSet `traffic-agent` a *k* repliche
8. Apre i port-forward: `orchestrator-service:8080` e `grafana:3000`

### 2. Simulazione (`simulationManager.py`)

1. Avvia il **server FastMCP** (porta 8001) in un thread in background
2. Lancia SUMO (headless o con GUI) e si connette tramite TraCI
3. Ad ogni step di simulazione: legge i dati di veicoli e code per corsia nella memoria condivisa
4. Applica eventuali **comandi in attesa** (cambio fase, cambio durata) accodati dagli agenti
5. Ogni `decision_interval` step: invia una POST all'Orchestrator per avviare un ciclo agentico

### 3. Loop Agentico (per ogni ciclo decisionale)

```
SUMO → POST /trigger_agentic → Orchestrator
  └─► Dispatch di tutti gli agenti in parallelo
        Ogni TrafficAgent:
          1. Si connette al server MCP (SSE persistente)
          2. Invia il messaggio iniziale all'LLM con system prompt + step ID + direttiva globale
          3. L'LLM ragiona e chiama gli strumenti (fino a MAX_ITERATIONS=5):
             ├── compute_stress_index(tls_ids)  → stress 0.0–100.0
             ├── compute_phase_duration(stress) → durata verde adattiva
             ├── set_traffic_light_duration(tl_id, duration)
             └── set_traffic_light(tl_id, phase_index)
          4. Restituisce {stress_index, prompt_text, actions_taken}
  └─► L'Orchestrator raccoglie gli output di tutti gli agenti
        LLM Orchestrator:
          1. Chiama save_agent_stress per ogni agente → SQLite
          2. Chiama get_recent_stress(limit=N) → storico stress
          3. Analizza lo stress corrente + il trend storico
          4. Restituisce una direttiva per ogni agente:
             prioritize_flow | hold_or_balance | reduce_aggressiveness
```

---

## 📐 Formula dello Stress Index

Lo stress index (0–100) viene calcolato per zona dallo strumento MCP `compute_stress_index`:

```
saturazione    = min(coda_totale / capacità_corsia, 1.0)
                 dove capacità_corsia = Σ(lunghezza_corsia / 7.5)

halting_ratio  = veicoli_fermi / veicoli_totali

inter_stress   = (saturazione × 60) + (halting_ratio × 40)

stress_finale  = media(inter_stress) sulle intersezioni gestite
```

| Range | Livello | Comportamento agente |
|-------|---------|----------------------|
| < 10 | 🟢 Basso | Nessuna azione, mantiene la configurazione attuale |
| 10–22 | 🟡 Moderato | Regola la durata della fase in modo adattivo |
| ≥ 22 | 🔴 Alto | Può modificare la politica della fase semaforica |

---

## 🚀 Come Iniziare

### Prerequisiti

| Strumento | Versione | Scopo |
|-----------|----------|-------|
| Python | ≥ 3.10 | Eseguire il motore SUMO e il backend |
| SUMO | ≥ 1.18 | Simulazione del traffico |
| Docker | ≥ 24 | Runtime container per Minikube |
| Minikube | ≥ 1.32 | Cluster Kubernetes locale |
| kubectl | ≥ 1.28 | Gestione K8s |
| Helm | ≥ 3.12 | Installazione dello stack di monitoring |

### Installazione

```bash
# 1. Clona il repository
git clone https://github.com/melomatte/TrafficAgenticAi.git
cd TrafficAgenticAi

# 2. Crea un ambiente virtuale e installa le dipendenze
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

pip install -r requirements.txt

# 3. Imposta SUMO_HOME
export SUMO_HOME=/usr/share/sumo    # adatta al percorso della tua installazione SUMO
```

### Configurare le credenziali LLM

Crea il file `trafficAgentic/.env` con le tue credenziali LLM:

```env
# Usando il proxy LiteLLM (consigliato — supporta molti modelli)
LLM_API_KEY=<tua_api_key>
LLM_SDK=litellm
MODEL_NAME=<nome_modello>        # es. gemini/gemini-2.0-flash
PROVIDER=cloud

# Usando OpenAI direttamente
LLM_API_KEY=<tua_openai_key>
LLM_SDK=openai
MODEL_NAME=gpt-4o
PROVIDER=cloud

# Usando OpenRouter
LLM_API_KEY=<tua_openrouter_key>
LLM_SDK=openrouter
MODEL_NAME=<nome_modello>
PROVIDER=cloud

# Usando un modello locale (LM Studio)
LLM_SDK=openai
MODEL_NAME=<nome_modello_locale>
PROVIDER=local
```

---

## ▶️ Eseguire il Sistema

Il sistema prevede **due processi indipendenti** da avviare separatamente.

### Passo 1 — Avvia il Backend Server

```bash
# Dalla root del progetto
python3 backend_server/backend_server.py
```

Il backend espone:
- REST API su `http://localhost:8000` (upload topologia)
- Server MCP su `http://localhost:8000` (strumenti di persistenza stress per l'orchestratore)

### Passo 2 — Avvia l'Infrastruttura Agentica

```bash
# Dalla root del progetto — avvia Minikube, K8s, monitoring e agenti
python3 trafficAgentic/agenticTrafficManager.py \
    --simulation_name 2cross \
    --k 2 \
    --memory 8192 \
    --cpus 4
```

| Argomento | Default | Descrizione |
|-----------|---------|-------------|
| `--simulation_name` | `2cross` | Nome della cartella di rete in `sumo_engine/urbanNetworks/` |
| `--k` | `2` | Numero di agenti / cluster (deve corrispondere alle intersezioni disponibili) |
| `--memory` | `8192` | RAM (MB) allocata a Minikube |
| `--cpus` | `4` | Core CPU allocati a Minikube |

### Passo 3 — Avvia la Simulazione SUMO

```bash
# Dalla root del progetto
python3 sumo_engine/simulationManager.py \
    --simulation_name 2cross \
    --decision_interval 60 \
    --gui false
```

| Argomento | Default | Descrizione |
|-----------|---------|-------------|
| `--simulation_name` | `2cross` | Rete da simulare |
| `--decision_interval` | `60` | Step SUMO tra un ciclo agentico e l'altro |
| `--gui` | `false` | Imposta `true` per abilitare l'interfaccia grafica di SUMO |

### Arresto

Premi `Ctrl+C` nel terminale di `agenticTrafficManager`. Il gestore di pulizia eseguirà automaticamente:
- Chiusura di tutti i tunnel port-forward
- Eliminazione delle risorse Kubernetes
- Arresto di Minikube

---

## 📊 Osservabilità

Una volta avviato, Grafana è disponibile su **http://localhost:3000** (credenziali: `admin` / `admin`).

Quattro dashboard personalizzate sono pre-configurate:

| Dashboard | Contenuto |
|-----------|-----------|
| **Health Dashboard** | Stato dei pod agente, uptime, tassi di errore |
| **Stress Dashboard** | Stress index per agente e globale nel tempo |
| **Prompt Dashboard** | Monitoraggio dei prompt e delle risposte LLM |
| **Logs Dashboard** | Stream di log strutturati completo (via Loki) |

Tutte le interazioni LLM vengono registrate come JSON strutturato su stdout e acquisite da Promtail → Loki.

---

## 🌐 Reti Urbane Disponibili

| Rete | Tipo | Descrizione |
|------|------|-------------|
| `cross` | Sintetica | Singola intersezione a 4 vie |
| `2cross` | Sintetica | Due intersezioni collegate (default) |
| `Ncross` | Sintetica | Griglia con 80 nodi (`grid80.net.xml`) |
| `Prova_VialeAldini` | Reale (OSM) | Bologna — corridoio Viale Aldini |
| `Simplified_bolo` | Reale (OSM) | Rete stradale Bologna semplificata |
| `Simplified_bolo_center` | Reale (OSM) | Centro città di Bologna |

---

## 🧩 Riferimento Strumenti MCP

### Server MCP Motore SUMO (porta 8001)

| Strumento | Input | Output | Descrizione |
|-----------|-------|--------|-------------|
| `compute_stress_index` | `tls_ids: list[str]` | `float` | Calcola lo stress di zona (0–100) dalla memoria condivisa |
| `compute_phase_duration` | `stress_index: float` | `float` | Restituisce la durata verde adattiva (15–60 s) |
| `set_traffic_light_duration` | `tl_id, duration` | stato | Accoda un cambio di durata fase in SUMO |
| `set_traffic_light` | `tl_id, phase_index` | stato | Accoda un cambio di fase in SUMO (con transizione giallo sicura) |

### Server MCP Backend (porta 8000)

| Strumento | Input | Output | Descrizione |
|-----------|-------|--------|-------------|
| `save_agent_stress` | `agent_id, stress_index, prompt_text` | stato | Persiste uno snapshot di stress agente su SQLite |
| `get_recent_stress` | `limit: int` | lista | Restituisce gli N record di stress più recenti |

---

## 🔧 Supporto Provider LLM

L'`AgentConnector` fornisce un'interfaccia unificata verso molteplici provider senza modifiche al codice degli agenti:

| Provider | SDK | Configurazione |
|----------|-----|----------------|
| OpenAI | `openai` | `LLM_SDK=openai` |
| Proxy LiteLLM | `litellm` | `LLM_SDK=litellm` |
| OpenRouter | `openrouter` | `LLM_SDK=openrouter` |
| LM Studio (locale) | Compatibile OpenAI | `PROVIDER=local` |

---

## 🗺️ Formato Topologia (Token-Slim)

Per minimizzare l'utilizzo del contesto LLM, le topologie di rete stradale sono codificate in un formato compatto **Token-Slim**:

```
<junction_id>: <edge_in>><edge_out>(<destinazione>), ...
```

Esempio:

```
J1: E_north>E_south(J2), E_west>E_east(EXT), E_east>E_west(EXT)
J2: E_south>E_north(J1), E_east>E_exit(EXT)
```

Questo formato viene generato automaticamente dal file SUMO `.net.xml` durante la fase di bootstrap tramite clustering K-Means.

---

## 📋 Requisiti

### Python (root)

```
fastapi
fastmcp
requests
uvicorn
scikit-learn
docker
minikube
kubernetes
sumo
traci
helm
```

### Pod Agente / Orchestratore

Vedi `trafficAgentic/src/traffic_agent/requirements.txt` e `trafficAgentic/src/orchestrator/requirements.txt`.

---

## 📁 Riferimento Rapido File Chiave

| File | Ruolo |
|------|-------|
| `trafficAgentic/agenticTrafficManager.py` | Script di orchestrazione principale (avviare per primo) |
| `sumo_engine/simulationManager.py` | Runner simulazione SUMO |
| `backend_server/backend_server.py` | Server REST + MCP di persistenza |
| `trafficAgentic/src/traffic_agent/agent_core.py` | Loop agentico TrafficAgent |
| `trafficAgentic/src/orchestrator/orchestrator_core.py` | Loop agentico Orchestratore |
| `trafficAgentic/src/traffic_agent/agent_policies.py` | System prompt agente |
| `trafficAgentic/src/orchestrator/orchestrator_policies.py` | System prompt orchestratore |
| `trafficAgentic/src/traffic_agent/llm_connector.py` | Connettore LLM unificato |
| `trafficAgentic/clusteringTopology/topology_library.py` | Clustering K-Means + generazione topologia |
| `sumo_engine/mcp_server.py` | Strumenti FastMCP esposti agli agenti |
| `trafficAgentic/config/k8s/` | Manifest Kubernetes |
| `trafficAgentic/config/dashboards/` | Configurazioni JSON dashboard Grafana |
| `trafficAgentic/.env` | Credenziali LLM (da creare — non committato) |

---

## ⚠️ Limitazioni Conosciute e TODO

- Il mapping fase-politica è attualmente hardcoded (`PRIORITY_MAIN → phase_index: 0`, ecc.)
- La gestione degli errori MCP può essere resa più robusta su tutte le chiamate agli strumenti
- La stabilità di TraCI con comandi concorrenti richiede ulteriori test su reti di grandi dimensioni
- La modalità GUI (`sumo-gui`) richiede XQuartz su macOS; la modalità headless è consigliata per esecuzioni automatizzate
- Lo strumento di memoria stress per l'orchestratore non è ancora implementato lato MCP

---

## 📄 Licenza

Questo progetto è open source. Vedi [LICENSE](LICENSE) per i dettagli.

---

## Autori

| | | |
|:--:|:--:|:--:|
| <a href="https://github.com/BlackRaffo70"><img src="https://github.com/BlackRaffo70.png" width="110" alt="avatar Raffaele Neri"></a> | <a href="https://github.com/melomatte"><img src="https://github.com/melomatte.png" width="110" alt="avatar Matteo Melotti"></a> | <a href="https://github.com/MarcoCrisafulli5"><img src="https://github.com/MarcoCrisafulli5.png" width="110" alt="avatar Marco Crisafulli"></a> |
| **Raffaele Neri**<br/>[@BlackRaffo70](https://github.com/BlackRaffo70) | **Matteo Melotti**<br/>[@melottimatteo](https://github.com/melomatte) | **Marco Crisafulli**<br/>[@MarcoCrisafulli5](https://github.com/MarcoCrisafulli5) |
