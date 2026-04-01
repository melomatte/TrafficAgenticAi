import json, os

BASE = "urbanNetworks/Simplified_bolo_center"
DATA = os.path.join(BASE, "data")

tls = json.load(open(os.path.join(DATA, "tls.json")))
edges = json.load(open(os.path.join(DATA, "edges.json")))

OUT = os.path.join(DATA, "clusters.json")

points = tls + edges

x_mid = (min(p["x"] for p in points) + max(p["x"] for p in points)) / 2
y_mid = (min(p["y"] for p in points) + max(p["y"] for p in points)) / 2

def cluster(x,y):
    if x < x_mid and y >= y_mid: return "north_west"
    if x >= x_mid and y >= y_mid: return "north_east"
    if x < x_mid and y < y_mid: return "south_west"
    return "south_east"

clusters = {
    "north_west": {"tls": [], "edges": []},
    "north_east": {"tls": [], "edges": []},
    "south_west": {"tls": [], "edges": []},
    "south_east": {"tls": [], "edges": []}
}

for t in tls:
    clusters[cluster(t["x"], t["y"])]["tls"].append(t["id"])

for e in edges:
    clusters[cluster(e["x"], e["y"])]["edges"].append(e["id"])

json.dump(clusters, open(OUT, "w"), indent=2)

print("Cluster salvati →", OUT)