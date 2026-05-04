import argparse
import glob
import os
import platform
import subprocess
import signal
import sys
import threading
import time
from dotenv import load_dotenv  
from clusteringTopology.topology_builder import build_topologies

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
LOG_DIR = "containerLogs"
os.makedirs(LOG_DIR, exist_ok=True)

AGENT_LOG_DIR = "agentLogs"
os.makedirs(AGENT_LOG_DIR, exist_ok=True)

# Pulizia automatica delle vecchie simulazioni
print(f"🧹 Pulizia vecchi log degli agenti in '{AGENT_LOG_DIR}'...")
for filepath in glob.glob(os.path.join(AGENT_LOG_DIR, "*")):
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"⚠️ Impossibile rimuovere il vecchio log {filepath}: {e}")

PLATFORM = platform.system()   # "Linux" | "Darwin" | "Windows"

# Evento cross-platform usato al posto di signal.pause() -> (non disponibile su Windows)
_shutdown_event = threading.Event()

# ---------------------------------------------------------------------------
# Funzioni per diagnostica
# ---------------------------------------------------------------------------

def _header(step: int, text: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {step}. {text}")
    print(f"{'='*50}")

def _fatal(message: str, hint: str = "") -> None:
    """Stampa un errore strutturato e termina."""
    print(f"\n❌  ERRORE: {message}")
    if hint:
        print(f"    ↳ {hint}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Controllo prerequisiti Docker
# ---------------------------------------------------------------------------

def check_docker() -> None:
    """Verifica che Docker sia installato e il daemon sia raggiungibile."""
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except FileNotFoundError:
        hints = {
            "Linux":   "Installa Docker Engine: https://docs.docker.com/engine/install/",
            "Darwin":  "Installa Docker Desktop per Mac: https://docs.docker.com/desktop/mac/install/",
            "Windows": "Installa Docker Desktop per Windows: https://docs.docker.com/desktop/windows/install/",
        }
        _fatal("Docker non trovato nel PATH.", hints.get(PLATFORM, "Installa Docker."))
    except subprocess.CalledProcessError:
        hints = {
            "Linux":   "Avvia il daemon con: sudo systemctl start docker",
            "Darwin":  "Avvia Docker Desktop dall'icona nella barra dei menu.",
            "Windows": "Avvia Docker Desktop dal menu Start.",
        }
        _fatal(
            "Docker è installato ma il daemon non risponde.",
            hints.get(PLATFORM, "Avvia il daemon Docker."),
        )


# ---------------------------------------------------------------------------
# Configurazione GUI X11 (dipendente dalla piattaforma)
# ---------------------------------------------------------------------------

def setup_gui() -> bool:
    """
    Abilita l'accesso al server X11 per la GUI di SUMO.
    Restituisce True se la configurazione è riuscita, False altrimenti.
    """
    if PLATFORM == "Linux":
        ret = os.system("xhost +local:docker > /dev/null 2>&1")
        if ret != 0:
            print("⚠️  xhost fallito: nessun server X in esecuzione.")
            print("    ↳ Avvia una sessione grafica oppure usa --no-gui.")
            return False
        print("   ✔ xhost configurato (Linux).")
        return True

    elif PLATFORM == "Darwin":
        print("   macOS rilevato.")
        print("   ↳ Assicurati che XQuartz sia installato e in esecuzione.")
        print("     Installa da: https://www.xquartz.org/")
        print("     Poi esegui nel terminale XQuartz: xhost +localhost")
        ret = os.system("xhost +localhost > /dev/null 2>&1")
        if ret != 0:
            print("⚠️  xhost non disponibile: la finestra SUMO potrebbe non aprirsi.")
            return False
        else:
            print("   ✔ xhost configurato (macOS/XQuartz).")
            return True

    elif PLATFORM == "Windows":
        print("   Windows rilevato.")
        print("   ↳ Per la GUI di SUMO è necessario un X server esterno (es. VcXsrv o X410).")
        print("     1. Installa VcXsrv: https://sourceforge.net/projects/vcxsrv/")
        print("     2. Avvialo con 'Disable access control' attivo.")
        print("     3. Imposta la variabile d'ambiente DISPLAY=host.docker.internal:0")
        if not os.environ.get("DISPLAY"):
            print("⚠️  DISPLAY non impostata: la finestra SUMO probabilmente non si aprirà.")
            return False
        print("   ✔ DISPLAY trovata (Windows).")
        return True

    print(f"⚠️  Piattaforma '{PLATFORM}' non riconosciuta: skip configurazione X11.")
    return False


# ---------------------------------------------------------------------------
# Gestione intelligente dei container Docker
# ---------------------------------------------------------------------------

def _get_compose_services() -> set:
    """Restituisce i servizi definiti nel docker-compose.yml corrente."""
    result = subprocess.run(
        ["docker", "compose", "config", "--services"],
        capture_output=True, text=True,
    )
    return set(result.stdout.strip().splitlines()) if result.returncode == 0 else set()


def _get_running_services() -> set:
    """Restituisce i servizi attualmente in esecuzione."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        capture_output=True, text=True,
    )
    return set(result.stdout.strip().splitlines()) if result.returncode == 0 else set()


def smart_compose_up(docker_env: dict) -> None:
    """
    Avvia o aggiorna i container in modo efficiente:

    • Nessun container attivo  → build + up completo (prima esecuzione).
    • Container già attivi      → rebuild solo delle immagini cambiate,
                                  ricreazione solo dei container aggiornati,
                                  rimozione dei container orfani (servizi
                                  eliminati dal compose).

    La chiave è NON usare --force-recreate: Docker ricrea solo ciò che
    è effettivamente cambiato, sfruttando la cache dei layer.
    """
    defined = _get_compose_services()
    running = _get_running_services()
    missing = defined - running

    if not running:
        print("   Nessun container attivo. Avvio completo dell'infrastruttura...")
    elif missing:
        print(f"   Container parzialmente attivi.")
        print(f"   ✔ In esecuzione : {', '.join(sorted(running))}")
        print(f"   ✗ Mancanti      : {', '.join(sorted(missing))}")
        print("   Avvio dei container mancanti e aggiornamento degli esistenti...")
    else:
        print(f"   Tutti i container sono attivi: {', '.join(sorted(running))}")
        print("   Aggiornamento incrementale (solo immagini o config cambiate)...")

    # --build         : ricostruisce solo le immagini con contesto modificato
    # --remove-orphans: rimuove container di servizi rimossi dal compose
    # NO --force-recreate: evita ricreazioni inutili
    cmd = ["docker", "compose", "up", "--build", "--remove-orphans", "--force-recreate", "-d"]
    try:
        subprocess.run(cmd, env=docker_env, check=True)
    except subprocess.CalledProcessError:
        print("\n❌ ERRORE: Fallita la build o l'avvio dei container.")
        print("   Possibili cause:")
        print("   • Porta già occupata  → docker ps  per vedere i processi attivi")
        print("   • Errore Dockerfile   → docker compose logs  per i dettagli")
        if PLATFORM == "Linux":
            print("   • Permessi insufficienti → aggiungi il tuo utente al gruppo 'docker'")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def stream_docker_logs(container_name: str, filename: str) -> None:
    """Redireziona l'output continuo del container nel file specificato."""
    filepath = os.path.join(LOG_DIR, filename)
    with open(filepath, "w") as log_file:
        subprocess.Popen(
            ["docker", "logs", "-f", container_name],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup(signum=None, frame=None) -> None:
    print("\n🛑 Arresto di tutti i container in corso...")
    subprocess.run(["docker", "compose", "down"])
    print("✅ Sistema stoppato in modo pulito.")
    _shutdown_event.set()   # sblocca il wait() nel main
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
if PLATFORM != "Windows":
    # SIGTERM non esiste su Windows
    signal.signal(signal.SIGTERM, cleanup)


# ---------------------------------------------------------------------------
# Entry point principale
# ---------------------------------------------------------------------------

def run_application(simulation_name,decision_interval,k,outdir,gui):
    
    # 0. Prerequisiti
    check_docker()

    # 1. Creazione topologie
    _header(1, "Costruzione topologie")
    success = build_topologies(
        simulation_name=simulation_name,
        k=k if k is not None else 1,
        outdir=outdir,
    )

    if not success:
        _fatal("Generazione topologie fallita.")
    print("✅ Topologie generate correttamente")

    # 2. GUI X11 -> per visione simulazione nonostante stia girando in ambiente containerizzato
    _header(2, "Configurazione GUI")
    if gui == "true":
        setup_gui()
    else:
        print("   Modalità headless: skip configurazione X11.")

    # 3. Creazione infrastruttura Docker
    """ 
    Per la corretta creazione dell'infrastruttura è necessario creare un file .env (nella root del progetto) con struttura:
        LLM_API_KEY=<CHIAVE>
        LLM_SDK=litellm
        MODEL_NAME=[gemini-2.5-pro,vertex_ai/mistral-small-2503] 
        PROVIDER=[cloud, local]
    """
    _header(3, "Avvio infrastruttura Docker")
    load_dotenv()            
    docker_env = os.environ.copy()
    smart_compose_up(docker_env)
    print("✅ Infrastruttura pronta.")

    # 4. Aggancio log dei container in background
    _header(4, f"Aggancio ai log (cartella: {LOG_DIR}/)")
    for container, logfile in [
        ("mcp_server",      "mcp_server.log"),
        ("agentic_system",  "agentic_systems.log"),
    ]:
        threading.Thread(
            target=stream_docker_logs,
            args=(container, logfile),
            daemon=True,
        ).start()
        print(f"   📄 {container} → {LOG_DIR}/{logfile}")

    # 5. Attesa server
    print(f"\n⏳ Pausa di 3 secondi per garantire che tutti i server siano in ascolto...")
    time.sleep(3)

    # 6. Avvio simulazione SUMO -> stampa direttamente a riga di comando
    _header(6, "Avvio Simulazione SUMO")
    if gui == "true":
        print("   (La finestra di SUMO si aprirà a breve)")
    print("👉 Premi Ctrl+C per spegnere l'intera infrastruttura.")
    print("_"*50+"\n")

    result = subprocess.run([
        "docker", "exec", "sumo_simulation",
        "python3", "simulationManager.py",
        "--simulation_name",   str(simulation_name),
        "--decision_interval", str(decision_interval),
        "--gui", str(gui),
    ])
    if result.returncode != 0:
        _fatal(
            "Impossibile avviare simulationManager.py nel container 'sumo_simulation'.",
            "Verifica che il container sia in esecuzione con: docker ps",
        )

    # Blocco cross-platform
    _shutdown_event.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic Traffic Manager",formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--simulation_name", default="2cross", help="Nome della simulazione")
    parser.add_argument("--decision_interval", type=int, default=60, help="Step SUMO tra un trigger IA e il successivo")
    parser.add_argument("--k", type=int,help="Numero di cluster/agenti desiderato")
    parser.add_argument("--outdir", default="agentContainer/agentArchitecture/agent_topologies", help="Directory di output delle topologie (dentro il container agent)")
    parser.add_argument("--gui", default="false", choices=["true", "false"], help="Avvia SUMO con o senza l'interfaccia grafica")

    args = parser.parse_args()

    run_application(
        simulation_name=args.simulation_name,
        decision_interval=args.decision_interval,
        k=args.k,
        outdir=args.outdir,
        gui=args.gui,
    )