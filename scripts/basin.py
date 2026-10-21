"""Murray-Darling Basin boundary test (MDBA Water Act 2007 polygon in data/mdb_boundary.geojson)."""
import json
RINGS = [poly[0] for poly in json.load(open("data/mdb_boundary.geojson"))["features"][0]["geometry"]["coordinates"]]
def inside(lon, lat):
    for r in RINGS:
        c = False; j = len(r) - 1
        for i in range(len(r)):
            xi, yi = r[i]; xj, yj = r[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi: c = not c
            j = i
        if c: return True
    return False
