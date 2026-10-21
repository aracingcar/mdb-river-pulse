"""Export data/river.db + data/rivers.json to data/data.js for the viewer.
Usage: build_data.py --from 2026-10-01 --to 2026-10-21 [--step 6]"""
import argparse, json, math, re, sqlite3, datetime as dt
ap = argparse.ArgumentParser(); ap.add_argument("--from", dest="t0", required=True); ap.add_argument("--to", dest="t1", required=True)
ap.add_argument("--step", type=int, default=6); ap.add_argument("--db", default="data/river.db"); a = ap.parse_args()
TZ = dt.timezone(dt.timedelta(hours=10))
start = dt.datetime.fromisoformat(a.t0).replace(tzinfo=TZ)
end = dt.datetime.fromisoformat(a.t1).replace(tzinfo=TZ) + dt.timedelta(days=1)
S = a.step * 3600; n = int((end - start).total_seconds() // S); t0 = int(start.timestamp())
db = sqlite3.connect(a.db)
def norm(s):
    s = s.upper().split("@")[0].split(" AT ")[0]
    s = re.sub(r"\b(RIVER|CREEK|CK|R)\b\.?", "", s); return re.sub(r"[^A-Z]", "", s)
sts = []
for sid, name, lat, lon in db.execute("SELECT id,name,lat,lon FROM stations"):
    ser = {}
    for p in ("flow", "level", "temp"):
        sums = [0.0] * n; cnt = [0] * n
        for ts, v, u in db.execute("SELECT ts,value,unit FROM obs WHERE station=? AND param=? AND ts>=? AND ts<?", (sid, p, t0, t0 + n * S)):
            if p == "flow":   # normalise to ML/d (viewer converts to m3/s for display)
                v = v * 86.4 if u == "cumec" else v
            if v is None or (p == "temp" and not 0 < v < 40) or (p == "flow" and v < 0): continue
            b = (ts - t0) // S; sums[b] += v; cnt[b] += 1
        if any(cnt): ser[p] = [round(sums[i] / cnt[i], 3) if cnt[i] else None for i in range(n)]
    if "flow" in ser or "level" in ser or "temp" in ser:
        sts.append({"id": sid, "name": name, "lat": lat, "lon": lon, "key": norm(name), **ser})
last = max((i for g in sts for i, v in enumerate(g.get("flow", [])) if v is not None), default=n - 1)
if last < n - 1:   # trim trailing bins nobody has reported yet
    n = last + 1
    for g in sts:
        for p in ("flow", "level", "temp"):
            if p in g: g[p] = g[p][:n]
print(len(sts), "gauges;", {p: sum(p in s for s in sts) for p in ("flow", "level", "temp")})
def km(la1, lo1, la2, lo2): return math.hypot((la1 - la2) * 111, (lo1 - lo2) * 111 * math.cos(math.radians(la1)))
rivers = []
for name, c in json.load(open("data/rivers.json")):
    la = sum(p[1] for p in c) / len(c); lo = sum(p[0] for p in c) / len(c); key = norm(name)
    sc = sorted((km(la, lo, s["lat"], s["lon"]) * (0.25 if key and s["key"] == key else 1), i) for i, s in enumerate(sts))[:3]
    sc = [x for x in sc if x[0] < 150]
    w = [round(1 / (d + 5) ** 2, 5) for d, _ in sc]; tot = sum(w) or 1
    rivers.append({"c": c, "g": [i for _, i in sc], "w": [round(x / tot, 3) for x in w]})
meta = {"start": start.isoformat(), "step": a.step, "n": n}
open("data/data.js", "w").write("window.RIVERDATA=" + json.dumps({"meta": meta, "gauges": sts, "rivers": rivers}, separators=(",", ":")) + ";")
print("wrote data/data.js", sum(1 for r in rivers if r["g"]), "of", len(rivers), "chunks linked")
