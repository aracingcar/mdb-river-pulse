"""Fetch observations from BoM Water Data Online (SOS 2.0) into data/river.db (SQLite).

Incremental: for each (station, parameter) only data after the latest stored timestamp is
requested, so re-running with a later --to extends the store.

  python3 -I scripts/fetch_bom.py --stations data/major.json --from 2026-10-01 --to 2026-10-21
"""
import argparse, json, re, sqlite3, urllib.request, urllib.parse, datetime as dt
import time, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://www.bom.gov.au/waterdata/services"
PARAM = "http://bom.gov.au/waterdata/services/parameters/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
PROPS = {"flow": "Water Course Discharge", "level": "Water Course Level", "temp": "Water Temperature",
         "svol": "Storage Volume", "slevel": "Storage Level"}
PROCEDURES = {"Water Course Discharge": "Pat4_C_B_1", "Water Course Level": "Pat3_C_B_1", "Water Temperature": "Pat1_C_B_1",
               "Storage Volume": "Pat6_P_1", "Storage Level": "Pat7_P_1"}
TZ = dt.timezone(dt.timedelta(hours=10))   # AEST, as BoM reports
RAW = re.compile(r'tstypes/Pat\d_(C_B|P)_1"')  # raw merged series (not hourly/daily aggregates)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations(id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS obs(station TEXT, param TEXT, ts INTEGER, value REAL, unit TEXT,
                               PRIMARY KEY(station, param, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fetch_windows(
    station TEXT, param TEXT, start TEXT, end TEXT, points INTEGER,
    status TEXT, error TEXT, checked_at TEXT,
    PRIMARY KEY(station,param,start,end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_obs(station TEXT, param TEXT, ts INTEGER, value REAL, unit TEXT,
                                    PRIMARY KEY(station,param,ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_windows(
    station TEXT, param TEXT, start TEXT, end TEXT, points INTEGER,
    status TEXT, error TEXT, checked_at TEXT,
    PRIMARY KEY(station,param,start,end)
) WITHOUT ROWID;
"""

def get(station, prop, t0, t1, daily_means=False):
    q = urllib.parse.urlencode({
        "service": "SOS", "version": "2.0", "request": "GetObservation",
        "featureOfInterest": f"http://bom.gov.au/waterdata/services/stations/{station}",
        "observedProperty": PARAM + prop,
        "procedure": "http://bom.gov.au/waterdata/services/tstypes/" + PROCEDURES[prop] + ("_DailyMean" if daily_means else ""),
        "temporalFilter": f"om:phenomenonTime,{t0}/{t1}",
    }, quote_via=urllib.parse.quote)
    error = None
    for attempt in range(3):
        try:
            r = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": UA})
            with urllib.request.urlopen(r, timeout=120) as response:
                xml = response.read().decode("utf-8")
            root = ET.fromstring(xml)
            if "ExceptionReport" in root.tag:
                raise ValueError(" ".join(root.itertext()).strip()[:500])
            if "GetObservationResponse" not in root.tag:
                raise ValueError("Unexpected response: " + root.tag)
            return xml
        except Exception as exc:
            error = exc
            if attempt < 2: time.sleep(attempt + 1)
    raise RuntimeError(str(error))

def parse(xml, daily_means=False):
    pattern = re.compile(r'tstypes/Pat\d_C_B_1_DailyMean"') if daily_means else RAW
    blocks = [b for b in re.findall(r"<om:OM_Observation.*?</om:OM_Observation>", xml, re.S) if pattern.search(b)]
    if not blocks:
        return [], None
    b = blocks[0]
    unit = re.search(r'<wml2:uom code="([^"]*)"', b)
    rows = []
    for t, v in re.findall(r"<wml2:time>([^<]+)</wml2:time><wml2:value[^>]*?>([^<]*)<", b):
        try: rows.append((int(dt.datetime.fromisoformat(t).timestamp()), float(v)))
        except ValueError: pass
    return rows, unit.group(1) if unit else None

def work(job, daily_means=False):
    sid, key, t0, t1 = job
    try:
        rows, unit = parse(get(sid, PROPS[key], t0, t1, daily_means), daily_means)
        return sid, key, rows, unit, None, t0, t1
    except Exception as exc:
        return sid, key, [], None, str(exc), t0, t1

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", required=True); ap.add_argument("--db", default="data/river.db")
    ap.add_argument("--props", default="flow,level,temp", help="comma list from: " + ",".join(PROPS))
    ap.add_argument("--backfill", action="store_true", help="fetch exactly [from,to] for (station,param) pairs that already have data, ignoring stored max ts")
    ap.add_argument("--resume", action="store_true", help="skip previously completed backfill request windows")
    ap.add_argument("--include-known-stations", action="store_true", help="also backfill stations already holding observations in the database")
    ap.add_argument("--daily-means", action="store_true", help="fetch BoM's midnight-to-midnight daily means into the separate daily store")
    ap.add_argument("--from", dest="t0", required=True); ap.add_argument("--to", dest="t1", required=True)
    a = ap.parse_args()
    if a.resume and not a.backfill: ap.error("--resume requires --backfill")
    db = sqlite3.connect(a.db, timeout=300); db.executescript(SCHEMA)
    observations = "daily_obs" if a.daily_means else "obs"
    checkpoints = "daily_windows" if a.daily_means else "fetch_windows"
    stations = json.load(open(a.stations))
    if a.include_known_stations:
        if not a.backfill: ap.error("--include-known-stations requires --backfill")
        known = db.execute("SELECT id,name,lat,lon FROM stations s WHERE EXISTS (SELECT 1 FROM obs WHERE station=s.id) OR EXISTS (SELECT 1 FROM daily_obs WHERE station=s.id)").fetchall()
        stations = list({s[0]:s for s in stations + known}.values())
    db.executemany("INSERT OR REPLACE INTO stations VALUES(?,?,?,?)", stations); db.commit()
    end = dt.datetime.fromisoformat(a.t1).replace(tzinfo=TZ) + dt.timedelta(days=1) - dt.timedelta(minutes=1)
    jobs = []
    for sid, *_ in stations:
        for key in a.props.split(","):
            last = db.execute(f"SELECT MAX(ts) FROM {observations} WHERE station=? AND param=?", (sid, key)).fetchone()[0]
            if a.backfill:
                if last is None and (not a.daily_means or not db.execute("SELECT 1 FROM obs WHERE station=? AND param=? LIMIT 1", (sid,key)).fetchone()): continue
                last = None
            start = dt.datetime.fromtimestamp(last + 1, TZ) if last else dt.datetime.fromisoformat(a.t0).replace(tzinfo=TZ)
            if start < end:
                job = (sid, key, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
                if a.resume and db.execute(f"SELECT 1 FROM {checkpoints} WHERE station=? AND param=? AND start=? AND end=? AND status='complete'", job).fetchone():
                    continue
                jobs.append(job)
    n = failed = empty = 0
    print(f"{a.t0} to {a.t1}: {len(jobs)} requests", flush=True)
    with ThreadPoolExecutor(16) as ex:
        for i, f in enumerate(as_completed([ex.submit(work, j, a.daily_means) for j in jobs])):
            sid, key, rows, unit, error, t0, t1 = f.result()
            if error:
                failed += 1
                print(f"FAILED {sid} {key}: {error}", flush=True)
            elif not rows:
                empty += 1
            if rows:
                before = db.total_changes
                db.executemany(f"INSERT OR IGNORE INTO {observations} VALUES(?,?,?,?,?)", [(sid, key, t, v, unit) for t, v in rows])
                n += db.total_changes - before
            db.execute(f"INSERT OR REPLACE INTO {checkpoints} VALUES(?,?,?,?,?,?,?,?)", (sid,key,t0,t1,len(rows),'failed' if error else 'complete',error,dt.datetime.now(dt.timezone.utc).isoformat()))
            # Release the write lock before waiting for another network response.
            db.commit()
            if i % 50 == 0:
                print(i, len(jobs), n, flush=True)
    db.commit(); print(f"done: +{n} rows; {empty} empty responses; {failed} failed requests", flush=True)
    db.close()
    if failed: raise SystemExit(1)
