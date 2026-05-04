FROM python:3.10-slim

# Evita che Python scriva file .pyc su disco e forza i log a stampare subito a schermo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install fastmcp httpx

# Impostiamo la directory di lavoro dentro il container
WORKDIR /app

# Copiamo il server MCP all'interno
COPY . /app

EXPOSE 8080

# Comando di avvio del server
CMD ["python", "mcp_server.py"]