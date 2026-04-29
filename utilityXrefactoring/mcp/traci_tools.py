import traci

def get_stress_index(intersection_ids: list[str] | None = None) -> dict:
    """
    Compute the Stress Index (0-100) for a list of intersections (traffic lights).
    If no IDs provided, uses all traffic lights in the simulation.
    """
    tl_ids = intersection_ids or list(traci.trafficlight.getIDList())
    
    intersections = []
    for tl_id in tl_ids:
        controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
        # Deduplicate while preserving order
        seen = set()
        unique_lanes = [l for l in controlled_lanes if not (l in seen or seen.add(l))]
        
        lanes_status = {}
        total_queue = 0
        total_vehicles = 0

        for lane_id in unique_lanes:
            halting  = traci.lane.getLastStepHaltingNumber(lane_id)
            vehicles = traci.lane.getLastStepVehicleNumber(lane_id)
            moving   = vehicles - halting
            length   = traci.lane.getLength(lane_id)

            lanes_status[lane_id] = {
                "length":   length,
                "halting":  halting,
                "moving":   moving,
                "vehicles": vehicles,
            }
            total_queue    += halting
            total_vehicles += vehicles

        intersections.append({
            "id":            tl_id,
            "total_vehicles": total_vehicles,
            "total_queue":    total_queue,
            "lanes_status":   lanes_status,
        })

    index = compute_stress_index(intersections)

    return {
        "stress_index":    index,
        "intersections":   len(tl_ids),
        "sim_time":        traci.simulation.getTime(),
        "detail":          [
            {
                "id":       i["id"],
                "vehicles": i["total_vehicles"],
                "queue":    i["total_queue"],
            }
            for i in intersections
        ],
    }


def compute_stress_index(intersections: list) -> float:
    if not intersections:
        return 0

    total_stress = 0
    counted = 0

    for inter in intersections:
        total_v = inter.get("total_vehicles", 0)
        if total_v == 0:
            continue

        capacita_totale_incrocio = sum(
            l_data.get("length", 150) / 7.5
            for l_data in inter.get("lanes_status", {}).values()
        )
        capacita_totale_incrocio = max(capacita_totale_incrocio, 1)

        saturation    = min(inter.get("total_queue", 0) / capacita_totale_incrocio, 1.0)
        moving        = sum(l["moving"] for l in inter.get("lanes_status", {}).values())
        halting_ratio = (total_v - moving) / total_v

        total_stress += (saturation * 60) + (halting_ratio * 40)
        counted += 1

    return round(total_stress / counted, 2) if counted else 0.0

def simulation_step(steps: int = 1) -> dict:
    """Advance the simulation by N steps."""
    for _ in range(steps):
        traci.simulationStep()
    return {
        "time": traci.simulation.getTime(),
        "vehicles": traci.vehicle.getIDCount(),
    }

def get_vehicle_data(vehicle_id: str) -> dict:
    """Get position, speed, lane for a vehicle."""
    return {
        "position": traci.vehicle.getPosition(vehicle_id),
        "speed":    traci.vehicle.getSpeed(vehicle_id),
        "lane":     traci.vehicle.getLaneID(vehicle_id),
        "edge":     traci.vehicle.getRoadID(vehicle_id),
    }

def list_vehicles() -> list[str]:
    return traci.vehicle.getIDList()

def set_traffic_light(tl_id: str, phase_index: int) -> str:
    traci.trafficlight.setPhase(tl_id, phase_index)
    return f"TL {tl_id} set to phase {phase_index}"

def set_vehicle_speed(vehicle_id: str, speed: float, duration: float = 10.0) -> str:
    traci.vehicle.slowDown(vehicle_id, speed, duration)
    return f"{vehicle_id} slowing to {speed} m/s"

def add_vehicle(vehicle_id: str, route_id: str, depart: float = 0) -> str:
    traci.vehicle.add(vehicle_id, route_id, depart=str(depart))
    return f"Added {vehicle_id} on route {route_id}"

def get_edge_occupancy(edge_id: str) -> dict:
    return {
        "vehicle_count": traci.edge.getLastStepVehicleNumber(edge_id),
        "mean_speed":    traci.edge.getLastStepMeanSpeed(edge_id),
        "occupancy":     traci.edge.getLastStepOccupancy(edge_id),
    }