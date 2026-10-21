"""Fetch BoM daily means for a July–June water year plus the current year.

python3 -I scripts/backfill_year.py --start-year 2025 --export-to 2026-10-21
Each station/parameter request is checkpointed. Export only after all succeed.
"""
import argparse
import calendar
import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument('--start-year', type=int, required=True)
ap.add_argument('--export-to', default='2026-10-21')
ap.add_argument('--stations', default='data/all_fetch.json')
args = ap.parse_args()
start = f'{args.start_year}-07-01'
end_year = f'{args.start_year+1}-06-30'
report_path = root / 'data' / f'backfill-{args.start_year}-{args.start_year+1}.json'
report = {'waterYear':f'{args.start_year}–{args.start_year+1}', 'start':start, 'end':end_year, 'exportTo':args.export_to, 'aggregation':'BoM DailyMean.24HR', 'dayTimezone':'station-local standard time (AEST/ACST), grouped by calendar date', 'status':'fetching', 'months':[]}
report_path.write_text(json.dumps(report,indent=2)+'\n')
command = [sys.executable,'-I','scripts/fetch_bom.py','--stations',args.stations,'--backfill','--resume','--include-known-stations','--daily-means','--from',start,'--to',args.export_to]
for attempt in range(3):
    print(f'=== Daily means {start} through {args.export_to}: attempt {attempt+1} ===',flush=True)
    result = subprocess.run(command,cwd=root)
    if result.returncode == 0: break
if result.returncode:
    report['status']='incomplete'
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print('Requests still failed. Rerun to resume; no export made.',flush=True)
    raise SystemExit(result.returncode)

zone=dt.timezone(dt.timedelta(hours=10))
t0=dt.datetime.fromisoformat(start).replace(tzinfo=zone).isoformat(timespec='seconds')
t1=(dt.datetime.fromisoformat(args.export_to).replace(tzinfo=zone)+dt.timedelta(days=1)-dt.timedelta(minutes=1)).isoformat(timespec='seconds')
with sqlite3.connect(root/'data/river.db',timeout=300) as db:
    statuses=dict(db.execute('SELECT status,count(*) FROM daily_windows WHERE start=? AND end=? GROUP BY status',(t0,t1)))
    if statuses.get('failed',0): raise RuntimeError('Daily requests remain failed')
    report['completedRequests']=statuses.get('complete',0)
    report['emptyResponses']=db.execute("SELECT count(*) FROM daily_windows WHERE start=? AND end=? AND points=0 AND status='complete'",(t0,t1)).fetchone()[0]
    months=[(args.start_year,m) for m in range(7,13)]+[(args.start_year+1,m) for m in range(1,7)]
    for year,month in months:
        begin=dt.datetime(year,month,1,tzinfo=zone)
        finish=begin+dt.timedelta(days=calendar.monthrange(year,month)[1])
        rows=db.execute('SELECT param,count(distinct station),count(*) FROM daily_obs WHERE ts>=? AND ts<? GROUP BY param',(int(begin.timestamp()),int(finish.timestamp()))).fetchall()
        report['months'].append({'start':begin.date().isoformat(),'end':(finish-dt.timedelta(days=1)).date().isoformat(),'parameters':{p:{'stationsWithData':n,'observations':count} for p,n,count in rows}})
        if not rows: raise RuntimeError('No daily observations for '+begin.date().isoformat())
report['status']='rebuilding'
report_path.write_text(json.dumps(report,indent=2)+'\n')
subprocess.run([sys.executable,'-I','scripts/build_data.py','--from',start,'--to',args.export_to],cwd=root,check=True)
report['status']='complete'
report['completedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
report_path.write_text(json.dumps(report,indent=2)+'\n')
print('Completed daily means for the full water year and current year.',flush=True)
