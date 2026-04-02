# TrafficAgenticAi

Progetto Python per la gestione dei semafori tramite sistema Agentic AI, con supporto visivo grazie a simulatore SUMO (Simulation of Urban MObility).

## Struttura del progetto

```
TrafficAgenticAi/
├── clusteringTopology/   # Eseguire create_topologies.py (che si avvale di topology_builder.py) per la creazione delle topologie di ogni agent
├── agenticArchitecture/  # Nella cartella agent sono presenti i file che rappresentano l'agent, in simulation l'intermediario per la simulazione
├── urbanNetworks/        # Reti stradali urbane utilizzate nelle simulazioni
```

## Requisiti

- Python 3.11+
- SUMO (Simulation of Urban MObility)

## Setup

```bash
# Clona il repository
git clone https://github.com/melomatte/TrafficAgenticAi.git
cd TrafficAgenticAi

# Crea e attiva l'ambiente virtuale
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Installa le dipendenze
pip install -r requirements.txt
```
