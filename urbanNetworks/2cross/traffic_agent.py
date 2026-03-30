"""
traffic_agent.py
================
Agente di controllo semaforico per simulazione SUMO a 2 incroci.

Architettura
------------
- SUMO viene avviato come subprocess con TraCI abilitato
- Ogni step di simulazione, ogni TrafficLight locale legge le code
  e applica la fase corrente in autonomia (logica locale)
- Ogni DECISION_INTERVAL secondi di simulazione, il LLMAdvisor
  interroga Llama via Ollama e può sovrascrivere la fase attiva
  se una direzione è congestionata

Requisiti
---------
  pip install traci sumolib requests
  ollama pull llama3          # o qualsiasi modello locale installato
"""

import os
import sys
import time
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import traci
import requests

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

SUMO_BINARY   = os.getenv("SUMO_BINARY", "sumo-gui")   # oppure "sumo" per headless
SUMO_CFG      = os.getenv("SUMO_CFG",    "sim.sumocfg")
TRACI_PORT    = int(os.getenv("TRACI_PORT", "8813"))

OLLAMA_URL    = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3")

# Ogni quanti secondi di simulazione Llama può intervenire
DECISION_INTERVAL = int(os.getenv("DECISION_INTERVAL", "10"))

# Fase minima (secondi sim) prima che un semaforo possa cambiare
MIN_GREEN_DURATION = int(os.getenv("MIN_GREEN_DURATION", "10"))

# Soglia code (n. veicoli) oltre cui si forza una rivalutazione immediata
QUEUE_THRESHOLD = int(os.getenv("QUEUE_THRESHOLD", "8"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("traffic_agent")


# ---------------------------------------------------------------------------
# Definizioni fasi semaforo
# ---------------------------------------------------------------------------
# SUMO usa stringhe di fase: ogni carattere è una luce per ogni lane-link.
# Per i nostri incroci a 4 bracci con 2 corsie per arco (8 link in/uscita)
# definiamo 2 fasi principali + 2 fasi di giallo intermedio.
#
# Fase 0  — NS verde  (Nord↔Sud liberi, Est↔Ovest rosso)
# Fase 1  — giallo NS
# Fase 2  — EW verde  (Est↔Ovest liberi, Nord↔Sud rosso)
# Fase 3  — giallo EW
#
# La stringa di fase ha tanti caratteri quanti i link controllati dal TL.
# Viene costruita dinamicamente in TrafficLight.build_phase_string().

PHASE_NS_GREEN  = 0
PHASE_NS_YELLOW = 1
PHASE_EW_GREEN  = 2
PHASE_EW_YELLOW = 3

YELLOW_DURATION = 3   # secondi di giallo


# ---------------------------------------------------------------------------
# TrafficLight — logica locale per singolo incrocio
# ---------------------------------------------------------------------------

@dataclass
class TrafficLight:
    tl_id: str

    # stato interno
    current_phase:     int   = PHASE_NS_GREEN
    phase_timer:       float = 0.0          # secondi trascorsi nella fase corrente
    pending_phase:     Optional[int] = None  # fase richiesta da LLM, applicata dopo giallo

    # metriche raccolte ad ogni step
    queue_ns:  int = 0
    queue_ew:  int = 0

    # lane ids per N/S e E/W (popolati in setup)
    lanes_ns:  list = field(default_factory=list)
    lanes_ew:  list = field(default_factory=list)

    # -----------------------------------------------------------------------
    def setup(self) -> None:
        """Legge da SUMO i link controllati e classifica le lane N/S vs E/W."""
        controlled = traci.trafficlight.getControlledLinks(self.tl_id)
        # controlled è lista di liste di (inLane, outLane, via)
        for group in controlled:
            for link in group:
                in_lane = link[0]
                # Euristica: le lane con 'n' o 's' nel nome → NS; 'e' o 'w' → EW
                lower = in_lane.lower()
                if any(c in lower for c in ("_n", "_s", "n2c", "c2n", "s2c", "c2s",
                                             "n1_", "s1_", "n2_", "s2_",
                                             "c1_n", "c1_s", "c2_n", "c2_s")):
                    if in_lane not in self.lanes_ns:
                        self.lanes_ns.append(in_lane)
                else:
                    if in_lane not in self.lanes_ew:
                        self.lanes_ew.append(in_lane)

        log.debug(f"[{self.tl_id}] lanes_ns={self.lanes_ns}")
        log.debug(f"[{self.tl_id}] lanes_ew={self.lanes_ew}")

        # Imposta fase iniziale
        self._apply_phase(self.current_phase)

    # -----------------------------------------------------------------------
    def build_phase_string(self, green_group: str) -> str:
        """
        Costruisce la stringa di fase SUMO per il semaforo.
        green_group: 'ns' oppure 'ew'
        """
        controlled = traci.trafficlight.getControlledLinks(self.tl_id)
        total_links = sum(len(g) for g in controlled)

        chars = []
        for group in controlled:
            for link in group:
                in_lane = link[0].lower()
                is_ns = any(k in in_lane for k in ("n2c", "c2n", "s2c", "c2s",
                                                    "n1_", "s1_", "n2_", "s2_",
                                                    "c1_n", "c1_s", "c2_n", "c2_s",
                                                    "_n", "_s"))
                if green_group == "ns":
                    chars.append("G" if is_ns else "r")
                else:
                    chars.append("r" if is_ns else "G")

        if not chars:
            # fallback: tutti rossi (non dovrebbe accadere)
            chars = ["r"] * total_links

        return "".join(chars)

    def build_yellow_string(self, from_green: str) -> str:
        """Giallo per tutte le lane che erano verdi."""
        s = self.build_phase_string(from_green)
        return s.replace("G", "y")

    # -----------------------------------------------------------------------
    def _apply_phase(self, phase: int) -> None:
        if phase == PHASE_NS_GREEN:
            state = self.build_phase_string("ns")
        elif phase == PHASE_EW_GREEN:
            state = self.build_phase_string("ew")
        elif phase == PHASE_NS_YELLOW:
            state = self.build_yellow_string("ns")
        elif phase == PHASE_EW_YELLOW:
            state = self.build_yellow_string("ew")
        else:
            return

        traci.trafficlight.setRedYellowGreenState(self.tl_id, state)
        self.current_phase = phase
        self.phase_timer   = 0.0
        log.debug(f"[{self.tl_id}] fase {phase} → stato '{state}'")

    # -----------------------------------------------------------------------
    def read_queues(self) -> None:
        """Legge il numero di veicoli fermi sulle lane NS e EW."""
        self.queue_ns = sum(
            traci.lane.getLastStepHaltingNumber(l)
            for l in self.lanes_ns if l in traci.lane.getIDList()
        )
        self.queue_ew = sum(
            traci.lane.getLastStepHaltingNumber(l)
            for l in self.lanes_ew if l in traci.lane.getIDList()
        )

    # -----------------------------------------------------------------------
    def step(self, dt: float) -> None:
        """
        Chiamato ad ogni step di simulazione.
        Gestisce autonomamente transizioni giallo→verde e rispetta MIN_GREEN.
        """
        self.phase_timer += dt
        self.read_queues()

        # --- gestione fase giallo: passa automaticamente alla verde successiva
        if self.current_phase in (PHASE_NS_YELLOW, PHASE_EW_YELLOW):
            if self.phase_timer >= YELLOW_DURATION:
                if self.pending_phase is not None:
                    self._apply_phase(self.pending_phase)
                    self.pending_phase = None
                else:
                    # torna alla verde opposta
                    next_p = (PHASE_EW_GREEN
                              if self.current_phase == PHASE_NS_YELLOW
                              else PHASE_NS_GREEN)
                    self._apply_phase(next_p)
            return  # durante il giallo non fare altro

        # --- logica locale: se una direzione ha troppe code e l'altra ha poche
        if self.phase_timer >= MIN_GREEN_DURATION:
            currently_green = "ns" if self.current_phase == PHASE_NS_GREEN else "ew"
            currently_red   = "ew" if currently_green == "ns" else "ns"
            q_green = self.queue_ns if currently_green == "ns" else self.queue_ew
            q_red   = self.queue_ns if currently_red   == "ns" else self.queue_ew

            # passa al giallo se la direzione rossa è molto congestionata
            # e quella verde è scarica
            if q_red > QUEUE_THRESHOLD and q_green < q_red * 0.5:
                log.info(
                    f"[{self.tl_id}] auto-switch: "
                    f"q_{currently_green}={q_green} q_{currently_red}={q_red}"
                )
                yellow_phase = (PHASE_NS_YELLOW
                                if self.current_phase == PHASE_NS_GREEN
                                else PHASE_EW_YELLOW)
                target_phase = (PHASE_EW_GREEN
                                if self.current_phase == PHASE_NS_GREEN
                                else PHASE_NS_GREEN)
                self.pending_phase = target_phase
                self._apply_phase(yellow_phase)

    # -----------------------------------------------------------------------
    def request_phase_change(self, direction: str) -> None:
        """
        Chiamato dall'LLM Advisor per richiedere una nuova direzione verde.
        direction: 'ns' oppure 'ew'
        """
        target = PHASE_NS_GREEN if direction == "ns" else PHASE_EW_GREEN

        # già nella fase richiesta
        if self.current_phase == target:
            log.info(f"[{self.tl_id}] LLM richiede '{direction}' — già attivo, skip")
            return

        # in giallo: aggiorna solo il pending
        if self.current_phase in (PHASE_NS_YELLOW, PHASE_EW_YELLOW):
            self.pending_phase = target
            log.info(f"[{self.tl_id}] LLM richiede '{direction}' — in giallo, pending aggiornato")
            return

        # rispetta MIN_GREEN
        if self.phase_timer < MIN_GREEN_DURATION:
            log.info(
                f"[{self.tl_id}] LLM richiede '{direction}' — "
                f"MIN_GREEN non rispettato ({self.phase_timer:.1f}s), ignorato"
            )
            return

        # avvia transizione giallo
        yellow_phase = (PHASE_NS_YELLOW
                        if self.current_phase == PHASE_NS_GREEN
                        else PHASE_EW_YELLOW)
        self.pending_phase = target
        self._apply_phase(yellow_phase)
        log.info(f"[{self.tl_id}] LLM richiede '{direction}' — avvio giallo")

    # -----------------------------------------------------------------------
    def state_dict(self) -> dict:
        return {
            "tl_id":         self.tl_id,
            "current_phase": self.current_phase,
            "phase_timer":   round(self.phase_timer, 1),
            "queue_ns":      self.queue_ns,
            "queue_ew":      self.queue_ew,
            "green_dir":     "ns" if self.current_phase == PHASE_NS_GREEN else
                             "ew" if self.current_phase == PHASE_EW_GREEN else "yellow",
        }


# ---------------------------------------------------------------------------
# LLM Advisor — interroga Llama via Ollama
# ---------------------------------------------------------------------------

class LLMAdvisor:
    def __init__(self, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL):
        self.model   = model
        self.url     = url
        self.history = []   # conversazione multi-turn con Llama

    # -----------------------------------------------------------------------
    def _system_prompt(self) -> str:
        return (
            "Sei un controller intelligente per semafori stradali in una simulazione SUMO. "
            "Ricevi lo stato attuale dei due incroci (code NS e EW, fase attiva) "
            "e devi decidere per ciascun incrocio quale direzione deve avere il verde. "
            "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido nel formato:\n"
            '{"center1": "ns", "center2": "ew"}\n'
            "I valori ammessi sono \"ns\" (verde Nord-Sud) oppure \"ew\" (verde Est-Ovest). "
            "Non aggiungere testo fuori dal JSON."
        )

    # -----------------------------------------------------------------------
    def ask(self, tl_states: list[dict]) -> Optional[dict]:
        """
        Invia lo stato dei semafori a Llama e ottiene la decisione.
        Ritorna dict {tl_id: direzione} oppure None se fallisce.
        """
        user_msg = (
            "Stato attuale degli incroci:\n"
            + json.dumps(tl_states, indent=2, ensure_ascii=False)
            + "\n\nDecidi quale direzione deve essere verde per ciascun incrocio."
        )

        self.history.append({"role": "user", "content": user_msg})

        payload = {
            "model":    self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                *self.history,
            ],
            "stream": False,
        }

        try:
            resp = requests.post(self.url, json=payload, timeout=20)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()
            log.debug(f"LLM raw response: {raw}")

            # Estrai JSON anche se c'è testo attorno
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("Nessun JSON trovato nella risposta LLM")

            decision = json.loads(raw[start:end])

            # Valida
            for tl_id, direction in decision.items():
                if direction not in ("ns", "ew"):
                    raise ValueError(f"Direzione non valida: {direction}")

            self.history.append({"role": "assistant", "content": raw})

            # Mantieni storia breve (ultime 6 coppie)
            if len(self.history) > 12:
                self.history = self.history[-12:]

            log.info(f"LLM decisione: {decision}")
            return decision

        except requests.exceptions.Timeout:
            log.warning("LLM timeout — mantengo fase attuale")
        except requests.exceptions.ConnectionError:
            log.warning("LLM non raggiungibile — mantengo fase attuale")
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            log.warning(f"LLM risposta non valida: {e}")

        # Rimuovi l'ultimo messaggio utente se non abbiamo ricevuto risposta
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()

        return None


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

def run_simulation() -> None:
    # --- Avvia SUMO ---
    sumo_cmd = [
        SUMO_BINARY,
        "-c", SUMO_CFG,
        "--remote-port", str(TRACI_PORT),
        "--no-step-log", "true",
        "--waiting-time-memory", "100",
    ]
    log.info(f"Avvio SUMO: {' '.join(sumo_cmd)}")
    sumo_proc = subprocess.Popen(sumo_cmd)

    time.sleep(2)  # attendi che SUMO sia pronto

    try:
        traci.init(port=TRACI_PORT)
        log.info("TraCI connesso")

        # --- Crea oggetti TrafficLight per ogni semaforo in rete ---
        tl_ids = traci.trafficlight.getIDList()
        log.info(f"Semafori trovati: {tl_ids}")

        traffic_lights: dict[str, TrafficLight] = {}
        for tl_id in tl_ids:
            tl = TrafficLight(tl_id=tl_id)
            tl.setup()
            traffic_lights[tl_id] = tl

        advisor = LLMAdvisor()

        step          = 0
        sim_time      = 0.0
        last_llm_time = -DECISION_INTERVAL  # forza subito la prima chiamata

        # --- Loop di simulazione ---
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step     += 1
            sim_time  = traci.simulation.getTime()
            dt        = traci.simulation.getDeltaT()

            # 1. Ogni step: logica locale per ogni semaforo
            for tl in traffic_lights.values():
                tl.step(dt)

            # 2. Ogni DECISION_INTERVAL oppure se una coda supera la soglia
            time_since_llm = sim_time - last_llm_time
            emergency = any(
                tl.queue_ns > QUEUE_THRESHOLD * 2 or tl.queue_ew > QUEUE_THRESHOLD * 2
                for tl in traffic_lights.values()
            )

            if time_since_llm >= DECISION_INTERVAL or emergency:
                states = [tl.state_dict() for tl in traffic_lights.values()]
                log.info(
                    f"[t={sim_time:.0f}s] Chiamata LLM "
                    f"({'emergency' if emergency else 'scheduled'}) — "
                    f"stati: {json.dumps(states)}"
                )
                decision = advisor.ask(states)

                if decision:
                    for tl_id, direction in decision.items():
                        if tl_id in traffic_lights:
                            traffic_lights[tl_id].request_phase_change(direction)

                last_llm_time = sim_time

            # Log periodico
            if step % 100 == 0:
                for tl in traffic_lights.values():
                    s = tl.state_dict()
                    log.info(
                        f"[t={sim_time:.0f}s] {tl.tl_id}: "
                        f"verde={s['green_dir']} "
                        f"q_ns={s['queue_ns']} q_ew={s['queue_ew']}"
                    )

        log.info("Simulazione terminata")

    except traci.exceptions.FatalTraCIError as e:
        log.error(f"Errore TraCI: {e}")
    finally:
        traci.close()
        sumo_proc.terminate()
        log.info("SUMO terminato")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_simulation()
