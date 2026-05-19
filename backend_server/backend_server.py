import shutil
import sqlite3
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File
import uvicorn
import os
from fastmcp import FastMCP

"""
comando per esecuzione (da root progetto):
    python3 backend_server/backend_server.py 

Script per server backend (sia api che mcp) su localhost porta 8000
"""

# Inizializzazione FastAPI principale
app = FastAPI(title="Traffic Persistence Backend")

# Inizializzazione Server MCP per i tool AI
mcp = FastMCP("TrafficPersistenceBackend")
BASE_DIR = os.getcwd()
DB_DIR = os.path.join(BASE_DIR, "backend_server", "data")
DB_PATH = os.path.join(DB_DIR, "traffic_state.db")

print(f"🧹 Pulizia cartella '{DB_DIR}'...")
if os.path.exists(DB_DIR):
    try:
        shutil.rmtree(DB_DIR)
    except Exception as e:
        print(f"Errore pulizia {DB_DIR}: {e}")
else:
    print(f"🧹 Cartella '{DB_DIR}' non esistente")

print(f"📁 Creazione cartella '{DB_DIR}'...")
os.makedirs(DB_DIR, exist_ok=True)

def init_db():
    """Inizializza lo schema SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Tabella Topologie
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topologies (
                agent_id TEXT PRIMARY KEY,
                topology_data TEXT,
                updated_at TIMESTAMP
            )
        ''')
        # Tabella Storico Stress
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stress_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                stress_value REAL,
                prompt_text TEXT,
                timestamp TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

# ==============================================================================
# 1. ENDPOINT REST STANDARD (Bootstrapping e Gestione Sistema)
# ==============================================================================

@app.post("/api/topology/{agent_id}")
async def upload_json_file(agent_id: str, file: UploadFile = File(...)):
    """Carica un file .json fisico e lo salva nel database come testo."""
    
    # 1. Leggiamo il contenuto del file
    file_content = await file.read()
    
    # 2. Validiamo che sia un JSON corretto
    try:
        # Decodifichiamo i byte in stringa e proviamo a parsarlo
        json_string = file_content.decode('utf-8')
        json_data = json.loads(json_string) 
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Il file caricato non è un JSON valido.")

    # 3. Lo salviamo nel DB come stringa di testo (esattamente come nel tuo originale)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO topologies (agent_id, topology_data, updated_at) VALUES (?, ?, ?)",
            (agent_id, json_string, datetime.now())
        )
        
    return {
        "status": "success", 
        "message": f"File '{file.filename}' salvato con successo per {agent_id}"
    }

@app.get("/api/topology/{agent_id}")
async def get_topology(agent_id: str):
    """Restituisce il JSON salvato."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topology_data FROM topologies WHERE agent_id = ?", (agent_id,))
        row = cursor.fetchone()
        
        if row:
            # FastAPI convertirà automaticamente questo dizionario in una risposta JSON
            return json.loads(row[0])
            
        raise HTTPException(status_code=404, detail=f"Topologia non trovata per {agent_id}")

@app.get("/api/stress")
async def get_stress_history(limit: int = 1000):
    """Restituisce gli ultimi stati di stress salvati."""
    with sqlite3.connect(DB_PATH) as conn:
        # Impostiamo row_factory per farci restituire dizionari invece di tuple
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Ordiniamo in modo decrescente (DESC) per avere i più recenti
        cursor.execute(
            "SELECT agent_id, stress_value AS stress_index, prompt_text, timestamp FROM stress_levels ORDER BY timestamp DESC LIMIT ?" 
            (limit,)
        )
        rows = cursor.fetchall()

    return [dict(row) for row in rows]

# ==============================================================================
# 2. TOOL MCP (Funzioni per gli Agenti LLM e Orchestratore)
# ==============================================================================

@mcp.tool()
def write_topology(agent_id: str, topology_data: dict) -> str:
    """Salva o aggiorna la topologia (incroci assegnati) per un agente (via LLM)."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO topologies (agent_id, topology_data, updated_at) VALUES (?, ?, ?)",
            (agent_id, json.dumps(topology_data), datetime.now())
        )
    return f"Topologia salvata per {agent_id}"

@mcp.tool()
def save_agent_stress(agent_id: str,stress_index: float,prompt_text: str) -> bool:
    """
    Salva lo stato di stress prodotto da un agente nel database.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stress_levels (agent_id, stress_value, prompt_text, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, stress_index, prompt_text, datetime.now())
        )
        # Il blocco 'with' esegue in automatico il conn.commit() in caso di successo
    
    return True


@mcp.tool()
def get_recent_stress(limit: int) -> list[dict]:
    """
    Restituisce gli ultimi stati di stress salvati dal database.
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Impostiamo row_factory per farci restituire dizionari invece di tuple
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Ordiniamo in modo decrescente (DESC) per avere i più recenti
        cursor.execute(
            "SELECT agent_id, stress_value AS stress_index, prompt_text, timestamp FROM stress_levels ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        
    # Convertiamo l'oggetto sqlite3.Row in un normale dizionario Python
    return [dict(row) for row in rows]

# Montiamo il server MCP all'interno dell'app FastAPI
# In questo modo FastAPI gestirà le rotte /api/* e l'app ASGI di FastMCP girerà sotto /mcp/*
app.mount("/mcp", mcp.http_app(transport="sse"))

if __name__ == "__main__":
    print("🚀 Avvio Backend Server...")
    print("   🌐 REST API: http://0.0.0.0:8000/api")
    print("   🛠️ MCP (SSE): http://0.0.0.0:8000/mcp/sse")
    uvicorn.run(app, host="0.0.0.0", port=8000)