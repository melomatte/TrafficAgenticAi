from fastmcp import FastMCP
from utilityXrefactoring.mcp.sim_manager import SimManager
import utilityXrefactoring.mcp.traci_tools as tt
import os

mcp = FastMCP("traci-mcp")

sim = SimManager(
    host=os.environ.get("SUMO_HOST", "127.0.0.1"),
    port=int(os.environ.get("SUMO_PORT", 8813)),
)

@mcp.tool()
def simulation_step(steps: int = 1) -> dict:
    """Advance the simulation by N steps."""
    return tt.simulation_step(steps)

@mcp.tool()
def list_vehicles() -> list[str]:
    """List all active vehicle IDs in the simulation."""
    return tt.list_vehicles()

@mcp.tool()
def get_vehicle_data(vehicle_id: str) -> dict:
    """Get position, speed, lane and edge for a vehicle."""
    return tt.get_vehicle_data(vehicle_id)

@mcp.tool()
def set_traffic_light(tl_id: str, phase_index: int) -> str:
    """Set a traffic light to a specific phase index."""
    return tt.set_traffic_light(tl_id, phase_index)

@mcp.tool()
def set_vehicle_speed(vehicle_id: str, speed: float, duration: float = 10.0) -> str:
    """Override a vehicle's speed for a given duration (seconds)."""
    return tt.set_vehicle_speed(vehicle_id, speed, duration)

@mcp.tool()
def add_vehicle(vehicle_id: str, route_id: str, depart: float = 0) -> str:
    """Inject a new vehicle into the simulation on a given route."""
    return tt.add_vehicle(vehicle_id, route_id, depart)

@mcp.tool()
def get_edge_occupancy(edge_id: str) -> dict:
    """Get vehicle count, mean speed and occupancy for a road edge."""
    return tt.get_edge_occupancy(edge_id)

@mcp.tool()
def get_stress_index(intersection_ids: list[str] | None = None) -> dict:
    """
    Compute the network Stress Index (0-100) across all or selected intersections.
    0 = free flow, 100 = full gridlock.
    Omit intersection_ids to evaluate the entire network.
    """
    return tt.get_stress_index(intersection_ids)


if __name__ == "__main__":
    sim.start()
    mcp.run(transport="http", host="localhost", port=8000)