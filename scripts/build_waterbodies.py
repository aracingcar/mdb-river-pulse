"""data/waterbodies_raw.json (OSM lakes/reservoirs) -> data/waterbodies.json:
[{name, area_km2, c:[lon,lat], ring:[[lon,lat]...]}] for named water bodies inside the basin. Usage: build_waterbodies.py [min_km2]"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from basin import inside
MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
def stitch(ways):
    ways = [list(w) for w in ways if len(w) > 1]; rings = []
    while ways:
        r = ways.pop()
        grew = True
        while grew and r[0] != r[-1]:
            grew = False
            for i, w in enumerate(ways):
                if w[0] == r[-1]: r += w[1:]
                elif w[-1] == r[-1]: r += w[::-1][1:]
                elif w[-1] == r[0]: r = w[:-1] + r
                elif w[0] == r[0]: r = w[::-1][:-1] + r
                else: continue
                ways.pop(i); grew = True; break
        if r[0] == r[-1] and len(r) > 3: rings.append(r)
    return rings
def area_km2(r):
    la = sum(p[1] for p in r) / len(r)
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2 * 111 * 111 * math.cos(math.radians(la))
def simp(r, d=0.002):
    o = [r[0]]
    for p in r[1:-1]:
        if math.hypot(p[0] - o[-1][0], p[1] - o[-1][1]) >= d: o.append(p)
    return o + [r[-1]]
out = {}
for e in json.load(open("data/waterbodies_raw.json"))["elements"]:
    name = e.get("tags", {}).get("name")
    if not name: continue
    if e["type"] == "way": rings = stitch([[(p["lon"], p["lat"]) for p in e["geometry"]]]) if e.get("geometry") else []
    else: rings = stitch([[(p["lon"], p["lat"]) for p in m["geometry"]] for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")])
    for r in rings:
        a = area_km2(r)
        if a < MIN: continue
        cx = sum(p[0] for p in r) / len(r); cy = sum(p[1] for p in r) / len(r)
        if not inside(cx, cy): continue
        r = simp(r)
        if len(r) < 4: continue
        out[(e["type"], e["id"], len(out))] = {"name": name, "area": round(a, 2), "c": [round(cx, 3), round(cy, 3)], "ring": [[round(x, 4), round(y, 4)] for x, y in r]}
res = sorted(out.values(), key=lambda b: -b["area"])
json.dump(res, open("data/waterbodies.json", "w"), separators=(",", ":"))
print(len(res), "water bodies; largest:", [(b["name"], b["area"]) for b in res[:8]])
