import json, os, traci

BASE = "urbanNetworks/Simplified_bolo_center"
OUT_DIR = os.path.join(BASE, "data")
os.makedirs(OUT_DIR, exist_ok=True)

SUMO = "/Users/raffaele/sumo/bin/sumo"
CFG = os.path.join(BASE, "sim.sumocfg")
OUT = os.path.join(OUT_DIR, "tls.json")

traci.start([SUMO, "-c", CFG])

tls = []
for t in traci.trafficlight.getIDList():
    x, y = traci.junction.getPosition(t)
    tls.append({"id": t, "x": x, "y": y})

json.dump(tls, open(OUT, "w"), indent=2)

print("Semafori:", len(tls))
print("Saved →", OUT)

traci.close()