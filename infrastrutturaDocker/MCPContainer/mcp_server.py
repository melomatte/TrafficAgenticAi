from fastmcp import FastMCP
import requests

# Inizializziamo il server MCP
mcp = FastMCP("MCPSimulationServer")

# L'indirizzo del server (unico client di traci) all'interno del container sumo_simulation
SUMO_API_URL = "http://sumo_simulation:5000"

@mcp.tool()
def get_intersection_metrics(tls_id: str) -> str:
    """Restituisce il numero di veicoli in coda per un dato incrocio."""
    try:
        response = requests.get(f"{SUMO_API_URL}/get_metrics/{tls_id}", timeout=2)
        return response.text
    except Exception as e:
        return f'{{"error": "{str(e)}"}}'

@mcp.tool()
def set_traffic_light_phase(tls_id: str, phase_index: int) -> str:
    """Forza un semaforo a passare a una fase specifica."""
    try:
        # Passiamo i parametri tramite query string
        url = f"{SUMO_API_URL}/set_phase?tls_id={tls_id}&phase_index={phase_index}"
        response = requests.post(url, timeout=2)
        if response.status_code == 200:
            return f"SUCCESS: Comando inviato per {tls_id} (Fase {phase_index})."
        return f"ERROR: Status {response.status_code}"
    except Exception as e:
        return f"ERROR: Impossibile inviare il comando: {str(e)}"

if __name__ == "__main__":
    print("🚀 Avvio MCP Server in ascolto...")
    mcp.run(transport="sse", host="0.0.0.0", port=8080)