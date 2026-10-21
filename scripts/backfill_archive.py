"""Fetch, validate, publish and verify one water year before fetching the next.

Run in the dedicated water-year-backfill worktree, sharing the local SQLite
database through its ignored data/river.db symlink. Default target: July 2012.
Progress and a process lock live in .backfill/; reruns resume safely.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
RUNTIME = ROOT / '.backfill'
RUNTIME.mkdir(exist_ok=True)
STATE = RUNTIME / 'archive-state.json'
REPO = 'aracingcar/mdb-river-pulse'
SITE = 'https://aracingcar.github.io/mdb-river-pulse/'


def command(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def save(state, **changes):
    state.update(changes, updatedAt=dt.datetime.now(dt.timezone.utc).isoformat())
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2) + '\n')
    temp.replace(STATE)


def dataset(text):
    prefix = 'window.RIVERDATA='
    if not text.startswith(prefix) or not text.endswith(';'):
        raise ValueError('Invalid data bundle wrapper')
    return json.loads(text[len(prefix):-1])


def validate(year):
    data = dataset((ROOT / 'data/data.js').read_text())
    meta = data['meta']
    assert meta['start'].startswith(f'{year}-07-01'), meta
    assert meta['step'] == 24 and meta['aggregation'] == 'daily_mean', meta
    assert meta['n'] >= 365 and data['gauges'] and data['rivers']
    for gauge in data['gauges']:
        for key in ('flow', 'level', 'temp'):
            if key not in gauge:
                continue
            assert len(gauge[key]) == meta['n'], (gauge['id'], key)
            for value in gauge[key]:
                assert value is None or math.isfinite(value), (gauge['id'], key)
    for river in data['rivers']:
        assert all(0 <= i < len(data['gauges']) for i in river['g'])
    report = json.loads((ROOT / f'data/backfill-{year}-{year+1}.json').read_text())
    assert report['status'] == 'complete' and len(report['months']) == 12
    assert report['completedRequests'] > 0
    assert all(month['parameters'].get('flow', {}).get('observations', 0) > 0
               for month in report['months'])
    return meta


def verify_deployment(commit, year, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = json.loads(command('gh', 'run', 'list', '--repo', REPO,
                                  '--commit', commit, '--limit', '5', '--json',
                                  'databaseId,status,conclusion,name', capture=True))
        pages = [run for run in runs if 'pages' in run['name'].lower()]
        if pages and pages[0]['status'] == 'completed':
            if pages[0]['conclusion'] != 'success':
                raise RuntimeError(f'Pages deployment failed: {pages[0]}')
            break
        time.sleep(10)
    else:
        raise TimeoutError('Timed out waiting for GitHub Pages deployment')
    expected = hashlib.sha256((ROOT / 'data/data.js').read_bytes()).hexdigest()
    last_error = None
    for attempt in range(12):
        try:
            request = urllib.request.Request(SITE + 'data/data.js?v=' + commit,
                                             headers={'User-Agent': 'MDB-River-Pulse-backfill'})
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('Live bundle does not yet match the published commit')
            assert dataset(content.decode())['meta']['start'].startswith(f'{year}-07-01')
            return
        except Exception as error:
            last_error = error
            time.sleep(10)
    raise RuntimeError(f'Could not verify live bundle: {last_error}')


def publish(state, year, commit):
    save(state, phase='pushing', year=year, commit=commit)
    command('git', '-c', 'http.version=HTTP/1.1', '-c', 'http.postBuffer=52428800',
            'push', 'origin', 'HEAD:main')
    save(state, phase='deploying')
    verify_deployment(commit, year)
    history = state.setdefault('published', [])
    if not any(item['year'] == year for item in history):
        history.append({'year': year, 'commit': commit,
                        'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat()})
    save(state, phase='ready', nextYear=year-1, lastPublishedYear=year,
         lastPublishedCommit=commit, error=None)
    print(f'PUBLISHED AND VERIFIED {year}–{year+1}: {SITE}', flush=True)


def run(args):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if state.get('phase') == 'complete':
        print('Archive already published through July 2012.', flush=True)
        return
    account = command('gh', 'api', 'user', '--jq', '.login', capture=True).strip()
    if account != 'aracingcar':
        raise RuntimeError('Expected GitHub account aracingcar; found ' + account)
    save(state, pid=os.getpid(), earliestYear=args.earliest_year, site=SITE)
    if state.get('phase') in ('committed', 'pushing', 'deploying'):
        publish(state, state['year'], state['commit'])
        if args.once:
            return
    while True:
        year = state.get('nextYear')
        if year is None:
            current = dataset(command('git', 'show', 'HEAD:data/data.js', capture=True))
            year = int(current['meta']['start'][:4]) - 1
        if year < args.earliest_year:
            save(state, phase='complete', completedAt=dt.datetime.now(dt.timezone.utc).isoformat())
            print('COMPLETE: live data starts on 1 July 2012.', flush=True)
            return
        save(state, year=year, nextYear=year, phase='fetching', commit=None, error=None)
        print(f'BACKFILL {year}–{year+1}', flush=True)
        command(sys.executable, '-I', 'scripts/backfill_year.py', '--start-year', str(year),
                '--export-to', args.export_to)
        save(state, phase='validating')
        meta = validate(year)
        command('git', 'add', '--', 'data/data.js', f'data/backfill-{year}-{year+1}.json')
        staged = command('git', 'diff', '--cached', '--name-only', capture=True).splitlines()
        allowed = {'data/data.js', f'data/backfill-{year}-{year+1}.json'}
        if not staged or not set(staged) <= allowed:
            raise RuntimeError('Unexpected files staged for publication: ' + repr(staged))
        command('git', '-c', 'user.name=aracingcar', '-c',
                'user.email=111629207+aracingcar@users.noreply.github.com', 'commit', '-m',
                f'Extend daily river observations through water year {year}-{year+1}')
        commit = command('git', 'rev-parse', 'HEAD', capture=True).strip()
        save(state, phase='committed', commit=commit, exportedDays=meta['n'])
        publish(state, year, commit)
        if args.once:
            return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--earliest-year', type=int, default=2012)
    parser.add_argument('--export-to', default='2026-10-21')
    parser.add_argument('--once', action='store_true')
    options = parser.parse_args()
    with (RUNTIME / 'archive.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('The archive runner is already active.', flush=True)
            raise SystemExit(0)
        try:
            run(options)
        except Exception as error:
            state = json.loads(STATE.read_text()) if STATE.exists() else {}
            save(state, error=str(error), failedAt=dt.datetime.now(dt.timezone.utc).isoformat())
            traceback.print_exc()
            raise SystemExit(1)
