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
        return len(traci.trafficlight.getAllProgramLogics(tls_id)[0].phases)

    def set_phase(self, tls_id, phase):
        traci.trafficlight.setPhase(tls_id, phase)

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