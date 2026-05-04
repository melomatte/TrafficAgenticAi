from fastmcp import FastMCP
import httpx
import time

mcp = FastMCP("MCPSimulationServer")

SUMO_API_URL = "http://sumo_simulation:5000"

# Memoria temporanea lato MCP
stress_memory: list[dict] = []
global_directive_memory: list[dict] = []


@mcp.tool()
async def compute_stress_index(tls_ids: list[str]) -> float:
    """
    Calcola lo stress index degli incroci indicati.
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

        return float(data.get("stress_index", 0.0))

    except Exception as e:
        print(f"Errore MCP compute_stress_index: {e}")
        return 0.0


@mcp.tool()
async def set_traffic_light(tl_id: str, phase_index: int) -> dict:
    """
    Imposta la fase di un semaforo in SUMO.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUMO_API_URL}/set_traffic_light",
                json={
                    "tl_id": tl_id,
                    "phase_index": phase_index
                },
                timeout=5.0
            )
            response.raise_for_status()

        return {
            "status": "ok",
            "tl_id": tl_id,
            "phase_index": phase_index
        }

    except Exception as e:
        print(f"Errore MCP set_traffic_light: {e}")
        return {
            "status": "error",
            "tl_id": tl_id,
            "phase_index": phase_index,
            "error": str(e)
        }


@mcp.tool()
async def save_agent_stress(
    agent_id: str,
    stress_index: float,
    prompt_text: str
) -> bool:
    """
    Salva lo stato di stress prodotto da un agente.
    """
    item = {
        "agent_id": agent_id,
        "stress_index": stress_index,
        "prompt_text": prompt_text,
        "timestamp": time.time()
    }

    stress_memory.append(item)

    # Mantiene solo gli ultimi 100 record
    del stress_memory[:-100]

    return True


@mcp.tool()
async def get_recent_stress(limit: int) -> list[dict]:
    """
    Restituisce gli ultimi stati di stress salvati.
    """
    return stress_memory[-limit:]


@mcp.tool()
async def save_global_directive(
    action: str,
    target_agent: str | None,
    reasoning: str
) -> dict:
    """
    Salva l'ultima direttiva prodotta dall'orchestratore.
    """
    directive = {
        "action": action,
        "target_agent": target_agent,
        "reasoning": reasoning,
        "timestamp": time.time()
    }

    global_directive_memory.append(directive)

    del global_directive_memory[:-50]

    return {
        "status": "ok",
        "saved": directive
    }


@mcp.tool()
async def get_last_global_directive() -> dict:
    """
    Restituisce l'ultima direttiva globale salvata.
    """
    if not global_directive_memory:
        return {
            "action": "hold_current",
            "target_agent": None,
            "reasoning": "No directive available"
        }

    return global_directive_memory[-1]


if __name__ == "__main__":
    print("🚀 Avvio MCP Server in ascolto...")
    mcp.run(transport="sse", host="0.0.0.0", port=8080)