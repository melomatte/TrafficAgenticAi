import json
import os
from sumo_adapter import SumoAdapter
from traffic_agent import TrafficAgent

SUMO_BINARY = "/Users/raffaele/sumo/bin/sumo"
CONFIG_PATH = "/Users/raffaele/PycharmProjects/TrafficAgenticAi/Simulazione Sumo/Prova_VialeAldini/osm.sumocfg"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "../results/agent_results.json")

NEIGHBORS_MAP = {
    "GS_3676669638": ["GS_3676669641"],
    "GS_3676669641": ["GS_3676669638", "cluster_250734679_250734904_3892417426"],
    "cluster_13513497278_13513497279_13513497280_13513497281_#3more": [],
    "cluster_250734679_250734904_3892417426": ["GS_3676669641", "cluster_252163030_252163109_4413681321"],
    "cluster_252163030_252163109_4413681321": ["cluster_250734679_250734904_3892417426", "joinedS_250734659_250734907"],
    "joinedS_250734659_250734907": ["cluster_252163030_252163109_4413681321"],
}

TOTAL_STEPS = 2000


def main():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # reset file
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    env = SumoAdapter(SUMO_BINARY, CONFIG_PATH)
    env.start(use_gui=False)

    tls_ids = env.get_tls_ids()
    print("Semafori trovati:", tls_ids)

    agents = {
        tls_id: TrafficAgent(
            tls_id=tls_id,
            neighbors=NEIGHBORS_MAP.get(tls_id, []),
            min_green_steps=10,
            queue_threshold=0
        )
        for tls_id in tls_ids
    }

    all_logs = []

    try:
        for step in range(TOTAL_STEPS):
            step_log = {
                "step": step,
                "agents": {}
            }

            states = {}
            messages = {}

            # osservazione
            for tls_id, agent in agents.items():
                state = agent.observe(env)
                msg = agent.build_message(state)

                states[tls_id] = state
                messages[tls_id] = msg

            # decisione
            for tls_id, agent in agents.items():
                neighbor_msgs = [messages[n] for n in agent.neighbors if n in messages]
                action = agent.decide(states[tls_id], neighbor_msgs)

                step_log["agents"][tls_id] = {
                    "state": states[tls_id],
                    "message_sent": messages[tls_id],
                    "messages_received": neighbor_msgs,
                    "action": action
                }

                print(
                    f"[STEP {step}] {tls_id} | "
                    f"action={action} | "
                    f"queue={states[tls_id]['total_queue']} | "
                    f"received={neighbor_msgs}"
                )

                current_phase = states[tls_id]["phase"]
                num_phases = states[tls_id]["num_phases"]

                if action == "NEXT_PHASE":
                    next_phase = (current_phase + 1) % num_phases
                    env.set_phase(tls_id, next_phase)
                else:
                    env.set_phase(tls_id, current_phase)

            all_logs.append(step_log)

            with open(LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(all_logs, f, indent=2)

            env.step()

    except KeyboardInterrupt:
        print("Interrotto.")
    finally:
        env.close()
        print("TraCI chiuso.")
        print(f"Log salvato in: {LOG_FILE}")


if __name__ == "__main__":
    main()