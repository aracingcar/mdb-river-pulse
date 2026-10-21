"""Simplify OSM river ways (Overpass JSON, `out geom tags`) into data/rivers.json:
a list of [name, [[lon,lat],...]] chunks of <=CH vertices. Usage: build_rivers.py raw.json"""
import json, sys, math
MIN_D, CH = 0.004, 10   # degrees between kept vertices (~400 m); vertices per chunk
raw = json.load(open(sys.argv[1]))
out = []
for w in raw["elements"]:
    g = w.get("geometry") or []
    name = w.get("tags", {}).get("name", "")
    if len(g) < 2: continue
    pts = [(g[0]["lon"], g[0]["lat"])]
    for p in g[1:-1]:
        if math.hypot(p["lon"] - pts[-1][0], p["lat"] - pts[-1][1]) >= MIN_D: pts.append((p["lon"], p["lat"]))
    pts.append((g[-1]["lon"], g[-1]["lat"]))
    for i in range(0, len(pts) - 1, CH - 1):
        c = pts[i:i + CH]
        if len(c) > 1: out.append([name, [[round(x, 4), round(y, 4)] for x, y in c]])
json.dump(out, open("data/rivers.json", "w"), separators=(",", ":"))
print(len(out), "chunks")
