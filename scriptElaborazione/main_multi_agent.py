import json
import os
from sumo_adapter import SumoAdapter

# per evitare problemi XQuartz usa sumo, non sumo-gui
SUMO_BINARY = "/usr/share/sumo/bin/sumo-gui"

MAPS = {
    "viale_aldini": "/Users/raffaele/PycharmProjects/TrafficAgenticAi/Simulazione Sumo/Prova_VialeAldini/osm.sumocfg",
    "cross": "/home/matteo/Documents/Scalable/TrafficAgenticAi/urbanNetworks/cross/sim.sumocfg",
}

MAP_NAME = "cross"
CONFIG_PATH = MAPS[MAP_NAME]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, f"../results/agent_results_{MAP_NAME}.json")

TOTAL_STEPS = 2000
QUEUE_THRESHOLD = 10

STATE_NS_GREEN = "GGGggrrrrrGGGggrrrrr"
STATE_EW_GREEN = "rrrrrGGGggrrrrrGGGgg"
STATE_ALL_RED = "rrrrrrrrrrrrrrrrrrrr"

CURRENT_OPEN = "NS"


def main():
    global CURRENT_OPEN

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    env = SumoAdapter(SUMO_BINARY, CONFIG_PATH)
    env.start(use_gui=False)

    tls_ids = env.get_tls_ids()
    print("Mappa selezionata:", MAP_NAME)
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

    # Apire Quartz
    # python3 Simulazione\ Sumo/scriptElaborazione/main_multi_agent.py
