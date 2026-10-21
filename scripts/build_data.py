"""Export data/river.db + data/rivers.json to data/data.js for the viewer.
Usage: build_data.py --from 2026-10-01 --to 2026-10-21 [--step 24]"""
import argparse, json, math, re, sqlite3, datetime as dt
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="t0", required=True); ap.add_argument("--to", dest="t1", required=True)
ap.add_argument("--step", type=int, choices=[24], default=24); ap.add_argument("--db", default="data/river.db"); a = ap.parse_args()
TZ = dt.timezone(dt.timedelta(hours=10))
start = dt.datetime.fromisoformat(a.t0).replace(tzinfo=TZ)
end = dt.datetime.fromisoformat(a.t1).replace(tzinfo=TZ) + dt.timedelta(days=1)
S = a.step * 3600; n = int((end - start).total_seconds() // S); t0 = int(start.timestamp())
db = sqlite3.connect(a.db, timeout=300)
# Murray-Darling Basin boundary (MDBA, Water Act 2007): keep only gauges and river reaches inside it
BND = json.load(open("data/mdb_boundary.geojson"))["features"][0]["geometry"]["coordinates"]
RINGS = [poly[0] for poly in BND]
def inside(lon, lat):
    for r in RINGS:
        c = False; j = len(r) - 1
        for i in range(len(r)):
            xi, yi = r[i]; xj, yj = r[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi: c = not c
            j = i
        if c: return True
    return False
def norm(s):
    s = s.upper().split("@")[0].split(" AT ")[0]
    s = re.sub(r"\b(RIVER|CREEK|CK|R)\b\.?", "", s); return re.sub(r"[^A-Z]", "", s)
PARAMS = ("flow", "level", "temp", "svol", "slevel")
sts = []; dropped_g = []
for sid, name, lat, lon in db.execute("SELECT id,name,lat,lon FROM stations"):
    ser = {}
    for p in PARAMS:
        sums = [0.0] * n; cnt = [0] * n
        tbl = "obs" if p in ("svol", "slevel") else "daily_obs"   # storage series were fetched raw; the rest come from the daily table
        for ts, v, u in db.execute(f"SELECT ts,value,unit FROM {tbl} WHERE station=? AND param=? AND ts>=? AND ts<?", (sid, p, t0, t0 + n * S)):
            if v is None or not math.isfinite(v): continue
            if p == "flow":   # normalise to ML/d (viewer converts to m3/s for display)
                v = v * 86.4 if u == "cumec" else v
            if v is None or (p == "temp" and not 0 < v < 40) or (p == "flow" and v < 0): continue
            b = (ts - t0) // S; sums[b] += v; cnt[b] += 1
        if any(cnt): ser[p] = [round(sums[i] / cnt[i], 3) if cnt[i] else None for i in range(n)]
    if not inside(lon, lat): dropped_g.append(name); continue
    if any(p in ser for p in PARAMS):
        sts.append({"id": sid, "name": name, "lat": lat, "lon": lon, "key": norm(name), **ser})
last = max((i for g in sts for i, v in enumerate(g.get("flow", [])) if v is not None), default=n - 1)
if last < n - 1:   # trim trailing bins nobody has reported yet
    n = last + 1
    for g in sts:
        for p in PARAMS:
            if p in g: g[p] = g[p][:n]
print(len(sts), "gauges;", {p: sum(p in s for s in sts) for p in ("flow", "level", "temp")})
def km(la1, lo1, la2, lo2): return math.hypot((la1 - la2) * 111, (lo1 - lo2) * 111 * math.cos(math.radians(la1)))
rivers = []; dropped_r = 0
for name, c in json.load(open("data/rivers.json")):
    if not inside(sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)): dropped_r += 1; continue
    la = sum(p[1] for p in c) / len(c); lo = sum(p[0] for p in c) / len(c); key = norm(name)
    sc = sorted((km(la, lo, s["lat"], s["lon"]) * (0.25 if key and s["key"] == key else 1), i) for i, s in enumerate(sts) if any(p in s for p in ("flow", "level", "temp")))[:3]
    sc = [x for x in sc if x[0] < 150]
    w = [round(1 / (d + 5) ** 2, 5) for d, _ in sc]; tot = sum(w) or 1
    rivers.append({"c": c, "g": [i for _, i in sc], "w": [round(x / tot, 3) for x in w]})
print("outside basin, dropped:", len(dropped_g), "gauges,", dropped_r, "river reaches")
bnd = RINGS[0][::8] + [RINGS[0][0]]
# water bodies (OSM outlines): link each to its own gauges (name match first, else nearby), so the viewer shows where water is
lakes = []
LAKE_STOP = re.compile(r"\b(LAKE|LK|DAM|RESERVOIR|RES|STORAGE|WEIR|WATER|THE|OF)\b")
def lkey(s): return re.sub(r"[^A-Z]", "", LAKE_STOP.sub("", s.upper().split("@")[0]))
try: wb = json.load(open("data/waterbodies.json"))
except FileNotFoundError: wb = []
for b in wb:
    lo, la = b["c"]; rad = 6 + math.sqrt(b["area"]) * 1.5; key = lkey(b["name"]); cand = []
    for i, g in enumerate(sts):
        if not any(p in g for p in ("svol", "slevel", "level", "temp")): continue
        d = km(la, lo, g["lat"], g["lon"]); gk = lkey(g["name"])
        named = bool(key) and bool(gk) and (key in gk or gk in key)
        if named and d < 60 + rad or d < rad: cand.append((0 if named else 1, d, i))
    cand.sort()
    lakes.append({"n": b["name"], "a": b["area"], "r": b["ring"], "g": [i for _, _, i in cand[:4]]})
print(len(lakes), "water bodies;", sum(1 for l in lakes if l["g"]), "with a nearby gauge")
# Ramsar wetland boundaries (SA DEW): the Coorong and Lakes Alexandrina & Albert, plus Murray wetlands inside the basin
import math as _m
def _simp(r, d=0.0015):
    o = [r[0]]
    for p in r[1:-1]:
        if _m.hypot(p[0] - o[-1][0], p[1] - o[-1][1]) >= d: o.append(p)
    return o + [r[-1]]
wetlands = []
for ft in json.load(open("data/ramsar_sa.geojson"))["features"]:
    nm = ft["properties"]["WETLAND"]
    if nm not in ("Coorong and Lakes Alexandrina and Albert", "Riverland", "Banrock Station Wetland Complex"): continue
    g = ft["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    for poly in polys:
        wetlands.append({"n": nm, "p": [[[round(x, 4), round(y, 4)] for x, y in _simp(ring)] for ring in poly]})
print(len(wetlands), "wetland polygons")
# total barrage releases to the Coorong / Murray Mouth (SA DEW, ML/day): daily value held across that day's bins
barrage = [None] * n
for ts, v in db.execute("SELECT ts,value FROM obs WHERE station='A4261002' AND param='barrage' AND ts>=? AND ts<?", (t0 - 86400, t0 + n * S)):
    for b in range(max(0, (ts - t0) // S), min(n, (ts - t0) // S + 86400 // S)): barrage[b] = round(v, 1)
print("barrage releases:", sum(v is not None for v in barrage), "of", n, "bins")
meta = {"start": start.isoformat(), "step": a.step, "n": n, "aggregation":"daily_mean", "source":"BoM DMQaQc.Merged.DailyMean.24HR", "dayTimezone":"station-local standard time (AEST/ACST), grouped by calendar date", "storageAggregation":"daily arithmetic mean of available raw BoM storage observations", "storageSource":"BoM Storage Volume / Storage Level"}
output = Path("data/data.js")
temporary = output.with_suffix(".js.tmp")
temporary.write_text("window.RIVERDATA=" + json.dumps({"meta": meta, "gauges": sts, "rivers": rivers, "lakes": lakes, "wetlands": wetlands, "barrage": {"pos": [138.8873, -35.5592], "v": barrage}, "boundary": [[round(x, 3), round(y, 3)] for x, y in bnd]}, separators=(",", ":")) + ";")
temporary.replace(output)
print("wrote data/data.js", sum(1 for r in rivers if r["g"]), "of", len(rivers), "chunks linked")
