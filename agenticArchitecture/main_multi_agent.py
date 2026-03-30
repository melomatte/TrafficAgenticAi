'''
python3 agenticArchitecture/main_multi_agent.py --config /home/matteo/Documents/Scalable/TrafficAgenticAi/urbanNetworks/cross/sim.sumocfg --sumo-binary /usr/share/sumo/bin/sumo-gui
'''

import argparse
import json
import os
from sumo_adapter import SumoAdapter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TOTAL_STEPS = 2000
QUEUE_THRESHOLD = 10

STATE_NS_GREEN = "GGGggrrrrrGGGggrrrrr"
STATE_EW_GREEN = "rrrrrGGGggrrrrrGGGgg"
STATE_ALL_RED = "rrrrrrrrrrrrrrrrrrrr"

CURRENT_OPEN = "NS"


def main():
    global CURRENT_OPEN

    parser = argparse.ArgumentParser(description="Traffic multi-agent simulation")
    parser.add_argument("--config", "-c", required=True, help="Percorso al file .sumocfg della simulazione")
    parser.add_argument("--sumo-binary", "-s", required=True, help="Percorso al binario SUMO (sumo-gui)")
    args = parser.parse_args()

    config_path = args.config
    sumo_binary = args.sumo_binary

    # Ricava il nome della mappa dal percorso per il log
    map_name = os.path.splitext(os.path.basename(config_path))[0]
    log_file = os.path.join(BASE_DIR, f"../results/agent_results_{map_name}.json")

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    env = SumoAdapter(sumo_binary, config_path)
    env.start(use_gui=False)

    tls_ids = env.get_tls_ids()
    print("Config:", config_path)
    print("Semafori trovati:", tls_ids)

    if not tls_ids:
        print("Nessun semaforo trovato.")
        return

    tls_id = tls_ids[0]

    ns_lanes = ["n2c_0", "n2c_1", "s2c_0", "s2c_1"]
    ew_lanes = ["e2c_0", "e2c_1", "w2c_0", "w2c_1"]

    all_logs = []

    try:
        for step in range(TOTAL_STEPS):
            tls_state = env.get_state(tls_id)

            ns_queue = sum(
                tls_state["lanes"].get(lane, {}).get("halting", 0)
                for lane in ns_lanes
            )
            ew_queue = sum(
                tls_state["lanes"].get(lane, {}).get("halting", 0)
                for lane in ew_lanes
            )

            if CURRENT_OPEN == "NS":
                env.set_state(tls_id, STATE_NS_GREEN)

                if ew_queue >= QUEUE_THRESHOLD:
                    env.set_state(tls_id, STATE_ALL_RED)
                    env.step()
                    CURRENT_OPEN = "EW"

            else:
                env.set_state(tls_id, STATE_EW_GREEN)

                if ns_queue >= QUEUE_THRESHOLD:
                    env.set_state(tls_id, STATE_ALL_RED)
                    env.step()
                    CURRENT_OPEN = "NS"

            step_log = {
                "step": step,
                "tls_id": tls_id,
                "current_open": CURRENT_OPEN,
                "ns_queue": ns_queue,
                "ew_queue": ew_queue
            }
            all_logs.append(step_log)

            print(
                f"[STEP {step}] open={CURRENT_OPEN} | "
                f"ns_queue={ns_queue} | ew_queue={ew_queue}"
            )

            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(all_logs, f, indent=2)

            env.step()

    except KeyboardInterrupt:
        print("Interrotto.")
    finally:
        env.close()
        print("TraCI chiuso.")
        print(f"Log salvato in: {log_file}")


if __name__ == "__main__":
    main()
