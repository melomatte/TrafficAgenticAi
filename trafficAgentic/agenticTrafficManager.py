import argparse
import os
import platform
import subprocess
import signal
import sys
import requests
import threading
import time
from clusteringTopology.topology_builder import build_topologies

"""
comando per esecuzione (da root progetto):
    python3 trafficAgentic/agenticTrafficManager.py --k 2
"""

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

DATA_DIR = "backend_server/data"
CONFIG_DIR = "trafficAgentic/config"
BACKEND_URL = "http://localhost:8000/api/topology"
TOPOLOGY_DIR = os.path.join(DATA_DIR, "agent_topologies")
K8S_DIR = os.path.join(CONFIG_DIR, "k8s")
DASHBOARD_DIR = os.path.join(CONFIG_DIR, "dashboards")
ENV_FILE_PATH = "trafficAgentic/.env"
PLATFORM = platform.system()

_port_forward_procs: list[subprocess.Popen] = []

# ---------------------------------------------------------------------------
# Helpers diagnostici
# ---------------------------------------------------------------------------

def _header(step: int, text: str) -> None:
    print(f"\n{'='*50}\n  {step}. {text}\n{'='*50}\n")

def _fatal(message: str, hint: str = "") -> None:
    print(f"\n❌  ERRORE: {message}")
    if hint:
        print(f"    ↳ {hint}")
    _do_cleanup()          # cleanup senza sys.exit, così possiamo uscire con codice 1
    sys.exit(1)

def _ok(msg: str) -> None:
    print(f"    ✅ {msg}")

def _warn(msg: str) -> None:
    print(f"    ⚠️  {msg}")

# ---------------------------------------------------------------------------
# Avvio minikube
# ---------------------------------------------------------------------------

def _minikube_is_running() -> bool:
    result = subprocess.run(
        ["minikube", "status", "--format", "{{.Host}}"],
        capture_output=True, text=True
    )
    return result.returncode == 0 and result.stdout.strip() == "Running"

def setup_minikube(memory: int, cpus: int) -> None:
    print("Verifica stato cluster Minikube...")
    try:
        if _minikube_is_running():
            _ok("   Cluster Minikube già in esecuzione.")
        else:
            print("   Avvio Minikube...")
            subprocess.run(
                ["minikube", "start", "--driver=docker",
                 f"--memory={memory}", f"--cpus={cpus}"],
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
    print("Verifica/Installazione stack di monitoraggio ufficiale (Helm)...")
    try:
        # 1. Aggiunta dei repository ufficiali
        subprocess.run(["helm", "repo", "add", "prometheus-community", "https://prometheus-community.github.io/helm-charts"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["helm", "repo", "add", "grafana", "https://grafana.github.io/helm-charts"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["helm", "repo", "update"], check=True, stdout=subprocess.DEVNULL)

        # 2. Installazione stack Prometheus + Grafana
        print("   Installazione Prometheus e Grafana...")
        grafana_config_path = os.path.join(CONFIG_DIR, "grafana.yaml")
        subprocess.run([
            "helm", "upgrade", "--install", "monitoring-stack", "prometheus-community/kube-prometheus-stack",
            "--namespace", "monitoring", "--create-namespace",
            "--set", "grafana.adminPassword=admin",
            "-f", grafana_config_path
        ], check=True, stdout=subprocess.DEVNULL)
        
        # 3. Installazione Loki
        print("   Configurazione ed installazione Loki...")
        loki_config_path = os.path.join(CONFIG_DIR, "loki-values.yaml")
        subprocess.run([
            "helm", "upgrade", "--install", "loki", "grafana/loki",
            "--namespace", "monitoring",
            "-f", loki_config_path
        ], check=True, stdout=subprocess.DEVNULL)

        # 4. Installazione Promtail (log collector utilizzato da Loki)
        print("   Installazione Promtail...")
        subprocess.run([
            "helm", "upgrade", "--install", "promtail", "grafana/promtail",
            "--namespace", "monitoring",
            "--set", "config.clients[0].url=http://loki:3100/loki/api/v1/push",
            # FONDAMENTALE: Usiamo lo stesso tenant 'local' che abbiamo attivato su Loki e Grafana
            "--set", "config.clients[0].tenant_id=local"
        ], check=True, stdout=subprocess.DEVNULL)

        # 5. Provisioning delle Dashboard personalizzate
        if os.path.exists(DASHBOARD_DIR) and os.listdir(DASHBOARD_DIR):
            print(f"   Caricamento Dashboard ({DASHBOARD_DIR}) personalizzate in Grafana...")
            try:
                # Crea la ConfigMap prendendo tutti i file JSON nella cartella
                subprocess.run([
                    "kubectl", "create", "configmap", "custom-grafana-dashboards",
                    f"--from-file={DASHBOARD_DIR}",
                    "--namespace", "monitoring"
                ], check=True, stdout=subprocess.DEVNULL)
                
                # Applica l'etichetta "magica" che dice a Grafana di leggerla
                subprocess.run([
                    "kubectl", "label", "configmap", "custom-grafana-dashboards",
                    "grafana_dashboard=1",
                    "--namespace", "monitoring"
                ], check=True, stdout=subprocess.DEVNULL)
                
            except subprocess.CalledProcessError as e:
                _warn(f"Errore durante il caricamento delle dashboard: {e}")

        _ok("Tutti i componenti ufficiali (Prometheus, Grafana, Loki, Promtail) sono pronti.\n")
    except FileNotFoundError:
        _fatal("Helm non trovato nel PATH", "Procedi con l'installazione di Helm")
    except subprocess.CalledProcessError as e:
        _fatal(f"Errore durante l'installazione dei componenti: {e}\n")

# ---------------------------------------------------------------------------
# Build immagini -> costruisce (in parallelo) le immagini dei container dentro Minikube
# ---------------------------------------------------------------------------
def build_images() -> bool:

    images = [
        ("orchestrator", "trafficAgentic/src/orchestrator"),
        ("agent",        "trafficAgentic/src/traffic_agent"),
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
        _warn("Nessuna cartella sorgente trovata: nessuna immagine costruita.")
    
    print("\nPulizia immagini orfane in Minikube...")
    subprocess.run(["minikube", "image", "prune"], stdout=subprocess.DEVNULL)

    return rebuilt

# ---------------------------------------------------------------------------
# Apply K8s — cross-platform, senza shell=True
# ---------------------------------------------------------------------------

def apply_k8s(images_rebuilt: bool, num_replicas: int) -> None:

    # Secret da .env (cross-platform, senza pipe shell)
    if os.path.exists(ENV_FILE_PATH):
        print("Aggiornamento Secret 'llm-secrets' (variabili d'ambiente per pod)")
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
        except subprocess.CalledProcessError as e:
            _fatal("Impossibile creare il Secret da .env.", str(e))
    else:
        _fatal("File .env non trovato: Secret non creato.", 
               "Il file .env deve essere nella cartella trafficAgentic/ e deve avere una struttura del tipo:\nLLM_API_KEY=<chiave>\nLLM_SDK=[litellm, openai, openrouter]\nMODEL_NAME=<modello>\nPROVIDER=[cloud, local]")

    # Manifesti YAML
    if not os.path.exists(K8S_DIR):
        _fatal(f"Cartella '{K8S_DIR}/' non trovata.", "Assicurati che i manifesti Kubernetes siano presenti.")
    print(f"Applicazione manifesti '{K8S_DIR}/'...")
    
    try:
        subprocess.run(
            ["kubectl", "apply", "-f", K8S_DIR],
            check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        _fatal(f"Applicazione YAML fallita.", f"Verifica la sintassi in {K8S_DIR}/")
    
    # Scaling degli agent -> sovrascrive il valore "replicas: 1" presente nel file YAML
    print(f"Scaling 'statefulset/traffic-agent' a {num_replicas} repliche...")
    try:
        subprocess.run(
            ["kubectl", "scale", "statefulset/traffic-agent", f"--replicas={num_replicas}"],
            check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        _fatal(f"Impossibile scalare lo StatefulSet: {e}")

    # Rollout restart — solo se c'è codice nuovo
    if images_rebuilt:
        print("Rollout restart (nuove immagini rilevate)...")
        _rollout_restart()
    else:
        print("    ℹ️ Nessuna immagine ricostruita: skip rollout restart.")

def _rollout_restart() -> None:

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

# ---------------------------------------------------------------------------
# Port forwarding
# ---------------------------------------------------------------------------

def start_port_forward(service: str, local_port: int, remote_port: int, namespace: str = "default") -> None:

    print(f"Port-forward: localhost:{local_port} → {service}:{remote_port} (ns: {namespace})")
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
# Cleanup — separato da sys.exit per essere chiamabile da _fatal
# ---------------------------------------------------------------------------

def _do_cleanup() -> None:
    print("\nAvvio procedura di spegnimento...")

    # 1. Port-forward processes
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

    # 2. Risorse Kubernetes
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

    # 3. Spegnimento Minikube
    print("Spegnimento Minikube...")
    result = subprocess.run(
        ["minikube", "stop"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        _ok("Minikube spento correttamente.")
    else:
        _warn(f"Minikube stop ha restituito un errore (non bloccante): {result.stderr.strip()}")

    _ok("Cluster pulito. Uscita.")

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
def run_application(simulation_name, k, memory, cpus):

    # 1. Topologie
    _header(1, "Costruzione Topologie")
    success = build_topologies(simulation_name=simulation_name, k=k, outdir=TOPOLOGY_DIR)
    if not success:
        _fatal("Generazione topologie fallita.")

    # 2. Aggiunta topologie a SQlite
    _header(2, f"Caricamento topologie nel backend ({BACKEND_URL})")

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
    setup_minikube(memory, cpus)
    print("\n"+"-"*50+"\n")
    setup_monitoring()
    print("\n"+"-"*50+"\n")
    images_rebuilt = build_images()
    apply_k8s(images_rebuilt, k)

    # 4. Port forwarding
    _header(4, "Port forwarding (Bridge Local → Cluster)...")
    start_port_forward("orchestrator-service",  8080, 8080, "default")
    start_port_forward("monitoring-stack-grafana", 3000, 80, namespace="monitoring")

    # Mettiamo lo script in attesa finché non si preme Ctrl+C
    print("\n"+"-"*50+"\n")
    try:
        print("Infrastruttura creata e avviata... Premi Ctrl+C per terminare e avviare il cleanup.")
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[!] Ricevuto segnale di interruzione (Ctrl+C). Avvio procedura di chiusura...")
    finally:
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
    parser.add_argument("--memory", type=int, default=8192, help="RAM dedicata al cluster Minikube")
    parser.add_argument("--cpus", type=int, default=4, help="Numero di CPU dedicate al cluster Minikube")
    args = parser.parse_args()

    run_application(args.simulation_name, args.k, args.memory, args.cpus)