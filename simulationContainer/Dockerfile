FROM ubuntu:22.04

# Evita richieste interattive durante l'installazione
ENV DEBIAN_FRONTEND=noninteractive

# Installazione SUMO, librerie grafiche X11 e Python
RUN apt-get update && apt-get install -y \
    sumo \
    sumo-tools \
    sumo-doc \
    python3 \
    python3-pip \
    libxext6 \
    libx11-6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installiamo requests per poter inviare il POST a FastAPI
RUN pip3 install traci requests fastapi uvicorn

# 3. Copia dello script
COPY simulationManager.py /app/simulationManager.py
COPY api_server.py /app/api_server.py
COPY shared_memory.py /app/shared_memory.py

# 4. Copia della cartella delle simulazioni (che ora è lì di fianco)
COPY urbanNetworks /app/simulations

# Resta in attesa dell'avvio da parte del manager
CMD ["sleep", "infinity"]