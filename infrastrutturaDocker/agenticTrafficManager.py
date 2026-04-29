import argparse
import os
import subprocess
import signal
import sys
import threading
import time
from clusteringTopology.topology_builder import build_topologies

LOG_DIR = "containerLogs"
os.makedirs(LOG_DIR, exist_ok=True)

def stream_docker_logs(container_name, filename):
    """Redireziona l'output continuo direttamente nel file specificato."""
    filepath = os.path.join(LOG_DIR, filename)
    with open(filepath, "w") as log_file:
        subprocess.Popen(
            ["docker", "logs", "-f", container_name], 
            stdout=log_file, 
            stderr=subprocess.STDOUT
        )

def cleanup(signum=None, frame=None):
    print("\n🛑 Arresto di tutti i container in corso...")
    subprocess.run(["docker", "compose", "down"])
    print("✅ Sistema stoppato in modo pulito.")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)

def run_application(simulation_name, decision_interval, k, outdir, provider, model_name):

    print("🏗️ 1. Avvio costruzione topologie prima della compose dei container\n")

    success = build_topologies(
        simulation_name=simulation_name,
        k=k if k is not None else 1, # Gestione sicura del valore k
        outdir=outdir
    )
    
    if not success:
        print("❌ Generazione fallita. Interruzione del manager.")
        sys.exit(1)
        
    print("✅ Topologie generate! Passo allo step successivo...")
    print("_"*50+"\n")

    # Per collegamento simulazione del container sumo_simulation
    print("🖥️ 2. Abilitazione server grafico X11 per SUMO-GUI...")
    os.system("xhost +local:docker > /dev/null 2>&1")
    print("_"*50+"\n")

    # Avvio docker -> forza la ricreazione se i container sono già presenti (per salvare nuove modifiche)
    print("🚀 3. Avvio infrastruttura Docker\n")

    # Creaazione ambiente di esecuzione (con variabili d'ambiente personalizzate per il compose) per subprocess.run (responsabile della creazione dell'infrastruttura docker) 
    docker_env = os.environ.copy()
    docker_env["MODEL_NAME"] = model_name
    docker_env["PROVIDER"] = provider

    try:
        
        subprocess.run(
            ["docker", "compose", "up", "--build", "--force-recreate", "-d"], 
            env=docker_env,
            check=True
        )

    except subprocess.CalledProcessError as e:
        print("\n❌ ERRORE CRITICO: Fallita la build o l'avvio dei container.")
        sys.exit(1)
    print("_"*50+"\n")

    # Scrittura dei log in file di testo
    print(f"📝 4. Aggancio ai log dei server in background. I log sono visibili dalla root del progetto nella cartella {LOG_DIR}")
    threading.Thread(target=stream_docker_logs, args=("mcp_server", "mcp_server.log"), daemon=True).start()
    threading.Thread(target=stream_docker_logs, args=("agentic_system", "agentic_systems.log"), daemon=True).start()
    threading.Thread(target=stream_docker_logs, args=("sumo_simulation", "sumo_simulation.log"), daemon=True).start()
    print("_"*50+"\n")

    # Breve pausa per essere sicuri che i server siano "in ascolto"
    print("Pausa di 3 secondi per garantire che tutti i server siano in ascolto..")
    time.sleep(3) 
    print("_"*50+"\n")

    # Avvio della simulazione in background -> Usando -d, lo script manda il comando e va subito avanti!
    print("🚗 5. Avvio della Simulazione SUMO in background...")
    subprocess.run([
        "docker", "exec", "-d", "sumo_simulation", "python3", "run_sim.py", 
        "--simulation_name", str(simulation_name), 
        "--decision_interval", str(decision_interval)
    ])
    print("_"*50+"\n")

    print("✅ Simulazione partita! (La finestra di SUMO si aprirà a breve)")
    print("👉 Premi Ctrl+C qui per spegnere l'intera infrastruttura.")
    print("_"*50+"\n")

    # Ctrl-C viene attivato il cleanup dei container
    signal.pause()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_name", default="2cross")
    parser.add_argument("--decision_interval", type=int, default=60)
    parser.add_argument("--k", type=int, help="Numero di cluster/agenti desiderato")
    # Attributo importante -> per adesso le topologie vengono messe nel container degli agent
    parser.add_argument("--outdir", default="agentContainer/agentArchitecture/topology", help="Posizione dove andranno le topologie prodotte")
    parser.add_argument("--provider", choices=["local", "cloud"], default="cloud", help="Scegli se usare LM Studio (local) o Gemini (cloud)")
    parser.add_argument("--model_name", choices=["gemini-2.5-pro", "vertex_ai/mistral-small-2503"], default="gemini-2.5-pro", help="Nome del modello cloud")

    args = parser.parse_args()

    run_application(args.simulation_name, args.decision_interval, args.k, args.outdir, args.provider, args.model_name)