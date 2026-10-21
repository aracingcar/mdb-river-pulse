"""Minimal reader for a single polygon shapefile (type 5) -> GeoJSON. Usage: shp_to_geojson.py in.shp out.geojson"""
import struct, sys, json
b = open(sys.argv[1], "rb").read()
assert struct.unpack("<i", b[32:36])[0] == 5, "not a polygon shapefile"
pos, rings = 100, []
while pos < len(b):
    _, clen = struct.unpack(">ii", b[pos:pos + 8]); rec = b[pos + 8:pos + 8 + clen * 2]; pos += 8 + clen * 2
    nparts, npts = struct.unpack("<ii", rec[36:44])
    parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts])) + [npts]
    off = 44 + 4 * nparts
    pts = [struct.unpack("<dd", rec[off + 16 * i:off + 16 * i + 16]) for i in range(npts)]
    rings += [[list(p) for p in pts[parts[i]:parts[i + 1]]] for i in range(nparts)]
def area(r): return sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1)) / 2
outer = [r for r in rings if area(r) < 0]; holes = [r for r in rings if area(r) >= 0]   # shapefile: outer rings clockwise
print(len(outer), "outer rings,", len(holes), "holes")
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "Murray-Darling Basin (Water Act 2007)"},
    "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in outer]}}]}, open(sys.argv[2], "w"))
