FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 1. Impostiamo la root del container
WORKDIR /app

# 2. Installiamo i pacchetti di sistema essenziali
RUN apt-get update && \
    apt-get install -y build-essential python3-dev && \
    rm -rf /var/lib/apt/lists/*

# 3. Gestione dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiamo tutto il codice dell'agente dentro /app [cite: 3]
COPY . .

EXPOSE 8000

WORKDIR /app/agentArchitecture

# 6. Avviamo Uvicorn puntando al file simulation_listener.py 
CMD ["uvicorn", "simulation_listener:app", "--host", "0.0.0.0", "--port", "8000"]