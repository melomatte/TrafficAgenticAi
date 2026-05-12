FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Dipendenze Python
# Assicurati di avere: redis, httpx (per parlare col gateway), pydantic e la libreria del tuo LLM (es. openai o litellm)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copiamo tutto il codice dell'agente
COPY . /app

# Nessun EXPOSE necessario! L'agente non è un server, è un client.

# 3. Avvio automatico del ciclo di vita dell'agente
CMD ["uvicorn", "agent_service:app", "--host", "0.0.0.0", "--port", "8080"]