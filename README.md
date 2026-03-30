# TrafficAgenticAi

Progetto Python per la gestione dei semafori tramite sistema Agentic AI, con supporto visivo grazie a simulatore SUMO (Simulation of Urban MObility).

## Struttura del progetto

```
TrafficAgenticAi/
├── utilsScript/          # Script Python utili per l'elaborazione
├── agenticArchitecture/  # Script per supporto sistema Agentic AI e supporto alla simulazione SUMO tramie TraCI
├── urbanNetworks/        # Reti stradali urbane utilizzate nelle simulazioni
├── results/              # Output e risultati delle elaborazioni
└── .gitignore            # File di esclusione Git
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
