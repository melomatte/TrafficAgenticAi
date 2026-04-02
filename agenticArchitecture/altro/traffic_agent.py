class TrafficAgent:
    def __init__(self, tls_id, neighbors=None, min_green_steps=15, max_green_steps=40, queue_threshold=10):
        self.tls_id = tls_id
        self.neighbors = neighbors or []
        self.min_green_steps = min_green_steps
        self.max_green_steps = max_green_steps
        self.queue_threshold = queue_threshold
        self.steps_in_current_phase = 0
        self.last_phase = None

    def observe(self, env):
        state = env.get_state(self.tls_id)

        if self.last_phase is None:
            self.last_phase = state["phase"]

        if state["phase"] == self.last_phase:
            self.steps_in_current_phase += 1
        else:
            self.steps_in_current_phase = 0
            self.last_phase = state["phase"]

        state["steps_in_current_phase"] = self.steps_in_current_phase
        return state

    def build_message(self, state):
        return {
            "tls_id": self.tls_id,
            "queue": state["total_queue"],
            "phase": state["phase"],
            "vehicles": state["total_vehicles"],
        }

    def decide(self, state, neighbor_messages):
        my_queue = state["total_queue"]
        neighbor_queue = sum(msg["queue"] for msg in neighbor_messages)
        time_in_phase = state["steps_in_current_phase"]

        # Rosso fisso finché non ci sono almeno 10 auto in coda
        if my_queue < self.queue_threshold:
            return "FORCE_RED"

        if time_in_phase < self.min_green_steps:
            return "HOLD"

        if time_in_phase >= self.max_green_steps:
            return "NEXT_PHASE"

        if neighbor_queue > my_queue:
            return "NEXT_PHASE"

        return "HOLD"