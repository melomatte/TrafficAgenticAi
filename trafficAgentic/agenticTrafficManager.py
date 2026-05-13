import argparse
import os
import platform
import subprocess
import signal
import sys
import requests
import threading
import time
import shutil
from dotenv import load_dotenv
from clusteringTopology.topology_builder import build_topologies

"""
comando per esecuzione (da root progetto):
    python3 trafficAgentic/agenticTrafficManager.py --k 2
"""

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
LOGS_DIR = "data"
BACKEND_URL = "http://localhost:8000/api/topology"
CONTAINER_DIR = os.path.join(LOGS_DIR, "container")
TOPOLOGY_DIR = os.path.join(LOGS_DIR, "agent_topologies")
PROMPT_DIR = os.path.join(LOGS_DIR, "agentPrompt")
K8S_DIR = "trafficAgentic/k8s"
ENV_FILE_PATH = "trafficAgentic/.env"


PLATFORM = platform.system()
_shutdown_event    = threading.Event()
_port_forward_procs: list[subprocess.Popen] = []
_log_procs: list[subprocess.Popen]          = []   # kubectl logs -f per ogni pod
_mount_proc: subprocess.Popen = None        # Processo background per il mount

# ---------------------------------------------------------------------------
# Helpers diagnostici
# ---------------------------------------------------------------------------
def _header(step: int, text: str) -> None:
    print(f"\n{'='*50}\n  {step}. {text}\n{'='*50}\n")

def _fatal(message: str, hint: str = "") -> None:
    """Stampa un errore strutturato, esegue il cleanup e termina con codice 1."""
    print(f"\n❌  ERRORE: {message}")
    if hint:
        print(f"    ↳ {hint}")
    _do_cleanup()          # cleanup senza sys.exit, così possiamo uscire con codice 1
    sys.exit(1)

def _ok(msg: str) -> None:
    print(f"    ✅ {msg}")

def _warn(msg: str) -> None:
    print(f"    ⚠️  {msg}")

def _info(msg: str) -> None:
    print(f"    ℹ️  {msg}")

# ---------------------------------------------------------------------------
# Setup cartelle -> ripulisce le cartelle con i log dell'architettura
# ---------------------------------------------------------------------------
def setup_directories() -> None:

    for d in [CONTAINER_DIR, PROMPT_DIR, TOPOLOGY_DIR]:
        if os.path.exists(d):
            print(f"🧹 Pulizia cartella '{d}'...")
            try:
                shutil.rmtree(d)
            except Exception as e:
                _warn(f"Errore pulizia {d}: {e}")
        os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Avvio minikube
# ---------------------------------------------------------------------------
def _minikube_is_running() -> bool:
    result = subprocess.run(
        ["minikube", "status", "--format", "{{.Host}}"],
        capture_output=True, text=True
    )
    return result.returncode == 0 and result.stdout.strip() == "Running"

def setup_minikube() -> None:
    print("Verifica stato cluster Minikube...")
    try:
        if _minikube_is_running():
            _ok("   Cluster Minikube già in esecuzione.")
        else:
            print("   Avvio Minikube (4 GB RAM, 2 CPU)...")
            subprocess.run(
                ["minikube", "start", "--driver=docker",
                 "--memory=4096", "--cpus=2"],
                check=True
            )

            # Verifica post-avvio
            if not _minikube_is_running():
                _fatal("Minikube avviato ma non risponde.", "Prova: minikube delete && minikube start")

            _ok("Cluster Minikube avviato.")
    except subprocess.CalledProcessError as e:
        _fatal("Errore durante l'avvio di Minikube.", str(e))

# ---------------------------------------------------------------------------
# Installazione stack grafana prometheus
# ---------------------------------------------------------------------------

def setup_monitoring() -> None:
    print("Verifica/Installazione stack Prometheus + Grafana (tramite Helm)...")
    try:
        # Aggiunge il repository Helm di Prometheus
        subprocess.run(
            ["helm", "repo", "add", "prometheus-community", "https://prometheus-community.github.io/helm-charts"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(["helm", "repo", "update"], check=True, stdout=subprocess.DEVNULL)

        # Installa lo stack nel namespace "monitoring"
        subprocess.run([
            "helm", "upgrade", "--install", "monitoring-stack", "prometheus-community/kube-prometheus-stack",
            "--namespace", "monitoring", "--create-namespace",
            # Impostiamo una password semplice per Grafana in ambiente di sviluppo
            "--set", "grafana.adminPassword=admin" 
        ], check=True, stdout=subprocess.DEVNULL)
        _ok("Prometheus e Grafana installati/aggiornati.")
    except FileNotFoundError:
        _warn("Helm non trovato nel PATH. Monitoraggio saltato.")
    except subprocess.CalledProcessError as e:
        _warn(f"Errore durante l'installazione di Prometheus/Grafana con Helm: {e}")

# ---------------------------------------------------------------------------
# Build immagini -> costruisce (in parallelo) le immagini dei container dentro minikube
# ---------------------------------------------------------------------------
def build_images() -> bool:

    images = [
        ("tua-immagine-orchestrator:latest", "trafficAgentic/src/orchestrator"),
        ("tua-immagine-agent:latest",        "trafficAgentic/src/traffic_agent"),
    ]

    rebuilt      = False
    errors       = []
    lock         = threading.Lock()

    def _build(img: str, folder: str) -> None:
        nonlocal rebuilt
        if not os.path.exists(folder):
            with lock:
                _warn(f"Cartella '{folder}' non trovata — salto {img}")
            return
        print(f"Building {img}...")

        result = subprocess.run(
            ["minikube", "image", "build", "-t", img, folder],
            capture_output=True
        )
        with lock:
            if result.returncode != 0:
                errors.append(f"{img}: {result.stderr.decode(errors='replace').strip()}")
            else:
                rebuilt = True
                _ok(f"{img} pronta.")

    threads = [threading.Thread(target=_build, args=(i, f)) for i, f in images]
    for t in threads: t.start()
    for t in threads: t.join()

    if errors:
        _fatal("Build fallita per una o più immagini:\n" + "\n".join(errors))

    if not rebuilt:
        _info("Nessuna cartella sorgente trovata: nessuna immagine costruita.")
    
    print("\nPulizia immagini orfane in Minikube (image prune)...")
    subprocess.run(["minikube", "image", "prune"], stdout=subprocess.DEVNULL)

    return rebuilt

# ---------------------------------------------------------------------------
# Apply K8s — cross-platform, senza shell=True
# ---------------------------------------------------------------------------
def apply_k8s(images_rebuilt: bool, num_replicas: int) -> None:
    """Crea/aggiorna Secret e manifesti. Fa rollout restart solo se le immagini sono cambiate."""

    # Secret da .env (cross-platform, senza pipe shell)
    if os.path.exists(ENV_FILE_PATH):
        print("Aggiornamento Secret 'llm-secrets'...")
        try:
            dry = subprocess.run(
                ["kubectl", "create", "secret", "generic", "llm-secrets",
                 f"--from-env-file={ENV_FILE_PATH}", "-o", "yaml", "--dry-run=client"],
                capture_output=True, text=True, check=True
            )
            subprocess.run(
                ["kubectl", "apply", "-f", "-"],
                input=dry.stdout, text=True, check=True,
                stdout=subprocess.DEVNULL
            )
            _ok("Secret aggiornato.")
        except subprocess.CalledProcessError as e:
            _fatal("Impossibile creare il Secret da .env.", str(e))
    else:
        _warn("File .env non trovato: Secret non creato.")

    # Manifesti YAML
    if not os.path.exists(K8S_DIR):
        _fatal(f"Cartella '{K8S_DIR}/' non trovata.",
               "Assicurati che i manifesti Kubernetes siano presenti.")
    print(f"Applicazione manifesti '{K8S_DIR}/'...")
    
    try:
        subprocess.run(
            ["kubectl", "apply", "-f", K8S_DIR],
            check=True, stdout=subprocess.DEVNULL
        )
        _ok("Manifesti applicati.")
    except subprocess.CalledProcessError:
        _fatal(f"Applicazione YAML fallita.", f"Verifica la sintassi in {K8S_DIR}/")
    
    # Scaling Imperativo degli Agenti
    # Questo sovrascrive il valore "replicas: 1" presente nel file YAML
    print(f"Scaling 'statefulset/traffic-agent' a {num_replicas} repliche...")
    try:
        subprocess.run(
            ["kubectl", "scale", "statefulset/traffic-agent", f"--replicas={num_replicas}"],
            check=True, stdout=subprocess.DEVNULL
        )
        _ok(f"Scaling a {num_replicas} completato.")
    except subprocess.CalledProcessError as e:
        _warn(f"Impossibile scalare lo StatefulSet: {e}")

    # Rollout restart — solo se c'è codice nuovo
    if images_rebuilt:
        print("Rollout restart (nuove immagini rilevate)...")
        _rollout_restart()
    else:
        _info("Nessuna immagine ricostruita: skip rollout restart.")

def _rollout_restart() -> None:
    """Riavvio rolling di tutti i workload + attesa completamento."""
    workloads = [
        ("deployment", "orchestrator-deployment"),
        ("statefulset", "traffic-agent"),
    ]
    for kind, name in workloads:
        subprocess.run(
            ["kubectl", "rollout", "restart", kind, name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    print("Attesa completamento rollout...")
    for kind, name in workloads:
        try:
            subprocess.run(
                ["kubectl", "rollout", "status", f"{kind}/{name}", "--timeout=180s"],
                check=True, stdout=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            _warn(f"Rollout di {name} non completato entro 180s. Procedo comunque.")
    _ok("Rollout completato.")

# ---------------------------------------------------------------------------
# Attesa pod
# ---------------------------------------------------------------------------
def wait_for_pod(app_label: str, timeout: int = 180) -> str:
    """
    Attende che almeno un pod con la label indicata sia Ready,
    poi restituisce il suo nome. Unico wait senza doppio polling.
    """
    print(f"   ⏳ Attesa pod '{app_label}' (timeout {timeout}s)...")
    try:
        subprocess.run(
            ["kubectl", "wait", "pod",
             "-l", f"app={app_label}",
             "--for=condition=Ready",
             f"--timeout={timeout}s"],
            check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        # Dump dello stato per diagnosi rapida
        diag = subprocess.run(
            ["kubectl", "describe", "pods", "-l", f"app={app_label}"],
            capture_output=True, text=True
        )
        print(diag.stdout[-3000:])   # ultime 3000 char per non inondare il terminale
        _fatal(
            f"Pod '{app_label}' non pronto entro {timeout}s.",
            f"Ispeziona con: kubectl describe pods -l app={app_label}"
        )

    result = subprocess.run(
        ["kubectl", "get", "pods",
         "-l", f"app={app_label}",
         "--field-selector=status.phase=Running",
         "-o", "jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True, check=True
    )
    pod_name = result.stdout.strip()
    if not pod_name:
        _fatal(f"Nessun pod Running per label app={app_label}.")
    _ok(f"Pod pronto: {pod_name}")
    return pod_name

def get_all_running_pods() -> list[str]:
    """Restituisce i nomi di tutti i pod Running nel cluster (esclude Terminating)."""
    result = subprocess.run(
        ["kubectl", "get", "pods",
         "--field-selector=status.phase=Running",
         "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [n for n in result.stdout.strip().split() if n]

# ---------------------------------------------------------------------------
# Logging del cluster
# ---------------------------------------------------------------------------
def _get_pod_containers(pod_name: str) -> list[str]:
    """Restituisce i nomi dei container applicativi (non init) di un pod."""
    result = subprocess.run(
        ["kubectl", "get", "pod", pod_name,
         "-o", "jsonpath={.spec.containers[*].name}"],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().split()
 
def start_cluster_logging() -> None:
    """
    Aggancia i log del cluster con granularità per container:
    - pod con un solo container  → containerLogs/<pod>.log
    - pod con più container      → containerLogs/<pod>-<container>.log
 
    Un processo kubectl logs -f per container: nessun mixing, nessun duplicato.
    """
    # Attesa StatefulSet agenti prima di raccogliere i nomi dei pod
    try:
        subprocess.run(
            ["kubectl", "rollout", "status", "statefulset/traffic-agent", "--timeout=120s"],
            check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        _warn("StatefulSet traffic-agent non ancora pronto — log degli agenti potrebbero essere incompleti.")
 
    pods = get_all_running_pods()
    if not pods:
        _warn("Nessun pod Running trovato da loggare.")
        return
 
    print(f"   Aggancio log per {len(pods)} pod:")
    for pod in pods:
        containers = _get_pod_containers(pod)
        if not containers:
            _warn(f"Impossibile leggere i container di '{pod}', salto.")
            continue
 
        for container in containers:
            # Nome file: <pod>.log se container unico, <pod>-<container>.log se multipli
            filename = f"{pod}.log" if len(containers) == 1 else f"{pod}-{container}.log"
            log_path = os.path.join(CONTAINER_DIR, filename)
            try:
                proc = subprocess.Popen(
                    ["kubectl", "logs", "-f", pod, "-c", container],
                    stdout=open(log_path, "w"),
                    stderr=subprocess.STDOUT,
                )
                _log_procs.append(proc)
                print(f"   📄 {CONTAINER_DIR}/{filename}  ({pod}/{container})")
            except Exception as e:
                _warn(f"Impossibile agganciare i log di {pod}/{container}: {e}")

# ---------------------------------------------------------------------------
# Port forwarding
# ---------------------------------------------------------------------------
def start_port_forward(service: str, local_port: int, remote_port: int, namespace: str = "default") -> None:
    """Apre un tunnel localhost:<local_port> → svc/<service>:<remote_port> nel namespace specificato."""
    print(f"   🔗 Port-forward: localhost:{local_port} → {service}:{remote_port} (ns: {namespace})")
    try:
        proc = subprocess.Popen(
            ["kubectl", "port-forward", f"svc/{service}",
             f"{local_port}:{remote_port}", "-n", namespace],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        _port_forward_procs.append(proc)
        time.sleep(1.5)
        if proc.poll() is not None:
            _fatal(
                f"Port-forward verso '{service}' fallito immediatamente.",
                f"Verifica che il servizio esista: kubectl get svc -n {namespace}"
            )
        _ok(f"Port-forward attivo su localhost:{local_port}")
    except FileNotFoundError:
        _fatal("kubectl non trovato nel PATH.")

# ---------------------------------------------------------------------------
# Mount cartella condivisa per vedere i prompt degli agent
# ---------------------------------------------------------------------------

def start_minikube_mount() -> None:
    """Avvia minikube mount in background per condividere la cartella PROMPT_DIR."""
    
    local_path = os.path.abspath(PROMPT_DIR)

    # Il comando minikube mount richiede percorsi assoluti!
    print(f"\nMontaggio volume condiviso: {local_path} -> /{PROMPT_DIR}")
    
    try:
        _mount_proc = subprocess.Popen(
            ["minikube", "mount", f"{local_path}:/{PROMPT_DIR}"],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True # Restituisce stringhe invece di byte
        )
        
        time.sleep(2)
        if _mount_proc.poll() is not None:
            _fatal("Il mount di Minikube sembra essersi interrotto subito","Controlla i permessi della cartella.")
        else:
            _ok("Cartella locale montata con successo su Minikube.\n")
            
    except Exception as e:
        _fatal(f"Impossibile avviare minikube mount: {e}")


# ---------------------------------------------------------------------------
# Cleanup — separato da sys.exit per essere chiamabile da _fatal
# ---------------------------------------------------------------------------
def _do_cleanup() -> None:
    """Termina processi figli e rimuove le risorse K8s. Non chiama sys.exit."""
    print("\n🛑 Avvio procedura di spegnimento...")

    # 0. Chiudi il processo di Mount
    if _mount_proc:
        print("   Chiusura processo di mount di Minikube...")
        try:
            _mount_proc.terminate()
            _mount_proc.wait(timeout=3)
        except Exception:
            try:
                _mount_proc.kill()
            except Exception:
                pass

    # 1. Log processes
    if _log_procs:
        print(f"   Chiusura {len(_log_procs)} processi di logging...")
        for proc in _log_procs:
            try:
                proc.terminate()
            except Exception:
                pass
        # Attesa fino a 3s per la chiusura ordinata
        deadline = time.time() + 3
        for proc in _log_procs:
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()

    # 2. Port-forward processes
    if _port_forward_procs:
        print(f"   Chiusura {len(_port_forward_procs)} tunnel port-forward...")
        for proc in _port_forward_procs:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # 3. Risorse Kubernetes
    print("   Rimozione risorse Kubernetes dal cluster...")
    subprocess.run(
        ["kubectl", "delete", "-f", K8S_DIR, "--ignore-not-found=true",
         "--grace-period=10"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.run(
        ["kubectl", "delete", "secret", "llm-secrets", "--ignore-not-found=true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # 4. Verifica che i pod siano effettivamente terminati (max 30s)
    print("   ⏳ Attesa terminazione pod (max 30s)...")
    deadline = time.time() + 30
    while time.time() < deadline:
        pods = get_all_running_pods()
        if not pods:
            break
        time.sleep(2)
    else:
        _warn("Alcuni pod potrebbero non essersi terminati entro 30s.")

    # 5. Spegnimento Minikube
    print("   🔌 Spegnimento Minikube...")
    result = subprocess.run(
        ["minikube", "stop"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        _ok("Minikube spento correttamente.")
    else:
        _warn(f"Minikube stop ha restituito un errore (non bloccante): {result.stderr.strip()}")

    print("✅ Cluster pulito. Uscita.")
    _shutdown_event.set()

def cleanup(signum=None, frame=None) -> None:
    """Handler per SIGINT/SIGTERM. Esegue il cleanup e termina con codice 0."""
    _do_cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
if PLATFORM != "Windows":
    signal.signal(signal.SIGTERM, cleanup)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_application(simulation_name, k):
    
    # Pulizia dalle precedenti esecuzioni dell'architettura 
    setup_directories()

    # 1. Topologie
    _header(1, "Costruzione Topologie")
    success = build_topologies(simulation_name=simulation_name, k=k, outdir=TOPOLOGY_DIR)
    if not success:
        _fatal("Generazione topologie fallita.")
    _ok("Topologie generate.")

    # 2. Aggiunta topologie a SQlite
    _header(2, "Caricamento Topologie nel backend (tramite api)")

    for filename in os.listdir(TOPOLOGY_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(TOPOLOGY_DIR, filename)
            
            # I file vengono salvati con il nome che avrà il pod dell'agente -> traffic-agent-N
            agent_id = "traffic-" + os.path.splitext(filename)[0]
            
            try:
                with open(file_path, "rb") as f:
                    files = {"file": (filename, f, "application/json")}
                    response = requests.post(f"{BACKEND_URL}/{agent_id}", files=files)
                    
                    if response.status_code == 200:
                        _ok(f"Topologia caricata: {agent_id}")
                    else:
                        _fatal(f"Errore durante il caricamento di {agent_id}: {response.text}")
                        
            except Exception as e:
                _fatal(f"Impossibile caricare la topologia {filename}", "Controlla se il server backend è attivo!")

    _ok("Tutte le topologie sono state elaborate.")

    # 3. Creazione infrastruttura kubernetes (dentro cluster minikube)
    _header(3, "Infrastruttura (Minikube / K8s)")
    setup_minikube()
    setup_monitoring()
    start_minikube_mount()
    images_rebuilt = build_images()
    apply_k8s(images_rebuilt, k)

    # 4. Networking + mount cartella condivisa (per agent prompt)
    _header(4, "Networking (Bridge Local → Cluster) + mount cartella condivisa (per prompt agent)")
    start_port_forward("orchestrator-service",  8080, 8080, "default")
    start_port_forward("monitoring-stack-grafana", 3000, 80, namespace="monitoring")

    # 5. Logging del cluster
    _header(5, f"Logging Cluster (→ {CONTAINER_DIR}/)")
    start_cluster_logging()

    # Mettiamo lo script in attesa finché non si preme Ctrl+C
    print("\n"+"-"*50+"\n")
    try:
        print("Infrastruttura creata e avviata... Premi Ctrl+C per terminare e avviare il cleanup.")
        threading.Event().wait()
    except KeyboardInterrupt:
        # Cattura la pressione di Ctrl+C
        print("\n[!] Ricevuto segnale di interruzione (Ctrl+C). Avvio procedura di chiusura...")
    finally:
        # Il blocco finally garantisce che cleanup() venga chiamato 
        # sia se premi Ctrl+C, sia se si verifica un altro errore imprevisto
        cleanup()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agentic Traffic Manager",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--simulation_name", default="2cross", help="Nome della simulazione")
    parser.add_argument("--k", type=int, default=2, help="Numero di agenti/cluster")
    args = parser.parse_args()

    run_application(args.simulation_name, args.k)