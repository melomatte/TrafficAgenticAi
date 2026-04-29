from fastmcp import FastMCP
import httpx

# Inizializziamo il server MCP
mcp = FastMCP("MCPSimulationServer")

# L'indirizzo del server (unico client di traci) all'interno del container sumo_simulation
SUMO_API_URL = "http://sumo_simulation:5000"

@mcp.tool()
async def compute_stress_index(tls_ids: list[str]) -> float:
    """
    Compute the stress level (0.0 - 100.0) of the specified intersections (Traffic Lights).
    Pass the list of traffic light IDs you manage.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUMO_API_URL}/compute_stress_index", 
                json={"tls_ids": tls_ids},
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            
        return float(data["stress_index"])
        
    except Exception as e:
        print(f"Errore MCP: {e}")
        return 0.0
    
if __name__ == "__main__":
    print("🚀 Avvio MCP Server in ascolto...")
    mcp.run(transport="sse", host="0.0.0.0", port=8080)