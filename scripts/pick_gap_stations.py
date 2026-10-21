"""Pick not-yet-fetched candidate gauges that cover river reaches with no nearby flow gauge.
Usage: pick_gap_stations.py [max_new] -> writes data/gap_stations.json"""
import json, math, sqlite3, sys
K = int(sys.argv[1]) if len(sys.argv) > 1 else 250; R = 40  # km
db = sqlite3.connect("data/river.db")
have = {r[0] for r in db.execute("SELECT DISTINCT station FROM obs WHERE param='flow'")}
tried = {r[0] for r in db.execute("SELECT id FROM stations")}
pos = {r[0]: (r[2], r[3]) for r in db.execute("SELECT id,name,lat,lon FROM stations")}
def km(a, b): return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))
cent = [(sum(p[1] for p in c) / len(c), sum(p[0] for p in c) / len(c)) for _, c in json.load(open("data/rivers.json"))]
unc = [c for c in cent if not any(km(c, pos[s]) < R for s in have)]
print(len(unc), "of", len(cent), "reaches lack a flow gauge within", R, "km")
cands = [c for c in json.load(open("data/candidates.json")) if c[0] not in tried]
cov = {c[0]: {i for i, u in enumerate(unc) if abs(u[0] - c[2]) < .4 and km(u, (c[2], c[3])) < R} for c in cands}
left = set(range(len(unc))); pick = []
while len(pick) < K:
    best = max(cands, key=lambda c: len(cov[c[0]] & left))
    g = cov[best[0]] & left
    if len(g) < 3: break
    pick.append(best); left -= g
print(len(pick), "stations picked; reaches still uncovered:", len(left))
json.dump(pick, open("data/gap_stations.json", "w"))
