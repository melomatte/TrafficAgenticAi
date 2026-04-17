import traci

class SumoAdapter:
    def __init__(self, sumo_binary, config_path):
        self.sumo_binary = sumo_binary
        self.config_path = config_path

    def start(self, use_gui=True, delay="100"):
        cmd = [
            self.sumo_binary,
            "-c", self.config_path,
        ]
        if use_gui:
            cmd += ["--start", "--delay", delay]

        traci.start(cmd)

    def close(self):
        traci.close()

    def step(self):
        traci.simulationStep()

    def get_tls_ids(self):
        return list(traci.trafficlight.getIDList())

    def get_controlled_lanes(self, tls_id):
        return list(set(traci.trafficlight.getControlledLanes(tls_id)))

    def get_phase(self, tls_id):
        return traci.trafficlight.getPhase(tls_id)

    def get_num_phases(self, tls_id):
        current_program = traci.trafficlight.getProgram(tls_id)
        logics = traci.trafficlight.getAllProgramLogics(tls_id)

        for logic in logics:
            if logic.programID == current_program:
                return len(logic.phases)

        return 1

    def set_phase(self, tls_id, phase):
        num_phases = self.get_num_phases(tls_id)
        if 0 <= phase < num_phases:
            traci.trafficlight.setPhase(tls_id, phase)

    def set_state(self, tls_id, state):
        traci.trafficlight.setRedYellowGreenState(tls_id, state)

    def get_tls_state_string(self, tls_id):
        return traci.trafficlight.getRedYellowGreenState(tls_id)

    def get_state(self, tls_id):
        lanes = self.get_controlled_lanes(tls_id)

        lane_data = {}
        total_queue = 0
        total_vehicles = 0

        for lane in lanes:
            halting = traci.lane.getLastStepHaltingNumber(lane)
            vehicles = traci.lane.getLastStepVehicleNumber(lane)
            mean_speed = traci.lane.getLastStepMeanSpeed(lane)

            lane_data[lane] = {
                "halting": halting,
                "vehicles": vehicles,
                "mean_speed": mean_speed,
            }

            total_queue += halting
            total_vehicles += vehicles

        return {
            "tls_id": tls_id,
            "phase": self.get_phase(tls_id),
            "num_phases": self.get_num_phases(tls_id),
            "total_queue": total_queue,
            "total_vehicles": total_vehicles,
            "lanes": lane_data,
        }

    def get_cluster_metrics(self, intersection_ids):
        """
        Raccoglie metriche aggregate per un gruppo di incroci.
        Restituisce un dict compatibile con TrafficAgent.decide().
        """
        data = {"intersections": []}

        for inter_id in intersection_ids:
            try:
                state = self.get_state(inter_id)
            except Exception:
                continue

            lanes_status = {}
            total_queue = 0
            total_vehicles = 0

            for lane_id, lane_data in state.get("lanes", {}).items():
                queue = lane_data.get("halting", 0)
                moving = lane_data.get("vehicle_count", 0)

                lanes_status[lane_id] = {
                    "queue": queue,
                    "moving": moving
                }

                total_queue += queue
                total_vehicles += moving

            data["intersections"].append({
                "id": inter_id,
                "total_queue": total_queue,
                "total_vehicles": total_vehicles,
                "lanes_status": lanes_status
            })

        return data