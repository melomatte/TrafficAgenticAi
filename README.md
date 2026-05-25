# 🚦 TrafficAgenticAI

Un sistema di IA agentica multi-agente per il controllo intelligente e autonomo del traffico urbano, alimentato da SUMO, Modelli Linguistici di Grandi Dimensioni (LLM) e Kubernetes.

---

## 📋 Overview

TrafficAgenticAI è un progetto di ricerca e ingegneria che combina l'IA agentica con il simulatore di traffico SUMO (Simulation of Urban MObility) per costruire un sistema di gestione del traffico completamente autonomo e distribuito.

Il sistema divide una rete stradale urbana in zone geografiche utilizzando il clustering K-Means. A ciascuna zona è assegnato un TrafficAgent — un agente IA autonomo che osserva la congestione locale, ragiona utilizzando un LLM e agisce sui semafori in tempo reale tramite l'interfaccia TraCI di SUMO. Un agente globale Orchestrator (Orchestratore) coordina tutti gli agenti locali, analizzando le tendenze di stress in tutta la rete ed emettendo direttive strategiche.

L'intera infrastruttura degli agenti viene eseguita su Kubernetes (tramite Minikube), con uno stack completo di osservabilità (Prometheus, Grafana, Loki, Promtail) distribuito automaticamente all'avvio.

---

## ✨ Key Features

- 🧠 Processo decisionale basato su LLM — gli agenti ragionano usando OpenAI, LiteLLM, OpenRouter, o modelli locali (LM Studio)
- 🗺️ Clustering automatico delle zone — K-Means divide qualsiasi rete SUMO in k zone per gli agenti all'avvio
- 🤝 Gerarchia a due livelli — i TrafficAgent locali gestiscono la tattica; l'Orchestrator globale gestisce la strategia
- 🔌 Tool calling MCP — gli agenti interagiscono con SUMO tramite FastMCP (trasporto SSE)
- 🐳 Nativo per Kubernetes — gli agenti vengono eseguiti come StatefulSet, l'orchestratore come Deployment, tutto all'interno di Minikube
- 📊 Osservabilità completa — dashboard Grafana per stress, salute, prompt LLM e log pronti all'uso
- 🏙️ Reti urbane reali incluse — centro città di Bologna, Viale Aldini e griglie sintetiche

---

## 🗂️ Project Structure

```
TrafficAgenticAI/
│
├── agenticTrafficManager.py     ← Main entry point: bootstraps K8s, topology, monitoring
│
├── sumo_engine/                 ← SUMO simulation layer
│   ├── simulationManager.py     ← Runs SUMO via TraCI + triggers agentic loop
│   ├── mcp_server.py            ← FastMCP server: exposes traffic tools to agents
│   ├── shared_memory.py         ← Thread-safe state shared between SUMO and MCP
│   └── urbanNetworks/           ← SUMO network files
│       ├── cross/               ← Synthetic single intersection
│       ├── 2cross/              ← Synthetic 2-intersection network
│       ├── Ncross/              ← Large 80-node grid
│       ├── Prova_VialeAldini/   ← Real Bologna street (OSM)
│       ├── Simplified_bolo/     ← Simplified Bologna road network
│       └── Simplified_bolo_center/  ← Bologna city center (OSM)
│
├── trafficAgentic/              ← Agentic AI layer
│   ├── clusteringTopology/      ← K-Means network partitioning
│   │   ├── topology_builder.py  ← Builds topologies from SUMO .net.xml
│   │   └── topology_library.py  ← Network parsing, clustering, Token-Slim format
│   ├── src/
│   │   ├── traffic_agent/       ← Local agent (runs as K8s StatefulSet)
│   │   │   ├── agent_core.py    ← Agentic loop with MCP tool calling
│   │   │   ├── agent_service.py ← FastAPI service (receives triggers)
│   │   │   ├── agent_policies.py ← System prompt for the agent LLM
│   │   │   ├── llm_connector.py ← Unified LLM interface (OpenAI/LiteLLM/OpenRouter/Local)
│   │   │   ├── adapter_connector.py ← SDK adapters + unified response wrappers
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   └── orchestrator/        ← Global orchestrator (runs as K8s Deployment)
│   │       ├── orchestrator_core.py  ← Aggregates agent outputs, issues directives
│   │       ├── orchestrator_service.py ← FastAPI service
│   │       ├── orchestrator_policies.py ← System prompt for the orchestrator LLM
│   │       ├── llm_connector.py
│   │       ├── adapter_connector.py
│   │       ├── Dockerfile
│   │       └── requirements.txt
│   └── config/
│       ├── grafana.yaml         ← Helm values for Grafana/Prometheus stack
│       ├── loki-values.yaml     ← Helm values for Loki
│       ├── dashboards/          ← Custom Grafana dashboards (stress, health, prompts, logs)
│       └── k8s/                 ← Kubernetes manifests
│           ├── agent.yaml       ← StatefulSet for traffic-agent pods
│           └── orchestrator.yaml ← Deployment for orchestrator pod
│
└── backend_server/              ← Persistence layer (REST API + MCP)
    ├── backend_server.py        ← FastAPI + FastMCP server (port 8000)
    └── data/
        ├── agent_topologies/    ← Per-agent topology JSON files
        └── traffic_state.db     ← SQLite: topologies + stress history
```

---

## 🏗️ Architecture

<img width="807" height="814" alt="image" src="https://github.com/user-attachments/assets/94d26872-05b9-484b-b441-f80407b6badc" />


---

## 🔄 System Workflow

### 1. Bootstrap (`agenticTrafficManager.py`)
1. Parses the SUMO `.net.xml` of the chosen simulation
2. Applies **K-Means clustering** (k = number of agents) to spatially partition intersections and road edges
3. Generates a **Token-Slim topology** for each agent (compact `E_IN>E_OUT(DEST)` format optimized for LLM context)
4. Uploads topologies to the backend server (SQLite)
5. Starts Minikube, installs the monitoring stack via Helm
6. Builds Docker images for `agent` and `orchestrator` inside Minikube
7. Applies K8s manifests and scales the `traffic-agent` StatefulSet to k replicas
8. Opens port-forwards: `orchestrator-service:8080` and `grafana:3000`

### 2. Simulation (`simulationManager.py`)
1. Starts the **FastMCP server** (port 8001) in a background thread
2. Launches SUMO (headless or with GUI) and connects via TraCI
3. Each simulation step: reads lane-level vehicle and queue data into shared memory
4. Applies any **pending commands** (phase changes, duration changes) queued by agents
5. Every `decision_interval` steps: fires a POST to the Orchestrator to trigger one agentic cycle

### 3. Agentic Loop (per decision cycle)
```
SUMO → POST /trigger_agentic → Orchestrator
  └─► Dispatches all agents in parallel
        Each TrafficAgent:
          1. Connects to MCP server (persistent SSE)
          2. Sends initial message to LLM with system prompt + step ID + global directive
          3. LLM reasons and calls tools (up to MAX_ITERATIONS=5):
             ├── compute_stress_index(tls_ids)  → stress 0.0–100.0
             ├── compute_phase_duration(stress) → adaptive green duration
             ├── set_traffic_light_duration(tl_id, duration)
             └── set_traffic_light(tl_id, phase_index)
          4. Returns {stress_index, prompt_text, actions_taken}
  └─► Orchestrator collects all agent outputs
        Orchestrator LLM:
          1. Calls save_agent_stress for each agent → SQLite
          2. Calls get_recent_stress(limit=N) → stress history
          3. Analyzes current stress + historical trend
          4. Returns one directive per agent:
             prioritize_flow | hold_or_balance | reduce_aggressiveness
```

---

## 📐 Stress Index Formula

The stress index (0–100) is computed per-zone by the MCP tool `compute_stress_index`:

```
saturation   = min(total_queue / lane_capacity, 1.0)
               where lane_capacity = Σ(lane_length / 7.5)

halting_ratio = halting_vehicles / total_vehicles

inter_stress = (saturation × 60) + (halting_ratio × 40)

final_stress = mean(inter_stress) across managed intersections
```

| Range | Level | Agent behavior |
|-------|-------|----------------|
| < 10 | 🟢 Low | No action, maintain current configuration |
| 10–22 | 🟡 Moderate | Adjust phase duration adaptively |
| ≥ 22 | 🔴 High | May change traffic light phase policy |

---

## 🚀 Getting Started

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | ≥ 3.10 | Running SUMO engine and backend |
| SUMO | ≥ 1.18 | Traffic simulation |
| Docker | ≥ 24 | Container runtime for Minikube |
| Minikube | ≥ 1.32 | Local Kubernetes cluster |
| kubectl | ≥ 1.28 | K8s management |
| Helm | ≥ 3.12 | Installing monitoring stack |

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/melomatte/TrafficAgenticAi.git
cd TrafficAgenticAi

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

pip install -r requirements.txt

# 3. Set SUMO_HOME
export SUMO_HOME=/usr/share/sumo    # adjust to your SUMO installation path
```

### Configure LLM credentials

Create the file `trafficAgentic/.env` with your LLM credentials:

```env
# Using LiteLLM proxy (recommended — supports many models)
LLM_API_KEY=<your_api_key>
LLM_SDK=litellm
MODEL_NAME=<model_name>        # e.g. gemini/gemini-2.0-flash
PROVIDER=cloud

# Using OpenAI directly
LLM_API_KEY=<your_openai_key>
LLM_SDK=openai
MODEL_NAME=gpt-4o
PROVIDER=cloud

# Using OpenRouter
LLM_API_KEY=<your_openrouter_key>
LLM_SDK=openrouter
MODEL_NAME=<model_name>
PROVIDER=cloud

# Using a local model (LM Studio)
LLM_SDK=openai
MODEL_NAME=<local_model_name>
PROVIDER=local
```

---

## ▶️ Running the System

The system has **two independent processes** that must be started separately.

### Step 1 — Start the Backend Server

```bash
# From the project root
python3 backend_server/backend_server.py
```

The backend exposes:
- REST API on `http://localhost:8000` (topology upload)
- MCP server on `http://localhost:8000` (stress persistence tools for the orchestrator)

### Step 2 — Start the Agentic Infrastructure

```bash
# From the project root — launches Minikube, K8s, monitoring, agents
python3 trafficAgentic/agenticTrafficManager.py \
    --simulation_name 2cross \
    --k 2 \
    --memory 8192 \
    --cpus 4
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--simulation_name` | `2cross` | Name of the network folder under `sumo_engine/urbanNetworks/` |
| `--k` | `2` | Number of agents / clusters (must match available intersections) |
| `--memory` | `8192` | RAM (MB) allocated to Minikube |
| `--cpus` | `4` | CPU cores allocated to Minikube |

### Step 3 — Start the SUMO Simulation

```bash
# From the project root
python3 sumo_engine/simulationManager.py \
    --simulation_name 2cross \
    --decision_interval 60 \
    --gui false
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--simulation_name` | `2cross` | Network to simulate |
| `--decision_interval` | `60` | SUMO steps between agentic cycles |
| `--gui` | `false` | Set to `true` to enable SUMO graphical interface |

### Stopping

Press `Ctrl+C` in the `agenticTrafficManager` terminal. The cleanup handler will automatically:
- Close all port-forward tunnels
- Delete Kubernetes resources
- Stop Minikube

---

## 📊 Observability

Once running, Grafana is available at **http://localhost:3000** (credentials: `admin` / `admin`).

Four custom dashboards are pre-provisioned:

| Dashboard | Content |
|-----------|---------|
| **Health Dashboard** | Agent pod status, uptime, error rates |
| **Stress Dashboard** | Per-agent and global stress index over time |
| **Prompt Dashboard** | LLM prompt and response monitoring |
| **Logs Dashboard** | Full structured log stream (via Loki) |

All LLM interactions are logged as structured JSON to stdout and ingested by Promtail → Loki.

---

## 🌐 Available Urban Networks

| Network | Type | Description |
|---------|------|-------------|
| `cross` | Synthetic | Single 4-way intersection |
| `2cross` | Synthetic | Two connected intersections (default) |
| `Ncross` | Synthetic | 80-node grid (`grid80.net.xml`) |
| `Prova_VialeAldini` | Real (OSM) | Bologna — Viale Aldini corridor |
| `Simplified_bolo` | Real (OSM) | Simplified Bologna road network |
| `Simplified_bolo_center` | Real (OSM) | Bologna city center |

---

## 🧩 MCP Tools Reference

### SUMO Engine MCP Server (port 8001)

| Tool | Input | Output | Description |
|------|-------|--------|-------------|
| `compute_stress_index` | `tls_ids: list[str]` | `float` | Computes zone stress 0–100 from shared memory |
| `compute_phase_duration` | `stress_index: float` | `float` | Returns adaptive green duration (15–60 s) |
| `set_traffic_light_duration` | `tl_id, duration` | status | Queues a phase-duration change in SUMO |
| `set_traffic_light` | `tl_id, phase_index` | status | Queues a phase change in SUMO (with safe yellow transition) |

### Backend MCP Server (port 8000)

| Tool | Input | Output | Description |
|------|-------|--------|-------------|
| `save_agent_stress` | `agent_id, stress_index, prompt_text` | status | Persists agent stress snapshot to SQLite |
| `get_recent_stress` | `limit: int` | list | Returns the N most recent stress records |

---

## 🔧 LLM Provider Support

The `AgentConnector` provides a unified interface to multiple providers with zero changes to agent code:

| Provider | SDK | Configuration |
|----------|-----|---------------|
| OpenAI | `openai` | `LLM_SDK=openai` |
| LiteLLM proxy | `litellm` | `LLM_SDK=litellm` |
| OpenRouter | `openrouter` | `LLM_SDK=openrouter` |
| LM Studio (local) | OpenAI-compat | `PROVIDER=local` |

---

## 🗺️ Topology Format (Token-Slim)

To minimize LLM context usage, road network topologies are encoded in a compact **Token-Slim** format:

```
<junction_id>: <edge_in>><edge_out>(<destination>), ...
```

Example:
```
J1: E_north>E_south(J2), E_west>E_east(EXT), E_east>E_west(EXT)
J2: E_south>E_north(J1), E_east>E_exit(EXT)
```

This format is generated automatically from the SUMO `.net.xml` file during the bootstrap phase using K-Means clustering.

---

## 📋 Requirements

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

### Agent / Orchestrator pods
See `trafficAgentic/src/traffic_agent/requirements.txt` and `trafficAgentic/src/orchestrator/requirements.txt`.

---

## 📁 Key Files Quick Reference

| File | Role |
|------|------|
| `trafficAgentic/agenticTrafficManager.py` | Main orchestration script (run first) |
| `sumo_engine/simulationManager.py` | SUMO simulation runner |
| `backend_server/backend_server.py` | Persistence REST + MCP server |
| `trafficAgentic/src/traffic_agent/agent_core.py` | TrafficAgent agentic loop |
| `trafficAgentic/src/orchestrator/orchestrator_core.py` | Orchestrator agentic loop |
| `trafficAgentic/src/traffic_agent/agent_policies.py` | Agent system prompt |
| `trafficAgentic/src/orchestrator/orchestrator_policies.py` | Orchestrator system prompt |
| `trafficAgentic/src/traffic_agent/llm_connector.py` | Unified LLM connector |
| `trafficAgentic/clusteringTopology/topology_library.py` | K-Means clustering + topology generation |
| `sumo_engine/mcp_server.py` | FastMCP tools exposed to agents |
| `trafficAgentic/config/k8s/` | Kubernetes manifests |
| `trafficAgentic/config/dashboards/` | Grafana dashboard JSON configs |
| `trafficAgentic/.env` | LLM credentials (create this — not committed) |

---

## ⚠️ Known Limitations & TODOs

- Phase-to-policy mapping is currently hardcoded (`PRIORITY_MAIN → phase_index: 0`, etc.)
- MCP error handling can be made more robust across all tool calls
- TraCI stability with concurrent commands needs further testing on large networks
- GUI mode (sumo-gui) requires XQuartz on macOS; headless is recommended for automated runs
- Stress memory tool for the orchestrator is not yet implemented on the MCP side

---

## 📄 License

This project is open source. See [LICENSE](LICENSE) for details.

## Autori

| | | |
|:--:|:--:|:--:|
| <a href="https://github.com/BlackRaffo70"><img src="https://github.com/BlackRaffo70.png" width="110" alt="avatar Raffaele Neri"></a> | <a href="https://github.com/melomatte"><img src="https://github.com/melomatte.png" width="110" alt="avatar Matteo Melotti"></a> | <a href="https://github.com/marcocrisafulli"><img src="https://github.com/marcocrisafulli.png" width="110" alt="avatar Enrico Borsetti"></a> |
| **Raffaele Neri**<br/>[@BlackRaffo70](https://github.com/BlackRaffo70) | **Matteo Melotti**<br/>[@melottimatteo](https://github.com/melomatte) | **Marco Crisafulli**<br/>[@marcocrisafulli](https://github.com/marcocrisafulli) |

---
