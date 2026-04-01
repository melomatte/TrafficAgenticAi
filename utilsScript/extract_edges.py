import json, os, traci

BASE = "urbanNetworks/Simplified_bolo_center"
OUT_DIR = os.path.join(BASE, "data")
os.makedirs(OUT_DIR, exist_ok=True)

SUMO = "/Users/raffaele/sumo/bin/sumo"
CFG = os.path.join(BASE, "sim.sumocfg")
OUT = os.path.join(OUT_DIR, "edges.json")

def center(edge):
    lane = f"{edge}_0"
    shape = traci.lane.getShape(lane)
    xs = [p[0] for p in shape]
    ys = [p[1] for p in shape]
    return sum(xs)/len(xs), sum(ys)/len(ys)

traci.start([SUMO, "-c", CFG])

edges = []
for e in traci.edge.getIDList():
    if e.startswith(":"): continue
    try:
        x, y = center(e)
        edges.append({"id": e, "x": x, "y": y})
    except:
        pass

json.dump(edges, open(OUT, "w"), indent=2)

print("Strade:", len(edges))
print("Saved →", OUT)

traci.close()