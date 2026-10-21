"""Fetch observations from BoM Water Data Online (SOS 2.0) into data/river.db (SQLite).

Incremental: for each (station, parameter) only data after the latest stored timestamp is
requested, so re-running with a later --to extends the store.

  python3 -I scripts/fetch_bom.py --stations data/major.json --from 2026-10-01 --to 2026-10-21
"""
import argparse, json, re, sqlite3, urllib.request, urllib.parse, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://www.bom.gov.au/waterdata/services"
PARAM = "http://bom.gov.au/waterdata/services/parameters/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
PROPS = {"flow": "Water Course Discharge", "level": "Water Course Level", "temp": "Water Temperature"}
TZ = dt.timezone(dt.timedelta(hours=10))   # AEST, as BoM reports
RAW = re.compile(r'tstypes/Pat\d_C_B_1"')  # raw merged series (not hourly/daily aggregates)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations(id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS obs(station TEXT, param TEXT, ts INTEGER, value REAL, unit TEXT,
                               PRIMARY KEY(station, param, ts)) WITHOUT ROWID;
"""

def get(station, prop, t0, t1):
    q = urllib.parse.urlencode({
        "service": "SOS", "version": "2.0", "request": "GetObservation",
        "featureOfInterest": f"http://bom.gov.au/waterdata/services/stations/{station}",
        "observedProperty": PARAM + prop,
        "temporalFilter": f"om:phenomenonTime,{t0}/{t1}",
    }, quote_via=urllib.parse.quote)
    for _ in range(3):
        try:
            r = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": UA})
            return urllib.request.urlopen(r, timeout=120).read().decode("utf-8", "ignore")
        except Exception:
            pass
    return ""

def parse(xml):
    blocks = [b for b in re.findall(r"<om:OM_Observation.*?</om:OM_Observation>", xml, re.S) if RAW.search(b)]
    if not blocks:
        return [], None
    b = blocks[0]
    unit = re.search(r'<wml2:uom code="([^"]*)"', b)
    rows = []
    for t, v in re.findall(r"<wml2:time>([^<]+)</wml2:time><wml2:value[^>]*?>([^<]*)<", b):
        try: rows.append((int(dt.datetime.fromisoformat(t).timestamp()), float(v)))
        except ValueError: pass
    return rows, unit.group(1) if unit else None

def work(job):
    sid, key, t0, t1 = job
    rows, unit = parse(get(sid, PROPS[key], t0, t1))
    return sid, key, rows, unit

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", required=True); ap.add_argument("--db", default="data/river.db")
    ap.add_argument("--backfill", action="store_true", help="fetch exactly [from,to] for (station,param) pairs that already have data, ignoring stored max ts")
    ap.add_argument("--from", dest="t0", required=True); ap.add_argument("--to", dest="t1", required=True)
    a = ap.parse_args()
    db = sqlite3.connect(a.db); db.executescript(SCHEMA)
    stations = json.load(open(a.stations))
    db.executemany("INSERT OR REPLACE INTO stations VALUES(?,?,?,?)", stations); db.commit()
    end = dt.datetime.fromisoformat(a.t1).replace(tzinfo=TZ) + dt.timedelta(days=1) - dt.timedelta(minutes=1)
    jobs = []
    for sid, *_ in stations:
        for key in PROPS:
            last = db.execute("SELECT MAX(ts) FROM obs WHERE station=? AND param=?", (sid, key)).fetchone()[0]
            if a.backfill:
                if last is None: continue
                last = None
            start = dt.datetime.fromtimestamp(last + 1, TZ) if last else dt.datetime.fromisoformat(a.t0).replace(tzinfo=TZ)
            if start < end:
                jobs.append((sid, key, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")))
    n = 0
    with ThreadPoolExecutor(16) as ex:
        for i, f in enumerate(as_completed([ex.submit(work, j) for j in jobs])):
            sid, key, rows, unit = f.result()
            if rows:
                db.executemany("INSERT OR IGNORE INTO obs VALUES(?,?,?,?,?)", [(sid, key, t, v, unit) for t, v in rows]); n += len(rows)
            if i % 50 == 0:
                db.commit(); print(i, len(jobs), n, flush=True)
    db.commit(); print("done: +%d rows" % n)
