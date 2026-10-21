"""Total daily barrage flow (ML/day), River Murray barrages -> data/river.db (station A4261002, param 'barrage').
Source: SA DEW water data portal chart 117 ("Total Daily Barrage Flow Summary"); covers roughly the last year."""
import json, sqlite3, urllib.request, datetime as dt
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
URL = "https://water.data.sa.gov.au/Data/LoadChart/?id=117&interval=Latest&timezone=660&useChartInterval=true&useLocationTimezone=true"
d = json.load(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=90))
ser = d["Series"][0]; assert "barrage flow" in ser["LegendText"].lower(), ser["LegendText"]
rows = [(int(dt.datetime.fromisoformat(p["Time"].replace("Z", "+00:00")).timestamp()), p["Value"]) for p in ser["Data"] if p["Value"] is not None]
db = sqlite3.connect("data/river.db", timeout=300)
db.execute("INSERT OR REPLACE INTO stations VALUES(?,?,?,?)", ("A4261002", "River Murray Calculated Barrage Flow", -35.5592, 138.8873))
db.executemany("INSERT OR REPLACE INTO obs VALUES(?,?,?,?,?)", [("A4261002", "barrage", t, v, "ML/d") for t, v in rows])
db.commit(); print(len(rows), "daily values", dt.datetime.utcfromtimestamp(rows[0][0]).date(), "to", dt.datetime.utcfromtimestamp(rows[-1][0]).date())
