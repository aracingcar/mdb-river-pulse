"""Fetch named OSM lakes/reservoirs (outlines) for the Murray-Darling bbox in tiles -> data/waterbodies_raw.json"""
import json, sys, urllib.request, urllib.parse, time
from concurrent.futures import ThreadPoolExecutor
MIRRORS = ["https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
W, S, E, N = 138.4, -37.8, 152.6, -24.5
NX, NY = 5, 5
NAME = "Lake|Lagoon|Dam|Reservoir|Storage|Weir|Hume|Mulwala|Eildon|Burrinjuck|Menindee|Wyangala|Burrendong|Blowering|Keepit|Copeton|Glenbawn|Dartmouth|Hindmarsh|Coorong|Cawndilla|Pamamaroo|Wetherell|Tantangara|Talbingo|Pindari|Windamere|Chaffey|Split Rock|Oberon|Googong|Eppalock|Rocklands|Bellfield|Nillahcootie|Mokoan|Cargelligo|Brewster"
Q = '[out:json][timeout:170];(way["natural"="water"]["name"~"{n}"]({b});relation["natural"="water"]["name"~"{n}"]({b});way["landuse"="reservoir"]["name"]({b});relation["landuse"="reservoir"]["name"]({b}););out geom;'
import os
os.makedirs("data/wb_tiles", exist_ok=True)
def tile(t):
    cf = f"data/wb_tiles/{t[0]}_{t[1]}.json"
    if os.path.exists(cf): return json.load(open(cf))
    ix, iy = t; b = f"{S + (N-S)*iy/NY:.3f},{W + (E-W)*ix/NX:.3f},{S + (N-S)*(iy+1)/NY:.3f},{W + (E-W)*(ix+1)/NX:.3f}"
    for rnd in range(4):
        for m in MIRRORS:
            try:
                req = urllib.request.Request(m, data=urllib.parse.urlencode({"data": Q.format(b=b, n=NAME)}).encode(), headers={"User-Agent": "mdb-river-pulse/0.1"})
                d = json.load(urllib.request.urlopen(req, timeout=200)); json.dump(d["elements"], open(cf, "w")); print("tile", t, len(d["elements"]), m.split("/")[2], flush=True); return d["elements"]
            except Exception as e: err = e
        time.sleep(5 * (rnd + 1))
    print("tile FAILED", t, err, flush=True); return None
tiles = [(x, y) for x in range(NX) for y in range(NY)]
with ThreadPoolExecutor(4) as ex: res = list(ex.map(tile, tiles))
els = {}
for r in res:
    for e in r or []: els[(e["type"], e["id"])] = e
json.dump({"elements": list(els.values()), "failed": [t for t, r in zip(tiles, res) if r is None]}, open("data/waterbodies_raw.json", "w"))
print(len(els), "water bodies; failed tiles:", [t for t, r in zip(tiles, res) if r is None])
