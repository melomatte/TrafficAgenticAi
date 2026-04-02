'''
python3 agenticArchitecture/main_multi_agent.py --config /home/matteo/Documents/Scalable/TrafficAgenticAi/urbanNetworks/cross/sim.sumocfg --sumo-binary /usr/share/sumo/bin/sumo-gui
'''
import argparse
import json
import os
from agenticArchitecture.simulation.sumo_adapter import SumoAdapter

# Cartella base dello script, usata per costruire il path del file di log
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Numero totale di step della simulazione
TOTAL_STEPS = 2000

# Soglia di veicoli in coda oltre la quale si esegue il cambio di fase
QUEUE_THRESHOLD = 10

# Stringhe di stato del semaforo (una lettera per ogni corsia controllata):
# G = verde, g = verde non prioritario, r = rosso
STATE_NS_GREEN = "GGGggrrrrrGGGggrrrrr"  # Verde per Nord-Sud, rosso per Est-Ovest
STATE_EW_GREEN = "rrrrrGGGggrrrrrGGGgg"  # Verde per Est-Ovest, rosso per Nord-Sud
STATE_ALL_RED  = "rrrrrrrrrrrrrrrrrrrr"  # Tutto rosso (usato durante la transizione)

# Direzione attualmente con il verde (NS = Nord-Sud, EW = Est-Ovest)
CURRENT_OPEN = "NS"


def main():
    global CURRENT_OPEN

    # --- Parsing degli argomenti da riga di comando ---
    parser = argparse.ArgumentParser(description="Traffic multi-agent simulation")
    parser.add_argument("--config", "-c", required=True, help="Percorso al file .sumocfg della simulazione")
    parser.add_argument("--sumo-binary", "-s", required=True, help="Percorso al binario SUMO (sumo o sumo-gui)")
    args = parser.parse_args()

    config_path = args.config       # Path al file di configurazione della simulazione
    sumo_binary = args.sumo_binary  # Path al binario SUMO da usare

    # Ricava il nome della mappa dal nome del file .sumocfg (senza estensione)
    # Es: "/path/to/sim.sumocfg" -> map_name = "sim"
    map_name = os.path.splitext(os.path.basename(config_path))[0]

    # Path del file JSON dove verranno salvati i log della simulazione
    log_file = os.path.join(BASE_DIR, f"../results/agent_results_{map_name}.json")

    # Crea la cartella dei risultati se non esiste
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Inizializza il file di log con una lista vuota
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    # --- Avvio della simulazione ---
    env = SumoAdapter(sumo_binary, config_path)
    env.start(use_gui=False)  # use_gui=False per eseguire senza interfaccia grafica

    # Recupera la lista degli ID dei semafori presenti nella rete
    tls_ids = env.get_tls_ids()
    print("Config:", config_path)
    print("Semafori trovati:", tls_ids)

    if not tls_ids:
        print("Nessun semaforo trovato.")
        return

    # Prende il primo semaforo disponibile nella rete
    tls_id = tls_ids[0]

    # Corsie afferenti all'asse Nord-Sud (2 corsie per direzione)
    ns_lanes = ["n2c_0", "n2c_1", "s2c_0", "s2c_1"]

    # Corsie afferenti all'asse Est-Ovest (2 corsie per direzione)
    ew_lanes = ["e2c_0", "e2c_1", "w2c_0", "w2c_1"]

    # Lista che accumula i log di ogni step per la scrittura su file
    all_logs = []

    try:
        for step in range(TOTAL_STEPS):

            # Legge lo stato corrente del semaforo (code, veicoli, velocità per corsia)
            tls_state = env.get_state(tls_id)

            # Calcola il totale dei veicoli in coda sull'asse Nord-Sud
            ns_queue = sum(
                tls_state["lanes"].get(lane, {}).get("halting", 0)
                for lane in ns_lanes
            )

            # Calcola il totale dei veicoli in coda sull'asse Est-Ovest
            ew_queue = sum(
                tls_state["lanes"].get(lane, {}).get("halting", 0)
                for lane in ew_lanes
            )

            # --- Logica di controllo del semaforo ---
            if CURRENT_OPEN == "NS":
                # Mantieni il verde sull'asse Nord-Sud
                env.set_state(tls_id, STATE_NS_GREEN)

                # Se la coda Est-Ovest supera la soglia, transizione verso EW
                if ew_queue >= QUEUE_THRESHOLD:
                    env.set_state(tls_id, STATE_ALL_RED)  # Step di transizione a tutto rosso
                    env.step()
                    CURRENT_OPEN = "EW"

            else:
                # Mantieni il verde sull'asse Est-Ovest
                env.set_state(tls_id, STATE_EW_GREEN)

                # Se la coda Nord-Sud supera la soglia, transizione verso NS
                if ns_queue >= QUEUE_THRESHOLD:
                    env.set_state(tls_id, STATE_ALL_RED)  # Step di transizione a tutto rosso
                    env.step()
                    CURRENT_OPEN = "NS"

            # --- Logging ---
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

            # Sovrascrive il file di log ad ogni step (permette di leggere i dati anche a simulazione in corso)
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(all_logs, f, indent=2)

            # Avanza la simulazione di un passo temporale
            env.step()

    except KeyboardInterrupt:
        print("Interrotto.")
    finally:
        # Chiude la connessione TraCI in ogni caso (anche in caso di errore)
        env.close()
        print("TraCI chiuso.")
        print(f"Log salvato in: {log_file}")


if __name__ == "__main__":
    main()