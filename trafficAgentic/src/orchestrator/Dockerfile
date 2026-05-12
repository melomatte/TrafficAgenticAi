FROM python:3.10-slim

# Evita che Python scriva file .pyc su disco e forza i log a stampare subito a schermo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Impostiamo la root del container
WORKDIR /app

# Gestione delle dipendenze
# Assicurati di avere un file requirements.txt nella cartella dell'orchestratore
# con dentro almeno: redis, openai (o litellm/quello che usi per l'LLM)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamo tutto il codice dell'orchestratore dentro /app
COPY . /app

# Avviamo direttamente lo script Python principale
CMD ["uvicorn", "orchestrator_service:app", "--host", "0.0.0.0", "--port", "8080"]